"""认证模块：Cookie 获取（手动/文件/扫码三种方式）"""

import sys
import time

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

def login_manual():
    """手动输入 Cookie"""
    print("\n[手动模式]")
    print("推荐方法：从 Network 面板一键复制")
    print("  1. 打开知乎主页（确保已登录）")
    print("  2. F12 → Network（网络）标签")
    print("  3. Ctrl+R 刷新页面")
    print("  4. 在左侧列表点击任意一个请求（比如 www.zhihu.com）")
    print("  5. 右侧找到 Request Headers → 找到 Cookie: 那一行")
    print("  6. 直接整行复制，粘贴到下方（按回车结束）：\n")
    cookie = input("Cookie: ").strip()
    if not cookie:
        print("未输入 Cookie，退出。")
        sys.exit(1)
    return cookie

def read_cookie_from_file(file_path):
    """从文件读取 Cookie（支持 name=value 每行一对，或整行 Cookie 字符串）"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]

        # 如果文件只有一行且包含分号，视为整行 Cookie 字符串
        if len(lines) == 1 and ";" in lines[0]:
            return lines[0]

        # 否则按每行 name=value 解析
        cookie_parts = []
        for line in lines:
            if "=" in line:
                name, value = line.split("=", 1)
                cookie_parts.append(f"{name.strip()}={value.strip()}")
            else:
                cookie_parts.append(line.strip())

        return "; ".join(cookie_parts)
    except Exception as e:
        print(f"读取 Cookie 文件失败: {e}")
        sys.exit(1)

def login_playwright(visible=False):
    """使用 Playwright 打开浏览器扫码登录，自动获取 Cookie"""
    if sync_playwright is None:
        print("\n[提示] 未安装 playwright，回退到手动模式。")
        print("如需自动扫码登录，请执行：pip install playwright && playwright install chromium")
        return login_manual()

    print("\n[自动扫码模式] 即将打开浏览器，请在浏览器中扫码登录知乎...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not visible)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.zhihu.com/signin", wait_until="domcontentloaded")
        print("请在弹出的浏览器窗口中扫码登录（等待最多 120 秒）...")
        # 轮询 z_c0（知乎登录凭证 Cookie）：出现即说明登录成功
        # 注意不能用 wait_for_url 等待跳转——登录页 URL 本身就匹配 zhihu.com 模式会立即返回
        logged_in = False
        for _ in range(60):
            time.sleep(2)
            if any(c["name"] == "z_c0" for c in context.cookies()):
                logged_in = True
                break
        if not logged_in:
            print("等待超时，未检测到登录成功，将按当前状态获取 Cookie。")
        time.sleep(2)
        cookies = context.cookies()
        browser.close()

    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    if not cookie_str:
        print("未能获取 Cookie，请重试或使用手动模式。")
        sys.exit(1)
    print("Cookie 获取成功。")
    return cookie_str

# ============================================================
# Cookie 获取（同步，在 asyncio.run 之前执行）

# ============================================================

def _acquire_cookie(cookie, cookie_file, no_scan, visible):
    """
    同步获取 Cookie（支持命令行、文件、Playwright 扫码、手动输入）。

    Returns:
        str: Cookie 字符串
    """
    if cookie:
        print("\n使用提供的 Cookie...")
        return cookie
    if cookie_file:
        print(f"\n从文件读取 Cookie: {cookie_file}")
        return read_cookie_from_file(cookie_file)
    if no_scan:
        return login_manual()

    print("\n请选择 Cookie 获取方式：")
    print("  [1] 手动粘贴 Cookie（推荐，最稳定）")
    print("  [2] 自动扫码登录（需要安装 playwright）")
    choice = input("\n请输入选项 (1/2，默认 1): ").strip() or "1"
    if choice == "2":
        return login_playwright(visible=visible)
    return login_manual()

