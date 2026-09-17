"""专栏导出模块：抓取指定知乎专栏的全部文章。

知乎专栏 API：
  - GET /api/v4/columns/{column_id} → 专栏元信息（标题、描述、封面等）
  - GET /api/v4/columns/{column_id}/articles → 专栏文章列表（分页）

正文获取策略（与 author.py 一致）：
  在 include 中加入 data[*].content 后，列表接口直接返回完整正文，
  无需请求单篇详情接口（后者触发 x-zse-96 签名校验，返回 403 / 10003）。
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
from zhihu_exporter.export import _fetch_page, _write_item_sync
from zhihu_exporter.formatters import (
    format_html_author_article,
    format_md_author_article,
)
from zhihu_exporter.images import _process_images
from zhihu_exporter.progress import load_progress, save_progress
from zhihu_exporter.utils import get_headers, sanitize_filename

# 专栏文章列表接口 include 参数：直接取回正文（绕开单篇详情接口的签名校验）
_ARTICLE_INCLUDE = (
    "data[*].content,data[*].title,data[*].created,data[*].updated,"
    "data[*].author,data[*].url,data[*].image_url,"
    "data[*].voteup_count,data[*].comment_count,data[*].excerpt"
)

PAGE_SIZE = 20  # 列表接口每页条数

def extract_column_id(url):
    """从专栏 URL 中提取 column_id。

    支持的 URL 格式：
      - https://www.zhihu.com/column/c_xxx
      - https://zhuanlan.zhihu.com/c_xxx
    """
    import re
    # 优先匹配 /column/c_xxx 格式
    m = re.search(r"/column/([^/?&]+)", url)
    if m:
        return m.group(1)
    # 其次匹配 zhuanlan.zhihu.com/c_xxx 格式
    m = re.search(r"zhuanlan\.zhihu\.com/([^/?&]+)", url)
    if m and m.group(1) != "p":  # /p/xxx 是单篇文章，不是专栏
        return m.group(1)
    return None


async def _verify_cookie_simple(session, headers, column_id):
    """验证 Cookie 是否有效（请求专栏信息 API，同时验证 Cookie + 专栏存在性）"""
    try:
        async with session.get(
            f"https://www.zhihu.com/api/v4/columns/{column_id}",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status == 200:
                return True
            # 403 通常表示 Cookie 过期或风控
            if resp.status == 403:
                return False
            # 404 表示专栏不存在，直接退出
            if resp.status == 404:
                print(f"错误：专栏不存在（ID: {column_id}，HTTP 404）")
                sys.exit(1)
            return False
    except Exception:
        return False


async def _crawl_column_async(
    column_id, cookie, output_dir, limit, incremental,
    fmt, concurrency, page_delay=None, max_retries=None, image_config=None,
    keyword=None,
):
    """异步抓取指定专栏的全部文章。

    Args:
        column_id: 专栏 ID（如 c_2034948472441402964）
        cookie: 登录 Cookie 字符串
        output_dir: 输出根目录
        limit: 限制条数（None=不限）
        incremental: 是否启用增量
        fmt: 输出格式
        concurrency: 并发数
        page_delay: 翻页间隔
        max_retries: 单页最大重试次数
        image_config: 图片处理配置
        keyword: 标题关键词过滤

    Returns:
        int: 本次新增写入的条目数
    """
    if aiohttp is None:
        print("错误：缺少必要依赖 aiohttp")
        print("请运行：pip install aiohttp")
        sys.exit(1)

    referer_url = f"https://www.zhihu.com/column/{column_id}"
    base_headers = get_headers(referer_url)
    if cookie:
        base_headers["cookie"] = cookie

    async with aiohttp.ClientSession() as session:
        # --- 验证 Cookie（游客模式跳过；公开专栏接口本就不需要登录态）---
        if cookie:
            print("\n正在验证 Cookie...")
            if not await _verify_cookie_simple(session, base_headers, column_id):
                print("Cookie 验证失败，请检查 Cookie 是否有效。")
                sys.exit(1)
            print("Cookie 验证通过。")
        else:
            print("\n游客模式：未提供 Cookie，仅抓取公开可见内容；付费 / 需登录专栏请用 -c 或 -C 提供 Cookie。")

        # --- 获取专栏信息 ---
        print(f"\n正在获取专栏信息...")
        col_info = await _fetch_page(
            session,
            f"https://www.zhihu.com/api/v4/columns/{column_id}",
            base_headers,
            asyncio.Semaphore(1),  # 单独用临时信号量
            max_retries=max_retries or MAX_RETRIES,
        )
        if col_info is None or "error" in col_info:
            print(f"错误：无法获取专栏信息（ID: {column_id}）")
            print("请检查专栏 ID 是否正确。")
            sys.exit(1)

        col_title = col_info.get("title") or col_info.get("name") or column_id
        col_description = col_info.get("description", "")
        col_url = col_info.get("url", referer_url)
        # 登录态下该接口不返回计数字段（仅游客态返回），取不到时显示未知而非 0
        col_articles_count = (col_info.get("articles_count")
                              or col_info.get("items_count") or 0)
        print(f"专栏名称：{col_title}")
        print(f"专栏文章数：{col_articles_count or '未知（登录状态接口不返回总数）'}")
        print(f"专栏链接：{col_url}")

        # --- 准备输出目录 ---
        safe_name = sanitize_filename(col_title)[:40] or column_id
        output_root = os.path.join(output_dir, safe_name)

        if fmt == "both":
            active_formats = ["md", "html"]
            fmt_label = "MD+HTML"
        else:
            active_formats = [fmt]
            fmt_label = fmt.upper()

        fmt_configs = {}
        for f in active_formats:
            d = os.path.join(output_root, f"专栏文章_{f}")
            os.makedirs(d, exist_ok=True)
            fmt_configs[f] = {"dir": d, "ext": ".md" if f == "md" else ".html"}

        # --- 图片配置 ---
        if image_config and image_config.get("enabled"):
            if image_config.get("host") == "local":
                image_config["local_dir"] = os.path.join(output_root, "assets", "images")
                os.makedirs(image_config["local_dir"], exist_ok=True)
            print(f"图片处理：{image_config['host']} 模式已启用")
        else:
            image_config = None

        # --- 加载进度 ---
        progress_file = os.path.join(output_root, ".progress_column.json")
        if incremental:
            p = load_progress(progress_file, "column")
            last_time = p.get("last_activity_time", 0)
            prev_count = p.get("article_count", 0)
            if last_time > 0:
                lt_str = datetime.fromtimestamp(last_time).strftime("%Y-%m-%d %H:%M:%S")
                print(f"\n[增量模式] 上次已抓取至 {lt_str}（{prev_count} 篇）")
                print(f"将只抓取此时间之后的新文章（{fmt_label}）...")
            else:
                print(f"\n[全量模式] 首次运行，将抓取所有专栏文章（共约 {col_articles_count} 篇）...")
        else:
            last_time = 0
            print(f"\n[全量模式] 已禁用增量，将重新抓取所有文章（{fmt_label}）...")

        # --- 开始抓取 ---
        semaphore = asyncio.Semaphore(concurrency)
        offset = 0
        is_end = False
        new_count = 0
        seen = 0
        new_latest_time = last_time

        if keyword:
            print(f"关键词过滤：仅导出标题包含「{keyword}」的内容")

        print(f"\n开始抓取专栏 [{col_title}] 的文章...")

        while not is_end:
            url = (
                f"https://www.zhihu.com/api/v4/columns/{column_id}/articles"
                f"?limit={PAGE_SIZE}&offset={offset}&include={quote(_ARTICLE_INCLUDE, safe='')}"
            )
            data = await _fetch_page(session, url, base_headers, semaphore,
                                     max_retries=max_retries or MAX_RETRIES)
            if data is None:
                print("\n请求失败次数过多，中止。")
                break
            if "error" in data:
                print(f"\nAPI 返回错误：{data.get('error', {}).get('message', '未知错误')}")
                break

            paging = data.get("paging", {})
            is_end = paging.get("is_end", True)
            items = data.get("data", [])

            # 时间过滤 + 关键词过滤 + limit 截断
            batch = []
            page_latest_time = 0
            for item in items:
                created = item.get("created", 0)
                page_latest_time = max(page_latest_time, created)

                # 增量过滤
                if incremental and last_time > 0 and created <= last_time:
                    is_end = True
                    break

                if keyword and keyword not in (item.get("title") or ""):
                    continue

                if limit and seen + len(batch) >= limit:
                    break

                batch.append(item)

            # 并发处理本页条目
            page_new = 0
            if batch:
                tasks = [
                    _process_column_item(
                        session, item, fmt_configs, active_formats,
                        image_config, semaphore, incremental,
                    )
                    for item in batch
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for item, r in zip(batch, results):
                    if isinstance(r, Exception):
                        print(f"\n处理条目时出错：{r}")
                        continue
                    if r.get("new"):
                        page_new += 1
                        new_count += 1
                    seen += 1

            non_empty = sum(1 for it in items if it.get("content"))
            filtered_by_keyword = len(items) - len(batch) if keyword else 0
            detail_parts = []
            if keyword:
                detail_parts.append(f"命中 {len(batch)} 条")
            detail = f"，{' '.join(detail_parts)}" if detail_parts else ""
            page_no = offset // PAGE_SIZE + 1
            print(f"  第 {page_no} 页：返回 {len(items)} 条{detail}，新增 {page_new} 条（累计新增 {new_count}）")

            new_latest_time = max(new_latest_time, page_latest_time)

            offset += PAGE_SIZE
            if is_end:
                break
            if limit and seen >= limit:
                print(f"  已达到上限（{limit} 条），停止。")
                break
            await asyncio.sleep(page_delay if page_delay is not None else PAGE_DELAY)

        # 保存进度
        for f in active_formats:
            key = f"column_{f}"
            prev = load_progress(progress_file, key)
            prev_count = prev.get("article_count", 0)
            save_progress(progress_file, key, new_latest_time, 0, prev_count + new_count)

        print(f"\n========== 专栏导出完成 ==========")
        print(f"专栏：{col_title}")
        print(f"本次新增：{new_count} 篇")
        print(f"输出格式：{fmt_label}")
        print(f"输出目录：{output_root}")

        return new_count


async def _process_column_item(session, item, fmt_configs, active_formats,
                                image_config=None, request_semaphore=None,
                                skip_existing=False):
    """处理单条专栏文章：生成各格式内容、处理图片并并发写入文件。

    Returns:
        dict: {"new": bool}
    """
    target_id = str(item.get("id", ""))
    raw_title = item.get("title", "（无标题）")
    title = sanitize_filename(raw_title)

    filepaths = {}
    for f in active_formats:
        cfg = fmt_configs[f]
        filepaths[f] = os.path.join(cfg["dir"], f"{title}{cfg['ext']}")

    result = {
        "new": False,
        "new_per_format": {f: False for f in active_formats},
    }

    pending_formats = [f for f in active_formats
                       if not (skip_existing and os.path.exists(filepaths[f]))]
    if not pending_formats:
        return result

    # 生成内容（专栏文章的格式与作者原创文章完全一致）
    contents = {}
    for f in pending_formats:
        if f == "html":
            contents[f] = format_html_author_article(item)
        else:
            contents[f] = format_md_author_article(item)

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