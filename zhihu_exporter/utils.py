"""工具函数模块：URL 提取、文件名清理、内容转换等"""

import re
from html import unescape
from urllib.parse import quote

# ============================================================
# 站点图标（favicon）：内嵌 data URI，页面无需外部图标文件
# 源文件见项目 assets/favicon.svg（与下方常量内容一致，随项目版本控制）

# ============================================================

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
<rect x="-20" y="-20" width="64" height="64" rx="5" fill="#0066cc"/>
<path fill="#fff" d="M2 21h4V9H2v12zm20-12c0-1.1-.9-2-2-2h-6.3l.9-4.4c.1-.5-.1-1-.4-1.4L13.2 2 6.4 8.8c-.3.3-.4.7-.4 1.2v9c0 1.1.9 2 2 2H19c.9 0 1.6-.6 1.9-1.4l2.9-8c.1-.2.2-.5.2-.6v-2z"/>
</svg>"""

FAVICON_DATA_URI = "data:image/svg+xml," + quote(FAVICON_SVG, safe="")


def favicon_link_html():
    """返回 <link rel="icon"> 标签（data URI 内嵌，无外部文件依赖）"""
    return f'<link rel="icon" href="{FAVICON_DATA_URI}">'


def extract_username(url):
    """从用户主页 URL 提取用户名（URL Token）"""
def extract_username(url):
    """从用户主页 URL 提取用户名（URL Token），支持 /posts 等子路径"""
    m = re.search(r"/people/([^/?]+)", url)
    return m.group(1) if m else None

def get_headers(referer_url):
    """构造请求头（缺 Cookie 部分，后续补充）"""
    return {
        "x-api-version": "3.0.40",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "x-requested-with": "fetch",
        "accept": "*/*",
        "referer": referer_url,
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

def sanitize_filename(name):
    """去除文件名中的非法字符"""
    return re.sub(r'[\\/:*?"<>|]', "_", name)[:80]

def process_content(html_content):
    """将知乎富文本 HTML 转为 Markdown 格式（用于 md 导出）"""
    if not html_content:
        return "（无内容）"
    text = html_content
    # <b> → **text**
    text = re.sub(r"<b>(.*?)</b>", r"**\1**", text)
    text = re.sub(r"<strong>(.*?)</strong>", r"**\1**", text)
    # <i> → *text*
    text = re.sub(r"<i>(.*?)</i>", r"*\1*", text)
    text = re.sub(r"<em>(.*?)</em>", r"*\1*", text)
    # <br> → 换行
    text = re.sub(r"<br\s*/?>", "\n", text)
    # <p>...</p> → 段落换行
    text = re.sub(r"<p.*?>", "\n", text)
    text = re.sub(r"</p>", "\n", text)
    # <img> → 保留图片链接
    text = re.sub(
        r'<img[^>]+src="([^"]+)"[^>]*>',
        r"\n![图片](\1)\n",
        text,
    )
    # <a href> → 保留链接
    text = re.sub(
        r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        r"[\2](\1)",
        text,
    )
    # <blockquote> → Markdown 引用
    text = re.sub(r"<blockquote.*?>", "\n> ", text)
    text = re.sub(r"</blockquote>", "\n", text)
    # <code> → Markdown 代码
    text = re.sub(r"<code>(.*?)</code>", r"`\1`", text)
    # <pre> → 代码块
    text = re.sub(r"<pre.*?>", "\n```\n", text)
    text = re.sub(r"</pre>", "\n```\n", text)
    # 去掉其余所有 HTML 标签
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    # 清理多余空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def build_activity_url(username):
    """构造知乎个人动态 API 地址"""
    return (
        f"https://www.zhihu.com/api/v3/moments/{username}/activities"
        f"?limit=7&desktop=true"
    )


def extract_cover_image(target, is_answer):
    """从知乎点赞条目中提取封面图片 URL，无图返回 None。

    文章优先使用 API 返回的 image_url，缺省时回退正文首图；回答提取正文首图。

    Args:
        target: 知乎 API 返回的 target 对象
        is_answer: True 表示回答，False 表示文章

    Returns:
        str or None: 封面图片 URL（data URI 占位图视为无封面）
    """
    url = "" if is_answer else (target.get("image_url") or "")
    if not url:
        # 回答 / 无 image_url 的文章：从正文中提取第一张图片
        # （懒加载图优先取 data-actualsrc / data-original）
        content = target.get("content", "") or target.get("excerpt", "")
        m = (re.search(r'data-actualsrc="([^"]+)"', content)
             or re.search(r'data-original="([^"]+)"', content)
             or re.search(r'<img[^>]+src="([^"]+)"', content))
        url = m.group(1) if m else ""
    return None if (not url or url.startswith("data:")) else url

