import asyncio, sys, time
sys.path.insert(0, ".")
import numpy as np
import edge_tts, miniaudio

SPOKEN = "这个 boss 二阶段一直掉血，怎么打"

async def synth(text):
    c = edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural", rate="+8%")
    buf = bytearray()
    async for ch in c.stream():
        if ch["type"] == "audio":
            buf.extend(ch["data"])
    return bytes(buf)

mp3 = asyncio.run(synth(SPOKEN))
d = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=16000)
pcm = np.array(d.samples, dtype=np.int16)
print("audio:", round(len(pcm) / 16000, 2), "s", flush=True)

from app.voice.asr import WhisperASR

t0 = time.time()
asr = WhisperASR("small")
asr.load()
print("model loaded in", round(time.time() - t0, 1), "s", flush=True)

t1 = time.time()
text = asr.transcribe(pcm)
cost = time.time() - t1
print("spoken :", SPOKEN)
print("heard  :", text)
print("transcribe:", round(cost, 2), "s, RTF", round(cost / (len(pcm) / 16000), 2))
