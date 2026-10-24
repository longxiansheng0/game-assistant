"""通话模式：麦克风常开，听到唤醒词就接话。

说话人一句话里同时带唤醒词和问题（"小助手，这boss怎么打"），
所以命中后把唤醒词后面的内容直接当问题，不用再说一遍。
"""

from __future__ import annotations

import queue
import re
import threading

import numpy as np

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000

MIN_SPEECH_MS = 280
END_SILENCE_MS = 620
MAX_SEGMENT_MS = 12000
NOISE_MULT = 3.2
MIN_THRESHOLD = 70.0

_PUNCT = " \t，,。.！!？?、~～\n"


def split_wake(text: str, wake: str) -> tuple[bool, str]:
    """返回 (是否命中, 唤醒词后面的内容)。"""
    wake = (wake or "").strip()
    if not wake:
        return False, text
    pos = text.find(wake)
    if pos >= 0:
        return True, text[pos + len(wake) :].strip(_PUNCT)
    flat_text = re.sub(r"\s+", "", text)
    flat_wake = re.sub(r"\s+", "", wake)
    if flat_wake and flat_wake in flat_text:
        return True, flat_text.replace(flat_wake, "", 1).strip(_PUNCT)
    return False, text


class WakeListener(threading.Thread):
    def __init__(self, asr, wake_word: str, on_wake, enabled=None, on_error=None) -> None:
        super().__init__(daemon=True)
        self.asr = asr
        self.wake_word = wake_word
        self.on_wake = on_wake
        self.enabled = enabled or (lambda: True)
        self.on_error = on_error
        self._stop_flag = threading.Event()
        self._segments: list[np.ndarray] = []
        self._queue: queue.Queue = queue.Queue(maxsize=3)
        self._speech_ms = 0
        self._silence_ms = 0
        self._noise = 0.0
        self._calib: list[float] = []
        self.running = False

    def stop(self) -> None:
        self._stop_flag.set()

    def run(self) -> None:
        import sounddevice as sd

        try:
            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=FRAME_SAMPLES,
                callback=self._on_audio,
            )
            stream.start()
        except Exception as exc:  # noqa: BLE001
            if self.on_error:
                self.on_error(f"通话模式打不开麦克风：{exc}")
            return

        self.running = True
        try:
            while not self._stop_flag.is_set():
                try:
                    audio = self._queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                if not self.enabled():
                    continue
                self._handle(audio)
        finally:
            self.running = False
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    # ---------- 内部 ----------

    def _handle(self, audio: np.ndarray) -> None:
        try:
            text = self.asr.transcribe(audio)
        except Exception:  # noqa: BLE001
            return
        if not text:
            return
        hit, rest = split_wake(text, self.wake_word)
        if hit and self.on_wake:
            try:
                self.on_wake(rest)
            except Exception:
                pass

    def _on_audio(self, indata, _frames, _time, _status) -> None:
        mono = indata[:, 0].copy()
        rms = float(np.sqrt(np.mean(mono.astype(np.float32) ** 2)))

        if len(self._calib) < 6:
            self._calib.append(rms)
            self._noise = float(np.mean(self._calib))
        threshold = max(self._noise * NOISE_MULT, MIN_THRESHOLD)
        loud = rms > threshold

        if loud:
            self._segments.append(mono)
            self._speech_ms += FRAME_MS
            self._silence_ms = 0
        elif self._segments:
            self._segments.append(mono)
            self._silence_ms += FRAME_MS
            if self._silence_ms >= END_SILENCE_MS:
                self._flush()
                return

        if self._segments and len(self._segments) * FRAME_MS >= MAX_SEGMENT_MS:
            self._flush()

    def _flush(self) -> None:
        audio = np.concatenate(self._segments) if self._segments else None
        speech = self._speech_ms
        self._segments = []
        self._speech_ms = 0
        self._silence_ms = 0
        if audio is None or speech < MIN_SPEECH_MS:
            return
        try:
            self._queue.put_nowait(audio)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(audio)
            except queue.Empty:
                pass
