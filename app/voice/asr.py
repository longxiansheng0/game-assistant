"""离线语音识别：faster-whisper（CPU int8）。

用 CPU 不用 GPU —— 打游戏时显卡是别人的。
"""

from __future__ import annotations

import os
import re
import socket
import threading
import numpy as np

from ..paths import models_dir

MODEL_DIR = models_dir()

PROMPT = "以下是普通话游戏对话，包含BOSS、装备、任务、技能等词。"


class WhisperASR:
    def __init__(self, model_size: str = "small", threads: int = 4) -> None:
        self.model_size = model_size
        self.threads = threads
        self._model = None
        self._lock = threading.Lock()
        self._infer_lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            # 必须在 import huggingface_hub 之前定好，它是在导入时读取的
            endpoint = pick_endpoint(os.getenv("HF_ENDPOINT_OVERRIDE", ""))
            if endpoint:
                os.environ["HF_ENDPOINT"] = endpoint
            os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "10")
            os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
            # 新版 huggingface_hub 默认走 Xet 存储，镜像站不支持，会 401
            os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

            from faster_whisper import WhisperModel

            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            kwargs = dict(
                device="cpu",
                compute_type="int8",
                cpu_threads=self.threads,
                num_workers=1,
                download_root=str(MODEL_DIR),
            )
            try:
                self._model = WhisperModel(self.model_size, **kwargs)
            except Exception:
                # 换另一个源再试一次
                os.environ["HF_ENDPOINT"] = (
                    "https://huggingface.co" if endpoint else "https://hf-mirror.com"
                )
                self._model = WhisperModel(self.model_size, **kwargs)

    def transcribe(self, audio: np.ndarray) -> str:
        self.load()
        data = audio.astype(np.float32) / 32768.0
        # 通话模式的唤醒线程可能和主线程同时识别，模型不能并发跑
        with self._infer_lock:
            return self._run(data)

    def _run(self, data: np.ndarray) -> str:
        segments, _info = self._model.transcribe(
            data,
            language="zh",
            beam_size=1,
            best_of=1,
            temperature=0.0,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300, "min_speech_duration_ms": 100},
            initial_prompt=PROMPT,
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        text = "".join(seg.text for seg in segments).strip()
        if _is_junk(text):
            return ""
        return _clean(text)


def pick_endpoint(override: str = "") -> str:
    """国内直连 huggingface.co 基本是挂的，先探一下，不通就走镜像。"""
    if override:
        return override
    try:
        socket.create_connection(("huggingface.co", 443), timeout=2.5).close()
        return ""
    except OSError:
        return "https://hf-mirror.com"


# whisper 对着噪声/咳嗽经常蹦出来的句子，直接丢掉，免得拿它去问模型
_JUNK = (
    "谢谢观看", "感谢观看", "谢谢大家", "请不吝点赞", "订阅", "字幕",
    "明镜与点点", "thanks for watching", "thank you", "please subscribe",
)


def _is_junk(text: str) -> bool:
    compact = re.sub(r"[\s，。,.!！?？、…]", "", text).lower()
    if len(compact) < 2:
        return True
    return any(junk in compact for junk in _JUNK)


def _clean(text: str) -> str:
    """Whisper 喜欢在句末塞标点，中文问答不需要。"""
    text = text.strip()
    for junk in ("。", "，", "？", "！", ".", ",", "?", "!"):
        if text.endswith(junk):
            text = text[:-1]
    return text.strip()
