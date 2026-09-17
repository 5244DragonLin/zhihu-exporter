"""核心导出模块：异步爬取、条目处理、文件写入"""

import asyncio
import os
import sys
from datetime import datetime

try:
    import aiohttp
except ImportError:
    aiohttp = None

from zhihu_exporter.config import PAGE_DELAY, RETRY_DELAY, MAX_RETRIES
from zhihu_exporter.utils import get_headers, sanitize_filename, build_activity_url
from zhihu_exporter.formatters import format_html_answer, format_html_article, format_md_answer, format_md_article
from zhihu_exporter.images import _process_images
from zhihu_exporter.progress import load_progress, save_progress

# ============================================================
# 异步 HTTP 请求工具

# ============================================================

async def _fetch_page(session, url, headers, semaphore, max_retries=MAX_RETRIES):
    """
    异步获取单页数据，带重试和 429 限流处理。

    Returns:
        (dict | None): 解析后的 JSON 数据，失败返回 None
    """
    for retry in range(max_retries):
        try:
            async with semaphore:
                async with session.get(
                    url, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        try:
                            return await resp.json()
                        except Exception:
                            return None
                    if resp.status == 429:
                        print(f"(被限流，等待 {RETRY_DELAY}s)", end=" ", flush=True)
                        await asyncio.sleep(RETRY_DELAY)
                    else:
                        print(f"(HTTP {resp.status})", end=" ", flush=True)
                        await asyncio.sleep(RETRY_DELAY)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            print(f"(网络错误: {e})", end=" ", flush=True)
            await asyncio.sleep(RETRY_DELAY)
    return None

async def _verify_cookie(session, username, headers):
    """
    验证 Cookie 是否有效。

    Returns:
        bool: Cookie 有效返回 True
    """
    try:
        async with session.get(
            build_activity_url(username), headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return "error" not in data
            return False
    except Exception:
        return False

# ============================================================
# 单条目异步写入

# ============================================================

def _write_item_sync(filepath, content):
    """同步写入单个文件（在线程池中执行），使用临时文件 + 原子重命名保证写入完整"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    tmp_path = filepath + ".tmp." + str(os.getpid())
    with open(tmp_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.replace(tmp_path, filepath)  # Windows 上原子覆盖替换
    return True

async def _process_item(session, item, format_configs, active_formats, image_config=None,
                        base_headers=None, request_semaphore=None, skip_existing=False):
    """
    异步处理单个点赞条目：为每种格式生成内容、处理图片并并发写入文件。

    Args:
        session: aiohttp.ClientSession
        image_config: 图片处理配置，None 或 {"enabled": True, "host": "local"|"gitee", "local_dir": ..., ...}
        base_headers: 请求头（用于查询问题详情 API）
        request_semaphore: 全局请求信号量（问题详情 / 图片下载与列表页共享并发额度）
        skip_existing: 目标文件已存在时跳过（增量补跑去重；全量模式传 False 以强制重写）
    """
    action = item.get("action_text", "")
    if action not in ("赞同了回答", "赞同了文章"):
        return {"new": False, "is_answer": False}

    is_answer = (action == "赞同了回答")
    target = item.get("target", {})
    activity_time = item.get("created_time", 0)
    time_upvoted = datetime.fromtimestamp(activity_time)
    date_str = time_upvoted.strftime("%Y-%m-%d")

    if is_answer:
        question = target.get("question", {})
        title = sanitize_filename(question.get("title", "无标题"))
    else:
        title = sanitize_filename(target.get("title", "无标题"))

    target_id = str(target.get("id", ""))

    # 计算各格式目标路径；增量模式下已存在的文件直接跳过（断点补跑时不重复请求与写入）
    filepaths = {}
    for f in active_formats:
        cfg = format_configs[f]
        file_dir = cfg["answers_dir"] if is_answer else cfg["articles_dir"]
        filepaths[f] = os.path.join(file_dir, f"{date_str}_{title}_{target_id}{cfg['ext']}")
    pending_formats = [f for f in active_formats
                       if not (skip_existing and os.path.exists(filepaths[f]))]
    if not pending_formats:
        return {
            "new": False,
            "new_per_format": {f: False for f in active_formats},
            "is_answer": is_answer,
            "activity_time": activity_time,
        }

    # 回答类型：查询问题详情（标签 + 问题说明）
    question_tags = []
    question_detail = ""
    if is_answer and base_headers:
        aid = target.get("id")
        if aid:
            try:
                async with request_semaphore:
                    async with session.get(
                        f"https://www.zhihu.com/api/v4/answers/{aid}?include=question.detail,question.topics",
                        headers=base_headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status == 200:
                            adata = await resp.json()
                            qdata = adata.get("question", {})
                            question_detail = qdata.get("detail", "") or ""
                            question_tags = [t.get("name", "") for t in qdata.get("topics", [])]
            except Exception:
                pass

    # 先生成需要写入的格式的内容
    contents = {}
    for f in pending_formats:
        if is_answer:
            contents[f] = format_html_answer(item, question_tags, question_detail) if f == "html" else format_md_answer(item, question_tags, question_detail)
        else:
            contents[f] = format_html_article(item) if f == "html" else format_md_article(item)

    # 如果有图片配置，下载替换图片 URL
    if image_config and image_config.get("enabled") and contents:
        contents = await _process_images(
            session=session,
            image_config=image_config,
            item_content=contents,
            target_id=target_id,
            request_semaphore=request_semaphore,
        )

    # 在线程池中并发写入文件
    loop = asyncio.get_running_loop()
    write_tasks = [loop.run_in_executor(None, _write_item_sync, filepaths[f], contents[f])
                   for f in pending_formats]
    results = await asyncio.gather(*write_tasks)

    new_per_format = {f: False for f in active_formats}
    for f, wrote in zip(pending_formats, results):
        new_per_format[f] = bool(wrote)

    return {
        "new": any(new_per_format.values()),
        "new_per_format": new_per_format,
        "is_answer": is_answer,
        "activity_time": activity_time,
    }

# ============================================================
# 异步核心爬取

# ============================================================

async def _crawl_async(
    username, cookie, output_dir, limit, incremental,
    fmt, concurrency, page_delay=None, max_retries=None, image_config=None,
    only_answers=False, only_articles=False,
):
    """
    异步核心爬取逻辑：使用 aiohttp 并发抓取知乎用户点赞内容。

    Args:
        username: 知乎用户名（URL Token）
        cookie: Cookie 字符串
        output_dir: 输出根目录
        limit: 限制条数（None=不限）
        incremental: 是否启用增量（false = 全量重抓）
        page_delay: 每页请求间隔秒数（None = 使用内置默认 0.8）
        max_retries: 单页最大重试次数（None = 使用内置默认 3）
        fmt: 输出格式
        concurrency: 并发数
        image_config: 图片处理配置，None 或 {"enabled": bool, "host": "local"|"gitee", ...}
        only_answers: 仅抓取赞同的回答，跳过文章
        only_articles: 仅抓取赞同的文章，跳过回答

    Returns:
        tuple: (answer_count, article_count)
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

        format_configs = {}
        for f in active_formats:
            if f == "md":
                cfg = {
                    "answers_dir": os.path.join(output_root, "赞同的回答_md"),
                    "articles_dir": os.path.join(output_root, "赞同的文章_md"),
                    "ext": ".md",
                }
            else:
                cfg = {
                    "answers_dir": os.path.join(output_root, "赞同的回答_html"),
                    "articles_dir": os.path.join(output_root, "赞同的文章_html"),
                    "ext": ".html",
                }
            os.makedirs(cfg["answers_dir"], exist_ok=True)
            os.makedirs(cfg["articles_dir"], exist_ok=True)
            format_configs[f] = cfg

        # --- 图片配置 ---
        if image_config and image_config.get("enabled"):
            if image_config.get("host") == "local":
                image_config["local_dir"] = os.path.join(output_root, "assets", "images")
                os.makedirs(image_config["local_dir"], exist_ok=True)
            print(f"图片处理：{image_config['host']} 模式已启用")
        else:
            image_config = None

        # --- 加载进度 ---
        progress_file = os.path.join(output_root, ".progress.json")

        if not incremental:
            last_time = 0
            prev_answers = 0
            prev_articles = 0
            print(f"\n[全量模式] 已禁用增量，将重新抓取所有点赞内容（{fmt_label}）...")
        else:
            min_last = None
            for f in active_formats:
                p = load_progress(progress_file, f)
                pt = p.get("last_activity_time", 0)
                if min_last is None or pt < min_last:
                    min_last = pt
            last_time = min_last or 0
            ref_p = load_progress(progress_file, active_formats[0])
            prev_answers = ref_p.get("answer_count", 0)
            prev_articles = ref_p.get("article_count", 0)

            if last_time > 0:
                last_time_str = datetime.fromtimestamp(last_time).strftime("%Y-%m-%d %H:%M:%S")
                print(f"\n[增量模式] 上次已抓取至 {last_time_str}（{prev_answers} 个回答 + {prev_articles} 篇文章）")
                print(f"将只抓取此时间之后的新点赞（{fmt_label}）...")
            else:
                print(f"\n[全量模式] 首次运行，将抓取所有点赞内容（{fmt_label}）...")

        # --- 开始抓取 ---
        # 按格式分别统计新增数量
        per_fmt_answers = {f: 0 for f in active_formats}
        per_fmt_articles = {f: 0 for f in active_formats}
        answer_count = 0   # 去重后的回答数（同一内容跨格式只计一次）
        article_count = 0
        total_items = 0
        new_latest_time = last_time
        skip_existing = incremental

        print(f"\n开始抓取用户 [{username}] 的点赞动态...")
        accepted_actions = []
        if not only_articles:
            accepted_actions.append("赞同了回答")
        if not only_answers:
            accepted_actions.append("赞同了文章")
        if only_answers:
            print("（仅处理赞同的回答）")
        elif only_articles:
            print("（仅处理赞同的文章）")

        url = build_activity_url(username)
        is_end = False
        stopped_early = False
        # 全局信号量：列表页 / 问题详情 / 图片下载共享，真实控制总并发
        semaphore = asyncio.Semaphore(concurrency)
        page_num = 0

        try:
            while not is_end:
                page_num += 1
                print(f"正在获取第 {page_num} 页...", end=" ", flush=True)

                data = await _fetch_page(session, url, base_headers, semaphore,
                                         max_retries=max_retries or MAX_RETRIES)
                if data is None:
                    print("\n请求失败次数过多，中止。请检查 Cookie 是否有效。")
                    break

                if "error" in data:
                    print(f"\nAPI 返回错误：{data.get('error', {}).get('message', '未知错误')}")
                    print("请检查 Cookie 是否有效或是否被风控。")
                    break

                is_end = data.get("paging", {}).get("is_end", True)
                url = data.get("paging", {}).get("next", "")
                items = data.get("data", [])

                # 筛选点赞条目
                candidates = []
                page_latest_time = 0
                for item in items:
                    action = item.get("action_text", "")
                    if action not in accepted_actions:
                        continue

                    activity_time = item.get("created_time", 0)
                    page_latest_time = max(page_latest_time, activity_time)

                    if last_time > 0 and activity_time <= last_time:
                        stopped_early = True
                        break

                    if limit and total_items + len(candidates) >= limit:
                        stopped_early = True
                        break

                    candidates.append(item)

                # 并发处理本页条目
                page_new_count = 0
                if candidates:
                    tasks = [_process_item(session, c, format_configs, active_formats,
                                           image_config, base_headers, semaphore, skip_existing)
                             for c in candidates]
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    for r in results:
                        if isinstance(r, Exception):
                            print(f"\n处理条目时出错：{r}")
                            continue
                        if r.get("new"):
                            page_new_count += 1
                            total_items += 1
                            # 按格式分别计数
                            new_per_fmt = r.get("new_per_format", {})
                            if r.get("is_answer"):
                                answer_count += 1
                                for f in active_formats:
                                    if new_per_fmt.get(f):
                                        per_fmt_answers[f] += 1
                            else:
                                article_count += 1
                                for f in active_formats:
                                    if new_per_fmt.get(f):
                                        per_fmt_articles[f] += 1

                    # 本页全部处理完成后才推进时间戳：
                    # 中途失败/中断时时间戳停在上一完整页，下次运行从本页重试，不丢数据
                    new_latest_time = max(new_latest_time, page_latest_time)

                print(f"本页新增 {page_new_count} 条（累计：{answer_count} 个回答 + {article_count} 篇文章）")

                if stopped_early:
                    if limit and total_items >= limit:
                        print(f"已达到上限 ({limit} 条)，停止。")
                    else:
                        print("已到达上次记录时间，停止翻页。")
                    break

                if page_new_count == 0 and not is_end:
                    print("本页无点赞动态，继续翻页...")

                await asyncio.sleep(page_delay if page_delay is not None else PAGE_DELAY)
        finally:
            # 无论正常结束、请求失败还是 Ctrl+C 中断，都保存进度
            for f in active_formats:
                p = load_progress(progress_file, f)
                prev_f_answers = p.get("answer_count", 0)
                prev_f_articles = p.get("article_count", 0)
                total_f_answers = prev_f_answers + per_fmt_answers[f]
                total_f_articles = prev_f_articles + per_fmt_articles[f]

                if limit and total_items >= limit:
                    save_progress(progress_file, f, last_time, total_f_answers, total_f_articles)
                    if f == active_formats[0]:
                        print(f"[注意] 因 --limit {limit} 截断，进度时间戳未推进，下次运行将继续从 "
                              f"{datetime.fromtimestamp(last_time).strftime('%Y-%m-%d %H:%M:%S')} 开始")
                else:
                    save_progress(progress_file, f, new_latest_time, total_f_answers, total_f_articles)

        print(f"\n========== 导出完成 ==========")
        print(f"本次新增（去重）：{answer_count} 个回答 + {article_count} 篇文章")
        print(f"输出格式：{fmt_label}")
        # 按格式展示实际写入的文件数
        for f in active_formats:
            print(f"  {f.upper()} 新增：{per_fmt_answers[f]} 个回答 + {per_fmt_articles[f]} 篇文章")

        for f in active_formats:
            cfg = format_configs[f]
            print(f"  {f.upper()} 回答目录：{cfg['answers_dir']}")
            print(f"  {f.upper()} 文章目录：{cfg['articles_dir']}")

        # --- 生成统计报告（无新增时跳过，避免全量重扫上千个文件）---
        if answer_count == 0 and article_count == 0:
            print("\n本次无新增内容，跳过统计报告生成（内容未变化，报告保持上次状态）。")
        else:
            from zhihu_exporter.summary import generate_summary
            generate_summary(
                output_root=output_root,
                active_formats=active_formats,
                per_fmt_answers=per_fmt_answers,
                per_fmt_articles=per_fmt_articles,
                answer_count=answer_count,
                article_count=article_count,
                fmt_label=fmt_label,
            )

        return answer_count, article_count

