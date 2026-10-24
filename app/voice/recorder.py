"""麦克风录音 + 能量 VAD 自动断句。

点一下开始录，说完自动停，不用按住。
"""

from __future__ import annotations

import threading

import numpy as np

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000

MIN_SPEECH_MS = 240      # 说话至少 0.24s 才算真的开口，挡掉咳嗽/键盘声
END_SILENCE_MS = 780     # 停顿 0.78s 就断句
MAX_TALK_MS = 20000      # 一次最多录 20s
NO_SPEECH_MS = 4000      # 4s 没人声，判定误触


class Recorder:
    def __init__(self) -> None:
        self._stream = None
        self._frames: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._speech_ms = 0
        self._silence_ms = 0
        self._total_ms = 0
        self._noise = 0.0
        self._calib: list[float] = []
        self._result: tuple[str, np.ndarray | None] | None = None
        self.active = False
        self.level = 0.0
        self.error = ""

    # ---------- 对外 ----------

    def start(self) -> bool:
        import sounddevice as sd

        self._frames = []
        self._speech_ms = 0
        self._silence_ms = 0
        self._total_ms = 0
        self._noise = 0.0
        self._calib = []
        self._result = None
        self.level = 0.0
        self.error = ""
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=FRAME_SAMPLES,
                callback=self._on_audio,
            )
            self._stream.start()
        except Exception as exc:  # 没麦克风 / 被占用 / 没授权
            self.error = f"麦克风打不开：{exc}"
            self._stream = None
            return False
        self.active = True
        return True

    def request_stop(self) -> None:
        """手动结束（再按一次热键）。"""
        with self._lock:
            if self._result is None:
                self._result = ("manual", self._collect())

    def cancel(self) -> None:
        with self._lock:
            self._result = ("cancel", None)
        self._shutdown()

    def poll(self) -> tuple[str, np.ndarray | None] | None:
        """主线程定时调用：拿结果并关掉设备。"""
        with self._lock:
            result = self._result
            self._result = None
        if result is None:
            return None
        self._shutdown()
        return result

    # ---------- 内部 ----------

    def _collect(self) -> np.ndarray | None:
        if not self._frames:
            return None
        return np.concatenate(self._frames)

    def _on_audio(self, indata, _frames, _time, _status) -> None:
        mono = indata[:, 0].copy()
        rms = float(np.sqrt(np.mean(mono.astype(np.float32) ** 2)))
        self.level = min(1.0, rms / 3500.0)

        with self._lock:
            if self._result is not None:
                return
            self._frames.append(mono)
            self._total_ms += FRAME_MS

            if len(self._calib) < 6:
                self._calib.append(rms)
                self._noise = float(np.mean(self._calib))
            threshold = max(self._noise * 3.0, 70.0)

            if rms > threshold:
                self._speech_ms += FRAME_MS
                self._silence_ms = 0
            else:
                self._silence_ms += FRAME_MS

            if self._speech_ms >= MIN_SPEECH_MS and self._silence_ms >= END_SILENCE_MS:
                self._result = ("auto", self._collect())
            elif self._speech_ms < MIN_SPEECH_MS and self._total_ms >= NO_SPEECH_MS:
                # 注意别用 == 0：偶尔一个噪声尖峰就会让条件永远不成立，然后一直录下去
                self._result = ("silent", None)
            elif self._total_ms >= MAX_TALK_MS:
                self._result = ("timeout", self._collect())

    def _shutdown(self) -> None:
        self.active = False
        self.level = 0.0
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
