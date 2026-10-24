import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
from app.ui.orb import Orb

states = ["idle", "listening", "thinking", "speaking"]
sizes = [96, 64]
cell = 100
img = QImage(cell * 4, cell * 2, QImage.Format_ARGB32)
img.fill(QColor("#252a35"))
p = QPainter(img)
for row, size in enumerate(sizes):
    o = Orb(size)
    for i, s in enumerate(states):
        o.set_state(s)
        pm = o.grab()
        p.drawPixmap(i * cell + (cell - size) // 2, row * cell + (cell - size) // 2, pm)
p.end()
img.save("preview_orb.png")
print("ok")
