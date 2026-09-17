"""格式化模块：Markdown / HTML 富文本输出"""

import re
from datetime import datetime
from zhihu_exporter.utils import process_content, favicon_link_html, extract_cover_image


def _de_lazy_images(content):
    """把知乎懒加载 img 静态化：src 为占位 SVG、真图在 data-actualsrc 时，
    将 src 替换为真实图片 URL 并移除 lazy class（静态页面无知乎 JS 无法自动加载）。"""
    if not content:
        return content

    def repl(m):
        tag = m.group(0)
        asrc = re.search(r'data-actualsrc="([^"]+)"', tag)
        if not asrc or ("data:image/svg" not in tag and "lazy" not in tag):
            return tag
        # 1) src 换成真实图
        tag = re.sub(r'src="[^"]*"', 'src="%s"' % asrc.group(1), tag, count=1)
        # 2) 移除 lazy class
        tag = tag.replace("zh-lightbox-thumb lazy", "zh-lightbox-thumb")
        tag = re.sub(r'\s+lazy(?="|\s)', "", tag)
        return tag

    return re.sub(r'<img[^>]*data-actualsrc="[^"]+"[^>]*>', repl, content)


def _html_to_plain(html_str):
    """将简单 HTML 转为纯文本（适配知乎问题说明中的 br/p 标签）"""
    if not html_str:
        return ""
    text = re.sub(r'<br\s*/?>', '\n', html_str)
    text = re.sub(r'</p>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# ============================================================
# HTML 富文本模板

# ============================================================

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{favicon_link}
<title>{title}</title>
<style>
  body {{
    max-width: 800px;
    margin: 40px auto;
    padding: 0 20px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC",
                 "PingFang SC", "Microsoft YaHei", sans-serif;
    font-size: 16px;
    line-height: 1.8;
    color: #1a1a1a;
    background: #fff;
  }}
  h1 {{ font-size: 24px; margin-bottom: 0.3em; }}
  .meta {{
    color: #8590a6;
    font-size: 14px;
    margin: 0.5em 0 1.5em;
    line-height: 1.8;
  }}
  .meta a {{ color: #175199; text-decoration: none; }}
  .meta a:hover {{ text-decoration: underline; }}
  .meta-item {{ display: inline-block; margin-right: 1.5em; }}
  hr.divider {{ border: none; border-top: 1px solid #eee; margin: 1.5em 0; }}
  .content img {{ max-width: 100%; height: auto; border-radius: 4px; }}
  .content blockquote {{
    border-left: 3px solid #ccc;
    padding-left: 1em;
    margin-left: 0;
    color: #646464;
  }}
  .content figure {{ margin: 1em 0; }}
  .content figcaption {{ color: #8590a6; font-size: 14px; text-align: center; }}
  .content pre {{
    background: #f6f8fa;
    padding: 1em;
    border-radius: 4px;
    overflow-x: auto;
    font-size: 14px;
  }}
  .content code {{
    background: #f6f8fa;
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 90%;
  }}
  .content pre code {{ background: none; padding: 0; }}
  .content a {{ color: #175199; }}
  .question-detail {{
    margin-top: 0.8em;
    padding: 12px 16px;
    background: #f6f8fa;
    border-radius: 6px;
    font-size: 14px;
    color: #444;
    line-height: 1.7;
  }}
  .cover {{ margin: 1em 0; }}
  .cover img {{ max-width: 100%; height: auto; border-radius: 6px; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">
{meta_html}
</div>
<hr class="divider">
{cover_html}
<div class="content">
{content_html}
</div>
</body>
</html>"""

def _build_meta_html(type_label, author_name, author_id, time_upvoted,
                     time_created, voteup_count, comment_count, answer_url,
                     question_url=None, question_title=None,
                     question_tags=None, question_detail=None):
    """构建 HTML 格式的元信息块（含问题标签和问题说明）"""
    parts = []
    parts.append(f'<span class="meta-item"><strong>类型</strong>：{type_label}</span>')
    if author_name:
        parts.append(
            f'<span class="meta-item"><strong>作者</strong>：'
            f'<a href="https://www.zhihu.com/people/{author_id}" target="_blank">{author_name}</a></span>'
        )
    else:
        parts.append('<span class="meta-item"><strong>作者</strong>：匿名用户</span>')
    parts.append(f'<span class="meta-item"><strong>赞同时间</strong>：{time_upvoted}</span>')
    parts.append(f'<span class="meta-item"><strong>创建时间</strong>：{time_created}</span>')
    parts.append(f'<span class="meta-item"><strong>赞同数</strong>：{voteup_count}</span>')
    parts.append(f'<span class="meta-item"><strong>评论数</strong>：{comment_count}</span>')
    if answer_url:
        parts.append(
            f'<span class="meta-item"><a href="{answer_url}" target="_blank">原文链接</a></span>'
        )
    if question_url and question_title:
        parts.append(
            f'<span class="meta-item"><strong>问题</strong>：'
            f'<a href="{question_url}" target="_blank">{question_title}</a></span>'
        )
    if question_tags:
        tags_str = "、".join(question_tags)
        parts.append(f'<span class="meta-item"><strong>标签</strong>：{tags_str}</span>')

    meta_html = "<br>".join(parts)

    if question_detail:
        meta_html += (
            f'<div class="question-detail">'
            f'<strong>问题说明</strong>：<br>{question_detail}</div>'
        )

    return meta_html

def format_html_answer(item, question_tags=None, question_detail=None):
    """格式化赞同回答为 HTML 富文本（正文前展示封面，无图则省略）"""
    target = item.get("target", {})
    question = target.get("question", {})
    author = target.get("author", {})
    time_upvoted = datetime.fromtimestamp(item.get("created_time", 0))
    time_created = datetime.fromtimestamp(target.get("created_time", 0))

    title = question.get("title", "（无标题）")
    meta_html = _build_meta_html(
        type_label="赞同的回答",
        author_name=author.get("name"),
        author_id=author.get("id", ""),
        time_upvoted=time_upvoted.strftime("%Y-%m-%d %H:%M:%S"),
        time_created=time_created.strftime("%Y-%m-%d %H:%M:%S"),
        voteup_count=target.get("voteup_count", 0),
        comment_count=target.get("comment_count", 0),
        answer_url=f"https://www.zhihu.com/question/{question.get('id', '')}/answer/{target.get('id', '')}",
        question_url=f"https://www.zhihu.com/question/{question.get('id', '')}",
        question_title=title,
        question_tags=question_tags,
        question_detail=question_detail,
    )
    cover = extract_cover_image(target, is_answer=True)
    cover_html = f'<div class="cover"><img src="{cover}" alt="cover"></div>' if cover else ""
    return HTML_TEMPLATE.format(
        favicon_link=favicon_link_html(),
        title=title,
        meta_html=meta_html,
        cover_html=cover_html,
        content_html=_de_lazy_images(target.get("content", "") or "（无内容）"),
    )

def format_html_article(item):
    """格式化赞同文章为 HTML 富文本（正文前展示封面，无图则省略）"""
    target = item.get("target", {})
    author = target.get("author", {})
    time_upvoted = datetime.fromtimestamp(item.get("created_time", 0))
    time_created = datetime.fromtimestamp(target.get("created", 0))

    title = target.get("title", "（无标题）")
    meta_html = _build_meta_html(
        type_label="赞同的文章",
        author_name=author.get("name"),
        author_id=author.get("id", ""),
        time_upvoted=time_upvoted.strftime("%Y-%m-%d %H:%M:%S"),
        time_created=time_created.strftime("%Y-%m-%d %H:%M:%S"),
        voteup_count=target.get("voteup_count", 0),
        comment_count=target.get("comment_count", 0),
        answer_url=target.get("url", ""),
    )
    cover = extract_cover_image(target, is_answer=False)
    cover_html = f'<div class="cover"><img src="{cover}" alt="cover"></div>' if cover else ""
    return HTML_TEMPLATE.format(
        favicon_link=favicon_link_html(),
        title=title,
        meta_html=meta_html,
        cover_html=cover_html,
        content_html=_de_lazy_images(target.get("content", "") or "（无内容）"),
    )

def format_md_answer(item, question_tags=None, question_detail=None):
    """格式化赞同回答为 Markdown（文末追加封面图，无图则省略）"""
    target = item.get("target", {})
    question = target.get("question", {})
    author = target.get("author", {})
    time_upvoted = datetime.fromtimestamp(item.get("created_time", 0))
    time_created = datetime.fromtimestamp(target.get("created_time", 0))

    lines = []
    lines.append(f"# {question.get('title', '（无标题）')}")
    lines.append("")
    lines.append("- **类型**：赞同的回答")
    lines.append(f"- **作者**：{author.get('name', '匿名用户')}")
    lines.append(f"- **作者主页**：https://www.zhihu.com/people/{author.get('id', '')}")
    lines.append(f"- **赞同时间**：{time_upvoted.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **回答创建时间**：{time_created.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **赞同数**：{target.get('voteup_count', 0)}")
    lines.append(f"- **评论数**：{target.get('comment_count', 0)}")
    lines.append(
        f"- **原文链接**：https://www.zhihu.com/question/{question.get('id', '')}/answer/{target.get('id', '')}"
    )
    lines.append(f"- **问题链接**：https://www.zhihu.com/question/{question.get('id', '')}")
    if question_tags:
        lines.append(f"- **标签**：{'、'.join(question_tags)}")
    lines.append("")
    lines.append("---")
    lines.append("")
    if question_detail:
        plain_detail = _html_to_plain(question_detail)
        lines.append("## 问题说明")
        lines.append("")
        lines.append(f"> {plain_detail}")
        lines.append("")
    lines.append("## 问题原文")
    lines.append("")
    lines.append(f"> {question.get('title', '（无标题）')}")
    lines.append("")
    lines.append("## 回答正文")
    lines.append("")
    lines.append(process_content(_de_lazy_images(target.get("content", ""))))
    lines.append("")
    cover = extract_cover_image(target, is_answer=True)
    if cover:
        lines.append("---")
        lines.append("")
        lines.append(f"![cover]({cover})")
        lines.append("")
    return "\n".join(lines)

# ============================================================
# 作者原创内容格式化（原创文章 / 原创回答）
# 数据来源：/api/v4/members/{token}/articles 与 /answers 列表接口（正文已内嵌）
# ============================================================

def _author_meta(target):
    """从作者原创条目中提取作者信息"""
    author = target.get("author") or {}
    name = author.get("name") or "匿名用户"
    url_token = author.get("url_token") or author.get("id") or ""
    return name, url_token


def format_md_author_article(target):
    """格式化作者原创文章为 Markdown"""
    name, url_token = _author_meta(target)
    time_created = datetime.fromtimestamp(target.get("created", 0) or 0)
    time_updated = datetime.fromtimestamp(target.get("updated", 0) or 0)
    url = target.get("url") or f"https://zhuanlan.zhihu.com/p/{target.get('id', '')}"

    lines = []
    lines.append(f"# {target.get('title', '（无标题）')}")
    lines.append("")
    lines.append("- **类型**：原创文章")
    lines.append(f"- **作者**：{name}")
    lines.append(f"- **作者主页**：https://www.zhihu.com/people/{url_token}")
    lines.append(f"- **发布时间**：{time_created.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **更新时间**：{time_updated.strftime('%Y-%m-%d %H:%M:%S')}")
    if target.get("voteup_count") is not None:
        lines.append(f"- **赞同数**：{target.get('voteup_count')}")
    if target.get("comment_count") is not None:
        lines.append(f"- **评论数**：{target.get('comment_count')}")
    lines.append(f"- **原文链接**：{url}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 文章正文")
    lines.append("")
    lines.append(process_content(_de_lazy_images(target.get("content", ""))))
    lines.append("")
    cover = extract_cover_image(target, is_answer=False)
    if cover:
        lines.append("---")
        lines.append("")
        lines.append(f"![cover]({cover})")
        lines.append("")
    return "\n".join(lines)


def format_html_author_article(target):
    """格式化作者原创文章为 HTML 富文本"""
    name, url_token = _author_meta(target)
    time_created = datetime.fromtimestamp(target.get("created", 0) or 0)
    time_updated = datetime.fromtimestamp(target.get("updated", 0) or 0)
    url = target.get("url") or f"https://zhuanlan.zhihu.com/p/{target.get('id', '')}"
    title = target.get("title", "（无标题）")

    parts = []
    parts.append('<span class="meta-item"><strong>类型</strong>：原创文章</span>')
    parts.append(
        f'<span class="meta-item"><strong>作者</strong>：'
        f'<a href="https://www.zhihu.com/people/{url_token}" target="_blank">{name}</a></span>'
    )
    parts.append(f'<span class="meta-item"><strong>发布时间</strong>：{time_created.strftime("%Y-%m-%d %H:%M:%S")}</span>')
    parts.append(f'<span class="meta-item"><strong>更新时间</strong>：{time_updated.strftime("%Y-%m-%d %H:%M:%S")}</span>')
    if target.get("voteup_count") is not None:
        parts.append(f'<span class="meta-item"><strong>赞同数</strong>：{target.get("voteup_count")}</span>')
    if target.get("comment_count") is not None:
        parts.append(f'<span class="meta-item"><strong>评论数</strong>：{target.get("comment_count")}</span>')
    parts.append(f'<span class="meta-item"><a href="{url}" target="_blank">原文链接</a></span>')

    cover = extract_cover_image(target, is_answer=False)
    cover_html = f'<div class="cover"><img src="{cover}" alt="cover"></div>' if cover else ""
    return HTML_TEMPLATE.format(
        favicon_link=favicon_link_html(),
        title=title,
        meta_html="<br>".join(parts),
        cover_html=cover_html,
        content_html=_de_lazy_images(target.get("content", "") or "（无内容）"),
    )


def format_md_author_answer(target):
    """格式化作者原创回答为 Markdown"""
    name, url_token = _author_meta(target)
    question = target.get("question") or {}
    q_title = question.get("title", "（无标题）")
    time_created = datetime.fromtimestamp(target.get("created_time", 0) or 0)
    time_updated = datetime.fromtimestamp(target.get("updated_time", 0) or 0)
    answer_url = (f"https://www.zhihu.com/question/{question.get('id', '')}"
                  f"/answer/{target.get('id', '')}")

    lines = []
    lines.append(f"# {q_title}")
    lines.append("")
    lines.append("- **类型**：原创回答")
    lines.append(f"- **作者**：{name}")
    lines.append(f"- **作者主页**：https://www.zhihu.com/people/{url_token}")
    lines.append(f"- **回答时间**：{time_created.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **更新时间**：{time_updated.strftime('%Y-%m-%d %H:%M:%S')}")
    if target.get("voteup_count") is not None:
        lines.append(f"- **赞同数**：{target.get('voteup_count')}")
    if target.get("comment_count") is not None:
        lines.append(f"- **评论数**：{target.get('comment_count')}")
    lines.append(f"- **原文链接**：{answer_url}")
    lines.append(f"- **问题链接**：https://www.zhihu.com/question/{question.get('id', '')}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 问题")
    lines.append("")
    lines.append(f"> {q_title}")
    lines.append("")
    lines.append("## 回答正文")
    lines.append("")
    lines.append(process_content(_de_lazy_images(target.get("content", ""))))
    lines.append("")
    return "\n".join(lines)


def format_html_author_answer(target):
    """格式化作者原创回答为 HTML 富文本"""
    name, url_token = _author_meta(target)
    question = target.get("question") or {}
    q_title = question.get("title", "（无标题）")
    time_created = datetime.fromtimestamp(target.get("created_time", 0) or 0)
    time_updated = datetime.fromtimestamp(target.get("updated_time", 0) or 0)
    answer_url = (f"https://www.zhihu.com/question/{question.get('id', '')}"
                  f"/answer/{target.get('id', '')}")

    parts = []
    parts.append('<span class="meta-item"><strong>类型</strong>：原创回答</span>')
    parts.append(
        f'<span class="meta-item"><strong>作者</strong>：'
        f'<a href="https://www.zhihu.com/people/{url_token}" target="_blank">{name}</a></span>'
    )
    parts.append(f'<span class="meta-item"><strong>回答时间</strong>：{time_created.strftime("%Y-%m-%d %H:%M:%S")}</span>')
    parts.append(f'<span class="meta-item"><strong>更新时间</strong>：{time_updated.strftime("%Y-%m-%d %H:%M:%S")}</span>')
    if target.get("voteup_count") is not None:
        parts.append(f'<span class="meta-item"><strong>赞同数</strong>：{target.get("voteup_count")}</span>')
    if target.get("comment_count") is not None:
        parts.append(f'<span class="meta-item"><strong>评论数</strong>：{target.get("comment_count")}</span>')
    parts.append(f'<span class="meta-item"><a href="{answer_url}" target="_blank">原文链接</a></span>')
    parts.append(
        f'<span class="meta-item"><strong>问题</strong>：'
        f'<a href="https://www.zhihu.com/question/{question.get("id", "")}" target="_blank">{q_title}</a></span>'
    )

    return HTML_TEMPLATE.format(
        favicon_link=favicon_link_html(),
        title=q_title,
        meta_html="<br>".join(parts),
        cover_html="",
        content_html=_de_lazy_images(target.get("content", "") or "（无内容）"),
    )


def format_md_article(item):
    """格式化赞同文章为 Markdown（文末追加封面图，无图则省略）"""
    target = item.get("target", {})
    author = target.get("author", {})
    time_upvoted = datetime.fromtimestamp(item.get("created_time", 0))
    time_created = datetime.fromtimestamp(target.get("created", 0))

    lines = []
    lines.append(f"# {target.get('title', '（无标题）')}")
    lines.append("")
    lines.append("- **类型**：赞同的文章")
    lines.append(f"- **作者**：{author.get('name', '匿名用户')}")
    lines.append(f"- **作者主页**：https://www.zhihu.com/people/{author.get('id', '')}")
    lines.append(f"- **赞同时间**：{time_upvoted.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **文章创建时间**：{time_created.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- **赞同数**：{target.get('voteup_count', 0)}")
    lines.append(f"- **评论数**：{target.get('comment_count', 0)}")
    lines.append(f"- **原文链接**：{target.get('url', '')}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 文章标题")
    lines.append("")
    lines.append(f"> {target.get('title', '（无标题）')}")
    lines.append("")
    lines.append("## 文章正文")
    lines.append("")
    lines.append(process_content(_de_lazy_images(target.get("content", ""))))
    lines.append("")
    cover = extract_cover_image(target, is_answer=False)
    if cover:
        lines.append("---")
        lines.append("")
        lines.append(f"![cover]({cover})")
        lines.append("")
    return "\n".join(lines)

