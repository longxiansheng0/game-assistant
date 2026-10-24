import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from app.config import Settings
from app.ui.settings_dialog import SettingsDialog

app = QApplication(sys.argv)
s = Settings()
s.save = lambda: None
dlg = SettingsDialog(s, first_run=False)
dlg.show()
app.processEvents()

imgs = []
for i in range(4):
    dlg.tabs.setCurrentIndex(i)
    app.processEvents()
    imgs.append(dlg.grab().toImage())

w, h = imgs[0].width(), imgs[0].height()
canvas = QImage(w * 2, h * 2, QImage.Format_ARGB32)
canvas.fill(QColor("#0b0e14"))
p = QPainter(canvas)
for i, im in enumerate(imgs):
    p.drawImage((i % 2) * w, (i // 2) * h, im)
p.end()
canvas.save("preview_settings_all.png")
print("ok", canvas.width(), canvas.height())
