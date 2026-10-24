import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
from app.ui.orb import Orb

cases = [
    ("look NE", "idle", (-0.8, -0.7), 0.0, 0.0),
    ("look S", "idle", (0.0, 1.0), 0.0, 0.0),
    ("listen", "listening", (0.6, -0.2), 0.0, 0.0),
    ("think", "thinking", None, 0.0, 0.0),
    ("speak", "speaking", (-0.3, 0.2), 0.0, 0.0),
    ("hover", "idle", (0.0, 0.0), 1.0, 0.0),
]

cell = 92
img = QImage(cell * len(cases), cell * 2 + 24, QImage.Format_ARGB32)
img.fill(QColor("#20242e"))
p = QPainter(img)
for row, size in enumerate((84, 60)):
    for i, (label, state, gaze, hover, press) in enumerate(cases):
        o = Orb(size)
        o.set_state(state)
        o._debug_gaze = gaze
        o._hover = hover
        p.drawPixmap(i * cell + (cell - size) // 2, row * cell + 20 + (cell - size) // 2, o.grab())
for i, (label, *_rest) in enumerate(cases):
    p.setPen(QColor("#9fb0cc")) if size else None
p.setPen(QColor("#9fb0cc"))
for i, (label, *_rest) in enumerate(cases):
    p.drawText(i * cell + 8, 14, label)
p.end()
img.save("preview_pet.png")
print("ok")
