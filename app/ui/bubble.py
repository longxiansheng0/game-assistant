"""气泡：输入问题 + 流式显示回答。可拖拽边缘改大小。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

BG = QColor(17, 22, 33, 246)
BORDER = QColor(110, 140, 220, 55)
TEXT = "#dbe4f7"
MUTED = "#7c8aa8"
ACCENT = "#6c8afd"

LEFT, RIGHT, TOP, BOTTOM = 1, 2, 4, 8


class Bubble(QWidget):
    submitted = Signal(str)
    closed = Signal()
    resized = Signal(int, int)
    talkRequested = Signal()

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

        self.input = QLineEdit()
        self.input.setPlaceholderText("问点什么…（回车发送，留空 = 看看我现在该怎么办）")
        self.input.setStyleSheet(
            "QLineEdit{background:#0d111b;border:1px solid #232c42;border-radius:9px;"
            "padding:7px 10px;color:#dbe4f7;font-size:13px;selection-background-color:#2f3f6b;}"
            "QLineEdit:focus{border:1px solid #3d5bb5;}"
        )
        self.input.returnPressed.connect(self._submit)

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

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(6)
        input_row.addWidget(self.input, 1)
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
        root.addLayout(head)
        root.addWidget(self.view, 1)
        root.addLayout(input_row)

        self._buffer = ""
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
        self.view.show()
        self._dirty = True
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
        self.view.setPlainText(message)
        self.status_label.setText("出错")
        self._grow_for_reading()

    def close_bubble(self) -> None:
        self._flush.stop()
        self.hide()
        self.closed.emit()

    # ---------- 内部 ----------

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
