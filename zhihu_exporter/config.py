"""配置管理模块：默认参数、配置文件加载、CLI 参数映射"""

import argparse
import os
import re
import sys

# ===================== 默认配置 =====================
DEFAULT_OUTPUT_DIR = "output"
PAGE_DELAY = 0.8   # 每页请求间隔（秒），避免触发风控
RETRY_DELAY = 5    # 被限流时重试等待秒数
MAX_RETRIES = 3    # 单页最大重试次数
DEFAULT_CONCURRENCY = 5  # 默认并发数
# ====================================================

_CONFIG_KEY_MAP = {
    # 认证（config.yaml 的 auth 节）
    "auth.cookie":    "cookie",
    "auth.cookie_file": "cookie_file",
    # 请求（request 节）
    "request.delay":  "page_delay",
    "request.max_retries": "max_retries",
    # 输出 / 抓取
    "output_dir":     "output",
    "format":         "format",
    "limit":          "limit",
    "incremental":    "incremental",
    "no_scan":        "no_scan",
    "visible":        "visible",
    "concurrency":    "concurrency",
    "user_url":       "user_url",
    "download_images": "download_images",
    "image_host":     "image_host",
    "gitee_token":    "gitee_token",
    "gitee_repo":     "gitee_repo",
    "gitee_branch":   "gitee_branch",
    "gitee_path_prefix": "gitee_path_prefix",
    # 抓取模式（v3.4）：upvotes=点赞导出（默认）；articles/answers/all=抓作者原创内容
    "mode":           "mode",
    "keyword":        "keyword",
}


# ============================================================
# 配置文件加载

# ============================================================

def _load_yaml_config(path):
    """加载 YAML 配置文件（延迟导入 PyYAML，自动修复非法转义字符）"""
    try:
        import yaml
    except ImportError:
        print("错误：读取 YAML 配置文件需要 PyYAML 库")
        print("请运行：pip install pyyaml")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    # 修复 Cookie / Token 等字段中可能出现的非法转义（如 \B → \\B）
    content = re.sub(r'(?<!\\)\\(?!["\\/bfnrtu])', r'\\\\', content)
    return yaml.safe_load(content)

def load_config(path):
    """加载 YAML 配置文件（仅支持 YAML；旧 JSON 配置已废弃）"""
    if not os.path.exists(path):
        print(f"错误：配置文件不存在：{path}")
        sys.exit(1)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".yaml", ".yml"):
        return _load_yaml_config(path)
    print(f"不支持的配置文件格式：{ext}，仅支持 .yaml / .yml")
    sys.exit(1)

def _extract_config_path_from_argv():
    """从 sys.argv 中手动提取 --config / -cfg 参数值（在 argparse 解析之前）"""
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg in ("--config", "-cfg"):
            if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("-"):
                return sys.argv[i + 1]
        elif arg.startswith("--config="):
            return arg.split("=", 1)[1]
        elif arg.startswith("-cfg="):
            return arg.split("=", 1)[1]
    return None

def _resolve_config_path():
    """确定要加载的配置文件路径。

    优先级：用户显式 --config/-cfg 参数 > 本地 config.yaml > config.example.yaml。
    都不存在返回 None（仅用命令行参数与内置默认值）。
    """
    explicit = _extract_config_path_from_argv()
    if explicit:
        return explicit
    for candidate in ("config.yaml", "config.example.yaml"):
        if os.path.exists(candidate):
            return candidate
    return None

def _flatten_sections(config: dict) -> dict:
    """把 auth / request 等嵌套节展开为「节名.键名」点号键（遵循《爬虫项目指南》）。"""
    flat = {}
    for key, value in config.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat[f"{key}.{sub_key}"] = sub_value
        else:
            flat[key] = value
    return flat

def apply_config_defaults(parser, config_path):
    """读取配置文件并将参数映射为 argparse 默认值（命令行参数优先级更高）"""
    config = _flatten_sections(load_config(config_path))
    mapped = {}
    for key, value in config.items():
        dest = _CONFIG_KEY_MAP.get(key, key)
        mapped[dest] = value

    parser.set_defaults(**mapped)
    return config

