"""记录浏览：对话记录 + 办公任务审计。"""

from __future__ import annotations

from html import escape

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .settings_dialog import BG, BORDER, MUTED, STYLE, TEXT

LIST_STYLE = (
    "QListWidget{background:#0d111b;border:1px solid #1b2231;border-radius:10px;"
    "padding:4px;color:#cbd7f2;outline:none;}"
    "QListWidget::item{padding:7px 8px;border-radius:6px;}"
    "QListWidget::item:selected{background:#26304a;color:#ffffff;}"
    "QListWidget::item:hover{background:#1a2233;}"
)
VIEW_STYLE = (
    "QTextBrowser{background:#0d111b;border:1px solid #1b2231;border-radius:10px;"
    "padding:10px;color:" + TEXT + ";font-size:13px;}"
)


class HistoryDialog(QDialog):
    def __init__(self, history, audit=None, on_clear=None) -> None:
        super().__init__()
        self.history = history
        self.audit = audit
        self.on_clear = on_clear
        self._drag: QPoint | None = None
        self._entries = []
        self._audits = []

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(STYLE)
        self.setMinimumSize(560, 480)
        self.resize(620, 560)
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

    def _page(self) -> tuple[QWidget, QListWidget, QTextBrowser]:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(8)
        listing = QListWidget()
        listing.setStyleSheet(LIST_STYLE)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        view.setStyleSheet(VIEW_STYLE)
        lay.addWidget(listing, 2)
        lay.addWidget(view, 3)
        return page, listing, view

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 18)
        root.setSpacing(10)

        title = QLabel("记录")
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

        chat_page, self.list, self.view = self._page()
        self.list.currentRowChanged.connect(self._show_entry)
        self.view.setPlainText("选一条看详情")

        audit_page, self.audit_list, self.audit_view = self._page()
        self.audit_list.currentRowChanged.connect(self._show_audit)
        self.audit_view.setPlainText("选一条看它当时跑了什么")

        self.tabs = QTabWidget()
        self.tabs.addTab(chat_page, "对话")
        self.tabs.addTab(audit_page, "办公任务")
        self.tabs.currentChanged.connect(lambda _i: self._refresh_count())

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
        root.addWidget(self.tabs, 1)
        root.addLayout(foot)

    # ---------- 数据 ----------

    def _load(self) -> None:
        self._load_chat()
        self._load_audit()
        self._refresh_count()

    def _refresh_count(self) -> None:
        if self.tabs.currentIndex() == 1:
            n = len(self._audits)
            self.count.setText(f"{n} 个办公任务" if n else "还没有办公任务")
        else:
            n = len(self._entries)
            self.count.setText(f"{n} 条" if n else "还没有记录")

    def _load_chat(self) -> None:
        self.list.clear()
        self._entries = self.history.recent(200)
        for entry in self._entries:
            question = entry.question.replace("\n", " ")[:26]
            label = f"{entry.clock}    {entry.game or '—'}    {question or '(空)'}"
            self.list.addItem(QListWidgetItem(label))
        if self._entries:
            self.list.setCurrentRow(0)
        else:
            self.view.setPlainText("还没有对话记录。\n\n问一次问题，这里就会多一条。")

    def _load_audit(self) -> None:
        self.audit_list.clear()
        self._audits = self.audit.recent(200) if self.audit is not None else []
        for entry in self._audits:
            src = "语音" if entry.source == "voice" else "打字"
            question = entry.question.replace("\n", " ")[:24]
            mark = "·" if entry.result and not entry.error else "⚠"
            self.audit_list.addItem(QListWidgetItem(f"{mark} {entry.clock}  {src}  {question}"))
        if self._audits:
            self.audit_list.setCurrentRow(0)
        else:
            self.audit_view.setPlainText(
                "还没有办公任务记录。\n\n在办公模式下跑一次任务，这里会记下它跑了哪些命令。"
            )

    def _show_entry(self, row: int) -> None:
        if row < 0 or row >= len(self._entries):
            return
        entry = self._entries[row]
        body = f"**问**：{entry.question or '(空)'}\n\n**答**：\n\n{entry.answer}"
        if entry.game:
            body = f"*{entry.game} · {entry.clock}*\n\n" + body
        self.view.setMarkdown(body)

    def _show_audit(self, row: int) -> None:
        if row < 0 or row >= len(self._audits):
            return
        self.audit_view.setHtml(_audit_html(self._audits[row]))

    def _clear(self) -> None:
        if self.tabs.currentIndex() == 1:
            if self.audit is not None:
                self.audit.clear()
            self._load_audit()
        else:
            self.history.clear()
            if self.on_clear is not None:
                self.on_clear()
            self._load_chat()
        self._refresh_count()


def _audit_html(entry) -> str:
    src = "语音" if entry.source == "voice" else "打字"
    confirm = {
        "accepted": "已确认",
        "not-needed": "无需确认",
        "cancelled": "被取消",
    }.get(entry.confirm, entry.confirm or "—")
    rows = []
    for step in entry.steps[:40]:
        ok = step.get("ok")
        color = "#34d399" if ok else ("#f87171" if ok is False else "#7d8db0")
        mark = "✓" if ok else ("✗" if ok is False else "·")
        rows.append(
            f'<tr><td style="color:{color};padding-right:8px;">{mark}</td>'
            f'<td style="color:#cbd7f2;">{escape(str(step.get("text", "")))}</td></tr>'
        )
    steps_html = (
        f'<table cellspacing="0" cellpadding="3">{"".join(rows)}</table>'
        if rows
        else '<div style="color:#7d8db0;">（没有执行任何命令）</div>'
    )
    result = escape(entry.result or entry.error or "（无结果）")
    return (
        f'<div style="color:{MUTED};font-size:12px;">'
        f"{entry.clock} · {src} · {escape(entry.permission or '—')} · "
        f"{confirm} · {entry.seconds}</div>"
        f'<div style="color:#eef3ff;font-size:15px;margin-top:10px;">'
        f"{escape(entry.question or '(空)')}</div>"
        f'<div style="color:#7d8db0;font-size:11px;margin-top:6px;">'
        f"工作区：{escape(entry.workspace or '—')}</div>"
        f'<hr style="border:none;border-top:1px solid #1b2231;margin:12px 0;">'
        f"{steps_html}"
        f'<div style="margin-top:12px;"><span style="color:{MUTED};font-size:12px;">'
        f'结果</span><br><span style="color:#cbd7f2;">{result}</span></div>'
    )
