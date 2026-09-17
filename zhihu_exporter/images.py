"""图片处理模块：下载、本地存储、Gitee 上传、URL 替换"""

import asyncio
import base64
import hashlib
import os
import re

try:
    import aiohttp
except ImportError:
    aiohttp = None

# ============================================================
# 图片下载与托管（local / gitee）

# ============================================================

IMAGE_RETRIES = 2  # 图片下载/上传最大重试次数
GITEE_API_BASE = "https://gitee.com/api/v5"  # Gitee API 地址

# 已知的知乎图片域名

_ZHIHU_IMG_DOMAINS = ("pic.zhimg.com", "picx.zhimg.com", "pic1.zhimg.com",
                       "pic2.zhimg.com", "pic3.zhimg.com", "pic4.zhimg.com",
                       "pica.zhimg.com", "picb.zhimg.com", "picc.zhimg.com",
                       "picd.zhimg.com")

def _zhihu_img_clean_url(url):
    """清理知乎 CDN 图片 URL：
    1. 剥离 unicom 等包装域名（unicom.zhimg.com/pic1.zhimg.com/... -> pic1.zhimg.com/...，
       包装域名常连接超时，剥掉后真实域名可正常下载）
    2. 去除尺寸后缀（如 _720w），获取更高清的原始图 URL
    """
    url = re.sub(r'https?://unicom\.zhimg\.com/(pic\d?\.zhimg\.com/)', r'https://\1', url)
    url = re.sub(r'/(80|100|200|400|720|1080|1440|1600|2000|2500)/', '/', url)
    url = re.sub(r'_(r|hd|720w|1080w|1440w|2000w)(\.\w+)', r'\2', url)
    return url

def _get_img_ext(url_or_ct):
    """从 URL 或 Content-Type 推断图片扩展名，默认 .jpg"""
    m = re.search(r'\.(\w{3,4})(?:\?|$)', url_or_ct)
    if m:
        ext = m.group(1).lower()
        if ext in ("jpg", "jpeg", "png", "gif", "webp", "bmp", "svg"):
            return ".jpg" if ext == "jpeg" else f".{ext}"
    ct = url_or_ct.lower() if "/" in url_or_ct else ""
    if "image/png" in ct:
        return ".png"
    if "image/gif" in ct:
        return ".gif"
    if "image/webp" in ct:
        return ".webp"
    return ".jpg"

def extract_image_urls(content):
    """从 HTML/Markdown 内容中提取所有图片 URL（去重，只保留知乎图床链接）。

    兼容知乎懒加载图格式：真图可能在 data-actualsrc / data-original 属性中。
    """
    urls = set()
    for m in re.finditer(r'(?:src|data-actualsrc|data-original)="([^"]+)"', content):
        url = m.group(1)
        if any(d in url for d in _ZHIHU_IMG_DOMAINS):
            urls.add(url)
    for m in re.finditer(r'!\[.*?\]\(([^)]+)\)', content):
        url = m.group(1)
        if any(d in url for d in _ZHIHU_IMG_DOMAINS):
            urls.add(url)
    return list(urls)

def _get_image_name(url):
    """根据 URL 生成唯一文件名：12 位 MD5 + 扩展名"""
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    ext = _get_img_ext(url)
    return f"{url_hash}{ext}"

async def _download_image_bytes(session, url, headers, semaphore):
    """下载单张图片（受全局信号量限流），返回 (image_name, bytes) 或 (None, None)"""
    img_name = _get_image_name(url)
    for retry in range(IMAGE_RETRIES):
        try:
            async with semaphore:
                async with session.get(
                    url, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        ct = resp.headers.get("Content-Type", "")
                        if ct and "image" in ct:
                            ext = _get_img_ext(ct)
                            base = os.path.splitext(img_name)[0]
                            img_name = f"{base}{ext}"
                        return img_name, data
                    if resp.status in (403, 404):
                        return None, None
        except Exception:
            await asyncio.sleep(1)
    return None, None

async def _upload_to_gitee(session, token, repo, branch, file_path, content_bytes, semaphore):
    """上传文件到 Gitee 仓库，返回 raw URL 或 None"""
    owner, repo_name = repo.split("/", 1)
    api_url = f"{GITEE_API_BASE}/repos/{owner}/{repo_name}/contents/{file_path}"
    payload = {
        "access_token": token,
        "content": base64.b64encode(content_bytes).decode(),
        "message": f"upload: {os.path.basename(file_path)}",
        "branch": branch,
    }
    for retry in range(IMAGE_RETRIES):
        try:
            async with semaphore:
                async with session.post(api_url, json=payload,
                                        timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status == 201:
                        return f"https://gitee.com/{owner}/{repo_name}/raw/{branch}/{file_path}"
                    data = await resp.json()
                    if resp.status == 400 and ("already exists" in str(data) or "已存在" in str(data)):
                        return f"https://gitee.com/{owner}/{repo_name}/raw/{branch}/{file_path}"
                    await asyncio.sleep(2)
        except Exception:
            await asyncio.sleep(2)
    return None

async def _process_images(session, image_config, item_content, target_id, request_semaphore=None):
    """
    处理单条内容的图片：下载 → 替换 URL。

    Args:
        session: aiohttp.ClientSession
        image_config: dict，包含 host / local_dir / gitee_* 等
        item_content: dict，key 为格式名（"md"/"html"），value 为内容字符串
        target_id: 条目 ID，用于构建子目录 / 远端路径
        request_semaphore: 全局请求信号量（下载与列表页/详情页共享并发额度）

    Returns:
        dict: 同样格式的 dict，内容中的图片 URL 已被替换
    """
    if not image_config or not image_config.get("enabled"):
        return item_content

    first_content = next(iter(item_content.values()), "")
    urls = extract_image_urls(first_content)
    if not urls:
        return item_content

    host = image_config.get("host", "local")
    headers = {"Referer": "https://www.zhihu.com/", "User-Agent": "Mozilla/5.0"}

    # 并发下载所有图片（与列表页/详情页共享全局并发额度）
    download_tasks = [_download_image_bytes(session, _zhihu_img_clean_url(u), headers, request_semaphore)
                      for u in urls]
    results = await asyncio.gather(*download_tasks, return_exceptions=True)

    # 构建 cleaned_url → 替换路径 映射
    url_map = {}

    if host == "gitee":
        token = image_config.get("gitee_token")
        repo = image_config.get("gitee_repo")
        branch = image_config.get("gitee_branch", "master")
        path_prefix = image_config.get("gitee_path_prefix", "").strip("/")
        gitee_sem = asyncio.Semaphore(2)

        upload_tasks = []
        upload_entries = []
        for orig_url, result in zip(urls, results):
            if isinstance(result, Exception) or result == (None, None):
                continue
            img_name, img_data = result
            if img_data is None:
                continue
            remote = f"{path_prefix}/{target_id}/{img_name}" if path_prefix else f"{target_id}/{img_name}"
            upload_tasks.append(_upload_to_gitee(session, token, repo, branch, remote, img_data, gitee_sem))
            upload_entries.append(_zhihu_img_clean_url(orig_url))

        upload_results = await asyncio.gather(*upload_tasks, return_exceptions=True)
        for cleaned_url, raw_url in zip(upload_entries, upload_results):
            if raw_url and not isinstance(raw_url, Exception):
                url_map[cleaned_url] = raw_url
    else:
        # 本地模式：在线程池中写文件
        # local_dir 是图片库的绝对根目录（如 output/<user>/assets/images）
        images_root = image_config.get("local_dir")
        local_full = os.path.join(images_root, target_id)
        os.makedirs(local_full, exist_ok=True)
        loop = asyncio.get_running_loop()

        # 生成相对路径片段：../assets/images/<target_id>/<img_name>
        rel_base = os.path.join("..", "assets", "images", target_id)

        def _write_local():
            written = {}
            for orig_url, result in zip(urls, results):
                if isinstance(result, Exception) or result == (None, None):
                    continue
                img_name, img_data = result
                if img_data is None:
                    continue
                filepath = os.path.join(local_full, img_name)
                with open(filepath, "wb") as fh:
                    fh.write(img_data)
                rel_path = os.path.join(rel_base, img_name).replace("\\", "/")
                written[_zhihu_img_clean_url(orig_url)] = rel_path
            return written

        url_map = await loop.run_in_executor(None, _write_local)

    if not url_map:
        return item_content

    # 替换所有格式内容中的图片 URL（兼容 src / data-actualsrc / data-original / Markdown）
    replaced = {}
    for fmt_key, content in item_content.items():
        for orig_url in urls:
            clean = _zhihu_img_clean_url(orig_url)
            if clean in url_map:
                replacement = url_map[clean]
                for attr in ("src", "data-actualsrc", "data-original"):
                    content = content.replace(f'{attr}="{orig_url}"', f'{attr}="{replacement}"')
                content = content.replace(f'({orig_url})', f'({replacement})')
        replaced[fmt_key] = content

    return replaced

