import sys
sys.path.insert(0, ".")
from app.vision.capture import grab, foreground_info, _target_rect, _effective_hwnd
from app.vision.capture import user32, _window_pid
import os

real = int(user32.GetForegroundWindow() or 0)
print("real foreground pid:", _window_pid(real), "| ours:", os.getpid())
print("effective:", _effective_hwnd(), "| info:", foreground_info()[1])
rect = _target_rect()
print("target:", rect)
cap = grab(max_width=4000)
print("captured:", cap.width, "x", cap.height, "|", len(cap.jpeg)//1024, "KB")
if rect:
    print("matches window:", (cap.width, cap.height) == (rect[2]-rect[0], rect[3]-rect[1]))
