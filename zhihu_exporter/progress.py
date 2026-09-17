"""进度管理模块：增量爬取进度读写"""

import json
import os
from datetime import datetime

def load_progress(progress_file, fmt):
    """加载指定导出格式的爬取进度"""
    default = {"last_activity_time": 0, "answer_count": 0, "article_count": 0}
    if os.path.exists(progress_file):
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                all_progress = json.load(f)
            return all_progress.get(fmt, default)
        except Exception:
            pass
    return default

def save_progress(progress_file, fmt, last_activity_time, answer_count, article_count):
    """保存指定导出格式的爬取进度（读写合并，不覆盖其他格式的记录）"""
    entry = {
        "last_activity_time": last_activity_time,
        "answer_count": answer_count,
        "article_count": article_count,
        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    all_progress = {}
    if os.path.exists(progress_file):
        try:
            with open(progress_file, "r", encoding="utf-8") as f:
                all_progress = json.load(f)
        except Exception:
            pass
    all_progress[fmt] = entry
    with open(progress_file, "w", encoding="utf-8") as f:
        json.dump(all_progress, f, ensure_ascii=False, indent=2)

