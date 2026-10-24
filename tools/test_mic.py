import sys, time
sys.path.insert(0, ".")
from app.voice.recorder import Recorder

r = Recorder()
print("start:", r.start(), "|", r.error)
if r.active:
    t0 = time.time()
    levels = []
    while time.time() - t0 < 2.5:
        levels.append(round(r.level, 3))
        res = r.poll()
        if res:
            print("finished early:", res[0])
            break
        time.sleep(0.25)
    print("levels:", levels)
    r.cancel()
    print("cancelled, active:", r.active)
