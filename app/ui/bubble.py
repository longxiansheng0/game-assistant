"""气泡：输入问题 + 流式显示回答。可拖拽边缘改大小。"""

from __future__ import annotations

from html import escape as _esc

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

BG = QColor(17, 22, 33, 246)
BORDER = QColor(110, 140, 220, 55)
TEXT = "#dbe4f7"
MUTED = "#7c8aa8"
ACCENT = "#6c8afd"

LEFT, RIGHT, TOP, BOTTOM = 1, 2, 4, 8


class ChatInput(QTextEdit):
    """聊天/确认通用输入框：随内容长高（1~6 行），回车提交，Shift+回车换行。"""

    submitted = Signal()
    MAX_LINES = 6

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.document().contentsChanged.connect(self.fit_height)
        self._apply_height(1)

    def _line(self) -> int:
        return max(14, self.fontMetrics().lineSpacing())

    def _apply_height(self, lines: int) -> None:
        self.setFixedHeight(self._line() * lines + 16)

    def fit_height(self) -> None:
        doc = self.document()
        doc.setTextWidth(max(80, self.viewport().width()))
        need = int(doc.size().height()) + 14
        lines = max(1, min(self.MAX_LINES, round(need / self._line())))
        self._apply_height(lines)

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, value: str) -> None:
        self.setPlainText(value or "")

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (
            event.modifiers() & Qt.ShiftModifier
        ):
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class Bubble(QWidget):
    submitted = Signal(str)
    closed = Signal()
    resized = Signal(int, int)
    talkRequested = Signal()
    historyRequested = Signal()
    stopRequested = Signal()
    confirmAccepted = Signal(str)
    confirmCancelled = Signal()

    MIN_W, MIN_H = 360, 150
    EDGE = 7
    COMPACT_H = 150
    READING_H = 360
    HEADER_H = 46

    def __init__(self, width: int = -1, height: int = -1) -> None:
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(self.MIN_W, self.MIN_H)
        self.setMouseTracking(True)

        self._manual = width > 0 and height > 0
        self._w = width if width > 0 else 440
        self._h = height if height > 0 else self.COMPACT_H
        self._resize_edge = 0
        self._drag_origin: QPoint | None = None
        self._geo_origin: QRect | None = None
        self._moving = False

        self.game_label = QLabel("未知画面")
        self.game_label.setStyleSheet(f"color:{MUTED}; font-size:11px;")
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color:{ACCENT}; font-size:11px;")

        close_btn = QPushButton("×")
        close_btn.setFixedSize(20, 20)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton{border:none;color:#7c8aa8;font-size:15px;background:transparent;}"
            "QPushButton:hover{color:#e8eeff;}"
        )
        close_btn.clicked.connect(self.close_bubble)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setStyleSheet(
            "QTextBrowser{background:transparent;border:none;color:" + TEXT + ";"
            "font-size:13px;selection-background-color:#2f3f6b;}"
            "QScrollBar:vertical{background:transparent;width:7px;}"
            "QScrollBar::handle:vertical{background:#33405e;border-radius:3px;min-height:24px;}"
            "QScrollBar::add-line,QScrollBar::sub-line{height:0;}"
        )
        self.view.hide()

        self.input = ChatInput()
        self.input.setPlaceholderText("问点什么…（回车发送，留空 = 看看我现在该怎么办）")
        self.input.setStyleSheet(
            "QTextEdit{background:#0d111b;border:1px solid #232c42;border-radius:9px;"
            "padding:6px 10px;color:#dbe4f7;font-size:13px;selection-background-color:#2f3f6b;}"
            "QTextEdit:focus{border:1px solid #3d5bb5;}"
            "QScrollBar:vertical{background:transparent;width:6px;}"
            "QScrollBar::handle:vertical{background:#33405e;border-radius:3px;min-height:18px;}"
            "QScrollBar::add-line,QScrollBar::sub-line{height:0;}"
        )
        self.input.submitted.connect(self._submit)
        self.input.document().contentsChanged.connect(self._grow_for_input)

        self.mic_btn = QPushButton("🎤")
        self.mic_btn.setFixedSize(30, 30)
        self.mic_btn.setCursor(Qt.PointingHandCursor)
        self.mic_btn.setToolTip("点一下说话（也可以按热键）")
        self.mic_btn.setStyleSheet(
            "QPushButton{border:none;border-radius:15px;background:#182034;color:#c9d6f5;"
            "font-size:13px;}"
            "QPushButton:hover{background:#223050;}"
        )
        self.mic_btn.clicked.connect(self.talkRequested.emit)

        self.history_btn = QPushButton("🕘")
        self.history_btn.setFixedSize(30, 30)
        self.history_btn.setCursor(Qt.PointingHandCursor)
        self.history_btn.setToolTip("对话记录")
        self.history_btn.setStyleSheet(
            "QPushButton{border:none;border-radius:15px;background:#182034;color:#c9d6f5;"
            "font-size:12px;}"
            "QPushButton:hover{background:#223050;}"
        )
        self.history_btn.clicked.connect(self.historyRequested.emit)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(6)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setFixedHeight(30)
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.setStyleSheet(
            "QPushButton{border:none;border-radius:8px;background:#5a2330;color:#ffd7dd;"
            "font-size:12px;padding:0 14px;}"
            "QPushButton:hover{background:#7a2c3c;}"
        )
        self.stop_btn.clicked.connect(self.stopRequested.emit)
        self.stop_btn.hide()

        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.stop_btn)
        input_row.addWidget(self.history_btn)
        input_row.addWidget(self.mic_btn)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        head.addWidget(self.game_label)
        head.addStretch(1)
        head.addWidget(self.status_label)
        head.addWidget(close_btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 14)
        root.setSpacing(8)
        self.confirm_input = ChatInput()
        self.confirm_input.setStyleSheet(
            "QTextEdit{background:#0f1420;border:1px solid #2a3348;border-radius:8px;"
            "padding:6px 10px;color:#e8eeff;font-size:13px;}"
            "QTextEdit:focus{border-color:#3d5bb5;}"
        )
        self.confirm_input.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.confirm_input.hide()
        self.confirm_input.submitted.connect(
            lambda: self.confirmAccepted.emit(self.confirm_input.toPlainText().strip())
        )

        self.confirm_bar = QWidget()
        confirm_row = QHBoxLayout(self.confirm_bar)
        confirm_row.setContentsMargins(0, 0, 0, 8)
        confirm_row.setSpacing(8)
        confirm_row.addStretch(1)
        self.confirm_ok = QPushButton("执行")
        self.confirm_cancel = QPushButton("取消")
        for btn in (self.confirm_ok, self.confirm_cancel):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(30)
            btn.setMinimumWidth(64)
        self.confirm_ok.setStyleSheet(
            "QPushButton{border:none;border-radius:8px;background:#2c5bd8;color:#eef3ff;"
            "font-size:12px;}QPushButton:hover{background:#3a6bee;}"
        )
        self.confirm_cancel.setStyleSheet(
            "QPushButton{border:none;border-radius:8px;background:#1d2740;color:#c9d6f5;"
            "font-size:12px;}QPushButton:hover{background:#27324f;}"
        )
        self.confirm_ok.clicked.connect(
            lambda: self.confirmAccepted.emit(self.confirm_input.toPlainText().strip())
        )
        self.confirm_cancel.clicked.connect(self.confirmCancelled.emit)
        confirm_row.addWidget(self.confirm_ok)
        confirm_row.addWidget(self.confirm_cancel)
        self.confirm_bar.hide()

        root.addLayout(head)
        root.addWidget(self.view, 1)
        root.addWidget(self.confirm_bar)
        root.addWidget(self.confirm_input)
        root.addLayout(input_row)

        self._buffer = ""
        self._task_html: str | None = None
        self._dirty = False
        self._flush = QTimer(self)
        self._flush.setInterval(70)
        self._flush.timeout.connect(self._render)

        self.resize(self._w, self._h)

    # ---------- 外观 ----------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(BORDER, 1))
        p.setBrush(BG)
        p.drawRoundedRect(rect, 14, 14)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(108, 138, 253, 22))
        p.drawRoundedRect(QRectF(rect.left() + 1, rect.top() + 1, rect.width() - 2, 26), 13, 13)

        self._draw_grip(p)
        p.end()

    def _draw_grip(self, p: QPainter) -> None:
        """右下角三道斜线，告诉别人这里能拖。"""
        if self._resize_edge:
            return
        c = QColor(150, 172, 220, 85)
        p.setPen(QPen(c, 1.5))
        x = self.width() - 4
        y = self.height() - 4
        for i in range(3):
            off = i * 3 + 1
            p.drawLine(x - off, y, x, y - off)

    # ---------- 对外 ----------

    def begin(self, game_name: str, hint: str = "", focus: bool = True) -> None:
        self._buffer = ""
        self._task_html = None
        self.view.clear()
        self.view.hide()
        self.input.clear()
        self.game_label.setText(f"●  {game_name or '未知画面'}")
        self.status_label.setText(hint)
        screen = QGuiApplication.primaryScreen().availableGeometry()
        if self._manual:
            w = min(self._w, screen.width() - 40)
            h = min(self._h, screen.height() - 40)
            self.resize(max(w, self.MIN_W), max(h, self.MIN_H))
        else:
            self.resize(self._w, self.COMPACT_H)
        # 语音模式下别抢游戏的焦点，不然人物会站住不动
        self.setAttribute(Qt.WA_ShowWithoutActivating, not focus)
        self.show()
        if focus:
            self.raise_()
            self.activateWindow()
            self.input.setFocus()

    def set_question(self, text: str) -> None:
        """把识别到的话作为引用放到最上面，下面接回答。"""
        self._buffer = f"> **你说**：{text}\n\n"
        self._task_html = None
        self.view.show()
        self._dirty = True
        self._render()
        self._grow_for_reading()

    def begin_confirm(self, text: str, level: str = "") -> None:
        """执行前的确认卡：把听到的话摆出来，等你点头。"""
        badge = (
            '<span style="color:#f87171;">⚠ 完全权限</span>' if level == "full" else ""
        )
        self._buffer = ""
        self._task_html = (
            '<div style="color:#8fa1c4;font-size:12px;">请确认任务 '
            f"{badge}</div>"
            '<div style="margin-top:12px;color:#7d8db0;font-size:13px;">'
            "看下面的字对不对——可以直接改；说「执行」开始</div>"
        )
        self._dirty = True
        self.view.show()
        self._render()
        self.input.hide()
        self.confirm_input.setPlainText(text)
        self.confirm_input.show()
        self.confirm_input.fit_height()
        self.confirm_input.setFocus()
        self.confirm_bar.show()
        self.mic_btn.hide()
        self.history_btn.hide()
        self.stop_btn.hide()
        self._grow_for_reading()
        # 确认卡得有地方放：标题 + 提示 + 按钮 + 输入框
        need = 190 + self.confirm_input.height()
        self.resize(self.width(), max(240, min(need, 380)))

    def end_confirm(self) -> None:
        self._task_html = None
        self.confirm_bar.hide()
        self.confirm_input.hide()
        self.confirm_input.clear()
        self.input.show()
        self.mic_btn.show()
        self.history_btn.show()
        self.input.setEnabled(True)
        self.input.clear()

    def begin_task(self, title: str = "办公任务") -> None:
        """切到任务卡形态：隐藏麦克风/历史，露出停止。"""
        self._buffer = ""
        self._task_html = None
        self.view.clear()
        self.view.show()
        self.input.setEnabled(False)
        self.input.setPlaceholderText("任务进行中，点「停止」可以中断")
        self.stop_btn.show()
        self.mic_btn.hide()
        self.history_btn.hide()
        self.status_label.setText("")
        self._grow_for_reading()

    def end_task(self) -> None:
        self.stop_btn.hide()
        self.mic_btn.show()
        self.history_btn.show()
        self.input.setEnabled(True)
        self.input.setPlaceholderText("继续说…")

    def render_task(self, steps: list, elapsed: str, running: bool, footer=None) -> None:
        colors = {"✓": "#34d399", "✗": "#f87171", "◐": "#f5b452", "○": "#5b6b8c"}
        rows = []
        for icon, text in steps:
            color = colors.get(icon, "#8ea2c8")
            dim = "#7d8db0" if icon == "○" else "#dfe7ff"
            rows.append(
                f'<tr><td style="color:{color};padding-right:8px;">{icon}</td>'
                f'<td style="color:{dim};">{_esc(text)}</td></tr>'
            )
        if not rows:
            rows.append('<tr><td style="color:#5b6b8c;padding-right:8px;">○</td>'
                        '<td style="color:#7d8db0;">准备中…</td></tr>')
        state = "运行中" if running else "已结束"
        head = (
            '<div style="color:#8fa1c4;font-size:12px;margin-bottom:6px;">'
            f'办公任务 · {state} <span style="color:#f5b452;">{elapsed}</span></div>'
        )
        table = f'<table cellspacing="0" cellpadding="3">{"".join(rows)}</table>'
        foot = ""
        if footer:
            label, body = footer
            foot = (
                '<div style="margin-top:14px;">'
                f'<span style="color:#8fa1c4;font-size:12px;">{_esc(label)}</span><br>'
                f'<span style="color:#e6ecfb;">{_esc(body)}</span></div>'
            )
        self._buffer = ""
        self._task_html = head + table + foot
        self._dirty = True
        self.view.show()
        self._render()
        self._grow_for_reading()

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def append(self, chunk: str) -> None:
        if not chunk:
            return
        if self._buffer == "":
            self.view.show()
            self._grow_for_reading()
        self._buffer += chunk
        self._task_html = None
        self._dirty = True
        if not self._flush.isActive():
            self._flush.start()

    def finish(self, note: str = "") -> None:
        self._flush.stop()
        self._render()
        self.status_label.setText(note)

    def show_error(self, message: str) -> None:
        self.view.show()
        self._buffer = ""
        self._task_html = None
        self.view.setPlainText(message)
        self.status_label.setText("出错")
        self._grow_for_reading()

    def close_bubble(self) -> None:
        self._flush.stop()
        self.hide()
        self.closed.emit()

    # ---------- 内部 ----------

    def _grow_for_input(self) -> None:
        """输入框长高了，窗口跟着长，别把字挤没了。"""
        need = self.input.height() + 86
        if self.height() < need:
            self.resize(self.width(), need)

    def _grow_for_reading(self) -> None:
        if self._manual or self.height() >= self.READING_H:
            return
        self.resize(self.width(), self.READING_H)

    def _submit(self) -> None:
        text = self.input.text().strip()
        self.input.clear()
        self.input.setPlaceholderText("继续说…")
        self.submitted.emit(text)

    def _render(self) -> None:
        if not self._dirty:
            return
        self._dirty = False
        if self._task_html is not None:
            self.view.setHtml(self._task_html)
        else:
            self.view.setMarkdown(self._buffer)
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close_bubble()
        else:
            super().keyPressEvent(event)

    def place_near(self, anchor: QPoint, screen_rect) -> None:
        x = anchor.x() - self.width() + 28
        y = anchor.y() - self.height() - 12
        if y < screen_rect.top() + 8:
            y = min(anchor.y() + 56, screen_rect.bottom() - self.height() - 8)
        x = max(screen_rect.left() + 8, min(x, screen_rect.right() - self.width() - 8))
        y = max(screen_rect.top() + 8, min(y, screen_rect.bottom() - self.height() - 8))
        self.move(x, y)

    # ---------- 拖拽：移动 + 缩放 ----------

    def _edge_at(self, pos: QPoint) -> int:
        edge = 0
        if pos.x() <= self.EDGE:
            edge |= LEFT
        if pos.x() >= self.width() - self.EDGE:
            edge |= RIGHT
        if pos.y() <= self.EDGE:
            edge |= TOP
        if pos.y() >= self.height() - self.EDGE:
            edge |= BOTTOM
        return edge

    def _cursor_for(self, edge: int) -> Qt.CursorShape:
        if edge in (LEFT | TOP, RIGHT | BOTTOM):
            return Qt.SizeFDiagCursor
        if edge in (RIGHT | TOP, LEFT | BOTTOM):
            return Qt.SizeBDiagCursor
        if edge in (LEFT, RIGHT):
            return Qt.SizeHorCursor
        if edge in (TOP, BOTTOM):
            return Qt.SizeVerCursor
        return Qt.ArrowCursor

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        edge = self._edge_at(event.position().toPoint())
        self._drag_origin = event.globalPosition().toPoint()
        self._geo_origin = self.geometry()
        if edge:
            self._resize_edge = edge
        elif event.position().y() < self.HEADER_H:
            self._moving = True
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_origin is None:
            edge = self._edge_at(event.position().toPoint())
            self.setCursor(self._cursor_for(edge))
            return

        delta = event.globalPosition().toPoint() - self._drag_origin
        geo = self._geo_origin
        if geo is None:
            return

        if self._resize_edge:
            x, y, w, h = geo.x(), geo.y(), geo.width(), geo.height()
            if self._resize_edge & RIGHT:
                w = max(self.MIN_W, geo.width() + delta.x())
            if self._resize_edge & LEFT:
                w = max(self.MIN_W, geo.width() - delta.x())
                x = geo.right() - w + 1
            if self._resize_edge & BOTTOM:
                h = max(self.MIN_H, geo.height() + delta.y())
            if self._resize_edge & TOP:
                h = max(self.MIN_H, geo.height() - delta.y())
                y = geo.bottom() - h + 1
            self.setGeometry(x, y, w, h)
        elif self._moving:
            self.move(geo.topLeft() + delta)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        was_resize = bool(self._resize_edge)
        self._resize_edge = 0
        self._moving = False
        self._drag_origin = None
        self._geo_origin = None
        self.setCursor(Qt.ArrowCursor)
        if was_resize:
            self._manual = True
            self._w, self._h = self.width(), self.height()
            self.resized.emit(self._w, self._h)
        self.update()
