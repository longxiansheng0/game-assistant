"""设置窗口：所有配置都在这里改，不用去动 json。

首次启动会以「欢迎」形式弹出，填完 key 就能用。
"""

from __future__ import annotations

from html import escape as _esc

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QThread, QTimer, Signal

from ..core.vocab import (
    CONFIRM_MAX_CHARS,
    CONFIRM_NO,
    CONFIRM_RETRY,
    CONFIRM_YES,
    DANGER_WORDS,
    GROUP_LABELS,
    PERMISSION_LABELS,
)
from ..paths import base_dir, data_dir
from ..voice.devices import MicProbe, list_devices, play_tone
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
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
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #2b3550; border-radius: 4px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: #364366; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; width: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
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

    def __init__(self, text: str, voice: str, rate: str, device: str = "") -> None:
        super().__init__()
        self.text = text
        self.voice = voice
        self.rate = rate
        self.device = device

    def run(self) -> None:
        try:
            from ..voice.tts import play, synthesize

            pcm = synthesize(self.text, self.voice, self.rate)
            if pcm is not None:
                play(pcm, device=self.device)
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
        self._probe: MicProbe | None = None
        self._mic_peak = 0.0
        self._mic_max = 0.0
        self._mic_elapsed = 0
        self._mic_timer = QTimer(self)
        self._mic_timer.setInterval(80)
        self._mic_timer.timeout.connect(self._mic_tick)

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

        title = QLabel("欢迎使用语音助手" if self.first_run else "设置")
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
        for build, title in (
            (self._tab_ai, "AI"),
            (self._tab_voice, "语音"),
            (self._tab_screen, "画面"),
            (self._tab_office, "办公"),
            (self._tab_hotkey, "快捷键"),
            (self._tab_help, "帮助"),
        ):
            self.tabs.addTab(self._scrollable(build()), title)

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

    def _scrollable(self, page: QWidget) -> QScrollArea:
        """内容多的时候能滚，别让字段被裁掉。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea > QWidget > QWidget{background:transparent;}"
        )
        return scroll

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

        self.search_chk = QCheckBox("允许联网")
        self.search_chk.setChecked(self.settings.allow_search)
        self.think_chk = QCheckBox("深度思考")
        self.think_chk.setChecked(self.settings.think)
        lay.addWidget(self.search_chk)
        lay.addWidget(self.think_chk)
        lay.addStretch(1)
        return page

    def _tab_voice(self) -> QWidget:
        page, lay = self._page()

        self.voice_chk = QCheckBox("语音输入")
        self.voice_chk.setChecked(self.settings.voice_enabled)
        self.tts_chk = QCheckBox("朗读回答")
        self.tts_chk.setChecked(self.settings.tts_enabled)
        lay.addWidget(self.voice_chk)

        self.call_chk = QCheckBox("通话模式")
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
        self.spk_combo = ComboBox()
        self.spk_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.spk_combo.setMinimumContentsLength(10)
        self.spk_combo.addItem("系统默认", "")
        for name in list_devices("output"):
            self.spk_combo.addItem(name, name)
        self.spk_combo.setCurrentIndex(max(0, self.spk_combo.findData(self.settings.output_device)))
        spk_test = QPushButton("测试")
        spk_test.setFixedWidth(64)
        spk_test.clicked.connect(self._test_speaker)
        spk_row = QHBoxLayout()
        spk_row.setSpacing(8)
        spk_row.addWidget(self.spk_combo, 1)
        spk_row.addWidget(spk_test)
        lay.addLayout(self._field("扬声器", spk_row))

        self.mic_combo = ComboBox()
        self.mic_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mic_combo.setMinimumContentsLength(10)
        self.mic_combo.addItem("系统默认", "")
        for name in list_devices("input"):
            self.mic_combo.addItem(name, name)
        self.mic_combo.setCurrentIndex(max(0, self.mic_combo.findData(self.settings.input_device)))
        mic_test = QPushButton("测试")
        mic_test.setFixedWidth(64)
        mic_test.clicked.connect(self._test_mic)
        mic_row = QHBoxLayout()
        mic_row.setSpacing(8)
        mic_row.addWidget(self.mic_combo, 1)
        mic_row.addWidget(mic_test)
        lay.addLayout(self._field("麦克风", mic_row))

        self.mic_bar = QProgressBar()
        self.mic_bar.setRange(0, 100)
        self.mic_bar.setTextVisible(False)
        self.mic_bar.setFixedHeight(6)
        self.mic_bar.setStyleSheet(
            "QProgressBar{background:#141a28;border:none;border-radius:3px;}"
            "QProgressBar::chunk{background:#3d5bb5;border-radius:3px;}"
        )
        self.mic_bar.hide()
        lay.addWidget(self.mic_bar)
        lay.addWidget(self._hint("测试麦克风时会显示实时音量，说句话看看条子动没动。"))

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

        self.capture_chk = QCheckBox("允许截屏")
        self.capture_chk.setChecked(self.settings.capture_enabled)
        lay.addWidget(self.capture_chk)
        lay.addWidget(self._hint("只截前台窗口本身，不截整屏；关掉后不会抓任何画面。"))

        self.ocr_chk = QCheckBox("OCR识别")
        self.ocr_chk.setChecked(self.settings.ocr_enabled)
        lay.addWidget(self.ocr_chk)
        lay.addWidget(self._hint("开启可识别截屏中的文本"))

        self.orb_combo = ComboBox()
        for size in (48, 56, 64, 72, 80, 96):
            self.orb_combo.addItem(f"{size} px", size)
        index = self.orb_combo.findData(self.settings.orb_size)
        self.orb_combo.setCurrentIndex(max(0, index))
        lay.addLayout(self._field("小球大小", self.orb_combo))
        lay.addStretch(1)
        return page

    def _tab_office(self) -> QWidget:
        page, lay = self._page()

        self.mode_combo = ComboBox()
        self.mode_combo.addItem("游戏模式 · 快，看画面答题", "game")
        self.mode_combo.addItem("办公模式 · 慢，能操作电脑", "office")
        index = self.mode_combo.findData(self.settings.mode)
        self.mode_combo.setCurrentIndex(max(0, index))
        lay.addLayout(self._field("当前模式", self.mode_combo))

        self.workspace_edit = QLineEdit(self.settings.workspace_dir)
        self.workspace_edit.setPlaceholderText(str(self.settings.workspace))
        browse = QPushButton("浏览…")
        browse.setFixedWidth(70)
        browse.clicked.connect(self._pick_workspace)
        ws_row = QHBoxLayout()
        ws_row.setSpacing(8)
        ws_row.addWidget(self.workspace_edit, 1)
        ws_row.addWidget(browse)
        lay.addLayout(self._field("工作区目录", ws_row))
        lay.addWidget(self._hint("办公任务只能在这个目录里读写，出不去。留空用默认位置。"))

        self.perm_combo = ComboBox()
        self.perm_combo.addItem("只读 · 只能看，不能改", "read-only")
        self.perm_combo.addItem("工作区可写 · 推荐", "workspace-write")
        self.perm_combo.addItem("完全权限 · 能改整台电脑", "danger-full-access")
        index = self.perm_combo.findData(self.settings.office_permission)
        self.perm_combo.setCurrentIndex(max(0, index))
        lay.addLayout(self._field("权限级别", self.perm_combo))

        self.confirm_combo = ComboBox()
        self.confirm_combo.addItem("每次语音任务都确认 · 初次使用推荐", "all")
        self.confirm_combo.addItem("只有高危任务才确认", "danger")
        self.confirm_combo.addItem("不确认（不推荐）", "off")
        index = self.confirm_combo.findData(self.settings.confirm_mode)
        self.confirm_combo.setCurrentIndex(max(0, index))
        lay.addLayout(self._field("语音任务确认", self.confirm_combo))
        lay.addWidget(
            self._hint("办公模式下，语音听来的任务会先念给你听，确认后才执行。用完全权限时建议选「每次确认」。")
        )

        self.confirm_timeout_spin = QSpinBox()
        self.confirm_timeout_spin.setRange(5, 60)
        self.confirm_timeout_spin.setSuffix(" 秒")
        self.confirm_timeout_spin.setValue(max(5, min(60, self.settings.confirm_timeout)))

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(30, 900)
        self.timeout_spin.setSingleStep(30)
        self.timeout_spin.setSuffix(" 秒")
        self.timeout_spin.setValue(max(30, min(900, self.settings.office_timeout)))

        timeout_row = QHBoxLayout()
        timeout_row.setSpacing(12)
        timeout_row.addLayout(self._field("确认等待时间", self.confirm_timeout_spin))
        timeout_row.addLayout(self._field("单次任务超时", self.timeout_spin))
        lay.addLayout(timeout_row)
        lay.addWidget(self._hint("确认超时没回应就当作取消；任务超时会杀掉进程。"))

        builtin = (base_dir() / "vendor" / "dsh").exists() and (base_dir() / "vendor" / "node").exists()
        label = QLabel("已内置执行组件" if builtin else "执行组件缺失（vendor 未构建）")
        label.setStyleSheet(("color:#34d399;" if builtin else "color:#f87171;") + "font-size:12px;")
        lay.addWidget(label)
        lay.addStretch(1)
        return page

    def _pick_workspace(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        start = self.workspace_edit.text().strip() or str(self.settings.workspace)
        chosen = QFileDialog.getExistingDirectory(self, "选择工作区目录", start)
        if chosen:
            self.workspace_edit.setText(chosen)

    def _tab_help(self) -> QWidget:
        page, lay = self._page()
        from PySide6.QtWidgets import QTextBrowser

        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        view.setStyleSheet(
            "QTextBrowser{background:#0d111b;border:1px solid #1b2231;border-radius:10px;"
            "padding:12px;color:" + TEXT + ";font-size:13px;}"
            "QScrollBar:vertical{background:transparent;width:8px;margin:0;}"
            "QScrollBar::handle:vertical{background:#2b3550;border-radius:4px;min-height:32px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}"
        )
        view.setHtml(_help_html(self.settings))
        lay.addWidget(view, 1)
        return page

    def _tab_hotkey(self) -> QWidget:
        page, lay = self._page()

        self.voice_hk = HotkeyEdit(self.settings.hotkey)
        self.mode_hk = HotkeyEdit(self.settings.mode_hotkey)
        lay.addLayout(self._field("说话键", self.voice_hk))
        lay.addLayout(self._field("切换游戏 / 办公模式", self.mode_hk))
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
            "input_device": self.mic_combo.currentData() or "",
            "output_device": self.spk_combo.currentData() or "",
            "tts_rate": f"{self.rate_slider.value():+d}%",
            "asr_model": self.asr_combo.currentData(),
            "max_image_width": self.width_spin.value(),
            "ocr_enabled": self.ocr_chk.isChecked(),
            "capture_enabled": self.capture_chk.isChecked(),
            "mode": self.mode_combo.currentData(),
            "workspace_dir": self.workspace_edit.text().strip(),
            "office_permission": self.perm_combo.currentData(),
            "office_timeout": self.timeout_spin.value(),
            "confirm_mode": self.confirm_combo.currentData(),
            "confirm_timeout": self.confirm_timeout_spin.value(),
            "orb_size": self.orb_combo.currentData(),
            "hotkey": self.voice_hk.text().strip(),
            "mode_hotkey": self.mode_hk.text().strip(),
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
        if data["mode_hotkey"]:
            if parse_combo(data["mode_hotkey"]) is None:
                return f"模式切换键不合法：{data['mode_hotkey']}"
            if data["mode_hotkey"].upper() == data["hotkey"].upper():
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

    def _test_speaker(self) -> None:
        err = play_tone(self.spk_combo.currentData() or "")
        if err:
            self.status.setStyleSheet("color:#f87171; font-size:12px;")
            self.status.setText(f"播放失败：{err[:80]}")
        else:
            self.status.setStyleSheet(f"color:{MUTED}; font-size:12px;")
            self.status.setText("听到「嘀」一声就说明这个扬声器通了")

    def _test_mic(self) -> None:
        if self._mic_timer.isActive():
            self._stop_mic_test()
            return
        if self._probe is None:
            self._probe = MicProbe()
        err = self._probe.start(self.mic_combo.currentData() or "")
        if err:
            self.status.setStyleSheet("color:#f87171; font-size:12px;")
            self.status.setText(f"麦克风打不开：{err[:80]}")
            return
        self._mic_elapsed = 0
        self._mic_peak = 0.0
        self._mic_max = 0.0
        self.mic_bar.setValue(0)
        self.mic_bar.show()
        self.status.setStyleSheet(f"color:{MUTED}; font-size:12px;")
        self.status.setText("说句话看看条子动不动（4 秒）")
        self._mic_timer.start()

    def _mic_tick(self) -> None:
        if self._probe is None:
            return
        self._mic_peak = max(self._probe.level, self._mic_peak * 0.82)
        self._mic_max = max(self._mic_max, self._probe.level)  # 峰值别跟着条子掉
        self.mic_bar.setValue(min(100, int(self._mic_peak * 100)))
        self._mic_elapsed += self._mic_timer.interval()
        if self._mic_elapsed >= 4000:
            self._stop_mic_test()

    def _stop_mic_test(self) -> None:
        self._mic_timer.stop()
        if self._probe is not None:
            self._probe.stop()
        self.mic_bar.hide()
        if self._mic_max > 0.02:
            self.status.setStyleSheet("color:#34d399; font-size:12px;")
            self.status.setText("收得到声音")
        else:
            self.status.setStyleSheet("color:#f0b45a; font-size:12px;")
            self.status.setText("没收到声音，检查一下选中的设备")

    def done(self, result: int) -> None:
        self._mic_timer.stop()
        if self._probe is not None:
            self._probe.stop()
        super().done(result)

    def _preview_voice(self) -> None:
        if self._preview is not None and self._preview.isRunning():
            return
        voice = self.voice_combo.currentData()
        rate = f"{self.rate_slider.value():+d}%"
        self.preview_btn.setEnabled(False)
        self.preview_btn.setText("…")
        self._preview = _PreviewWorker(PREVIEW_TEXT, voice, rate, self.spk_combo.currentData() or "")
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

def _help_html(settings) -> str:
    """把藏在代码里的规则摊开给用户看。值都从 vocab 里来，改一处两边同步。"""
    h = '<div style="font-size:13px;line-height:1.6;">'
    h += '<h3 style="color:#e8eeff;">快捷键</h3>'
    h += '<table cellpadding="3">'
    h += f'<tr><td style="color:#8fa1c4;">说话</td><td>&nbsp;&nbsp;{_esc(settings.hotkey)}</td></tr>'
    h += f'<tr><td style="color:#8fa1c4;">切换游戏 / 办公</td><td>&nbsp;&nbsp;{_esc(settings.mode_hotkey)}</td></tr>'
    h += '<tr><td style="color:#8fa1c4;">打开对话</td><td>&nbsp;&nbsp;点一下小球</td></tr>'
    h += '<tr><td style="color:#8fa1c4;">菜单</td><td>&nbsp;&nbsp;右键小球或托盘图标</td></tr>'
    h += '</table>'

    h += '<h3 style="color:#e8eeff;">两种模式</h3>'
    h += '<p><b>游戏模式</b>：看画面答题，5 秒内出声，不碰文件。<br><b>办公模式</b>：能跑命令、改文件，一个任务 5~60 秒。</p>'

    h += '<h3 style="color:#e8eeff;">语音任务确认</h3>'
    h += '<p>只在办公模式生效，只对语音来的任务。当前档位：<b>' + GROUP_LABELS.get(settings.confirm_mode, settings.confirm_mode) + '</b></p>'
    h += '<p>确认时把听到的话念一遍，等你回话：</p><ul>'
    h += '<li>同意：' + '、'.join(CONFIRM_YES) + '</li>'
    h += '<li>拒绝：' + '、'.join(CONFIRM_NO) + '（句子里带「不」也一律算拒绝）</li>'
    h += '<li>重听：' + '、'.join(CONFIRM_RETRY) + '</li></ul>'
    h += f'<p>超过 {CONFIRM_MAX_CHARS} 个字多半是回声，不算应答。{settings.confirm_timeout} 秒没回应自动取消。</p>'

    h += '<h3 style="color:#e8eeff;">高危词</h3>'
    h += '<p>「只有高危任务才确认」这一档下，出现这些词才会弹确认：</p><p style="color:#8fa1c4;">' + '、'.join(DANGER_WORDS) + '</p>'

    h += '<h3 style="color:#e8eeff;">权限级别</h3>'
    h += '<p>当前：<b>' + PERMISSION_LABELS.get(settings.office_permission, settings.office_permission) + '</b></p><ul>'
    h += '<li><b>只读</b>：只能看，改不了任何文件</li>'
    h += '<li><b>工作区可写</b>：写操作限制在工作区，越界直接被拒</li>'
    h += '<li><b>完全权限</b>：能改整台电脑，越界时也不会问你</li></ul>'
    h += '<p style="color:#f0b45a;">越界写入不会弹窗征求同意，是直接失败。</p>'

    h += '<h3 style="color:#e8eeff;">数据存在哪</h3>'
    h += '<ul>'
    h += '<li>设置（含 API Key）：config/settings.json</li>'
    h += '<li>对话记录：data/history.jsonl</li>'
    h += '<li>办公审计：data/office_audit.jsonl</li>'
    h += f'<li>办公工作区：{_esc(str(settings.workspace))}</li></ul>'

    h += '<h3 style="color:#e8eeff;">隐私</h3>'
    h += '<ul>'
    h += '<li>截图只截<b>前台窗口</b>，一次一帧，不录屏；可以在「画面」页关掉</li>'
    h += '<li>API Key 只存在本机，不上传</li>'
    h += '<li>办公模式<b>能读</b>电脑上的文件，但写操作被限制在工作区</li></ul>'
    h += '</div>'
    return h
