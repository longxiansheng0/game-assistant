import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
from app.ui.bubble import Bubble

b = Bubble()
b.begin("原神")
b.append("**弱雷**，二阶段会召小怪，先用范围技能清场。\n\n1. 雷系伤害 +50%，换雷系主 C\n2. 第二阶段召唤 4 只使徒，优先清小怪\n3. 护盾阶段换大剑，破盾效率翻倍\n\n来源：[BWiki 深渊使徒](https://wiki.biligame.com/ys/)")
b.finish("")
app.processEvents()
b.resize(520, 380)
app.processEvents()
pm = b.grab()
pm.save("preview_bubble.png")
print("bubble", pm.width(), pm.height())

# 右下角放大看抓手
corner = b.grab().toImage().copy(pm.width()-90, pm.height()-70, 90, 70)
big = corner.scaled(270, 210, Qt.KeepAspectRatio, Qt.FastTransformation)
canvas = QImage(270, 210, QImage.Format_ARGB32)
canvas.fill(QColor("#2b3240"))
p = QPainter(canvas); p.drawImage(0, 0, big); p.end()
canvas.save("preview_grip.png")
print("grip ok")
