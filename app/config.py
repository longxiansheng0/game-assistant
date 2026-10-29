"""配置：config/settings.json + 环境变量。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .paths import config_path

CONFIG_PATH = config_path()


def _config_dir() -> Path:
    """保证 config 是个目录。

    早期安装包不小心把 config 打成了一个文件，导致保存时报
    WinError 183（当文件已存在时无法创建该文件）。这里顺手自愈。
    """
    parent = CONFIG_PATH.parent
    if parent.exists() and not parent.is_dir():
        try:
            parent.rename(parent.with_name("config.broken"))
        except OSError:
            pass
    parent.mkdir(parents=True, exist_ok=True)
    return parent


@dataclass
class Settings:
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    hotkey: str = "F8"
    max_image_width: int = 1280
    allow_search: bool = True
    think: bool = False
    orb_x: int = -1
    orb_y: int = -1
    orb_size: int = 64
    opacity: float = 0.96
    bubble_w: int = -1
    bubble_h: int = -1
    voice_enabled: bool = True
    tts_enabled: bool = True
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    tts_rate: str = "+8%"
    asr_model: str = "small"
    hf_endpoint: str = ""
    asr_preload: bool = True
    ocr_enabled: bool = True
    ocr_max_side: int = 1600
    mode_hotkey: str = "Ctrl+F9"
    wake_word: str = "小助手"
    wake_ack: str = "主人，我在"
    call_mode: bool = False
    mode: str = "game"
    capture_enabled: bool = True
    workspace_dir: str = ""
    office_permission: str = "workspace-write"
    office_timeout: int = 180
    confirm_mode: str = "all"
    confirm_timeout: int = 15
    input_device: str = ""
    output_device: str = ""
    welcome_done: bool = False

    @classmethod
    def load(cls) -> "Settings":
        data: dict = {}
        _config_dir()
        if CONFIG_PATH.exists() and CONFIG_PATH.is_file():
            try:
                data = json.loads(CONFIG_PATH.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        known = {f.name for f in fields(cls)}
        cfg = cls(**{k: v for k, v in data.items() if k in known})

        cfg.api_key = os.getenv("DEEPSEEK_API_KEY", cfg.api_key or "")
        cfg.base_url = os.getenv("DEEPSEEK_BASE_URL", cfg.base_url)
        cfg.model = os.getenv("DEEPSEEK_MODEL", cfg.model)
        return cfg

    def save(self) -> None:
        _config_dir()
        data = asdict(self)
        # 防御：任何路径把 key 清空了，都别覆盖掉文件里已有的，否则用户会莫名其妙丢 key
        if not data.get("api_key"):
            try:
                old = json.loads(CONFIG_PATH.read_text("utf-8"))
                if old.get("api_key"):
                    data["api_key"] = old["api_key"]
            except (OSError, json.JSONDecodeError):
                pass
        CONFIG_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @property
    def ready(self) -> bool:
        return bool(self.api_key.strip())

    @property
    def workspace(self) -> Path:
        if self.workspace_dir.strip():
            return Path(self.workspace_dir).expanduser()
        return Path.home() / "Documents" / "VoiceAssistant" / "workspace"
