"""语音播报：edge-tts 合成 + 边播边合成 + 随时打断。

两个线程：一个负责"文字->PCM"，一个负责"PCM->喇叭"。
前一句还在播的时候，后一句已经在合成了，所以句子之间不断档。
"""

from __future__ import annotations

import queue
import re
import threading

import numpy as np

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
SENTENCE_END = re.compile(r"[。！？!?；;\n]")
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
MD = re.compile(r"(\*\*|__|`|#+|^\s*[-*]\s+)", re.MULTILINE)


def speakable(text: str) -> str:
    """把 markdown 洗成能念的普通话，否则它会把星号也念出来。"""
    text = LINK.sub(r"\1", text)
    text = MD.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class Speaker:
    def __init__(self, voice: str = DEFAULT_VOICE, rate: str = "+8%", on_idle=None) -> None:
        self.voice = voice
        self.rate = rate
        self.on_idle = on_idle
        self._text_q: queue.Queue = queue.Queue(maxsize=8)
        self._pcm_q: queue.Queue = queue.Queue(maxsize=6)
        self._stop = threading.Event()
        self._gen = 0
        self._buffer = ""
        self._busy = False
        self._synth_thread: threading.Thread | None = None
        self._play_thread: threading.Thread | None = None

    # ---------- 对外 ----------

    @property
    def busy(self) -> bool:
        return self._busy

    def feed(self, text: str) -> None:
        """流式喂进来的增量文本，攒够一句就送去合成。"""
        if not text:
            return
        self._buffer += text
        while True:
            match = SENTENCE_END.search(self._buffer)
            if not match:
                break
            cut = match.end()
            sentence = speakable(self._buffer[:cut])
            self._buffer = self._buffer[cut:]
            self._push(sentence)
        if len(self._buffer) > 90:
            head, self._buffer = self._buffer[:90], self._buffer[90:]
            self._push(speakable(head))

    def say(self, text: str) -> None:
        """单独说一句（唤醒应答这种），说完自动收尾。"""
        cleaned = speakable(text)
        if not cleaned:
            return
        self._push(cleaned)
        self.flush()

    def flush(self) -> None:
        rest = speakable(self._buffer)
        self._buffer = ""
        if rest:
            self._push(rest)
        self._ensure_threads()
        self._text_q.put(None)

    def stop(self) -> None:
        self._stop.set()
        self._gen += 1
        self._buffer = ""
        for q in (self._text_q, self._pcm_q):
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
        self._busy = False

    # ---------- 内部 ----------

    def _push(self, sentence: str) -> None:
        if not sentence:
            return
        self._stop.clear()
        self._ensure_threads()
        self._busy = True
        try:
            self._text_q.put((self._gen, sentence), timeout=5)
        except queue.Full:
            pass

    def _ensure_threads(self) -> None:
        if self._synth_thread is None or not self._synth_thread.is_alive():
            self._synth_thread = threading.Thread(target=self._synth_loop, daemon=True)
            self._synth_thread.start()
        if self._play_thread is None or not self._play_thread.is_alive():
            self._play_thread = threading.Thread(target=self._play_loop, daemon=True)
            self._play_thread.start()

    def _synth_loop(self) -> None:
        while True:
            item = self._text_q.get()
            if item is None:
                # 线程别退，退了以后新入队的句子可能没人消费（合成线程重启有竞态）
                self._pcm_q.put(None)
                continue
            gen, sentence = item
            if gen != self._gen or self._stop.is_set():
                continue
            try:
                pcm = self._synthesize(sentence)
            except Exception:
                continue
            if pcm is not None and gen == self._gen:
                try:
                    self._pcm_q.put((gen, pcm), timeout=10)
                except queue.Full:
                    pass

    def _play_loop(self) -> None:
        import sounddevice as sd

        stream = None
        rate = 24000
        try:
            while True:
                item = self._pcm_q.get()
                if item is None:
                    self._busy = False
                    if self.on_idle:
                        try:
                            self.on_idle()
                        except Exception:
                            pass
                    continue
                gen, pcm = item
                if gen != self._gen:
                    continue
                if stream is None:
                    stream = sd.OutputStream(
                        samplerate=rate, channels=1, dtype="int16", blocksize=int(rate * 0.08)
                    )
                    stream.start()
                pos = 0
                block = int(rate * 0.08)
                while pos < len(pcm):
                    if self._stop.is_set() or gen != self._gen:
                        break
                    chunk = pcm[pos : pos + block]
                    stream.write(np.asarray(chunk, dtype=np.int16).reshape(-1, 1))
                    pos += block
        except Exception:
            pass
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
            # 线程挂了也要把状态收干净，不然球会一直显示"说话中"
            self._busy = False
            if self.on_idle:
                try:
                    self.on_idle()
                except Exception:
                    pass

    def _synthesize(self, text: str) -> np.ndarray | None:
        return synthesize(text, self.voice, self.rate)


def synthesize(text: str, voice: str, rate: str = "+8%") -> np.ndarray | None:
    """文字 -> 24kHz 单声道 PCM。设置页试听和正式播报走同一条路。"""
    import asyncio

    import edge_tts
    import miniaudio

    async def collect() -> bytes:
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        data = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                data.extend(chunk["data"])
        return bytes(data)

    mp3 = asyncio.run(collect())
    if not mp3:
        return None
    decoded = miniaudio.decode(
        mp3, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=24000
    )
    return np.array(decoded.samples, dtype=np.int16)


def play(pcm: np.ndarray, rate: int = 24000) -> None:
    """一次性播完，给试听用。"""
    import sounddevice as sd

    with sd.OutputStream(
        samplerate=rate, channels=1, dtype="int16", blocksize=int(rate * 0.08)
    ) as stream:
        block = int(rate * 0.08)
        for start in range(0, len(pcm), block):
            stream.write(np.asarray(pcm[start : start + block], dtype=np.int16).reshape(-1, 1))
