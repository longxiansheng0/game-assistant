"""打包前后的路径解析。

开发时项目根目录，打包后是 exe 所在目录 —— 配置和模型都跟着 exe 走，
这样换台机器整个文件夹拷过去就能用。
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def base_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def models_dir() -> Path:
    return base_dir() / "models"


def config_path() -> Path:
    return base_dir() / "config" / "settings.json"


def data_dir() -> Path:
    return base_dir() / "data"
