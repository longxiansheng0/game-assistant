import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
from app.ui.orb import Orb

cases = [("game/idle", "game", "idle"), ("office/idle", "office", "idle"),
         ("office/think", "office", "thinking"), ("office/listen", "office", "listening"),
         ("office/speak", "office", "speaking")]
img = QImage(88 * len(cases), 88, QImage.Format_ARGB32)
img.fill(QColor("#20242e"))
p = QPainter(img)
for i, (_, mode, state) in enumerate(cases):
    o = Orb(88)
    o.set_mode(mode)
    o.set_state(state)
    o._debug_gaze = (0.0, 0.0)
    p.drawPixmap(i * 88, 0, o.grab())
p.end()
img.save("preview_mode.png")
print("ok")
