import os, sys
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, '.')
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
from app.ui.bubble import Bubble
long_text = '把下载文件夹里 2024 年之前的所有截图按月份归类，重复的删掉，最后生成一个清单告诉我每个月有多少张'
b = Bubble()
b.begin('办公模式')
b.resize(470, 400)
app.processEvents()
print('before confirm:', b.width(), b.height())
b.begin_confirm(long_text, 'full')
app.processEvents()
print('after confirm:', b.width(), b.height(), '| input:', b.confirm_input.height())
b.grab().save('preview_confirm.png')