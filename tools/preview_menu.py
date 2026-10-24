import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
from app.ui.orb import Orb

o = Orb(64)
o.set_toggles({"voice": True, "tts": True, "call": True, "autostart": False})
menu = o._build_menu()
menu.adjustSize()
pix = menu.grab()
pix.save("preview_menu.png")
print("menu size:", pix.width(), pix.height())
for act in menu.actions():
    if act.isSeparator():
        print("  ---")
    else:
        print(("  [x] " if act.isChecked() else "  [ ] " if act.isCheckable() else "      ") + act.text())
