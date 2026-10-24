"""配置：config/settings.json + 环境变量。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields

from .paths import config_path

CONFIG_PATH = config_path()


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
    text_hotkey: str = "Ctrl+F2"
    wake_word: str = "小助手"
    wake_ack: str = "主人，我在"
    call_mode: bool = False
    welcome_done: bool = False

    @classmethod
    def load(cls) -> "Settings":
        data: dict = {}
        if CONFIG_PATH.exists():
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
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
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
