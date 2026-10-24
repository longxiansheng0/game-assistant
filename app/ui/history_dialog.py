"""对话记录浏览。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from .settings_dialog import BG, BORDER, MUTED, STYLE, TEXT


class HistoryDialog(QDialog):
    def __init__(self, history) -> None:
        super().__init__()
        self.history = history
        self._drag: QPoint | None = None
        self._entries = []

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(STYLE)
        self.setMinimumSize(520, 460)
        self.resize(560, 520)
        self._build()
        self._load()

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

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 18)
        root.setSpacing(12)

        title = QLabel("对话记录")
        title.setStyleSheet("font-size:18px; font-weight:600;")
        self.count = QLabel("")
        self.count.setStyleSheet(f"color:{MUTED}; font-size:12px;")
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
        head.setSpacing(10)
        head.addWidget(title)
        head.addWidget(self.count)
        head.addStretch(1)
        head.addWidget(close_btn, 0, Qt.AlignTop)

        self.list = QListWidget()
        self.list.setStyleSheet(
            "QListWidget{background:#0d111b;border:1px solid #1b2231;border-radius:10px;"
            "padding:4px;color:#cbd7f2;outline:none;}"
            "QListWidget::item{padding:7px 8px;border-radius:6px;}"
            "QListWidget::item:selected{background:#26304a;color:#ffffff;}"
            "QListWidget::item:hover{background:#1a2233;}"
        )
        self.list.currentRowChanged.connect(self._show_entry)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setStyleSheet(
            "QTextBrowser{background:#0d111b;border:1px solid #1b2231;border-radius:10px;"
            "padding:10px;color:" + TEXT + ";font-size:13px;}"
        )
        self.view.setPlainText("选一条看详情")

        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear)
        done_btn = QPushButton("关闭")
        done_btn.setObjectName("primary")
        done_btn.clicked.connect(self.accept)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        foot.addWidget(clear_btn)
        foot.addStretch(1)
        foot.addWidget(done_btn)

        root.addLayout(head)
        root.addWidget(self.list, 2)
        root.addWidget(self.view, 3)
        root.addLayout(foot)

    def _load(self) -> None:
        self.list.clear()
        self._entries = self.history.recent(200)
        for entry in self._entries:
            question = entry.question.replace("\n", " ")[:26]
            label = f"{entry.clock}    {entry.game or '—'}    {question or '(空)'}"
            self.list.addItem(QListWidgetItem(label))
        self.count.setText(f"{len(self._entries)} 条" if self._entries else "还没有记录")
        if self._entries:
            self.list.setCurrentRow(0)
        else:
            self.view.setPlainText("还没有对话记录。\n\n问一次问题，这里就会多一条。")

    def _show_entry(self, row: int) -> None:
        if row < 0 or row >= len(self._entries):
            return
        entry = self._entries[row]
        body = f"**问**：{entry.question or '(空)'}\n\n**答**：\n\n{entry.answer}"
        if entry.game:
            body = f"*{entry.game} · {entry.clock}*\n\n" + body
        self.view.setMarkdown(body)

    def _clear(self) -> None:
        self.history.clear()
        self._load()
