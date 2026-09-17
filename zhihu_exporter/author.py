"""作者内容抓取模块：抓取指定用户的原创文章 / 回答（免浏览器、免签名）。

知乎 v4 列表接口 /api/v4/members/{token}/articles 与 /api/v4/members/{token}/answers
在携带登录 Cookie 且 include=data[*].content 时，会在列表响应中直接返回完整正文，
因此无需请求单篇详情接口（后者触发 x-zse-96 签名校验，返回 HTTP 403 / code 10003）。

与「点赞导出」的区别：点赞导出抓的是某账号点赞过的**他人**内容（走 moments 动态流），
本模块抓的是某账号**自己创作**的文章 / 回答（走 members 列表接口）。
"""

import asyncio
import os
import sys
from datetime import datetime
from urllib.parse import quote

try:
    import aiohttp
except ImportError:
    aiohttp = None

from zhihu_exporter.config import PAGE_DELAY, MAX_RETRIES
from zhihu_exporter.export import _fetch_page, _verify_cookie, _write_item_sync
from zhihu_exporter.formatters import (
    format_html_author_answer,
    format_html_author_article,
    format_md_author_answer,
    format_md_author_article,
)
from zhihu_exporter.images import _process_images
from zhihu_exporter.progress import load_progress, save_progress
from zhihu_exporter.utils import get_headers, sanitize_filename

# 列表接口 include 参数：直接取回正文（绕开单篇详情接口的签名校验）
_ARTICLE_INCLUDE = (
    "data[*].content,data[*].title,data[*].created,data[*].updated,"
    "data[*].author,data[*].url,data[*].image_url,"
    "data[*].voteup_count,data[*].comment_count,data[*].excerpt"
)
_ANSWER_INCLUDE = (
    "data[*].content,data[*].created_time,data[*].updated_time,"
    "data[*].author,data[*].question,data[*].url,"
    "data[*].voteup_count,data[*].comment_count"
)

# 预览用 include：不需要 content
_ARTICLE_INCLUDE_PREVIEW = (
    "data[*].title,data[*].created,data[*].author,data[*].url,"
    "data[*].voteup_count,data[*].comment_count"
)
_ANSWER_INCLUDE_PREVIEW = (
    "data[*].created_time,data[*].author,data[*].question,data[*].url,"
    "data[*].voteup_count,data[*].comment_count"
)

# 每种内容类型对应的输出子目录名与 API 路径
_KIND_META = {
    "articles": {"api": "articles", "label": "文章", "include": _ARTICLE_INCLUDE},
    "answers": {"api": "answers", "label": "回答", "include": _ANSWER_INCLUDE},
}

# 预览用元信息（更精简的 include，无 content）
_KIND_META_PREVIEW = {
    "articles": {"api": "articles", "label": "文章", "include": _ARTICLE_INCLUDE_PREVIEW},
    "answers": {"api": "answers", "label": "回答", "include": _ANSWER_INCLUDE_PREVIEW},
}

# 支持的作品类型 -> mode 值
MODE_TO_KINDS = {
    "articles": ["articles"],
    "answers": ["answers"],
    "all": ["articles", "answers"],
}

PAGE_SIZE = 20  # 列表接口每页条数


def _build_list_url(token, api, offset, limit, include):
    """构造作者内容列表接口 URL（include 做 URL 编码）"""
    return (
        f"https://www.zhihu.com/api/v4/members/{token}/{api}"
        f"?limit={limit}&offset={offset}&include={quote(include, safe='')}"
    )


def _item_title(item, is_answer):
    """取条目标题：文章取 title，回答取所属问题的标题"""
    if is_answer:
        return (item.get("question") or {}).get("title") or "（无标题）"
    return item.get("title") or "（无标题）"


def _item_time(item, is_answer):
    """取条目发布时间戳"""
    return item.get("created_time" if is_answer else "created") or 0


async def _process_author_item(session, item, is_answer, fmt_configs, active_formats,
                               image_config=None, skip_existing=False,
                               request_semaphore=None):
    """处理单条作者原创内容：生成各格式内容、处理图片并并发写入文件。

    Returns:
        dict: {"new": bool}
    """
    target_id = str(item.get("id", ""))
    raw_title = _item_title(item, is_answer)
    title = sanitize_filename(raw_title)
    ts = _item_time(item, is_answer)
    date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "unknown"

    filepaths = {}
    for f in active_formats:
        cfg = fmt_configs[f]
        filepaths[f] = os.path.join(cfg["dir"], f"{date_str}_{title}_{target_id}{cfg['ext']}")

    result = {
        "new": False,
        "new_per_format": {f: False for f in active_formats},
    }

    pending_formats = [f for f in active_formats
                       if not (skip_existing and os.path.exists(filepaths[f]))]
    if not pending_formats:
        return result

    contents = {}
    for f in pending_formats:
        if is_answer:
            contents[f] = (format_html_author_answer(item) if f == "html"
                           else format_md_author_answer(item))
        else:
            contents[f] = (format_html_author_article(item) if f == "html"
                           else format_md_author_article(item))

    if image_config and image_config.get("enabled") and contents:
        contents = await _process_images(
            session=session,
            image_config=image_config,
            item_content=contents,
            target_id=target_id,
            request_semaphore=request_semaphore,
        )

    loop = asyncio.get_running_loop()
    write_tasks = [loop.run_in_executor(None, _write_item_sync, filepaths[f], contents[f])
                   for f in pending_formats]
    results = await asyncio.gather(*write_tasks)

    for f, wrote in zip(pending_formats, results):
        result["new_per_format"][f] = bool(wrote)
    result["new"] = any(result["new_per_format"].values())
    return result


async def _crawl_kind(session, username, kind, base_headers, semaphore, fmt_configs,
                      active_formats, limit, incremental, keyword, page_delay, max_retries,
                      image_config, progress_file):
    """抓取单一类型（articles / answers）的全部内容。

    Returns:
        int: 本次新增写入的条目数（去重）
    """
    meta = _KIND_META[kind]
    is_answer = (kind == "answers")
    label = meta["label"]

    print(f"\n开始抓取 [{username}] 的原创{label}（免浏览器 / 免签名）...")

    offset = 0
    is_end = False
    new_count = 0
    seen = 0
    totals = None

    while not is_end:
        url = _build_list_url(username, meta["api"], offset, PAGE_SIZE, meta["include"])
        data = await _fetch_page(session, url, base_headers, semaphore,
                                 max_retries=max_retries or MAX_RETRIES)
        if data is None:
            print(f"\n原创{label}：请求失败次数过多，中止。")
            break
        if "error" in data:
            print(f"\n原创{label}：API 返回错误："
                  f"{data.get('error', {}).get('message', '未知错误')}")
            break

        paging = data.get("paging", {})
        if totals is None:
            totals = paging.get("totals")
        items = data.get("data", [])

        # 关键词过滤（按标题匹配）
        batch = []
        for item in items:
            if keyword and keyword not in _item_title(item, is_answer):
                continue
            batch.append(item)

        # limit 截断
        if limit:
            remaining = limit - seen
            if remaining <= 0:
                print(f"  已达到上限（{limit} 条），停止。")
                break
            batch = batch[:remaining]
        seen += len(batch)

        page_new = 0
        if batch:
            tasks = [_process_author_item(session, it, is_answer, fmt_configs, active_formats,
                                          image_config, incremental, semaphore)
                     for it in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for it, r in zip(batch, results):
                if isinstance(r, Exception):
                    print(f"\n处理条目时出错：{r}")
                    continue
                if r.get("new"):
                    page_new += 1
                    new_count += 1

        page_no = offset // PAGE_SIZE + 1
        print(f"  第 {page_no} 页：返回 {len(items)} 条，命中 {len(batch)} 条，"
              f"新增 {page_new} 条（累计新增 {new_count}）")

        is_end = paging.get("is_end", True)
        offset += PAGE_SIZE

        if limit and seen >= limit:
            print(f"  已达到上限（{limit} 条），停止。")
            break
        if is_end:
            break
        await asyncio.sleep(page_delay if page_delay is not None else PAGE_DELAY)

    # 保存进度（按类型 + 格式分别记录累计计数；增量判定基于文件存在性）
    for f in active_formats:
        key = f"author_{kind}_{f}"
        prev = load_progress(progress_file, key)
        art = prev.get("article_count", 0)
        ans = prev.get("answer_count", 0)
        if is_answer:
            ans += new_count
        else:
            art += new_count
        save_progress(progress_file, key, 0, ans, art)

    if totals is not None:
        print(f"原创{label}抓取完成：接口报告共 {totals} 条，本次新增 {new_count} 条。")
    else:
        print(f"原创{label}抓取完成：本次新增 {new_count} 条。")
    return new_count



async def _crawl_author_async(
    username, cookie, output_dir, limit, incremental,
    fmt, concurrency, page_delay=None, max_retries=None, image_config=None,
    kinds=("articles",), keyword=None,
):
    """异步抓取指定用户自己创作的文章 / 回答。

    Args:
        kinds: 抓取类型列表，元素为 "articles" / "answers"
        keyword: 标题关键词过滤（None 表示不过滤）

    Returns:
        int: 本次新增写入的条目总数（去重）
    """
    if aiohttp is None:
        print("错误：缺少必要依赖 aiohttp")
        print("请运行：pip install aiohttp")
        sys.exit(1)

    referer_url = f"https://www.zhihu.com/people/{username}"
    base_headers = get_headers(referer_url)
    base_headers["cookie"] = cookie

    async with aiohttp.ClientSession() as session:
        # --- 验证 Cookie ---
        print("\n正在验证 Cookie...")
        if not await _verify_cookie(session, username, base_headers):
            print("Cookie 验证失败，请检查 Cookie 是否有效。")
            sys.exit(1)
        print("Cookie 验证通过。")

        # --- 准备输出目录 ---
        output_root = os.path.join(output_dir, username)
        if fmt == "both":
            active_formats = ["md", "html"]
            fmt_label = "MD+HTML"
        else:
            active_formats = [fmt]
            fmt_label = fmt.upper()

        # --- 图片配置 ---
        if image_config and image_config.get("enabled"):
            if image_config.get("host") == "local":
                image_config["local_dir"] = os.path.join(output_root, "assets", "images")
                os.makedirs(image_config["local_dir"], exist_ok=True)
            print(f"图片处理：{image_config['host']} 模式已启用")
        else:
            image_config = None

        progress_file = os.path.join(output_root, ".progress_author.json")
        semaphore = asyncio.Semaphore(concurrency)
        total_new = 0

        if keyword:
            print(f"\n关键词过滤：仅导出标题包含「{keyword}」的内容")
        if incremental:
            print("[增量模式] 已存在的文件将被跳过（不重复下载）")
        else:
            print("[全量模式] 将重新写入所有匹配内容")

        for kind in kinds:
            label = _KIND_META[kind]["label"]
            fmt_configs = {}
            for f in active_formats:
                d = os.path.join(output_root, f"原创{label}_{f}")
                os.makedirs(d, exist_ok=True)
                fmt_configs[f] = {"dir": d, "ext": ".md" if f == "md" else ".html"}

            total_new += await _crawl_kind(
                session=session, username=username, kind=kind, base_headers=base_headers,
                semaphore=semaphore, fmt_configs=fmt_configs, active_formats=active_formats,
                limit=limit, incremental=incremental, keyword=keyword,
                page_delay=page_delay, max_retries=max_retries, image_config=image_config,
                progress_file=progress_file,
            )

        print(f"\n========== 原创内容导出完成 ==========")
        print(f"本次新增：{total_new} 篇")
        print(f"输出格式：{fmt_label}")
        print(f"输出目录：{output_root}")

        return total_new


async def _preview_author_async(
    username, cookie, kinds=("articles",), limit=None,
    keyword=None, page_delay=None, max_retries=None,
    concurrency=5,
):
    """预览指定用户的原创内容列表（只列出标题，不写入文件）。

    Args:
        username: 知乎用户名
        cookie: 登录 Cookie
        kinds: 类型列表（"articles" / "answers"）
        limit: 限制条数
        keyword: 标题关键词过滤

    Returns:
        int: 匹配到的条目总数
    """
    if aiohttp is None:
        print("错误：缺少必要依赖 aiohttp")
        sys.exit(1)

    referer_url = f"https://www.zhihu.com/people/{username}"
    base_headers = get_headers(referer_url)
    base_headers["cookie"] = cookie

    async with aiohttp.ClientSession() as session:
        print("正在验证 Cookie...", end=" ")
        if not await _verify_cookie(session, username, base_headers):
            print("失败")
            print("Cookie 验证失败，请检查 Cookie 是否有效。")
            sys.exit(1)
        print("通过")

        total_matched = 0

        for kind in kinds:
            meta = _KIND_META_PREVIEW[kind]
            is_answer = (kind == "answers")
            label = meta["label"]

            print(f"\n{'=' * 55}")
            print(f"  {username} 的原创{label}")
            if keyword:
                print(f"  关键词过滤：{keyword}")
            print(f"{'=' * 55}")

            offset = 0
            is_end = False
            semaphore = asyncio.Semaphore(concurrency)
            items_previewed = 0

            while not is_end and (limit is None or total_matched < limit):
                url = (f"https://www.zhihu.com/api/v4/members/{username}/{meta['api']}"
                       f"?limit={PAGE_SIZE}&offset={offset}"
                       f"&include={quote(meta['include'], safe='')}")
                data = await _fetch_page(session, url, base_headers, semaphore,
                                         max_retries=max_retries or MAX_RETRIES)
                if data is None or "error" in data:
                    break

                paging = data.get("paging", {})
                is_end = paging.get("is_end", True)
                items = data.get("data", [])

                for item in items:
                    if keyword and keyword not in _item_title(item, is_answer):
                        continue
                    if limit is not None and total_matched >= limit:
                        break

                    title = _item_title(item, is_answer)
                    print(f"  [{total_matched + 1}] {title}")
                    total_matched += 1
                    items_previewed += 1

                offset += PAGE_SIZE
                if is_end:
                    break
                await asyncio.sleep(page_delay if page_delay is not None else PAGE_DELAY)

            print(f"  共 {items_previewed} 篇\n")

    print(f"总共 {total_matched} 篇")
    return total_matched
