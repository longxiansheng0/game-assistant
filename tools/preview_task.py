import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
from app.ui.bubble import Bubble

b = Bubble()
b.begin("办公模式")
b.begin_task()
steps = [["✓", "scan · 读取工作区目录"], ["✓", "grep · 截图"], ["◐", "pwsh · Move-Item 37 个文件"], ["○", "汇总"]]
b.render_task(steps, "00:23", True)
app.processEvents(); b.resize(470, 330); app.processEvents()
b.grab().save("preview_task.png")

steps[2][0] = "✓"; steps[3][0] = "✓"
b.render_task(steps, "00:41", False, ("结果", "37 个截图已按月份归好，最早 2024-03，最新 2026-10。"))
b.end_task()
app.processEvents(); b.resize(470, 330); app.processEvents()
b.grab().save("preview_task_done.png")
print("ok")
