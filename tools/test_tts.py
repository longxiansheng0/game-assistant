import asyncio, sys, time
sys.path.insert(0, ".")
import numpy as np

from app.voice.tts import speakable

print("strip:", speakable("**弱雷**，二阶段先清小怪。\n- 见 [BWiki](https://x.com) 说明"))

import edge_tts, miniaudio

async def synth(text):
    c = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural", rate="+8%")
    buf = bytearray()
    async for ch in c.stream():
        if ch["type"] == "audio":
            buf.extend(ch["data"])
    return bytes(buf)

t0 = time.time()
mp3 = asyncio.run(synth("这个 boss 二阶段一直掉血，怎么打"))
print("tts bytes:", len(mp3), "time:", round(time.time() - t0, 2), "s")

d = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=24000)
pcm = np.array(d.samples, dtype=np.int16)
print("pcm:", round(len(pcm) / d.sample_rate, 2), "s @", d.sample_rate, "Hz")

import sounddevice as sd
print("default out:", sd.query_devices(kind="output")["name"][:30])
try:
    inp = sd.query_devices(kind="input")
    print("default in:", inp["name"][:30])
except Exception as e:
    print("no input device:", e)
