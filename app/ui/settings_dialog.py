"""设置窗口：所有配置都在这里改，不用去动 json。

首次启动会以「欢迎」形式弹出，填完 key 就能用。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

BG = QColor(17, 22, 33, 250)
BORDER = QColor(110, 140, 220, 60)
TEXT = "#dbe4f7"
MUTED = "#7c8aa8"
ACCENT = "#6c8afd"

STYLE = """
QWidget { color: #dbe4f7; font-size: 13px; }
QLineEdit, QComboBox, QSpinBox {
    background: #0d111b; border: 1px solid #232c42; border-radius: 8px;
    padding: 6px 9px; color: #dbe4f7; selection-background-color: #2f3f6b;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #3d5bb5; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: none; }
QComboBox QAbstractItemView {
    background: #141a26; color: #dbe4f7; border: 1px solid #232c42;
    selection-background-color: #26304a; outline: none;
}
QCheckBox { spacing: 7px; }
QCheckBox::indicator {
    width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid #33405e; background: #0d111b;
}
QCheckBox::indicator:checked { background: #6c8afd; border-color: #6c8afd; }
QTabWidget::pane { border: 1px solid #1b2231; border-radius: 10px; top: -1px; }
QTabBar::tab {
    background: transparent; color: #7c8aa8; padding: 7px 16px;
    border: none; margin-right: 2px;
}
QTabBar::tab:selected { color: #dbe4f7; border-bottom: 2px solid #6c8afd; }
QTabBar::tab:hover { color: #b9c6e6; }
QPushButton {
    background: #182034; border: 1px solid #232c42; border-radius: 8px;
    padding: 7px 16px; color: #cbd7f2;
}
QPushButton:hover { background: #223050; }
QPushButton#primary { background: #4a6cf0; border: none; color: white; }
QPushButton#primary:hover { background: #5b7bff; }
QSlider::groove:horizontal { height: 4px; background: #232c42; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 13px; margin: -5px 0; border-radius: 6px; background: #6c8afd;
}
"""

_QT_KEYS = {
    Qt.Key_Space: "SPACE",
    Qt.Key_Tab: "TAB",
    Qt.Key_CapsLock: "CAPSLOCK",
    Qt.Key_Insert: "INSERT",
    Qt.Key_Home: "HOME",
    Qt.Key_End: "END",
    Qt.Key_PageUp: "PAGEUP",
    Qt.Key_PageDown: "PAGEDOWN",
}


def combo_from_event(event) -> str:
    """把一次按键翻译成 "Ctrl+Alt+F8" 这种写法。"""
    key = event.key()
    if key in (Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta):
        return ""
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        name = f"F{key - Qt.Key_F1 + 1}"
    elif Qt.Key_A <= key <= Qt.Key_Z:
        name = chr(key)
    elif Qt.Key_0 <= key <= Qt.Key_9:
        name = chr(key)
    else:
        name = _QT_KEYS.get(key, "")
    if not name:
        return ""

    mods = []
    m = event.modifiers()
    if m & Qt.ControlModifier:
        mods.append("Ctrl")
    if m & Qt.AltModifier:
        mods.append("Alt")
    if m & Qt.ShiftModifier:
        mods.append("Shift")
    if m & Qt.MetaModifier:
        mods.append("Win")
    return "+".join(mods + [name])


class ComboBox(QComboBox):
    """系统默认的箭头在深色背景上几乎看不见，自己画一个。"""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#8593b3"), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        x = self.width() - 15
        y = self.height() / 2 - 2
        painter.drawLine(QPointF(x - 4, y), QPointF(x, y + 4))
        painter.drawLine(QPointF(x, y + 4), QPointF(x + 4, y))
        painter.end()


class HotkeyEdit(QLineEdit):
    """点一下，按下想用的组合键，就录进去了。"""

    def __init__(self, value: str = "") -> None:
        super().__init__(value)
        self.setReadOnly(True)
        self.setPlaceholderText("点这里，然后按组合键")
        self.setToolTip("Esc 清空 · 支持 Ctrl / Alt / Shift / Win 组合")

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Escape, Qt.Key_Backspace, Qt.Key_Delete):
            self.setText("")
            event.accept()
            return
        combo = combo_from_event(event)
        if combo:
            self.setText(combo)
            event.accept()
            return
        event.accept()


class _TestWorker(QThread):
    ok = Signal(str)
    fail = Signal(str)

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def run(self) -> None:
        try:
            from ..llm.deepseek import DeepSeekClient

            client = DeepSeekClient(self.api_key, self.base_url, self.model)
            client.chat([{"role": "user", "content": "ping"}], max_tokens=8)
            self.ok.emit("连接正常")
        except Exception as exc:  # noqa: BLE001
            self.fail.emit(str(exc))


PREVIEW_TEXT = "这个 BOSS 弱雷，二阶段会召唤小怪，先用范围技能清场。"


class _PreviewWorker(QThread):
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, text: str, voice: str, rate: str) -> None:
        super().__init__()
        self.text = text
        self.voice = voice
        self.rate = rate

    def run(self) -> None:
        try:
            from ..voice.tts import play, synthesize

            pcm = synthesize(self.text, self.voice, self.rate)
            if pcm is not None:
                play(pcm)
            self.finished_ok.emit()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class SettingsDialog(QDialog):
    saved = Signal()

    def __init__(self, settings, first_run: bool = False) -> None:
        super().__init__()
        self.settings = settings
        self.first_run = first_run
        self._drag: QPoint | None = None
        self._worker: _TestWorker | None = None
        self._preview: _PreviewWorker | None = None

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(STYLE)
        self.setMinimumSize(540, 560)
        self.resize(560, 620)
        self._build()

    # ---------- 外观 ----------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(BORDER, 1))
        p.setBrush(BG)
        p.drawRoundedRect(rect, 16, 16)
        p.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and event.position().y() < 54:
            self._drag = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None:
            self.move(self.pos() + event.globalPosition().toPoint() - self._drag)
            self._drag = event.globalPosition().toPoint()

    def mouseReleaseEvent(self, _event) -> None:
        self._drag = None

    # ---------- 构建 ----------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 18)
        root.setSpacing(12)

        title = QLabel("欢迎使用游戏助手" if self.first_run else "设置")
        title.setStyleSheet("font-size:18px; font-weight:600;")
        sub = QLabel(
            "先填一个 DeepSeek API Key，其它都能以后再改"
            if self.first_run
            else "改完点保存立即生效，不用重启"
        )
        sub.setStyleSheet(f"color:{MUTED}; font-size:12px;")

        close_btn = QPushButton("×")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton{border:none;background:transparent;color:#8b97b5;"
            "font-size:17px;padding:0px;margin:0px;}"
            "QPushButton:hover{color:#e8eeff;background:#1c2434;border-radius:12px;}"
        )
        close_btn.clicked.connect(self.reject)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(10)
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addWidget(title)
        text_col.addWidget(sub)
        head.addLayout(text_col, 1)
        head.addWidget(close_btn, 0, Qt.AlignTop)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_ai(), "AI")
        self.tabs.addTab(self._tab_voice(), "语音")
        self.tabs.addTab(self._tab_screen(), "画面")
        self.tabs.addTab(self._tab_hotkey(), "快捷键")

        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{MUTED}; font-size:12px;")

        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self._test)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        self.save_btn = QPushButton("开始使用" if self.first_run else "保存")
        self.save_btn.setObjectName("primary")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._save)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        foot.addWidget(self.test_btn)
        foot.addWidget(self.status, 1)
        foot.addWidget(cancel)
        foot.addWidget(self.save_btn)

        root.addLayout(head)
        root.addWidget(self.tabs, 1)
        root.addLayout(foot)

        if self.first_run:
            self.tabs.setCurrentIndex(0)

    # ---------- 四个页 ----------

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"color:{MUTED}; font-size:12px;")
        return label

    def _field(self, title: str, inner) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(6)
        cap = QLabel(title)
        cap.setStyleSheet("font-size:12px;")
        box.addWidget(cap)
        if isinstance(inner, QWidget):
            box.addWidget(inner)
        else:
            box.addLayout(inner)
        return box

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(13)
        return page, lay

    def _tab_ai(self) -> QWidget:
        page, lay = self._page()

        self.key_edit = QLineEdit(self.settings.api_key)
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("sk-…")
        self.show_key = QCheckBox("显示")
        self.show_key.toggled.connect(
            lambda on: self.key_edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        )
        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(self.show_key)
        lay.addLayout(self._field("DeepSeek API Key", key_row))
        lay.addWidget(self._hint("在 platform.deepseek.com 申请，按量付费，问一次几分钱。"))

        self.model_combo = ComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems(["deepseek-flash"])
        self.model_combo.setCurrentText(self.settings.model)
        lay.addLayout(self._field("模型", self.model_combo))
        lay.addWidget(self._hint("只有 deepseek-flash 支持读图；DeepSeek-V4-Pro 是纯文本。"))

        self.base_edit = QLineEdit(self.settings.base_url)
        lay.addLayout(self._field("接口地址", self.base_edit))

        self.search_chk = QCheckBox("让它自己联网查攻略")
        self.search_chk.setChecked(self.settings.allow_search)
        self.think_chk = QCheckBox("深度思考（更准，但要多等 3~8 秒）")
        self.think_chk.setChecked(self.settings.think)
        lay.addWidget(self.search_chk)
        lay.addWidget(self.think_chk)
        lay.addStretch(1)
        return page

    def _tab_voice(self) -> QWidget:
        page, lay = self._page()

        self.voice_chk = QCheckBox("允许语音输入（关掉就只打字）")
        self.voice_chk.setChecked(self.settings.voice_enabled)
        self.tts_chk = QCheckBox("朗读回答")
        self.tts_chk.setChecked(self.settings.tts_enabled)
        lay.addWidget(self.voice_chk)

        self.call_chk = QCheckBox("通话模式（听到唤醒词就开始）")
        self.call_chk.setChecked(self.settings.call_mode)
        lay.addWidget(self.call_chk)
        self.wake_edit = QLineEdit(self.settings.wake_word)
        self.wake_edit.setPlaceholderText("小助手")
        self.wake_edit.setMaxLength(8)
        self.ack_edit = QLineEdit(self.settings.wake_ack)
        self.ack_edit.setPlaceholderText("留空 = 不说话")
        self.ack_edit.setMaxLength(20)
        wake_row = QHBoxLayout()
        wake_row.setSpacing(12)
        wake_row.addLayout(self._field("唤醒词", self.wake_edit))
        wake_row.addLayout(self._field("唤醒应答", self.ack_edit))
        lay.addLayout(wake_row)
        lay.addWidget(
            self._hint(
                "喊「唤醒词 + 问题」一次说完；它先用「唤醒应答」回你一声，再开始答题。"
                "麦克风常开但只在本机判断，不上传；外放游戏声易误触发，建议戴耳机。"
            )
        )
        lay.addWidget(self.tts_chk)

        self.voice_combo = ComboBox()
        for voice_id, label in (
            ("zh-CN-XiaoxiaoNeural", "晓晓 · 女声，自然"),
            ("zh-CN-XiaoyiNeural", "晓伊 · 女声，年轻"),
            ("zh-CN-YunxiNeural", "云希 · 男声，清爽"),
            ("zh-CN-YunyangNeural", "云扬 · 男声，播报腔"),
        ):
            self.voice_combo.addItem(label, voice_id)
        index = self.voice_combo.findData(self.settings.tts_voice)
        self.voice_combo.setCurrentIndex(max(0, index))
        self.preview_btn = QPushButton("试听")
        self.preview_btn.setFixedWidth(66)
        self.preview_btn.setCursor(Qt.PointingHandCursor)
        self.preview_btn.clicked.connect(self._preview_voice)
        voice_row = QHBoxLayout()
        voice_row.setSpacing(8)
        voice_row.addWidget(self.voice_combo, 1)
        voice_row.addWidget(self.preview_btn)
        lay.addLayout(self._field("朗读音色", voice_row))

        self.rate_slider = QSlider(Qt.Horizontal)
        self.rate_slider.setRange(-20, 30)
        self.rate_slider.setSingleStep(2)
        try:
            self.rate_slider.setValue(int(self.settings.tts_rate.replace("%", "").replace("+", "")))
        except ValueError:
            self.rate_slider.setValue(8)
        self.rate_value = QLabel(f"{self.rate_slider.value():+d}%")
        self.rate_value.setStyleSheet(f"color:{ACCENT};")
        self.rate_slider.valueChanged.connect(lambda v: self.rate_value.setText(f"{v:+d}%"))
        rate_row = QHBoxLayout()
        rate_row.addWidget(self.rate_slider, 1)
        rate_row.addWidget(self.rate_value)
        lay.addLayout(self._field("语速", rate_row))

        self.asr_combo = ComboBox()
        for size, label in (
            ("base", "base · 最快"),
            ("small", "small · 推荐"),
            ("medium", "medium · 更准但慢"),
        ):
            self.asr_combo.addItem(label, size)
        index = self.asr_combo.findData(self.settings.asr_model)
        self.asr_combo.setCurrentIndex(max(0, index))
        lay.addLayout(self._field("识别模型", self.asr_combo))
        lay.addWidget(self._hint("换模型后第一次说话要重新加载。识别跑在 CPU 上，显卡留给游戏。"))
        lay.addStretch(1)
        return page

    def _tab_screen(self) -> QWidget:
        page, lay = self._page()

        self.width_spin = QSpinBox()
        self.width_spin.setRange(960, 1920)
        self.width_spin.setSingleStep(160)
        self.width_spin.setValue(max(960, min(1920, self.settings.max_image_width)))
        self.width_spin.setSuffix(" px")
        lay.addLayout(self._field("截图宽度", self.width_spin))
        lay.addWidget(self._hint("越小越省钱越快，1280 一般够用；看不清小字再往上调。"))

        self.ocr_chk = QCheckBox("OCR 识别屏幕上的小字")
        self.ocr_chk.setChecked(self.settings.ocr_enabled)
        lay.addWidget(self.ocr_chk)
        lay.addWidget(self._hint("在你说话的几秒里后台跑，不占等待时间。"))

        self.orb_combo = ComboBox()
        for size in (48, 56, 64, 72, 80, 96):
            self.orb_combo.addItem(f"{size} px", size)
        index = self.orb_combo.findData(self.settings.orb_size)
        self.orb_combo.setCurrentIndex(max(0, index))
        lay.addLayout(self._field("小球大小", self.orb_combo))
        lay.addStretch(1)
        return page

    def _tab_hotkey(self) -> QWidget:
        page, lay = self._page()

        self.voice_hk = HotkeyEdit(self.settings.hotkey)
        self.text_hk = HotkeyEdit(self.settings.text_hotkey)
        lay.addLayout(self._field("说话键", self.voice_hk))
        lay.addLayout(self._field("打字键", self.text_hk))
        lay.addWidget(
            self._hint(
                "点进输入框，直接按想用的组合键（Esc 清空）。\n"
                "建议用 F8 / F9 这种游戏里不常用的键，或者带 Ctrl 的组合，"
                "免得和游戏按键打架。"
            )
        )
        lay.addStretch(1)
        return page

    # ---------- 读写 ----------

    def _collect(self) -> dict:
        return {
            "api_key": self.key_edit.text().strip(),
            "model": self.model_combo.currentText().strip() or "deepseek-flash",
            "base_url": self.base_edit.text().strip() or "https://api.deepseek.com",
            "allow_search": self.search_chk.isChecked(),
            "think": self.think_chk.isChecked(),
            "voice_enabled": self.voice_chk.isChecked(),
            "tts_enabled": self.tts_chk.isChecked(),
            "call_mode": self.call_chk.isChecked(),
            "wake_word": self.wake_edit.text().strip(),
            "wake_ack": self.ack_edit.text().strip(),
            "tts_voice": self.voice_combo.currentData(),
            "tts_rate": f"{self.rate_slider.value():+d}%",
            "asr_model": self.asr_combo.currentData(),
            "max_image_width": self.width_spin.value(),
            "ocr_enabled": self.ocr_chk.isChecked(),
            "orb_size": self.orb_combo.currentData(),
            "hotkey": self.voice_hk.text().strip(),
            "text_hotkey": self.text_hk.text().strip(),
        }

    def _validate(self, data: dict) -> str:
        from .hotkey import parse_combo

        if data["call_mode"] and not data["wake_word"]:
            return "开了通话模式就得填个唤醒词"
        if data["call_mode"] and not data["voice_enabled"]:
            return "通话模式需要先打开语音输入"

        if not data["hotkey"]:
            return "说话键不能为空"
        if parse_combo(data["hotkey"]) is None:
            return f"说话键不合法：{data['hotkey']}"
        if data["text_hotkey"]:
            if parse_combo(data["text_hotkey"]) is None:
                return f"打字键不合法：{data['text_hotkey']}"
            if data["text_hotkey"].upper() == data["hotkey"].upper():
                return "两个快捷键不能设成一样"
        return ""

    def _save(self) -> None:
        data = self._collect()
        error = self._validate(data)
        if error:
            self.status.setStyleSheet("color:#f87171; font-size:12px;")
            self.status.setText(error)
            return
        for key, value in data.items():
            setattr(self.settings, key, value)
        self.settings.welcome_done = True
        try:
            self.settings.save()
        except Exception as exc:  # noqa: BLE001
            self.status.setStyleSheet("color:#f87171; font-size:12px;")
            self.status.setText(f"保存失败：{exc}")
            return
        self.saved.emit()
        self.accept()

    def _preview_voice(self) -> None:
        if self._preview is not None and self._preview.isRunning():
            return
        voice = self.voice_combo.currentData()
        rate = f"{self.rate_slider.value():+d}%"
        self.preview_btn.setEnabled(False)
        self.preview_btn.setText("…")
        self._preview = _PreviewWorker(PREVIEW_TEXT, voice, rate)
        self._preview.finished_ok.connect(self._preview_done)
        self._preview.failed.connect(self._preview_failed)
        self._preview.start()

    def _preview_done(self) -> None:
        self.preview_btn.setEnabled(True)
        self.preview_btn.setText("试听")

    def _preview_failed(self, message: str) -> None:
        self._preview_done()
        self.status.setStyleSheet("color:#f87171; font-size:12px;")
        self.status.setText(f"试听失败：{message}")

    def done(self, result: int) -> None:
        if self._preview is not None and self._preview.isRunning():
            self._preview.wait(4000)
        super().done(result)

    def _test(self) -> None:
        key = self.key_edit.text().strip()
        if not key:
            self.status.setStyleSheet("color:#f87171; font-size:12px;")
            self.status.setText("先填 Key 再测")
            return
        self.test_btn.setEnabled(False)
        self.status.setStyleSheet(f"color:{MUTED}; font-size:12px;")
        self.status.setText("测试中…")
        self._worker = _TestWorker(
            key,
            self.base_edit.text().strip() or "https://api.deepseek.com",
            self.model_combo.currentText().strip() or "deepseek-flash",
        )
        self._worker.ok.connect(self._on_test_ok)
        self._worker.fail.connect(self._on_test_fail)
        self._worker.start()

    def _on_test_ok(self, message: str) -> None:
        self.test_btn.setEnabled(True)
        self.status.setStyleSheet("color:#34d399; font-size:12px;")
        self.status.setText(f"✓ {message}")

    def _on_test_fail(self, message: str) -> None:
        self.test_btn.setEnabled(True)
        self.status.setStyleSheet("color:#f87171; font-size:12px;")
        self.status.setText(message)
