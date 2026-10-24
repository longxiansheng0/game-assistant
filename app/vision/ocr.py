"""屏幕文字识别。

模型看压缩过的截图时，任务名 / 装备属性这种小字容易读错。
OCR 在原始分辨率上跑一遍，把准确的字喂给模型 —— 检索攻略靠的就是这些字。
"""

from __future__ import annotations

import re
import threading
from typing import Any

import numpy as np

MAX_LINES = 60
MAX_CHARS = 900
MIN_SCORE = 0.55


class OcrEngine:
    def __init__(self, max_side: int = 1600) -> None:
        self.max_side = max_side
        self._engine: Any = None
        self._lock = threading.Lock()
        self.error = ""

    @property
    def ready(self) -> bool:
        return self._engine is not None

    def load(self) -> None:
        if self._engine is not None:
            return
        with self._lock:
            if self._engine is not None:
                return
            from rapidocr_onnxruntime import RapidOCR

            try:
                self._engine = RapidOCR(det_limit_side_len=self.max_side, det_limit_type="max")
            except TypeError:
                self._engine = RapidOCR()

    def read(self, image) -> str:
        """PIL 图片 -> 多行文本。识别不出来就返回空串，上层当没这回事。"""
        try:
            self.load()
        except Exception as exc:  # 依赖缺失 / 模型损坏
            self.error = str(exc)
            return ""

        data = _prepare(image, self.max_side)
        if data is None:
            return ""
        try:
            # 游戏里的字都是横排，跳过方向分类器，能省 0.5 秒
            result, _elapse = self._engine(data, use_det=True, use_cls=False, use_rec=True)
        except Exception as exc:
            self.error = str(exc)
            return ""
        return _format(result)

    def warmup(self) -> None:
        """启动时先跑一张小图，把 onnx 会话初始化掉，别让第一句话等它。"""
        from PIL import Image as PilImage, ImageDraw

        # 尺寸和行数都要接近真实截图：onnx 按输入尺寸分配内存池，
        # 识别又是逐框跑的，只喂几行字的话等于没热身
        canvas = PilImage.new("RGB", (1600, 1000), (20, 24, 32))
        draw = ImageDraw.Draw(canvas)
        for i in range(24):
            draw.text((40 + (i % 3) * 520, 30 + (i // 3) * 120), f"Warmup 测试 {i} 12345", fill=(230, 235, 245))
        self.read(canvas)
        self.read(canvas)


def _prepare(image, max_side: int) -> np.ndarray | None:
    if image is None:
        return None
    img = image.convert("RGB")
    if max(img.size) > max_side:
        ratio = max_side / max(img.size)
        img = img.resize((round(img.width * ratio), round(img.height * ratio)))
    arr = np.asarray(img)
    return np.ascontiguousarray(arr[:, :, ::-1])  # RapidOCR 内部按 BGR 处理


def _format(result, max_lines: int = MAX_LINES, max_chars: int = MAX_CHARS) -> str:
    if not result:
        return ""
    items = []
    for box, text, score in result:
        text = (text or "").strip()
        if not text or float(score) < MIN_SCORE:
            continue
        ys = [point[1] for point in box]
        xs = [point[0] for point in box]
        items.append((min(ys), min(xs), text))
    if not items:
        return ""

    items.sort(key=lambda it: (round(it[0] / 12), it[1]))

    lines: list[str] = []
    last_y = -999.0
    buffer = ""
    for y, _x, text in items:
        if abs(y - last_y) > 12 and buffer:
            lines.append(buffer)
            buffer = ""
        buffer = f"{buffer} {text}".strip() if buffer else text
        last_y = y
    if buffer:
        lines.append(buffer)

    seen = set()
    unique = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        unique.append(line)

    text = "\n".join(unique[:max_lines])
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return _clean(text)


def _clean(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
