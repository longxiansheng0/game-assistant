"""音频设备：枚举、解析、测试。

设备按名字记住（索引会随插拔变化），解析时优先 WASAPI，避免同一个设备
在 MME / DirectSound / WASAPI 下重复出现。
"""

from __future__ import annotations

import math
import threading

import numpy as np


def _preferred_hostapi() -> int | None:
    import sounddevice as sd

    try:
        apis = sd.query_hostapis()
    except Exception:
        return None
    for i, api in enumerate(apis):
        if "wasapi" in str(api.get("name", "")).lower():
            return i
    return None


def list_devices(kind: str) -> list[str]:
    """kind: "input" | "output"。

    只看 WASAPI：MME / DirectSound / WDM-KS 会把同一个设备重复列出来，
    连系统里已禁用的也照样出现。WASAPI 的列表就是控制面板里真正启用的那些。
    """
    try:
        import sounddevice as sd

        devices = sd.query_devices()
    except Exception:
        return []
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    preferred = _preferred_hostapi()
    names: list[str] = []
    for dev in devices:
        if int(dev.get(key, 0) or 0) <= 0:
            continue
        if preferred is not None and int(dev.get("hostapi", -1)) != preferred:
            continue
        name = str(dev.get("name", "")).strip()
        if name and name not in names:
            names.append(name)
    return names


def resolve(name: str, kind: str) -> int | None:
    """设备名 -> 索引；空名返回 None（用系统默认）。"""
    if not name:
        return None
    try:
        import sounddevice as sd

        devices = sd.query_devices()
    except Exception:
        return None
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    preferred = _preferred_hostapi()
    fallback = None
    for idx, dev in enumerate(devices):
        if int(dev.get(key, 0) or 0) <= 0:
            continue
        if str(dev.get("name", "")).strip() != name:
            continue
        if preferred is not None and int(dev.get("hostapi", -1)) == preferred:
            return idx
        if fallback is None:
            fallback = idx
    return fallback


TARGET_RATE = 16000


def _default_wasapi(kind: str) -> int | None:
    """系统默认设备也要落到 WASAPI 上：WDM-KS 那个默认经常打不开。"""
    import sounddevice as sd

    wasapi = _preferred_hostapi()
    if wasapi is None:
        return None
    try:
        api = sd.query_hostapis()[wasapi]
        idx = api.get("default_input_device" if kind == "input" else "default_output_device")
    except Exception:
        return None
    return int(idx) if idx is not None and int(idx) >= 0 else None


def _wasapi_extra(device, kind: str):
    """WASAPI 设备让系统自己重采样，比我们手算干净得多。"""
    import sounddevice as sd

    try:
        api = int(
            sd.query_devices(device if device is not None else sd.default.device[0], kind)["hostapi"]
        )
    except Exception:
        return None
    wasapi = _preferred_hostapi()
    if wasapi is None or api != wasapi:
        return None
    try:
        return sd.WasapiSettings(auto_convert=True)
    except Exception:
        return None


def open_input(name: str, frame_ms: int = 30, callback=None):
    """开一个单声道 int16 输入流，返回 (stream, 实际采样率)。

    WASAPI 设备经常只认 48k，不认 16k，所以先试 16k；失败了就按设备默认
    采样率开，调用方再用 downsample() 降回 16k 给 ASR。
    """
    import sounddevice as sd

    device = resolve(name, "input")
    if device is None:
        device = _default_wasapi("input")
    extra = _wasapi_extra(device, "input")
    try:
        stream = sd.InputStream(
            samplerate=TARGET_RATE,
            channels=1,
            dtype="int16",
            blocksize=TARGET_RATE * frame_ms // 1000,
            device=device,
            callback=callback,
            extra_settings=extra,
        )
        return stream, TARGET_RATE
    except Exception:
        info = sd.query_devices(device if device is not None else sd.default.device[0], "input")
        native = int(info.get("default_samplerate") or 48000)
        if native == TARGET_RATE:
            raise
        stream = sd.InputStream(
            samplerate=native,
            channels=1,
            dtype="int16",
            blocksize=native * frame_ms // 1000,
            device=device,
            callback=callback,
        )
        return stream, native


def downsample(mono, rate: int, target: int = TARGET_RATE):
    """把任意采样率降成 16k。整数倍先用滑动平均做低通，避免混叠。"""
    import numpy as np

    if rate == target or mono is None or len(mono) == 0:
        return mono
    factor = rate / target
    if abs(factor - round(factor)) < 0.02 and round(factor) >= 1:
        k = int(round(factor))
        n = len(mono) // k * k
        if n <= 0:
            return mono[:0]
        return mono[:n].reshape(-1, k).mean(axis=1).astype(np.int16)
    idx = np.linspace(0, len(mono) - 1, max(1, int(len(mono) * target / rate)))
    return np.interp(idx, np.arange(len(mono)), mono).astype(np.int16)


class MonoStream:
    """把单声道数据写进可能只支持多声道的设备（虚拟声卡常见）。"""

    def __init__(self, stream, channels: int) -> None:
        self._stream = stream
        self.channels = channels

    def start(self) -> None:
        self._stream.start()

    def stop(self) -> None:
        self._stream.stop()

    def close(self) -> None:
        self._stream.close()

    def write(self, data) -> None:
        import numpy as np

        mono = np.asarray(data, dtype=np.int16)
        if self.channels > 1:
            mono = np.repeat(mono, self.channels, axis=1)
        self._stream.write(mono)

    def __enter__(self):
        self._stream.start()
        return self

    def __exit__(self, *_exc) -> None:
        try:
            self._stream.stop()
        finally:
            self._stream.close()


def open_output(name: str, rate: int = 24000, frame_ms: int = 80, callback=None):
    """开一个单声道输出流，返回 (stream, 实际采样率)。

    和输入一样：WASAPI 设备常常只认 48k，先试目标采样率，失败就用设备默认。
    """
    import sounddevice as sd

    device = resolve(name, "output")
    if device is None:
        device = _default_wasapi("output")
    info = sd.query_devices(device if device is not None else sd.default.device[1], "output")
    native = int(info.get("default_samplerate") or 48000)
    max_ch = max(1, int(info.get("max_output_channels", 1) or 1))
    extra = _wasapi_extra(device, "output")
    candidates: list[tuple[int, int, object]] = []
    if extra is not None:
        candidates.append((rate, 1, extra))  # 让 WASAPI 自己转，音质最好
    candidates.append((rate, 1, None))
    if native != rate:
        candidates.append((native, 1, None))
    if max_ch >= 2:
        candidates.append((native, 2, None))
    if max_ch > 2:
        candidates.append((native, max_ch, None))  # 虚拟 7.1 声卡只认满声道
    last: Exception | None = None
    for use_rate, channels, settings in candidates:
        try:
            stream = sd.OutputStream(
                samplerate=use_rate,
                channels=channels,
                dtype="int16",
                blocksize=use_rate * frame_ms // 1000,
                device=device,
                callback=callback,
                extra_settings=settings,
            )
            return MonoStream(stream, channels), use_rate
        except Exception as exc:  # 采样率/声道数不被支持，换下一组
            last = exc
    raise last if last is not None else RuntimeError("打不开输出设备")


def resample(pcm, src: int, dst: int):
    """采样率转换：多相 + 窗函数低通。

    之前用线性插值，24k->48k 会带上一层镜像噪声，听感发糊；
    这里先补零上采样、过一道 sinc 低通，再按整数比抽取。
    """
    import numpy as np

    if src == dst or pcm is None or len(pcm) == 0:
        return pcm
    g = math.gcd(int(src), int(dst))
    up = int(dst // g)
    down = int(src // g)

    x = np.asarray(pcm, dtype=np.float32) / 32768.0
    if up > 1:
        buf = np.zeros(len(x) * up, dtype=np.float32)
        buf[::up] = x
    else:
        buf = x

    # 截止频率 = 目标 Nyquist / 上采样后的采样率
    cutoff = 0.5 / max(up, down)
    taps = 63
    n = np.arange(taps) - (taps - 1) / 2.0
    window = np.hamming(taps)
    kernel = np.sinc(2.0 * cutoff * n) * window
    kernel /= kernel.sum()
    buf = np.convolve(buf, kernel, mode="same")

    if down > 1:
        buf = buf[::down]

    return np.clip(buf * 32768.0, -32768.0, 32767.0).astype(np.int16)


def play_tone(name: str, seconds: float = 0.6, freq: float = 880.0) -> str:
    """播放器测试音；返回错误信息，空字符串表示成功。"""
    try:
        rate = 24000
        frames = int(rate * seconds)
        t = np.arange(frames) / rate
        wave = (np.sin(2 * math.pi * freq * t) * 0.25 * 32767).astype(np.int16)
        stream, real_rate = open_output(name, rate, 50)
        with stream:
            stream.write(resample(wave, rate, real_rate).reshape(-1, 1))
        return ""
    except Exception as exc:  # 设备被占用 / 不支持
        return str(exc)


class MicProbe:
    """实时电平，给「测试麦克风」用。"""

    def __init__(self) -> None:
        self.level = 0.0
        self._stream = None
        self._rate = TARGET_RATE

    def start(self, name: str) -> str:
        self.stop()
        try:
            self._stream, self._rate = open_input(name, 30, self._on_audio)
            self._stream.start()
            return ""
        except Exception as exc:
            self._stream = None
            return str(exc)

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        self.level = 0.0
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def _on_audio(self, indata, _frames, _time, _status) -> None:
        mono = indata[:, 0].astype(np.float32)
        rms = float(np.sqrt(np.mean(mono**2))) if mono.size else 0.0
        self.level = min(1.0, rms / 3500.0)
