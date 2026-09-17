"""主入口模块：CLI 参数解析与主处理流程"""

import argparse
import asyncio
import sys

from zhihu_exporter.config import DEFAULT_OUTPUT_DIR, DEFAULT_CONCURRENCY, _resolve_config_path, apply_config_defaults
from zhihu_exporter.utils import extract_username
from zhihu_exporter.auth import _acquire_cookie
from zhihu_exporter.export import _crawl_async
from zhihu_exporter.author import _crawl_author_async, MODE_TO_KINDS
from zhihu_exporter.column import _crawl_column_async, extract_column_id

# 自动识别专栏 URL（不需要 --mode column）
def _is_column_url(url):
    """判断 URL 是否为专栏链接（排除 zhuanlan.zhihu.com/p/ 单篇文章）"""
    import re
    # /column/xxx 肯定是专栏
    if re.search(r"/column/", url):
        return True
    # zhuanlan.zhihu.com 域名下，排除 /p/ 单文章页
    if re.search(r"zhuanlan\.zhihu\.com", url) and not re.search(r"zhuanlan\.zhihu\.com/p/", url):
        return True
    return False


# ============================================================
# 主处理函数（向后兼容的同步包装器）

# ============================================================

def main_function(user_url, cookie=None, cookie_file=None, output_dir=DEFAULT_OUTPUT_DIR,
                  limit=None, visible=False, no_scan=False,
                  incremental=True, fmt="md", concurrency=DEFAULT_CONCURRENCY,
                  page_delay=None, max_retries=None,
                  download_images=False, image_host="local",
                  gitee_token=None, gitee_repo=None, gitee_branch=None,
                  gitee_path_prefix=None,
                  mode="upvotes", keyword=None, preview=False,
                  only_answers=False, only_articles=False):
    """
    主处理函数：导出知乎内容为 Markdown 或 HTML。

    mode 决定抓取目标：
      - upvotes（默认）：导出用户**点赞过**的他人回答和文章（保留原行为）
      - articles：导出用户**自己创作**的全部文章
      - answers：导出用户**自己创作**的全部回答
      - all：同时导出原创文章与原创回答

    Args:
        user_url: 知乎用户主页 URL 或专栏 URL
        cookie: Cookie 字符串（可选）
        cookie_file: Cookie 文件路径（可选）
        output_dir: 输出根目录
        limit: 限制抓取条数（None 表示不限）
        visible: Playwright 扫码时是否显示浏览器窗口
        no_scan: 是否跳过 Playwright 扫码模式
        incremental: 是否启用增量机制（false = 全量重新抓取）
        fmt: 输出格式，"md"/"html"/"both"
        concurrency: 异步并发数
        download_images: 是否下载图片到本地/图床
        image_host: 图片托管方式，"local" 或 "gitee"
        gitee_token: Gitee 个人访问令牌（image_host=gitee 时必需）
        gitee_repo: Gitee 仓库，格式 "owner/repo"（image_host=gitee 时必需）
        gitee_branch: Gitee 分支名，默认 "master"
        gitee_path_prefix: Gitee 仓库中的路径前缀（可选）
        mode: 抓取模式，"upvotes"/"articles"/"answers"/"all"/"column"
        keyword: 关键词过滤（仅作者/专栏模式生效，仅导出标题包含该词的内容）
        only_answers: 仅导出赞同的回答（仅 upvotes 模式生效）
        only_articles: 仅导出赞同的文章（仅 upvotes 模式生效）

    Returns:
        点赞模式返回 tuple(answer_count, article_count)；
        作者/专栏模式返回新增条目数 int。
    """
    # 专栏模式：自动识别 URL 或显式 --mode column
    is_column_mode = (mode == "column") or _is_column_url(user_url)

    if is_column_mode:
        column_id = extract_column_id(user_url)
        if not column_id:
            print(f"错误：无法从 URL 提取专栏 ID：{user_url}")
            sys.exit(1)

        # 专栏模式：公开专栏可免 Cookie（游客模式），传了 Cookie 才走获取与校验流程
        cookie = _acquire_cookie(cookie, cookie_file, no_scan, visible) if (cookie or cookie_file) else ""

        print("=" * 50)
        print("  知乎专栏内容导出工具（专栏模式，支持增量，aiohttp 异步）")
        print("=" * 50)
        print(f"\n专栏链接：{user_url}")
        print(f"专栏 ID：{column_id}")
        print(f"登录状态：{'已提供 Cookie' if cookie else '游客模式（无 Cookie，仅限公开专栏）'}")
        if keyword:
            print(f"关键词过滤：{keyword}")
        print()

        img_cfg = None
        if download_images:
            img_cfg = {"enabled": True, "host": image_host}
            if image_host == "gitee":
                if not gitee_token or not gitee_repo:
                    print("错误：Gitee 模式需要 --gitee-token 和 --gitee-repo")
                    sys.exit(1)
                img_cfg["gitee_token"] = gitee_token
                img_cfg["gitee_repo"] = gitee_repo
                img_cfg["gitee_branch"] = gitee_branch or "master"
                if gitee_path_prefix:
                    img_cfg["gitee_path_prefix"] = gitee_path_prefix

        return asyncio.run(_crawl_column_async(
            column_id=column_id,
            cookie=cookie,
            output_dir=output_dir,
            limit=limit,
            incremental=incremental,
            fmt=fmt,
            concurrency=concurrency,
            page_delay=page_delay,
            max_retries=max_retries,
            image_config=img_cfg,
            keyword=keyword,
        ))

    # 用户模式（点赞 / 原创）
    username = extract_username(user_url)
    if not username:
        print(f"错误：无法从 URL 提取用户名：{user_url}")
        sys.exit(1)

    if mode not in ("upvotes",) + tuple(MODE_TO_KINDS.keys()):
        print(f"错误：未知的 mode：{mode}（可选：upvotes/articles/answers/all/column）")
        sys.exit(1)

    if only_answers and only_articles:
        print("错误：--only-answers 与 --only-articles 不能同时使用")
        sys.exit(1)

    is_author_mode = mode in MODE_TO_KINDS

    print("=" * 50)
    if is_author_mode:
        print("  知乎原创内容导出工具（作者模式，支持增量，aiohttp 异步）")
    else:
        print("  知乎点赞内容导出工具（支持增量，aiohttp 异步）")
    print("=" * 50)
    print(f"\n目标用户：{username}")
    print(f"主页链接：{user_url}")
    if is_author_mode:
        kinds = MODE_TO_KINDS[mode]
        print(f"抓取模式：{mode}（{'、'.join(_KIND_CN[k] for k in kinds)}）")
        if keyword:
            print(f"关键词过滤：{keyword}")
    elif only_answers:
        print("导出范围：仅赞同的回答")
    elif only_articles:
        print("导出范围：仅赞同的文章")

    cookie = _acquire_cookie(cookie, cookie_file, no_scan, visible)

    img_cfg = None
    if download_images:
        img_cfg = {"enabled": True, "host": image_host}
        if image_host == "gitee":
            if not gitee_token or not gitee_repo:
                print("错误：Gitee 模式需要 --gitee-token 和 --gitee-repo")
                sys.exit(1)
            img_cfg["gitee_token"] = gitee_token
            img_cfg["gitee_repo"] = gitee_repo
            img_cfg["gitee_branch"] = gitee_branch or "master"
            if gitee_path_prefix:
                img_cfg["gitee_path_prefix"] = gitee_path_prefix

    if is_author_mode:
        return asyncio.run(_crawl_author_async(
            username=username,
            cookie=cookie,
            output_dir=output_dir,
            limit=limit,
            incremental=incremental,
            fmt=fmt,
            concurrency=concurrency,
            page_delay=page_delay,
            max_retries=max_retries,
            image_config=img_cfg,
            kinds=MODE_TO_KINDS[mode],
            keyword=keyword,
        ))
    return asyncio.run(_crawl_async(
        username=username,
        cookie=cookie,
        output_dir=output_dir,
        limit=limit,
        incremental=incremental,
        fmt=fmt,
        concurrency=concurrency,
        page_delay=page_delay,
        max_retries=max_retries,
        image_config=img_cfg,
        only_answers=only_answers,
        only_articles=only_articles,
    ))


# 抓取模式的中文标签（用于日志）
_KIND_CN = {"articles": "文章", "answers": "回答"}

# ============================================================
# CLI 入口

# ============================================================

def main():
    """CLI入口函数"""
    parser = argparse.ArgumentParser(
        description="导出知乎用户的所有点赞回答和文章为本地 Markdown 文件"
                    "（支持增量爬取、Cookie/扫码双模式登录、aiohttp 异步并发、配置文件）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python zhihu_exporter.py https://www.zhihu.com/people/xxx
  python zhihu_exporter.py https://www.zhihu.com/people/xxx --cookie "your_cookie"
  python zhihu_exporter.py https://www.zhihu.com/people/xxx -o D:\\MyExports --limit 20
  python zhihu_exporter.py https://www.zhihu.com/people/xxx --no-incremental --visible
  python zhihu_exporter.py https://www.zhihu.com/people/xxx -f html
  python zhihu_exporter.py https://www.zhihu.com/people/xxx --config config.yaml  # --config 可省略：不传自动加载 config.yaml
  python zhihu_exporter.py https://www.zhihu.com/people/xxx --concurrency 10
  python zhihu_exporter.py https://www.zhihu.com/people/xxx --download-images
  python zhihu_exporter.py https://www.zhihu.com/people/xxx --download-images --image-host gitee --gitee-token TOKEN --gitee-repo owner/repo
  python zhihu_exporter.py https://www.zhihu.com/column/c_xxx                   # 导出专栏文章
  python zhihu_exporter.py https://zhuanlan.zhihu.com/c_xxx -f both              # 专栏 + 双格式
  python zhihu_exporter.py https://www.zhihu.com/column/c_xxx --keyword "关键词"  # 专栏 + 关键词过滤
        """,
    )

    # ---- 输入选项 ----
    input_group = parser.add_argument_group("输入选项")
    input_group.add_argument(
        "user_url",
        nargs="?",
        default=None,
        help="知乎用户主页 URL 或专栏 URL（例如 https://www.zhihu.com/people/xxx 或 https://www.zhihu.com/column/c_xxx）",
    )
    input_group.add_argument(
        "-c", "--cookie",
        default=None,
        help="知乎登录 Cookie 字符串（不提供则进入交互式登录流程）",
    )
    input_group.add_argument(
        "-C", "--cookie-file",
        default=None,
        help="从文件读取 Cookie（每行一对 name=value 或 Cookie 字符串）",
    )

    # ---- 配置文件选项 ----
    config_group = parser.add_argument_group("配置文件")
    config_group.add_argument(
        "--config", "-cfg",
        default=None,
        help="从 YAML 配置文件加载参数（默认自动加载 config.yaml，读不到回退 config.example.yaml；命令行参数优先级更高）",
    )

    # ---- 输出选项 ----
    output_group = parser.add_argument_group("输出选项")
    output_group.add_argument(
        "-o", "--output",
        default=DEFAULT_OUTPUT_DIR,
        help=f"输出根目录（默认: {DEFAULT_OUTPUT_DIR}）",
    )
    output_group.add_argument(
        "-f", "--format",
        choices=["md", "html", "both"],
        default="md",
        help="输出格式：md=Markdown 纯文本，html=HTML 富文本（保留原始排版、图片、样式），"
             "both=同时导出两种（默认: md）",
    )
    output_group.add_argument(
        "-l", "--limit",
        type=int,
        default=None,
        help="限制抓取条数，达到上限后停止（默认: 不限制）",
    )
    output_group.add_argument(
        "--download-images",
        action="store_true",
        help="下载文章/回答中的图片到本地或上传到 Gitee 图床",
    )
    output_group.add_argument(
        "--image-host",
        choices=["local", "gitee"],
        default="local",
        help="图片托管方式：local=下载到本地 assets/images/，gitee=上传到 Gitee 仓库（默认: local）",
    )
    output_group.add_argument(
        "--gitee-token",
        default=None,
        help="Gitee 个人访问令牌（--image-host gitee 时必需）",
    )
    output_group.add_argument(
        "--gitee-repo",
        default=None,
        help="Gitee 仓库名，格式 owner/repo（--image-host gitee 时必需）",
    )
    output_group.add_argument(
        "--gitee-branch",
        default="master",
        help="Gitee 仓库分支名（默认: master）",
    )
    output_group.add_argument(
        "--gitee-path-prefix",
        default=None,
        help="Gitee 仓库中存放图片的路径前缀（可选）",
    )

    # ---- 抓取选项 ----
    scrape_group = parser.add_argument_group("抓取选项")
    scrape_group.add_argument(
        "--mode",
        choices=["upvotes", "articles", "answers", "all", "column"],
        default="upvotes",
        help="抓取模式：upvotes=导出用户点赞过的他人内容（默认）；"
             "articles=导出用户自己创作的文章；answers=导出用户自己创作的回答；"
             "all=同时导出原创文章与原创回答；column=导出专栏全部文章"
             "（后三者免浏览器/免签名；专栏 URL 自动识别）",
    )
    scrape_group.add_argument(
        "--keyword",
        default=None,
        help="关键词过滤：仅导出标题包含该词的内容（仅 --mode articles/answers/all/column 生效）",
    )
    scrape_group.add_argument(
        "--only-answers",
        action="store_true",
        help="仅导出赞同的回答，跳过文章（仅 --mode upvotes 生效）",
    )
    scrape_group.add_argument(
        "--only-articles",
        action="store_true",
        help="仅导出赞同的文章，跳过回答（仅 --mode upvotes 生效）",
    )
    scrape_group.add_argument(
        "--incremental",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="增量模式开关（默认取配置文件 incremental，内置开启）；"
             "--no-incremental 禁用增量，全量重新抓取所有点赞内容",
    )
    scrape_group.add_argument(
        "--no-scan",
        action="store_true",
        help="跳过 Playwright 扫码模式，仅使用手动粘贴 Cookie（默认: 优先扫码）",
    )
    scrape_group.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"异步并发数，控制同时处理的条目数量（默认: {DEFAULT_CONCURRENCY}）",
    )

    # ---- 浏览器选项 ----
    browser_group = parser.add_argument_group("浏览器选项（Playwright 扫码时生效）")
    browser_group.add_argument(
        "--visible",
        action="store_true",
        help="扫码登录时显示浏览器窗口（默认: 后台运行）",
    )

    # ---- 配置文件加载（在 argparse 解析之前，先用配置文件设默认值）----
    # 自动加载：命令行 --config > 当前目录 config.yaml > config.example.yaml
    config_path = _resolve_config_path()
    if config_path:
        print(f"加载配置文件：{config_path}")
        apply_config_defaults(parser, config_path)

    args = parser.parse_args()

    if not args.user_url:
        print("错误：未提供用户主页 URL。请通过命令行参数或配置文件（user_url）指定。")
        sys.exit(1)

    try:
        main_function(
            user_url=args.user_url,
            cookie=args.cookie,
            cookie_file=args.cookie_file,
            output_dir=args.output,
            limit=args.limit,
            visible=args.visible,
            no_scan=args.no_scan,
            incremental=args.incremental if args.incremental is not None else True,
            page_delay=getattr(args, 'page_delay', None),
            max_retries=getattr(args, 'max_retries', None),
            fmt=args.format,
            concurrency=args.concurrency,
            download_images=args.download_images,
            image_host=args.image_host,
            gitee_token=args.gitee_token,
            gitee_repo=args.gitee_repo,
            gitee_branch=args.gitee_branch,
            gitee_path_prefix=args.gitee_path_prefix,
            mode=args.mode,
            keyword=args.keyword,
only_answers=args.only_answers,
            only_articles=args.only_articles,
        )
    except KeyboardInterrupt:
        print("\n\n操作被用户中断")
        sys.exit(130)
    except Exception as e:
        print(f"\n处理失败: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()

