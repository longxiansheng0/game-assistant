"""悬浮球：透明、置顶、可拖动，用颜色和动画表达状态。"""

from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QMenu, QWidget

ACCENTS = {
    "idle": QColor(108, 138, 253),
    "listening": QColor(52, 211, 153),
    "thinking": QColor(251, 191, 36),
    "speaking": QColor(167, 139, 250),
    "loading": QColor(96, 165, 250),
    "error": QColor(248, 113, 113),
}

STATE_HINTS = {
    "idle": "点我提问 · 右键菜单",
    "listening": "在听…",
    "thinking": "思考中…",
    "speaking": "说话中…",
    "loading": "加载语音模型…",
    "error": "出错了",
}


class Orb(QWidget):
    activated = Signal()
    resetRequested = Signal()
    quitRequested = Signal()
    voiceRequested = Signal()
    toggleChanged = Signal(str, bool)
    settingsRequested = Signal()
    historyRequested = Signal()

    def __init__(self, size: int = 64) -> None:
        super().__init__()
        self.state = "idle"
        self.mode = "game"
        self._voice_mode = "push"
        self._hotkey_label = "F8"
        self._wake_word = "小助手"
        self._mode_hotkey = "Ctrl+F9"
        self._level = 0.0
        self._hover = 0.0
        self._press = 0.0
        self._gaze_x = 0.0
        self._gaze_y = 0.0
        self._glance_vec = (0.0, 0.0)
        self._glance_until = 0.0
        self._next_glance = 3.0
        self._debug_gaze: tuple[float, float] | None = None
        self._last_tick = time.time()
        self._toggles = {"office": False, "voice": True, "tts": True, "call": False, "autostart": False}
        self._drag_from: QPointF | None = None
        self._moved = False
        self._born = time.time()

        # 用 Qt.Tool：不占任务栏按钮，控制入口放在系统托盘里
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("语音助手")  # 任务栏上显示的名字
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(STATE_HINTS["idle"])

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(33)

    # ---------- 状态 ----------

    def set_voice_info(self, mode: str, hotkey: str, wake_word: str) -> None:
        self._voice_mode = "call" if mode == "call" else "push"
        self._hotkey_label = hotkey or "F8"
        self._wake_word = wake_word or "小助手"

    def set_mode_hotkey(self, label: str) -> None:
        self._mode_hotkey = (label or "").strip()

    def set_mode(self, mode: str) -> None:
        self.mode = "office" if mode == "office" else "game"
        self.setToolTip(
            f"游戏模式 · {STATE_HINTS[self.state]}"
            if self.mode == "game"
            else f"办公模式 · {STATE_HINTS[self.state]}"
        )
        self.update()

    def set_level(self, value: float) -> None:
        """麦克风音量，让球跟着你说话起伏。"""
        self._level = max(0.0, min(1.0, float(value)))

    def set_toggles(self, toggles: dict[str, bool]) -> None:
        self._toggles.update(toggles)

    def set_state(self, state: str) -> None:
        if state not in ACCENTS:
            state = "idle"
        self.state = state
        self.setToolTip(STATE_HINTS[state])
        self.update()

    # ---------- 绘制 ----------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        now = time.time()
        t = now - self._born
        dt = min(0.1, max(0.0, now - self._last_tick))
        self._last_tick = now
        self._hover += ((1.0 if self.underMouse() else 0.0) - self._hover) * min(1.0, dt * 12)
        self._press = max(0.0, self._press - dt * 4.5)

        w = min(self.width(), self.height())
        cx = self.width() / 2
        cy = self.height() / 2
        r = (w * 0.5 - 11) * (1.0 + 0.05 * self._hover - 0.07 * self._press)
        accent = ACCENTS[self.state]

        pulse = 0.5 + 0.5 * math.sin(t * 2.2)
        if self.state == "thinking":
            pulse = 0.35 + 0.45 * (0.5 + 0.5 * math.sin(t * 7))
        elif self.state == "loading":
            pulse = 0.3 + 0.35 * (0.5 + 0.5 * math.sin(t * 1.6))
        elif self.state == "listening":
            pulse = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(t * 4.5))
            pulse = min(1.0, pulse + self._level * 0.45)

        # 外发光
        for i, alpha in enumerate((46, 26, 12)):
            radius = r * (1.25 + i * 0.3)
            grad = QRadialGradient(cx, cy, radius)
            edge = QColor(accent)
            edge.setAlpha(0)
            core = QColor(accent)
            core.setAlpha(int(alpha * (0.55 + 0.45 * pulse)))
            grad.setColorAt(0.45, core)
            grad.setColorAt(1.0, edge)
            p.setPen(Qt.NoPen)
            p.setBrush(grad)
            p.drawEllipse(QPointF(cx, cy), radius, radius)

        # 球体
        body = QRadialGradient(cx, cy - r * 0.4, r * 1.6)
        if self.mode == "office":
            body.setColorAt(0.0, QColor(33, 45, 64, 240))
            body.setColorAt(0.62, QColor(16, 25, 40, 245))
            body.setColorAt(1.0, QColor(8, 13, 23, 250))
        else:
            body.setColorAt(0.0, QColor(40, 47, 68, 240))
            body.setColorAt(0.62, QColor(21, 25, 38, 245))
            body.setColorAt(1.0, QColor(11, 14, 22, 250))
        p.setBrush(body)
        p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 70 + int(60 * pulse)), 1.1))
        p.drawEllipse(QPointF(cx, cy), r, r)

        # 内圈高光
        p.setPen(QPen(QColor(255, 255, 255, 26), 1.0))
        p.drawEllipse(QPointF(cx, cy - 1), r - 3.5, r - 3.5)

        self._draw_face(p, cx, cy, r, t, accent, pulse)
        self._draw_state_ring(p, cx, cy, r, t, accent, pulse)
        p.end()

    def _gaze(self, t: float) -> tuple[float, float]:
        """眼睛看哪儿：平时看鼠标，发呆时偶尔瞟一眼旁边。"""
        if self._debug_gaze is not None:
            return self._debug_gaze
        if self.state in ("thinking", "loading"):
            return (-0.45, -0.75)
        if t < self._glance_until:
            return self._glance_vec
        if t > self._next_glance:
            self._glance_vec = (random.uniform(-1, 1), random.uniform(-0.6, 0.5))
            self._glance_until = t + random.uniform(0.7, 1.2)
            self._next_glance = t + random.uniform(4.5, 8.5)
            return self._glance_vec

        try:
            cursor = QCursor.pos()
            center = self.mapToGlobal(self.rect().center())
            dx = cursor.x() - center.x()
            dy = cursor.y() - center.y()
        except Exception:
            return (0.0, 0.0)
        dist = math.hypot(dx, dy)
        if dist < 1:
            return (0.0, 0.0)
        reach = min(1.0, dist / 280.0)
        return (dx / dist * reach, dy / dist * reach)

    def _draw_face(self, p, cx, cy, r, t, accent, pulse) -> None:
        """两只眼睛：跟着鼠标转、会眨眼、凑近会睁大。"""
        gx, gy = self._gaze(t)
        eye_r = r * 0.145 * (1.0 + 0.10 * self._hover)
        gap = r * 0.25
        blink = 1.0
        phase = t % 4.6
        if 4.2 <= phase < 4.32:
            blink = 0.12
        elif 4.32 <= phase < 4.44:
            blink = 0.55

        shift_x = gx * r * 0.13
        shift_y = gy * r * 0.11

        for sign in (-1, 1):
            eye = QColor(226, 236, 255)
            eye.setAlpha(240)
            p.setBrush(eye)
            p.setPen(Qt.NoPen)
            ex = cx + sign * gap + shift_x
            ey = cy + shift_y
            if self.state in ("thinking", "loading"):
                p.drawRoundedRect(
                    QRectF(ex - eye_r, ey - eye_r * 0.42, eye_r * 2, eye_r * 0.84),
                    eye_r * 0.42,
                    eye_r * 0.42,
                )
            else:
                h = max(eye_r * 2 * blink, eye_r * 0.26)
                p.drawEllipse(QPointF(ex, ey), eye_r, h / 2)

    def _draw_state_ring(self, p, cx, cy, r, t, accent, pulse) -> None:
        ring = r + 3.0
        if self.state in ("thinking", "loading"):
            start = (t * (70 if self.state == "loading" else 220)) % 360
            pen = QPen(accent, 2.6)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawArc(QRectF(cx - ring, cy - ring, ring * 2, ring * 2), int(start * 16), 110 * 16)
        elif self.state == "listening":
            for k in range(2):
                frac = ((t * 1.25 + k * 0.5) % 1.0)
                rr = ring + frac * r * (0.20 + 0.32 * self._level)
                c = QColor(accent)
                c.setAlpha(int((55 + 95 * self._level) * (1 - frac)))
                p.setPen(QPen(c, 1.6))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(cx, cy), rr, rr)
        elif self.state == "speaking":
            bars = 5
            spread = r * 0.60
            mid = cy + r * 0.50
            step = spread / (bars - 1)
            for i in range(bars):
                amp = 0.22 + 0.78 * abs(math.sin(t * 6.0 + i * 0.9))
                hgt = r * 0.26 * amp
                x = cx - spread / 2 + i * step
                p.setPen(Qt.NoPen)
                c = QColor(accent)
                c.setAlpha(205)
                p.setBrush(c)
                p.drawRoundedRect(
                    QRectF(x - 1.2, mid - hgt / 2, 2.4, hgt), 1.2, 1.2
                )
        else:
            c = QColor(accent)
            c.setAlpha(50 + int(40 * pulse))
            p.setPen(QPen(c, 1.4))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), ring, ring)

        if self.mode == "office":
            self._draw_mode_dot(p, cx, cy, ring, accent, pulse)

    def _draw_mode_dot(self, p, cx, cy, ring, accent, pulse) -> None:
        """办公模式：外面再套一层细环 + 右上角小方章。"""
        c = QColor(accent)
        c.setAlpha(40 + int(30 * pulse))
        p.setPen(QPen(c, 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), ring + 4.0, ring + 4.0)

        x = cx + ring * 0.70
        y = cy - ring * 0.70
        s = 2.7
        dot = QColor(accent)
        dot.setAlpha(210 + int(40 * pulse))
        p.setPen(QPen(QColor(10, 14, 22, 200), 1.0))
        p.setBrush(dot)
        p.drawRoundedRect(QRectF(x - s, y - s, s * 2, s * 2), 1.1, 1.1)

    # ---------- 交互 ----------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press = 1.0
            self._drag_from = event.globalPosition()
            self._moved = False
            event.accept()

    def changeEvent(self, event) -> None:
        # 点任务栏把它最小化的话，宠物就没了；直接弹回来
        if event.type() == QEvent.WindowStateChange and self.isMinimized():
            QTimer.singleShot(0, self.showNormal)
        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        # 别让"关闭窗口"把宠物弄丢，收进托盘就行
        event.ignore()
        self.hide()

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is None:
            return
        delta = event.globalPosition() - self._drag_from
        if abs(delta.x()) + abs(delta.y()) > 3:
            self._moved = True
        self.move(self.pos() + delta.toPoint())
        self._drag_from = event.globalPosition()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_from = None
            if not self._moved:
                self.activated.emit()
            event.accept()

    def contextMenuEvent(self, event) -> None:
        self._build_menu().exec(QCursor.pos())

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#151a26;color:#dfe7ff;border:1px solid #2a3348;"
            "border-radius:8px;padding:6px;}"
            "QMenu::item{padding:6px 18px;border-radius:5px;}"
            "QMenu::item:selected{background:#26304a;}"
        )
        menu.addAction("对话", self.activated.emit)

        # 模式项：显示当前在哪个模式，括号里是切换键，点一下换过去
        mode_label = "办公模式" if self.mode == "office" else "游戏模式"
        menu.addAction(
            mode_label, lambda: self.toggleChanged.emit("office", self.mode != "office")
        )

        # 语音输入方式：按键 / 通话，标签跟着当前模式变
        label = "通话模式" if self._voice_mode == "call" else "按键说话"
        menu.addAction(
            label, lambda: self.toggleChanged.emit("call", self._voice_mode != "call")
        )

        menu.addSeparator()
        menu.addAction("设置…", self.settingsRequested.emit)
        menu.addSeparator()
        menu.addAction("退出", self.quitRequested.emit)
        return menu
