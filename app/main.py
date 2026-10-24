"""应用装配：悬浮球 + 语音对话 + 气泡 + 热键 + 后台线程。"""

from __future__ import annotations

import sys
import time
from typing import Callable

from PySide6.QtCore import QObject, QPoint, QThread, QTimer, Signal
from PySide6.QtGui import QFont, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from .config import Settings
from .core.agent import GameAssistant
from .core.history import History
from .llm.deepseek import DeepSeekClient
from .ui.bubble import Bubble
from .ui.hotkey import HotkeyListener
from .ui.orb import Orb
from .util import startup
from .vision.capture import (
    focus_window,
    foreground_hwnd,
    foreground_info,
    grab,
    guess_game_name,
)
from .vision.capture import Capture
from .vision.ocr import OcrEngine
from .voice.asr import WhisperASR
from .voice.recorder import Recorder
from .voice.tts import Speaker
from .voice.wake import WakeListener

NO_KEY_HINT = (
    "还没配置 DeepSeek API Key。\n\n"
    "右键小球 →「设置…」，把 Key 填进去就行。\n"
    "Key 在 platform.deepseek.com 申请，按量付费，问一次几分钱。"
)


class AskWorker(QThread):
    """抓屏 + 问答都在子线程里跑，UI 不能卡。"""

    status = Signal(str)
    delta = Signal(str)
    ok = Signal(str)
    fail = Signal(str)

    def __init__(
        self,
        assistant: GameAssistant,
        question: str,
        max_width: int,
        shot: Capture | None = None,
        ocr_text: str = "",
    ) -> None:
        super().__init__()
        self.assistant = assistant
        self.question = question
        self.max_width = max_width
        self.shot = shot
        self.ocr_text = ocr_text

    def run(self) -> None:
        try:
            shot = self.shot
            if shot is None:
                self.status.emit("看一眼屏幕…")
                shot = grab(max_width=self.max_width)
            answer = self.assistant.ask(
                self.question,
                shot,
                on_status=self.status.emit,
                on_delta=self.delta.emit,
                ocr_text=self.ocr_text,
            )
            self.ok.emit(answer or "")
        except Exception as exc:  # noqa: BLE001 - 任何失败都要回到 UI，不能静默
            self.fail.emit(str(exc) or exc.__class__.__name__)


def make_app_icon() -> QIcon:
    """拿悬浮球自己渲染一个图标，省得打包还得带 ico 文件。"""
    temp = Orb(64)
    temp._timer.stop()
    return QIcon(temp.grab())


class FuncWorker(QThread):
    """随便丢个耗时函数进来跑，结果用信号回主线程。"""

    ok = Signal(object)
    fail = Signal(str)

    def __init__(self, fn: Callable[[], object]) -> None:
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            self.ok.emit(self.fn())
        except Exception as exc:  # noqa: BLE001
            self.fail.emit(str(exc) or exc.__class__.__name__)


class AssistantApp(QObject):
    triggered = Signal()
    textTriggered = Signal()
    hotkeyError = Signal(str)
    speechIdle = Signal()
    wakeHit = Signal(str)

    def __init__(self, qt_app: QApplication, settings: Settings) -> None:
        super().__init__()
        self.qt_app = qt_app
        self.settings = settings
        self.assistant: GameAssistant | None = None
        self.worker: AskWorker | None = None
        self._workers: list[FuncWorker] = []
        self.hotkeys: list[HotkeyListener] = []
        self._prev_hwnd = 0
        self._listening = False
        self._asr_loading = False
        self._listen_wanted = False
        self._voice_mode = False
        self._muted = False
        self._dialog = None
        self._history_dialog = None
        self._wake: WakeListener | None = None
        self._wake_dying: WakeListener | None = None
        self._current_game = ""
        self._pending_question = ""

        self.orb = Orb(size=settings.orb_size)
        self.icon = make_app_icon()
        self.qt_app.setWindowIcon(self.icon)
        self.orb.setWindowIcon(self.icon)
        self.tray: QSystemTrayIcon | None = None
        self._tray_menu = None
        self.bubble = Bubble(settings.bubble_w, settings.bubble_h)
        self.recorder = Recorder()
        self.history = History()
        self.asr = WhisperASR(settings.asr_model)
        self.ocr = OcrEngine(settings.ocr_max_side)
        self._pre_shot: Capture | None = None
        self._pre_ocr = ""
        self._pre_stamp = 0.0
        self._pre_token = 0
        self.speaker = Speaker(settings.tts_voice, settings.tts_rate, on_idle=self.speechIdle.emit)

        self._mic_timer = QTimer(self)
        self._mic_timer.setInterval(60)
        self._mic_timer.timeout.connect(self._poll_mic)

        self._build_backend()
        self._wire()
        self._place_orb()
        self._setup_tray()
        self._start_hotkeys()
        self._sync_toggles()
        self._sync_call_mode()  # 上次开着通话模式的话，启动就继续听
        # 启动 12 秒后偷偷把识别模型读进内存，省得第一次说话还要等
        QTimer.singleShot(12000, self._preload_asr)
        QTimer.singleShot(900, self._maybe_first_run)

    # ---------- 装配 ----------

    def _build_backend(self) -> None:
        if not self.settings.ready:
            return
        try:
            client = DeepSeekClient(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                model=self.settings.model,
            )
        except Exception:
            return
        self.assistant = GameAssistant(
            client, allow_search=self.settings.allow_search, think=self.settings.think
        )

    def _wire(self) -> None:
        self.orb.activated.connect(self.open_bubble)
        self.orb.voiceRequested.connect(self.on_talk)
        self.orb.quitRequested.connect(self.quit)
        self.orb.resetRequested.connect(self._reset_memory)
        self.orb.toggleChanged.connect(self._on_toggle)
        self.orb.settingsRequested.connect(self.open_settings)
        self.orb.historyRequested.connect(self.open_history)
        self.bubble.submitted.connect(self.ask)
        self.bubble.closed.connect(self._restore_focus)
        self.bubble.resized.connect(self._on_bubble_resized)
        self.bubble.talkRequested.connect(self.on_talk)
        self.triggered.connect(self.on_talk)
        self.textTriggered.connect(self.open_bubble)
        self.hotkeyError.connect(self._show_quick_error)
        self.speechIdle.connect(self._on_speech_idle)
        self.wakeHit.connect(self._on_wake)

    def _place_orb(self) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        if self.settings.orb_x >= 0 and self.settings.orb_y >= 0:
            x, y = self.settings.orb_x, self.settings.orb_y
        else:
            x = screen.right() - self.orb.width() - 36
            y = screen.bottom() - self.orb.height() - 90
        x = min(max(x, screen.left()), screen.right() - self.orb.width())
        y = min(max(y, screen.top()), screen.bottom() - self.orb.height())
        self.orb.move(x, y)
        self.orb.show()

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setToolTip("游戏助手 · F2 说话")
        self.tray.activated.connect(self._on_tray_activated)
        self._refresh_tray_menu()
        self.tray.show()

    def _refresh_tray_menu(self) -> None:
        if self.tray is None:
            return
        menu = self.orb._build_menu()
        # QSystemTrayIcon 不是 QWidget，不能当父对象；菜单也不归它管，得自己留引用
        if self._tray_menu is not None:
            self._tray_menu.deleteLater()
        self._tray_menu = menu
        self.tray.setContextMenu(menu)

    def _on_tray_activated(self, reason) -> None:
        if reason != QSystemTrayIcon.DoubleClick:
            return
        if not self.orb.isVisible():
            self.orb.show()
        self.open_bubble()

    def _start_hotkeys(self) -> None:
        combos: list[tuple[str, Callable[[], None]]] = []
        if self.settings.hotkey:
            combos.append((self.settings.hotkey, self.triggered.emit))
        if self.settings.text_hotkey and self.settings.text_hotkey != self.settings.hotkey:
            combos.append((self.settings.text_hotkey, self.textTriggered.emit))
        for combo, callback in combos:
            listener = HotkeyListener(combo, callback, self.hotkeyError.emit)
            listener.start()
            self.hotkeys.append(listener)

    # ---------- 语音 ----------

    def on_talk(self) -> None:
        """热键/麦克风按钮：说一句话。"""
        if self._listening:
            self.recorder.request_stop()
            return
        if self._asr_loading:
            self._listen_wanted = True  # 模型还在加载，加载完自动开始听
            return
        if self.speaker.busy:
            # 打断：这一轮剩下的字不要再念了
            self._muted = True
            self.speaker.stop()
            self.orb.set_state("idle")
        if self.bubble.isVisible():
            # 先收起上一轮的气泡，免得它被拍进截图里，让模型看见自己的答案
            self.bubble.close_bubble()
        if self.worker is not None and self.worker.isRunning():
            return
        if not self.settings.voice_enabled:
            self.open_bubble()
            return
        if not self.asr.ready:
            self._load_asr()
            return
        self._listen()

    def _load_asr(self) -> None:
        self._asr_loading = True
        self._listen_wanted = True
        self.orb.set_state("thinking")
        self._peek("第一次用语音，正在加载识别模型（约 250MB，只需一次）…")
        self._spawn_asr_load()

    def _preload_asr(self) -> None:
        if not self.settings.voice_enabled or not self.settings.asr_preload:
            return
        if self.asr.ready or self._asr_loading:
            return
        self._asr_loading = True
        self._spawn_asr_load()

    def _spawn_asr_load(self) -> None:
        self._spawn(
            self._load_engines,
            lambda _r: self._after_asr_load(True, ""),
            lambda msg: self._after_asr_load(False, msg),
        )

    def _load_engines(self) -> None:
        self.asr.load()
        if self.settings.ocr_enabled:
            try:
                self.ocr.warmup()
            except Exception:
                pass

    def _spawn(self, fn: Callable[[], object], on_ok=None, on_fail=None) -> FuncWorker:
        worker = FuncWorker(fn)
        if on_ok is not None:
            worker.ok.connect(on_ok)
        if on_fail is not None:
            worker.fail.connect(on_fail)
        self._workers.append(worker)
        worker.finished.connect(lambda: self._drop_worker(worker))
        worker.start()
        return worker

    def _drop_worker(self, worker: FuncWorker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        worker.deleteLater()

    def _after_asr_load(self, ok: bool, message: str) -> None:
        self._asr_loading = False
        want = self._listen_wanted
        self._listen_wanted = False
        if not ok:
            if want:
                self.orb.set_state("error")
                self._peek(f"语音模型加载失败：{message}")
                QTimer.singleShot(2600, lambda: self.orb.set_state("idle"))
            return
        if want:
            if self.bubble.isVisible():
                self.bubble.set_status("语音就绪，开始说吧")
            self._listen()
        else:
            self._wake_start()  # 通话模式在等这个模型

    def _listen(self) -> None:
        if not self.recorder.start():
            self.orb.set_state("error")
            self._peek(self.recorder.error)
            QTimer.singleShot(2600, lambda: self.orb.set_state("idle"))
            return
        # 你开口的这几秒里，把画面抓下来、字认出来，等下就不用等
        self._wake_stop()
        self._prewarm_capture()
        self._listening = True
        self.orb.set_state("listening")
        self._mic_timer.start()
        if self.bubble.isVisible():
            self.bubble.set_status("在听…")

    def _poll_mic(self) -> None:
        self.orb.set_level(self.recorder.level)
        result = self.recorder.poll()
        if result is None:
            return
        self._mic_timer.stop()
        self._listening = False
        self.orb.set_level(0.0)
        kind, audio = result
        if kind == "cancel":
            self.orb.set_state("idle")
            self._wake_start()
            return
        if kind == "silent" or audio is None or len(audio) < 4800:
            self.orb.set_state("error")
            if self.bubble.isVisible():
                self.bubble.set_status("没听到声音")
            QTimer.singleShot(1500, lambda: self.orb.set_state("idle"))
            self._wake_start()
            return
        self._transcribe(audio)

    # ---------- 预抓帧 + 预 OCR ----------

    def _prewarm_capture(self) -> None:
        if not self.settings.ready:
            return
        self._pre_token += 1
        token = self._pre_token
        try:
            shot = grab(
                max_width=self.settings.max_image_width,
                keep_full=self.settings.ocr_enabled,
            )
        except Exception:
            return
        full, shot.full = shot.full, None
        self._pre_shot = shot
        self._pre_ocr = ""
        self._pre_stamp = time.time()
        if full is None:
            return
        self._spawn(lambda: self.ocr.read(full), lambda text: self._on_pre_ocr(token, text))

    def _on_pre_ocr(self, token: int, text: object) -> None:
        if token == self._pre_token:
            self._pre_ocr = str(text or "")

    def _take_prewarm(self) -> tuple[Capture | None, str]:
        shot, text, stamp = self._pre_shot, self._pre_ocr, self._pre_stamp
        self._pre_shot, self._pre_ocr = None, ""
        if shot is None or time.time() - stamp > 45:
            return None, ""
        return shot, text

    def _transcribe(self, audio) -> None:
        self.orb.set_state("thinking")
        if self.bubble.isVisible():
            self.bubble.set_status("转文字…")
        self._spawn(lambda: self.asr.transcribe(audio), self._on_transcript, self._on_transcript_fail)

    def _on_transcript(self, text: object) -> None:
        heard = str(text or "").strip()
        if not heard:
            self.orb.set_state("error")
            if self.bubble.isVisible():
                self.bubble.set_status("没听清，再说一次")
            QTimer.singleShot(1500, lambda: self.orb.set_state("idle"))
            return
        self._ask_with_question(heard)

    def _on_transcript_fail(self, message: str) -> None:
        self.orb.set_state("error")
        if self.bubble.isVisible():
            self.bubble.show_error(f"识别失败：{message}")
        QTimer.singleShot(2600, lambda: self.orb.set_state("idle"))
        self._wake_start()

    def _on_speech_idle(self) -> None:
        if (self.worker is None or not self.worker.isRunning()) and not self._listening:
            self.orb.set_state("idle")

    # ---------- 通话模式 ----------

    def wake_available(self) -> bool:
        return bool(
            self.settings.call_mode
            and self.settings.voice_enabled
            and self.settings.api_key.strip()
            and self.settings.wake_word.strip()
        )

    def _wake_enabled(self) -> bool:
        """唤醒线程里调用：它在忙的时候别接话。"""
        return bool(
            not self._listening
            and not (self.worker is not None and self.worker.isRunning())
            and not self.speaker.busy
        )

    def _wake_start(self) -> None:
        if not self.wake_available():
            return
        if self._wake is not None and self._wake.is_alive():
            return
        # 旧的监听线程还在收尾（关麦克风流），等它退干净再开新的，免得两个流抢设备
        if self._wake_dying is not None:
            if self._wake_dying.is_alive():
                QTimer.singleShot(400, self._wake_start)
                return
            self._wake_dying = None
        if not self.asr.ready:
            self._ensure_engines()  # 模型没好，加载完会再调一次
            return
        self._wake = WakeListener(
            self.asr,
            self.settings.wake_word,
            on_wake=self.wakeHit.emit,
            enabled=self._wake_enabled,
            on_error=self.hotkeyError.emit,
        )
        self._wake.start()

    def _wake_stop(self) -> None:
        if self._wake is not None:
            self._wake.stop()
            self._wake_dying = self._wake
            self._wake = None

    def _sync_call_mode(self) -> None:
        self._wake_stop()
        if self.wake_available():
            self._ensure_engines()
            self._wake_start()

    def _ensure_engines(self) -> None:
        if self.asr.ready or self._asr_loading:
            return
        self._asr_loading = True
        self._spawn_asr_load()

    def _on_wake(self, question: str) -> None:
        if not self._wake_enabled():
            return
        if self.speaker.busy:
            self.speaker.stop()
        heard = (question or "").strip()

        ack = (self.settings.wake_ack or "").strip()
        spoke = False
        if ack and self.settings.tts_enabled:
            self.speaker.say(ack)  # 先给个回应，让你知道它听见了
            spoke = True

        if heard:
            self._wake_stop()
            self._prewarm_capture()
            self._ask_with_question(heard, keep_audio=spoke)
        else:
            # 应答还在播，等它说完再开麦，否则自己那句会被录成问题
            self._listen_after_ack()

    def _listen_after_ack(self, tries: int = 40) -> None:
        if self.speaker.busy and tries > 0:
            QTimer.singleShot(100, lambda: self._listen_after_ack(tries - 1))
            return
        self._listen()

    def _ask_with_question(self, question: str, keep_audio: bool = False) -> None:
        self._wake_stop()
        title, process = foreground_info()
        self._current_game = guess_game_name(title, process)
        self._voice_mode = True
        self.bubble.begin(self._current_game, focus=False)
        geo = self.orb.screen().availableGeometry()
        anchor = self.orb.mapToGlobal(QPoint(self.orb.width() // 2, 0))
        self.bubble.place_near(anchor, geo)
        self.bubble.set_question(question)
        self.ask(question, keep_audio=keep_audio)

    # ---------- 交互 ----------

    def toggle_bubble(self) -> None:
        if self.bubble.isVisible():
            self.bubble.close_bubble()
            return
        if self.worker is not None and self.worker.isRunning():
            return
        self.open_bubble()

    def open_bubble(self) -> None:
        self._prev_hwnd = foreground_hwnd()
        self._prewarm_capture()  # 趁气泡还没盖上去，先抓一张干净的
        title, process = foreground_info()
        self._voice_mode = False
        self._current_game = guess_game_name(title, process)
        self.bubble.begin(self._current_game)
        geo = self.orb.screen().availableGeometry()
        anchor = self.orb.mapToGlobal(QPoint(self.orb.width() // 2, 0))
        self.bubble.place_near(anchor, geo)
        if not self.settings.ready:
            self.bubble.show_error(NO_KEY_HINT)

    def ask(self, question: str, keep_audio: bool = False) -> None:
        if self.assistant is None:
            self.bubble.show_error(NO_KEY_HINT)
            return
        if self.worker is not None and self.worker.isRunning():
            return
        if self.speaker.busy and not keep_audio:
            self.speaker.stop()
        self._muted = False
        self._pending_question = question

        self.orb.set_state("thinking")
        self.bubble.set_status("稍等…")
        self.bubble.input.setEnabled(False)

        shot, ocr_text = self._take_prewarm()
        self.worker = AskWorker(
            self.assistant,
            question,
            self.settings.max_image_width,
            shot=shot,
            ocr_text=ocr_text,
        )
        self.worker.status.connect(self.bubble.set_status)
        self.worker.delta.connect(self._on_delta)
        self.worker.ok.connect(self._on_done)
        self.worker.fail.connect(self._on_fail)
        self.worker.start()

    def _on_delta(self, chunk: str) -> None:
        if self.orb.state != "speaking":
            self.orb.set_state("speaking")
        self.bubble.append(chunk)
        if self.settings.tts_enabled and not self._muted:
            self.speaker.feed(chunk)

    def _on_done(self, answer: str) -> None:
        self.bubble.finish("")
        self.bubble.input.setEnabled(True)
        if answer:
            self.history.add(self._current_game, self._pending_question, answer)
        if self.settings.tts_enabled:
            self.speaker.flush()  # 剩余的话交给喇叭，播完再回 idle
        else:
            self.orb.set_state("idle")
        if not self._voice_mode:
            self.bubble.input.setFocus()
        self._wake_start()

    def _on_fail(self, message: str) -> None:
        if self.speaker.busy:
            self.speaker.stop()
        self.orb.set_state("error")
        self.bubble.show_error(message)
        self.bubble.input.setEnabled(True)
        QTimer.singleShot(2600, lambda: self.orb.set_state("idle"))
        self._wake_start()

    def _peek(self, text: str) -> None:
        """不抢焦点地弹个提示。"""
        if not self.bubble.isVisible():
            title, process = foreground_info()
            self._voice_mode = True
            self.bubble.begin(guess_game_name(title, process), focus=False)
            geo = self.orb.screen().availableGeometry()
            anchor = self.orb.mapToGlobal(QPoint(self.orb.width() // 2, 0))
            self.bubble.place_near(anchor, geo)
        self.bubble.set_status(text)

    def _show_quick_error(self, message: str) -> None:
        if not self.bubble.isVisible():
            self.open_bubble()
        self.bubble.show_error(message)

    def _restore_focus(self) -> None:
        focus_window(self._prev_hwnd)
        self._prev_hwnd = 0

    def _on_bubble_resized(self, width: int, height: int) -> None:
        self.settings.bubble_w = width
        self.settings.bubble_h = height
        try:
            self.settings.save()
        except Exception:
            pass

    # ---------- 设置 ----------

    def _maybe_first_run(self) -> None:
        if self.settings.api_key.strip() or self.settings.welcome_done:
            return
        self.open_settings(first_run=True)

    def open_settings(self, first_run: bool = False) -> None:
        if self._dialog is not None:
            self._dialog.raise_()
            self._dialog.activateWindow()
            return
        from .ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.settings, first_run=first_run)
        dialog.saved.connect(self._apply_settings)
        dialog.finished.connect(self._on_dialog_closed)
        self._dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_dialog_closed(self, _result: int) -> None:
        self._dialog = None
        if not self.settings.welcome_done:
            self.settings.welcome_done = True
            try:
                self.settings.save()
            except Exception:
                pass

    def _apply_settings(self) -> None:
        self._build_backend()
        self._restart_hotkeys()
        self.speaker.voice = self.settings.tts_voice
        self.speaker.rate = self.settings.tts_rate
        if self.asr.model_size != self.settings.asr_model:
            self.asr = WhisperASR(self.settings.asr_model)
        self._sync_call_mode()
        size = max(40, min(120, int(self.settings.orb_size)))
        if self.orb.width() != size:
            center = self.orb.geometry().center()
            self.orb.setFixedSize(size, size)
            screen = QGuiApplication.primaryScreen().availableGeometry()
            x = min(max(center.x() - size // 2, screen.left()), screen.right() - size)
            y = min(max(center.y() - size // 2, screen.top()), screen.bottom() - size)
            self.orb.move(x, y)
        self._sync_toggles()

    def _restart_hotkeys(self) -> None:
        for listener in self.hotkeys:
            listener.stop()
        self.hotkeys.clear()
        self._start_hotkeys()

    def _sync_toggles(self) -> None:
        self._refresh_tray_menu()
        self.orb.set_toggles(
            {
                "voice": self.settings.voice_enabled,
                "tts": self.settings.tts_enabled,
                "call": self.settings.call_mode,
                "autostart": startup.is_enabled(),
            }
        )

    def _on_toggle(self, key: str, enabled: bool) -> None:
        if key == "voice":
            self.settings.voice_enabled = enabled
        elif key == "tts":
            self.settings.tts_enabled = enabled
            if not enabled and self.speaker.busy:
                self.speaker.stop()
        elif key == "call":
            if enabled and not self.settings.voice_enabled:
                self.settings.voice_enabled = True
                if not self.settings.wake_word.strip():
                    self.settings.wake_word = "小助手"
            self.settings.call_mode = enabled
        elif key == "autostart":
            try:
                startup.enable() if enabled else startup.disable()
            except Exception:
                pass
        try:
            self.settings.save()
        except Exception:
            pass
        self._sync_call_mode()
        self._sync_toggles()

    def open_history(self) -> None:
        if self._history_dialog is not None:
            self._history_dialog.raise_()
            self._history_dialog.activateWindow()
            return
        from .ui.history_dialog import HistoryDialog

        dialog = HistoryDialog(self.history)
        dialog.finished.connect(self._on_history_closed)
        self._history_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_history_closed(self, _result: int) -> None:
        self._history_dialog = None

    def _reset_memory(self) -> None:
        if self.assistant:
            self.assistant.reset()
        self.orb.set_state("idle")

    # ---------- 退出 ----------

    def quit(self) -> None:
        try:
            if self._listening:
                self._mic_timer.stop()
                self.recorder.cancel()
            self._wake_stop()
            self.speaker.stop()
            if self.tray is not None:
                self.tray.hide()
        except Exception:
            pass
        try:
            self.settings.orb_x = self.orb.x()
            self.settings.orb_y = self.orb.y()
            self.settings.save()
        except Exception:
            pass
        for hk in self.hotkeys:
            hk.stop()
        # 等一会儿，别等太久：OCR 这种 C 代码中途打断不了，等下去只会让退出变卡
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(1500)
        for worker in list(self._workers):
            worker.wait(1200)
        self.qt_app.quit()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("游戏助手")
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Microsoft YaHei UI", 10))

    settings = Settings.load()
    controller = AssistantApp(app, settings)
    app._controller = controller  # 防 GC
    return app.exec()
