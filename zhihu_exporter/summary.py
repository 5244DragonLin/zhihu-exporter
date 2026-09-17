"""统计报告模块：生成全量统计 HTML/MD 报告和作者独立页面"""

import hashlib
import os
import re
from collections import Counter, defaultdict
from datetime import datetime

from zhihu_exporter.categories import classify_tags, split_tags
from zhihu_exporter.utils import FAVICON_DATA_URI, favicon_link_html

# ============================================================
# HTML 转义（避免外部依赖）

# ============================================================

def _esc_html(text):
    """基本的 HTML 实体转义"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ============================================================
# 文件系统扫描
# ============================================================

_AUTHOR_PATTERN = re.compile(r'<strong>作者</strong>：(?:<a[^>]*>([^<]*)</a>|(匿名用户))')
_VOTEUP_PATTERN = re.compile(r'<strong>赞同数</strong>：(\d+)')
_TITLE_PATTERN = re.compile(r'<h1>(.*?)</h1>')
_DATE_PATTERN = re.compile(r'^(\d{4}-\d{2})')
_HTML_TAGS_PATTERN = re.compile(r'<strong>标签</strong>：([^<]+)')
_HTML_QUESTION_PATTERN = re.compile(r'<strong>问题</strong>：<a href="([^"]+)"[^>]*>([^<]+)</a>')
_HTML_VOTETIME_PATTERN = re.compile(r'<strong>赞同时间</strong>：([^<]+)')
_MD_TAGS_PATTERN = re.compile(r'^- \*\*标签\*\*：(.+)$')
_MD_QUESTION_PATTERN = re.compile(r'^- \*\*问题链接\*\*：(.+)$')
_MD_VOTETIME_PATTERN = re.compile(r'^- \*\*赞同时间\*\*：(.+)$')


def _scan_html_files(output_root):
    """扫描 HTML 输出目录，提取所有条目的作者和赞同数等信息。

    Returns:
        dict: {
            "total_entries": 全量条目总数,
            "top_voteups": 赞同数 Top 50 列表,
            "top_authors": 作者排行 Top 10,
            "date_distribution": [(YYYY-MM, count), ...],
            "all_entries": 全部条目列表,
        }
    """
    html_answers = os.path.join(output_root, "赞同的回答_html")
    html_articles = os.path.join(output_root, "赞同的文章_html")

    all_entries = []
    date_counter = Counter()
    category_counter = Counter()
    answer_files = 0
    article_files = 0

    for dir_path in [html_answers, html_articles]:
        if not os.path.isdir(dir_path):
            continue
        is_answer_dir = (dir_path == html_answers)
        for fname in sorted(os.listdir(dir_path)):
            if not fname.endswith(".html"):
                continue
            filepath = os.path.join(dir_path, fname)
            if is_answer_dir:
                answer_files += 1
            else:
                article_files += 1

            # 提取日期
            date_match = _DATE_PATTERN.match(fname)
            date_str = date_match.group(1) if date_match else "unknown"
            date_counter[date_str] += 1

            # 读取 HTML 提取元信息
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    html_content = f.read(100000)
            except Exception:
                continue

            title_m = _TITLE_PATTERN.search(html_content)
            title = title_m.group(1) if title_m else fname

            author_m = _AUTHOR_PATTERN.search(html_content)
            if author_m:
                author_name = author_m.group(1) if author_m.group(1) else "匿名用户"
            else:
                author_name = ""

            voteup_m = _VOTEUP_PATTERN.search(html_content)
            voteup = int(voteup_m.group(1)) if voteup_m else 0

            tags_m = _HTML_TAGS_PATTERN.search(html_content)
            tags = split_tags(tags_m.group(1)) if tags_m else []

            vt_m = _HTML_VOTETIME_PATTERN.search(html_content)
            vote_time = vt_m.group(1).strip() if vt_m else ""

            q_m = _HTML_QUESTION_PATTERN.search(html_content)
            question_url = q_m.group(1) if q_m else ""
            # 文章无"问题"字段时，回退用条目标题做手动覆盖匹配
            question_title = q_m.group(2) if q_m else title
            category = classify_tags(tags, question_url=question_url, question_title=question_title)
            category_counter[category] += 1

            all_entries.append({
                "author_name": author_name,
                "voteup": voteup,
                "title": title,
                "html_path": filepath,
                "date": date_str,
                "tags": tags,
                "category": category,
                "question_url": question_url,
                "vote_time": vote_time,
            })

    # 赞同数排行 Top 50
    top_voteups = sorted(all_entries, key=lambda e: e["voteup"], reverse=True)[:50]

    # 作者排行 Top 10
    author_counter = Counter(e["author_name"] or "匿名用户" for e in all_entries)
    top_authors = author_counter.most_common(10)

    # 日期分布按时间排序
    sorted_dates = sorted(date_counter.items(), key=lambda x: x[0])

    return {
        "total_entries": len(all_entries),
        "total_answers": answer_files,
        "total_articles": article_files,
        "top_voteups": top_voteups,
        "top_authors": top_authors,
        "date_distribution": sorted_dates,
        "category_distribution": category_counter.most_common(),
        "all_entries": all_entries,
    }


# ============================================================
# MD 文件系统扫描
# ============================================================

_MD_TITLE_PATTERN = re.compile(r'^# (.+)$')
_MD_AUTHOR_PATTERN = re.compile(r'^- \*\*作者\*\*：(.+)$')
_MD_VOTEUP_PATTERN = re.compile(r'^- \*\*赞同数\*\*：(\d+)$')


def _scan_md_files(output_root):
    """扫描 MD 输出目录，提取所有条目的作者和赞同数等信息。

    Returns:
        dict: 与 _scan_html_files 结构相同
    """
    md_answers = os.path.join(output_root, "赞同的回答_md")
    md_articles = os.path.join(output_root, "赞同的文章_md")

    all_entries = []
    date_counter = Counter()
    category_counter = Counter()
    answer_files = 0
    article_files = 0

    for dir_path in [md_answers, md_articles]:
        if not os.path.isdir(dir_path):
            continue
        is_answer_dir = (dir_path == md_answers)
        for fname in sorted(os.listdir(dir_path)):
            if not fname.endswith(".md"):
                continue
            filepath = os.path.join(dir_path, fname)
            if is_answer_dir:
                answer_files += 1
            else:
                article_files += 1

            # 提取日期
            date_match = _DATE_PATTERN.match(fname)
            date_str = date_match.group(1) if date_match else "unknown"
            date_counter[date_str] += 1

            # 读取 MD 提取元信息（只读前 30 行，元数据都在文件头部）
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    lines = [f.readline() for _ in range(30)]
            except Exception:
                continue

            title = fname
            author_name = ""
            voteup = 0
            tags = []
            question_url = ""
            vote_time = ""

            for line in lines:
                if not title or title == fname:
                    t_m = _MD_TITLE_PATTERN.match(line)
                    if t_m:
                        title = t_m.group(1)
                        continue
                if not author_name:
                    a_m = _MD_AUTHOR_PATTERN.match(line)
                    if a_m:
                        author_name = a_m.group(1).strip()
                        continue
                if not vote_time:
                    vt_m = _MD_VOTETIME_PATTERN.match(line)
                    if vt_m:
                        vote_time = vt_m.group(1).strip()
                        continue
                if voteup == 0:
                    v_m = _MD_VOTEUP_PATTERN.match(line)
                    if v_m:
                        voteup = int(v_m.group(1))
                        continue
                if not tags:
                    tg_m = _MD_TAGS_PATTERN.match(line)
                    if tg_m:
                        tags = split_tags(tg_m.group(1))
                        continue
                if not question_url:
                    qu_m = _MD_QUESTION_PATTERN.match(line)
                    if qu_m:
                        question_url = qu_m.group(1).strip()
                        continue
                if title != fname and author_name and voteup > 0 and tags:
                    break

            category = classify_tags(tags, question_url=question_url, question_title=title)
            category_counter[category] += 1

            all_entries.append({
                "author_name": author_name,
                "voteup": voteup,
                "title": title,
                "file_path": filepath,
                "date": date_str,
                "tags": tags,
                "category": category,
                "question_url": question_url,
                "vote_time": vote_time,
            })

    # 赞同数排行 Top 50
    top_voteups = sorted(all_entries, key=lambda e: e["voteup"], reverse=True)[:50]

    # 作者排行 Top 10
    author_counter = Counter(e["author_name"] or "匿名用户" for e in all_entries)
    top_authors = author_counter.most_common(10)

    # 日期分布按时间排序
    sorted_dates = sorted(date_counter.items(), key=lambda x: x[0])

    return {
        "total_entries": len(all_entries),
        "total_answers": answer_files,
        "total_articles": article_files,
        "top_voteups": top_voteups,
        "top_authors": top_authors,
        "date_distribution": sorted_dates,
        "category_distribution": category_counter.most_common(),
        "all_entries": all_entries,
    }


# ============================================================
# 作者独立页面
# ============================================================

def _write_author_page(authors_dir, author, author_hash, rank, author_entries, output_root, esc):
    """生成单个作者的所有点赞文章页面。

    Args:
        authors_dir: authors/ 子目录绝对路径
        author: 作者名（原始）
        author_hash: 作者名的 MD5 前 8 位
        rank: 排行序号，用于锚点定位
        author_entries: 该作者的全部条目列表
        output_root: 输出根目录
        esc: HTML 转义函数
    """
    author_entries = sorted(author_entries, key=lambda e: e["voteup"], reverse=True)

    rows = []
    for i, e in enumerate(author_entries, 1):
        rel_path = os.path.relpath(e["html_path"], output_root).replace("\\", "/")
        title_esc = esc(e["title"])
        rows.append(
            f'<tr><td>{i}</td>'
            f'<td><a href="../{rel_path}" target="_blank">{title_esc}</a></td>'
            f'<td style="text-align:right">{e["voteup"]}</td></tr>'
        )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(author)} - 统计报告</title>
<style>
  body {{
    max-width: 900px;
    margin: 40px auto;
    padding: 0 20px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC",
                 "PingFang SC", "Microsoft YaHei", sans-serif;
    font-size: 16px;
    line-height: 1.8;
    color: #1a1a1a;
    background: #fff;
  }}
  h1 {{ text-align: center; }}
  .back-link {{
    display: inline-block;
    margin-bottom: 20px;
    padding: 8px 20px;
    background: #0066cc;
    color: #fff;
    border-radius: 4px;
    text-decoration: none;
    font-size: 14px;
  }}
  .back-link:hover {{ background: #0052a3; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 1em;
  }}
  th, td {{
    padding: 10px 12px;
    border-bottom: 1px solid #eee;
    text-align: left;
  }}
  th {{ background: #f6f8fa; font-weight: 600; }}
  tr:hover {{ background: #f9f9f9; }}
  .summary {{ color: #8590a6; margin-bottom: 1em; }}
</style>
</head>
<body>
<a class="back-link" href="../summary.html#author-{rank}">← 返回统计报告</a>
<h1>{esc(author)}</h1>
<p class="summary">共 {len(author_entries)} 条赞同</p>
<table>
<thead><tr><th style="width:50px">#</th><th>标题</th><th style="width:80px;text-align:right">赞同数</th></tr></thead>
<tbody>
{"".join(rows)}
</tbody>
</table>
</body>
</html>"""

    filepath = os.path.join(authors_dir, f"author_{author_hash}.html")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    return filepath


# ============================================================
# 返回链接注入
# ============================================================

def _append_return_link(html_path, voteup_index):
    """向文章 HTML 末尾追加"返回统计报告"链接块（带去重检查）"""
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return

    if "summary.html#voteup-" in content:
        return  # 已有返回链接，跳过

    link_block = (
        f'\n<div style="text-align:center;margin-top:40px;padding:20px 0;border-top:1px solid #eee">'
        f'<a href="../summary.html#voteup-{voteup_index}" '
        f'style="display:inline-block;padding:8px 20px;background:#0066cc;color:#fff;border-radius:4px;text-decoration:none;font-size:14px">'
        f'← 返回统计报告</a></div>\n'
    )

    with open(html_path, "a", encoding="utf-8") as f:
        f.write(link_block)


# ============================================================
# 生成统计报告 HTML
# ============================================================

def _generate_summary_html(summary_data, generation_time, fmt_label, active_formats,
                           per_fmt_answers, per_fmt_articles, answer_count, article_count,
                           output_root, username):
    """生成统计报告 HTML 并写入磁盘，同时生成作者页面和返回链接。

    Args:
        summary_data: _scan_html_files 的返回值
        generation_time: 报告生成时间字符串
        fmt_label: 格式标签 "HTML" / "MD" / "MD+HTML"
        active_formats: ["html"] / ["md"] / ["html", "md"]
        per_fmt_answers: 各格式新增回答数
        per_fmt_articles: 各格式新增文章数
        answer_count: 本次新增回答总数
        article_count: 本次新增文章总数
        output_root: 输出根目录
    """
    esc = _esc_html

    authors_dir = os.path.join(output_root, "authors")
    os.makedirs(authors_dir, exist_ok=True)

    # ---- 概览表格 ----
    overview_rows = []
    for f in active_formats:
        fa = per_fmt_answers.get(f, 0)
        fr = per_fmt_articles.get(f, 0)
        overview_rows.append(
            f'<tr><td>{f.upper()}</td>'
            f'<td style="text-align:right">{fa}</td>'
            f'<td style="text-align:right">{fr}</td></tr>'
        )
    overview_rows.append(
        f'<tr><td><strong>历史累计</strong></td>'
        f'<td style="text-align:right"><strong>{summary_data["total_answers"]}</strong></td>'
        f'<td style="text-align:right"><strong>{summary_data["total_articles"]}</strong></td></tr>'
    )

    # ---- 日期分布条形图（年度折叠，点击展开月度明细）----
    dates = summary_data["date_distribution"]  # [(YYYY-MM, count), ...]

    year_groups = defaultdict(list)
    for month, count in dates:
        year = month[:4]
        year_groups[year].append((month, count))

    year_totals = [(y, sum(c for _, c in items)) for y, items in year_groups.items()]
    year_totals.sort(key=lambda x: x[0])
    year_global_max = max(c for _, c in year_totals) if year_totals else 1

    bar_html_parts = []
    for year, total in year_totals:
        year_width = (total / year_global_max * 100) if year_global_max > 0 else 0
        monthly_items = year_groups[year]
        month_rows = []
        for month, count in monthly_items:
            m_width = (count / total * 100) if total > 0 else 0
            month_rows.append(
                f'<div class="bar-row month-row">'
                f'<div class="bar-month">{month}</div>'
                f'<div class="bar-num">{count}</div>'
                f'<div class="bar-track"><div class="bar-fill" style="width:{m_width:.1f}%"></div></div>'
                f'</div>'
            )

        bar_html_parts.append(
            f'<details class="year-group">'
            f'<summary class="bar-row year-bar">'
            f'<div class="bar-month">{year}</div>'
            f'<div class="bar-num">{total}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{year_width:.1f}%"></div></div>'
            f'</summary>'
            f'<div class="month-bars">{"".join(month_rows)}</div>'
            f'</details>'
        )

    bar_html = "\n".join(bar_html_parts) if bar_html_parts else '<p style="color:#8590a6">暂无数据</p>'

    # ---- 领域分布（折叠式：点击领域名展开该领域全部条目）----
    cats = summary_data["category_distribution"]  # [(领域, count), ...]
    # 按领域一次性分组，避免对每个领域全量过滤 all_entries
    entries_by_cat = defaultdict(list)
    for e in summary_data["all_entries"]:
        entries_by_cat[e.get("category")].append(e)
    cat_global_max = max(c for _, c in cats) if cats else 1
    cat_html_parts = []
    for cat, count in cats:
        cat_width = (count / cat_global_max * 100) if cat_global_max > 0 else 0
        entries = entries_by_cat.get(cat, [])
        rows = []
        for e in entries:
            rel_path = os.path.relpath(e["html_path"], output_root).replace("\\", "/")
            rows.append(
                f'<li><a href="{rel_path}" target="_blank">{esc(e["title"])}</a>'
                f'<span style="color:#8590a6"> · {e.get("voteup", 0)} 赞</span></li>'
            )
        extra = ""
        if cat == "其他":
            other_tags = Counter()
            for e in entries:
                for t in e.get("tags", []):
                    other_tags[t] += 1
            top_other = [t for t, _ in other_tags.most_common(10)]
            if top_other:
                extra = (f'<p class="summary" style="margin:4px 0">「其他」高频标签：{"、".join(top_other)}'
                         f'（可在 categories.py 的 CATEGORY_KEYWORDS 补充关键词，'
                         f'或在 MANUAL_OVERRIDES 中单独归类某个问题）</p>')
        cat_html_parts.append(
            f'<details class="cat-group">'
            f'<summary class="bar-row cat-bar">'
            f'<div class="bar-cat">{esc(cat)}</div>'
            f'<div class="bar-num">{count}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{cat_width:.1f}%"></div></div>'
            f'</summary>'
            f'<div class="cat-items">{extra}<ul>{"".join(rows)}</ul></div>'
            f'</details>'
        )
    cat_html = "\n".join(cat_html_parts) if cat_html_parts else '<p style="color:#8590a6">暂无数据</p>'

    # ---- 最新点赞 Top 10（按赞同时间倒序）----
    latest_entries = sorted(
        summary_data["all_entries"],
        key=lambda e: e.get("vote_time") or "0000-00-00 00:00:00",
        reverse=True,
    )[:10]
    latest_rows = []
    for i, e in enumerate(latest_entries, 1):
        author_display = esc(e.get("author_name", "")) or "匿名用户"
        rel_path = os.path.relpath(e["html_path"], output_root).replace("\\", "/")
        latest_rows.append(
            f'<tr id="latest-{i}">'
            f'<td>{i}</td>'
            f'<td><a href="{rel_path}">{esc(e["title"])}</a></td>'
            f'<td>{author_display}</td>'
            f'<td style="white-space:nowrap">{esc(e.get("vote_time", "") or "-")}</td>'
            f'<td style="text-align:right">{e["voteup"]}</td></tr>'
        )

    # ---- 作者排行 ----
    author_rows = []
    for i, (author, cnt) in enumerate(summary_data["top_authors"], 1):
        author_display = esc(author) if author else "匿名用户"
        author_hash = hashlib.md5((author or "匿名用户").encode()).hexdigest()[:8]
        author_rows.append(
            f'<tr id="author-{i}">'
            f'<td>{i}</td>'
            f'<td><a href="authors/author_{author_hash}.html">{author_display}</a></td>'
            f'<td style="text-align:right">{cnt}</td></tr>'
        )

    # ---- 赞同数排行 ----
    voteup_rows = []
    for i, e in enumerate(summary_data["top_voteups"], 1):
        author_display = esc(e.get("author_name", "")) or "匿名用户"
        rel_path = os.path.relpath(e["html_path"], output_root).replace("\\", "/")
        title_cell = f'<a href="{rel_path}">{esc(e["title"])}</a>'
        voteup_rows.append(
            f'<tr id="voteup-{i}">'
            f'<td>{i}</td>'
            f'<td>{title_cell}</td>'
            f'<td>{author_display}</td>'
            f'<td style="text-align:right">{e["voteup"]}</td></tr>'
        )

    # ---- 组装完整 HTML ----
    summary_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>统计报告</title>
<link rel="icon" href="{FAVICON_DATA_URI}">
<style>
  html {{ scroll-behavior: smooth; }}
  body {{
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC",
                 "PingFang SC", "Microsoft YaHei", sans-serif;
    font-size: 16px;
    line-height: 1.8;
    color: #1a1a1a;
    background: #fff;
  }}
  .layout {{ display: flex; align-items: flex-start; }}
  .sidebar {{
    width: 170px;
    flex-shrink: 0;
    position: sticky;
    top: 0;
    height: 100vh;
    overflow-y: auto;
    padding: 28px 14px;
    box-sizing: border-box;
    border-right: 1px solid #eee;
    background: #fafafa;
  }}
  .sidebar h3 {{
    font-size: 12px;
    color: #8590a6;
    letter-spacing: 2px;
    margin: 0 0 14px 6px;
  }}
  .sidebar a {{
    display: block;
    padding: 7px 10px;
    margin: 2px 0;
    border-radius: 4px;
    color: #444;
    text-decoration: none;
    font-size: 14px;
    line-height: 1.5;
  }}
  .sidebar a:hover {{ background: #eef3fb; color: #175199; }}
  .main {{ flex: 1; min-width: 0; max-width: 1200px; margin: 0 auto; padding: 24px 28px 48px; }}
  h1 {{ text-align: center; }}
  h2 {{ border-bottom: 2px solid #0066cc; padding-bottom: 0.3em; margin-top: 2em; }}
  .report-time {{
    text-align: center;
    color: #8590a6;
    margin-bottom: 1.5em;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 1em 0;
  }}
  th, td {{
    padding: 10px 12px;
    border-bottom: 1px solid #eee;
  }}
  th {{ background: #f6f8fa; font-weight: 600; text-align: left; }}
  th.num {{ text-align: right; }}
  tr:hover {{ background: #f9f9f9; }}
  /* 横向条形图 */
  .bar-row {{
    display: flex;
    align-items: center;
    margin: 4px 0;
    height: 28px;
  }}
  .bar-month {{
    width: 75px;
    flex-shrink: 0;
    font-size: 13px;
    color: #555;
  }}
  .bar-cat {{
    width: 120px;
    flex-shrink: 0;
    font-size: 13px;
    color: #555;
  }}
  .bar-num {{
    width: 36px;
    flex-shrink: 0;
    text-align: right;
    font-size: 13px;
    color: #8590a6;
    margin-right: 8px;
  }}
  .bar-track {{
    flex: 1;
    height: 18px;
    background: #f0f0f0;
    border-radius: 3px;
    overflow: hidden;
  }}
  .bar-fill {{
    height: 100%;
    background: linear-gradient(90deg, #0066cc, #4d94ff);
    border-radius: 3px;
    min-width: 2px;
    transition: width 0.3s;
  }}
  /* 年度折叠 */
  .year-group {{
    margin: 2px 0;
  }}
  .year-group > summary {{
    list-style: none;
    cursor: pointer;
  }}
  .year-group > summary::-webkit-details-marker {{
    display: none;
  }}
  .year-bar {{
    font-weight: 600;
  }}
  .year-bar::before {{
    content: "▸ ";
    display: inline-block;
    width: 16px;
    transition: transform 0.2s;
    color: #0066cc;
    flex-shrink: 0;
  }}
  .year-group[open] > .year-bar::before {{
    content: "▾ ";
  }}
  .month-bars {{
    margin-left: 16px;
    border-left: 2px solid #e8e8e8;
    padding-left: 12px;
  }}
  .month-row .bar-month {{
    font-size: 12px;
  }}
  /* 领域折叠 */
  .cat-group {{
    margin: 2px 0;
  }}
  .cat-group > summary {{
    list-style: none;
    cursor: pointer;
  }}
  .cat-group > summary::-webkit-details-marker {{
    display: none;
  }}
  .cat-bar {{
    font-weight: 600;
  }}
  .cat-bar::before {{
    content: "▸ ";
    display: inline-block;
    width: 16px;
    transition: transform 0.2s;
    color: #0066cc;
    flex-shrink: 0;
  }}
  .cat-group[open] > .cat-bar::before {{
    content: "▾ ";
  }}
  .cat-items {{
    margin-left: 16px;
    border-left: 2px solid #e8e8e8;
    padding-left: 12px;
  }}
  .cat-items ul {{
    margin: 6px 0 12px;
    padding-left: 1.2em;
    line-height: 1.9;
  }}
</style>
</head>
<body>
<div class="layout">
<nav class="sidebar">
<h3>目录</h3>
<a href="#sec-overview">概览</a>
<a href="#sec-date">日期分布</a>
<a href="#sec-category">领域分布</a>
<a href="#sec-latest">最新点赞 Top 10</a>
<a href="#sec-author">作者排行 Top 10</a>
<a href="#sec-voteup">赞同数排行 Top 50</a>
</nav>
<div class="main">
<h1>{esc(username)}知乎点赞统计报告</h1>
<p class="report-time"><strong>生成时间：{generation_time}</strong> | 输出格式：{fmt_label}</p>

<h2 id="sec-overview">概览</h2>
<table>
<thead><tr><th>格式</th><th class="num">新增回答</th><th class="num">新增文章</th></tr></thead>
<tbody>
{"".join(overview_rows)}
</tbody>
</table>
<p>本次共 <strong>{answer_count}</strong> 个回答 + <strong>{article_count}</strong> 篇文章（历史累计 <strong>{summary_data["total_answers"]}</strong> 个回答 + <strong>{summary_data["total_articles"]}</strong> 篇文章）</p>

<h2 id="sec-date">日期分布</h2>
{bar_html}

<h2 id="sec-category">领域分布</h2>
{cat_html}

<h2 id="sec-latest">最新点赞 Top 10</h2>
<table>
<thead><tr><th style="width:50px">#</th><th>标题</th><th style="width:120px">作者</th><th style="width:170px">赞同时间</th><th class="num" style="width:80px">赞同数</th></tr></thead>
<tbody>
{"".join(latest_rows)}
</tbody>
</table>

<h2 id="sec-author">作者排行 Top 10</h2>
<table>
<thead><tr><th style="width:50px">#</th><th>作者</th><th class="num" style="width:80px">赞同条数</th></tr></thead>
<tbody>
{"".join(author_rows)}
</tbody>
</table>

<h2 id="sec-voteup">赞同数排行 Top 50</h2>
<table>
<thead><tr><th style="width:50px">#</th><th>标题</th><th style="width:120px">作者</th><th class="num" style="width:80px">赞同数</th></tr></thead>
<tbody>
{"".join(voteup_rows)}
</tbody>
</table>
</div>
</div>
</body>
</html>"""

    summary_path = os.path.join(output_root, "summary.html")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary_html)

    # ---- 生成作者独立页面（按作者一次性分组）----
    entries_by_author = defaultdict(list)
    for e in summary_data["all_entries"]:
        entries_by_author[e.get("author_name") or "匿名用户"].append(e)
    for i, (author, cnt) in enumerate(summary_data["top_authors"], 1):
        author_key = author or "匿名用户"
        author_hash = hashlib.md5(author_key.encode()).hexdigest()[:8]
        _write_author_page(authors_dir, author_key, author_hash, i,
                           entries_by_author.get(author_key, []), output_root, esc)

    # ---- 向赞同数排行文章末尾追加返回链接 ----
    for i, e in enumerate(summary_data["top_voteups"], 1):
        _append_return_link(e["html_path"], i)

    return summary_path


# ============================================================
# 生成统计报告 MD
# ============================================================

def _generate_summary_md(summary_data, generation_time, fmt_label, active_formats,
                         per_fmt_answers, per_fmt_articles, answer_count, article_count,
                         output_root):
    """生成统计报告 Markdown 并写入磁盘。

    不含作者独立页面和返回链接（MD 无锚点机制）。
    """
    username = os.path.basename(output_root)

    # ---- 概览表格 ----
    overview_lines = ["| 格式 | 新增回答 | 新增文章 |", "|------|---------|---------|"]
    for f in active_formats:
        fa = per_fmt_answers.get(f, 0)
        fr = per_fmt_articles.get(f, 0)
        overview_lines.append(f"| {f.upper()} | {fa} | {fr} |")
    overview_lines.append(
        f"| **历史累计** | **{summary_data['total_answers']}** | **{summary_data['total_articles']}** |"
    )
    overview_lines.append(
        f"\n本次共 **{answer_count}** 个回答 + **{article_count}** 篇文章"
        f"（历史累计 **{summary_data['total_answers']}** 个回答 + **{summary_data['total_articles']}** 篇文章）"
    )
    overview = "\n".join(overview_lines)

    # ---- 日期分布 ----
    dates = summary_data["date_distribution"]
    if dates:
        max_count = max(c for _, c in dates)
        date_lines = ["| 月份 | 数量 | 柱状 |", "|------|------|------|"]
        for month, count in dates:
            bar = "█" * max(1, int(count / max(max_count, 1) * 20))
            date_lines.append(f"| {month} | {count} | {bar} |")
        date_section = "\n".join(date_lines)
    else:
        date_section = "暂无数据"

    # ---- 领域分布 ----
    cats = summary_data["category_distribution"]
    if cats:
        cat_max = max(c for _, c in cats)
        cat_lines = ["| 领域 | 数量 | 占比 | 柱状 |", "|------|------|------|------|"]
        for cat, count in cats:
            pct = count / max(summary_data["total_entries"], 1) * 100
            bar = "█" * max(1, int(count / max(cat_max, 1) * 20))
            cat_lines.append(f"| {cat} | {count} | {pct:.1f}% | {bar} |")
        cat_section = "\n".join(cat_lines)
    else:
        cat_section = "暂无数据"

    # ---- 最新点赞 Top 10（按赞同时间倒序）----
    latest_entries = sorted(
        summary_data["all_entries"],
        key=lambda e: e.get("vote_time") or "0000-00-00 00:00:00",
        reverse=True,
    )[:10]
    latest_lines = ["| # | 标题 | 作者 | 赞同时间 | 赞同数 |", "|---|------|------|---------|--------|"]
    for i, e in enumerate(latest_entries, 1):
        author_display = e.get("author_name", "") or "匿名用户"
        rel_path = os.path.relpath(e["file_path"], output_root).replace("\\", "/")
        title_cell = f"[{e['title']}]({rel_path})"
        latest_lines.append(
            f"| {i} | {title_cell} | {author_display} | {e.get('vote_time', '') or '-'} | {e['voteup']} |"
        )
    latest_section = "\n".join(latest_lines)

    # ---- 作者排行 Top 10 ----
    author_lines = ["| # | 作者 | 赞同条数 |", "|---|------|---------|"]
    for i, (author, cnt) in enumerate(summary_data["top_authors"], 1):
        author_display = author if author else "匿名用户"
        author_lines.append(f"| {i} | {author_display} | {cnt} |")
    author_section = "\n".join(author_lines)

    # ---- 赞同数排行 Top 50 ----
    voteup_lines = ["| # | 标题 | 作者 | 赞同数 |", "|---|------|------|-------|"]
    for i, e in enumerate(summary_data["top_voteups"], 1):
        author_display = e.get("author_name", "") or "匿名用户"
        rel_path = os.path.relpath(e["file_path"], output_root).replace("\\", "/")
        title_cell = f"[{e['title']}]({rel_path})"
        voteup_lines.append(f"| {i} | {title_cell} | {author_display} | {e['voteup']} |")
    voteup_section = "\n".join(voteup_lines)

    # ---- 组装完整 MD ----
    summary_md = f"""# {username}知乎点赞统计报告

**生成时间：{generation_time}** | 输出格式：{fmt_label}

## 概览

{overview}

## 日期分布

{date_section}

## 领域分布

{cat_section}

## 最新点赞 Top 10

{latest_section}

## 作者排行 Top 10

{author_section}

## 赞同数排行 Top 50

{voteup_section}
"""

    summary_path = os.path.join(output_root, "summary.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary_md)

    return summary_path


# ============================================================
# 公开入口
# ============================================================

def generate_summary(output_root, active_formats, per_fmt_answers, per_fmt_articles,
                     answer_count, article_count, fmt_label=None):
    """主入口：扫描文件系统，生成统计报告（HTML/MD）和作者独立页面（仅 HTML）。

    Args:
        output_root: 输出根目录（如 output/<username>）
        active_formats: 活跃导出格式 ["html"] / ["md"] / ["html", "md"]
        per_fmt_answers: 各格式新增回答数 {"html": N, "md": M}
        per_fmt_articles: 各格式新增文章数 {"html": N, "md": M}
        answer_count: 本次新增回答总数
        article_count: 本次新增文章总数
        fmt_label: 格式标签 "HTML" / "MD" / "MD+HTML"

    Returns:
        list[str]: 生成的所有报告文件路径列表，无数据则返回空列表
    """
    if fmt_label is None:
        fmt_label = "+".join(f.upper() for f in active_formats)

    generation_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    generated = []

    # HTML 报告
    if "html" in active_formats:
        summary_data = _scan_html_files(output_root)
        if summary_data["total_entries"] == 0:
            print("统计报告：未找到任何 HTML 文件，跳过 HTML 报告生成。")
        else:
            summary_path = _generate_summary_html(
                summary_data, generation_time, fmt_label, active_formats,
                per_fmt_answers, per_fmt_articles, answer_count, article_count,
                output_root,
                username=os.path.basename(output_root),
            )
            generated.append(summary_path)
            print(f"\nHTML 统计报告已生成：{summary_path}")
            print(f"  全量条目：{summary_data['total_entries']} 条")
            print(f"  作者页面：{len(summary_data['top_authors'])} 篇")

    # MD 报告
    if "md" in active_formats:
        summary_data = _scan_md_files(output_root)
        if summary_data["total_entries"] == 0:
            print("统计报告：未找到任何 MD 文件，跳过 MD 报告生成。")
        else:
            summary_path = _generate_summary_md(
                summary_data, generation_time, fmt_label, active_formats,
                per_fmt_answers, per_fmt_articles, answer_count, article_count,
                output_root,
            )
            generated.append(summary_path)
            print(f"\nMD 统计报告已生成：{summary_path}")
            print(f"  全量条目：{summary_data['total_entries']} 条")

    return generated
