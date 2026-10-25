"""应用装配：悬浮球 + 语音对话 + 气泡 + 热键 + 后台线程。"""

from __future__ import annotations

import re
import sys
import time
from typing import Callable

from PySide6.QtCore import QObject, QPoint, QThread, QTimer, Signal
from PySide6.QtGui import QFont, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from .config import Settings
from .act.dsh_bridge import DshBridge
from .core.agent import GameAssistant
from .core.audit import OfficeAudit
from .core.history import History
from .paths import base_dir, data_dir
from .llm.deepseek import DeepSeekClient
from .ui.bubble import Bubble
from .ui.hotkey import HotkeyListener
from .ui.orb import Orb
from .util import startup
from .vision.capture import (
    focus_window,
    text_only,
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


def _already_running() -> bool:
    """单实例：两个进程会抢全局热键，第二个直接退出。"""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, "Local\\VoiceAssistant-single-instance")
    if not handle:
        return False
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return True
    # 句柄故意不关：进程活着就一直占着
    return False


def make_app_icon() -> QIcon:
    """拿悬浮球自己渲染一个图标，省得打包还得带 ico 文件。"""
    temp = Orb(64)
    temp._timer.stop()
    return QIcon(temp.grab())


from .core.vocab import CONFIRM_MAX_CHARS, CONFIRM_NO, CONFIRM_RETRY, CONFIRM_YES, DANGER_WORDS


def _is_confirm_word(text: str) -> bool:
    """孤零零的一个「取消/执行」——多半是上一轮确认的尾巴，不是新任务。"""
    flat = text.replace(" ", "").replace("，", "").replace("。", "")
    if len(flat) > 4:
        return False
    return any(word in flat for word in CONFIRM_YES + CONFIRM_NO + CONFIRM_RETRY)


def spoken_summary(text: str, limit: int = 60) -> str:
    """朗读用：只取第一句，去掉 markdown，超长截断。"""
    clean = re.sub("[*`#>_~\\[\\]()]", "", text or "")
    clean = re.sub("\\s+", " ", clean).strip()
    if not clean:
        return ""
    match = re.search("[。！？!?；;]", clean)
    head = clean[: match.end()] if match else clean
    if len(head) > limit:
        head = head[:limit].rstrip("，,、 ") + "…"
    return head


def _mmss(seconds: float) -> str:
    minutes, rest = divmod(int(max(0, seconds)), 60)
    return f"{minutes:02d}:{rest:02d}"


class OfficeWorker(QThread):
    """办公模式：跑一个 dsh 任务，逐条把步骤发回主线程。"""

    step = Signal(object)
    done = Signal(str)
    fail = Signal(str)

    def __init__(self, bridge, task, cwd, api_key, permission, timeout, should_stop) -> None:
        super().__init__()
        self.bridge = bridge
        self.task = task
        self.cwd = cwd
        self.api_key = api_key
        self.permission = permission
        self.timeout = timeout
        self.should_stop = should_stop

    def run(self) -> None:
        try:
            final = self.bridge.run(
                self.task,
                cwd=self.cwd,
                on_step=self.step.emit,
                api_key=self.api_key,
                permission=self.permission,
                timeout=self.timeout,
                should_stop=self.should_stop,
            )
            self.done.emit(final)
        except Exception as exc:  # noqa: BLE001
            self.fail.emit(str(exc) or exc.__class__.__name__)


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
    modeTriggered = Signal()
    hotkeyError = Signal(str)
    speechIdle = Signal()
    speechStarted = Signal()
    wakeHit = Signal(str)

    def __init__(self, qt_app: QApplication, settings: Settings) -> None:
        super().__init__()
        self.qt_app = qt_app
        self.settings = settings
        self.assistant: GameAssistant | None = None
        self.worker: AskWorker | None = None
        self._workers: list[FuncWorker] = []
        self.bridge = DshBridge(base_dir())
        self.office_worker: OfficeWorker | None = None
        self._office_stop = False
        self._office_running = False
        self._task_steps: list[list[str]] = []
        self._task_footer: tuple[str, str] | None = None
        self._task_start = 0.0
        self._task_timer = QTimer(self)
        self._task_timer.setInterval(1000)
        self._task_timer.timeout.connect(self._tick_task)
        self.audit = OfficeAudit(data_dir() / "office_audit.jsonl")
        self._audit_steps: list[dict] = []
        self._audit_confirm = "not-needed"
        self._confirm_pending: str | None = None
        self._barge_hits = 0
        self._barge_used = False
        self._post_listen = False
        self._transcribe_ctx = "ask"
        self._confirm_closed_at = 0.0
        self._confirm_timer = QTimer(self)
        self._confirm_timer.setSingleShot(True)
        self._confirm_timer.timeout.connect(lambda: self._cancel_confirm("没等到回应，已取消"))
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
        self.recorder = Recorder(settings.input_device)
        self.history = History()
        self.asr = WhisperASR(settings.asr_model)
        self.ocr = OcrEngine(settings.ocr_max_side)
        self._pre_shot: Capture | None = None
        self._pre_ocr = ""
        self._pre_stamp = 0.0
        self._pre_token = 0
        self.speaker = Speaker(
            settings.tts_voice,
            settings.tts_rate,
            on_idle=self.speechIdle.emit,
            device=settings.output_device,
            on_start=self.speechStarted.emit,
        )

        self._mic_timer = QTimer(self)
        self._mic_timer.setInterval(60)
        self._mic_timer.timeout.connect(self._poll_mic)

        self._build_backend()
        self._wire()
        self._place_orb()
        self._setup_tray()
        self._start_hotkeys()
        self._sync_toggles()
        self._apply_mode()
        self._sync_call_mode()  # 上次开着通话模式的话，启动就继续听
        # 启动 12 秒后偷偷把识别模型读进内存，省得第一次说话还要等
        QTimer.singleShot(1200, self.speaker.warmup)  # 提前把音频流跑热
        QTimer.singleShot(1500, self._preload_asr)  # 启动就开始加载，球上能看见
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
        self.bubble.submitted.connect(self._on_typed_submit)
        self.bubble.closed.connect(self._restore_focus)
        self.bubble.resized.connect(self._on_bubble_resized)
        self.bubble.talkRequested.connect(self.on_talk)
        self.bubble.historyRequested.connect(self.open_history)
        self.bubble.stopRequested.connect(self._stop_office)
        self.bubble.confirmAccepted.connect(self._accept_confirm)
        # 「编辑」按钮在气泡内部处理；语音说「重说」才走 _retry_confirm
        self.bubble.confirmCancelled.connect(lambda: self._cancel_confirm("已取消"))
        self.triggered.connect(self.on_talk)
        self.modeTriggered.connect(self._toggle_mode)
        self.hotkeyError.connect(self._show_quick_error)
        self.speechIdle.connect(self._on_speech_idle)
        self.speechStarted.connect(self._on_speech_start)
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
        self.tray.setToolTip(f"语音助手 · {self.settings.hotkey} 说话")
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
        if self.settings.mode_hotkey and self.settings.mode_hotkey != self.settings.hotkey:
            combos.append((self.settings.mode_hotkey, self.modeTriggered.emit))
        for combo, callback in combos:
            listener = HotkeyListener(combo, callback, self.hotkeyError.emit)
            listener.start()
            self.hotkeys.append(listener)

    # ---------- 语音 ----------

    def on_talk(self) -> None:
        """热键/麦克风按钮：说一句话；办公任务跑着的时候 = 停止。"""
        if self._confirm_pending is not None:
            self._cancel_confirm("已取消")
            return
        self._stop_office()
        if self._office_running:
            return
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
        self.orb.set_state("loading")
        self._peek("正在加载语音模型（约 250MB，只需一次）…")
        self._spawn_asr_load()

    def _preload_asr(self) -> None:
        if not self.settings.voice_enabled or not self.settings.asr_preload:
            return
        if self.asr.ready or self._asr_loading:
            return
        self._asr_loading = True
        self.orb.set_state("loading")
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
            self.orb.set_state("idle")
            self._wake_start()  # 通话模式在等这个模型

    def _listen(self, prewarm: bool = True) -> None:
        if not self.recorder.start():
            self.orb.set_state("error")
            self._peek(self.recorder.error)
            self._post_listen = False
            QTimer.singleShot(2600, lambda: self.orb.set_state("idle"))
            self._wake_start()
            return
        # 你开口的这几秒里，把画面抓下来、字认出来，等下就不用等
        self._wake_stop()
        if prewarm:
            self._prewarm_capture()
        self._listening = True
        self.orb.set_state("listening")
        self._mic_timer.start()
        if self.bubble.isVisible():
            self.bubble.set_status("在听…")

    def _poll_mic(self) -> None:
        self.orb.set_level(self.recorder.level)
        if self._confirm_pending is not None or self._post_listen:
            self._poll_confirm_mic()
            return
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
        if not self.settings.ready or not self.settings.capture_enabled:
            self._pre_shot, self._pre_ocr, self._pre_stamp = None, "", 0.0
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
        self._transcribe_ctx = (
            "confirm"
            if self._confirm_pending is not None
            else ("post" if self._post_listen else "ask")
        )
        self.orb.set_state("thinking")
        if self.bubble.isVisible():
            self.bubble.set_status("转文字…")
        self._spawn(lambda: self.asr.transcribe(audio), self._on_transcript, self._on_transcript_fail)

    def _on_transcript(self, text: object) -> None:
        heard = str(text or "").strip()
        ctx = self._transcribe_ctx
        self._transcribe_ctx = "ask"
        if ctx == "confirm" and self._confirm_pending is None:
            return  # 确认早就结束了，这句是迟到的转录
        if self._confirm_pending is not None and heard:
            self._handle_confirm_words(heard)
            return
        if (
            heard
            and self._confirm_pending is None
            and _is_confirm_word(heard)
            and (self._post_listen or time.time() - self._confirm_closed_at < 8.0)
        ):
            # 刚结束的确认留下的尾巴，别当成新任务
            return
        if self._post_listen and heard:
            self._end_post_listen()
            self._ask_with_question(heard)
            return
        if not heard:
            # 插话只收到一团杂音：别把唤醒挂死在这里
            if self._post_listen:
                self._end_post_listen()
            else:
                self._wake_start()
            self.orb.set_state("error")
            if self.bubble.isVisible():
                self.bubble.set_status("没听清，再说一次")
            QTimer.singleShot(1500, lambda: self.orb.set_state("idle"))
            return
        self._ask_with_question(heard)

    def _on_transcript_fail(self, message: str) -> None:
        self._post_listen = False
        self.orb.set_state("error")
        if self.bubble.isVisible():
            self.bubble.show_error(f"识别失败：{message}")
        QTimer.singleShot(2600, lambda: self.orb.set_state("idle"))
        self._wake_start()

    def _on_speech_start(self) -> None:
        """喇叭真正出声的那一刻：球切到「正在说」。"""
        if self.orb.state != "speaking":
            self.orb.set_state("speaking")

    def _on_speech_idle(self) -> None:
        if self._confirm_pending is not None or self._post_listen:
            if not self._barge_used:
                # 朗读期间录到的都是它自己的声音，丢掉
                self.recorder.reset()
            self._barge_used = False
            if not self._listening:
                QTimer.singleShot(200, self._confirm_listen)
            elif self._post_listen and self._confirm_pending is None:
                self.orb.set_state("listening")
            return
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
            self._confirm_pending is None
            and not self._office_running
            and not self._listening
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
            device=self.settings.input_device,
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
        self.orb.set_state("loading")
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
        if self._office_running:
            self._show_task_card()
            return
        self._open_plain_bubble()

    def _open_plain_bubble(self, prewarm: bool = True) -> None:
        self._prev_hwnd = foreground_hwnd()
        if prewarm:
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
        if self._confirm_pending is not None:
            # 确认卡上直接改字后回车 = 明确同意
            self._accept_confirm(question)
            return
        if self.settings.mode == "office":
            if self._voice_mode and self._needs_confirm(question):
                self._begin_confirm(question)
                return
            self._ask_office(question)
            return
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

        if self.settings.capture_enabled:
            shot, ocr_text = self._take_prewarm()
        else:
            shot, ocr_text = text_only(), ""
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

    # ---------- 语音任务确认 ----------

    def _needs_confirm(self, text: str) -> bool:
        """只看档位，跟权限级别解耦：权限管后果范围，确认管输入可信度。"""
        mode = self.settings.confirm_mode
        if mode == "all":
            return True
        if mode == "danger":
            return any(word in text for word in DANGER_WORDS)
        return False

    def _begin_confirm(self, text: str) -> None:
        self._confirm_pending = text
        level = "full" if self.settings.office_permission == "danger-full-access" else ""
        self.bubble.begin_confirm(text, level)
        self.orb.set_state("thinking")
        self._barge_used = False
        self._barge_hits = 0
        if self.settings.tts_enabled:
            self.speaker.say(f"请确认：{text}")
        # 立刻开麦：朗读期间就能抢话，不用等它念完
        self._listen(prewarm=False)
        self._confirm_timer.start(max(5, int(self.settings.confirm_timeout)) * 1000)

    def _clear_confirm(self) -> None:
        self._confirm_pending = None
        self._confirm_timer.stop()
        self._confirm_closed_at = time.time()

    def _accept_confirm(self, text: str = "") -> None:
        task = (text or self._confirm_pending or "").strip()
        self._clear_confirm()
        self.bubble.end_confirm()
        if not task:
            self._cancel_confirm("没有任务内容")
            return
        if self.bubble.isVisible():
            self.bubble.close_bubble()
        self._ask_office(task, confirmed=True)

    def _cancel_confirm(self, note: str = "") -> None:
        if self._confirm_pending is None:
            return
        self.audit.record(
            self._confirm_pending,
            source="voice",
            permission=self.settings.office_permission,
            workspace=str(self.settings.workspace),
            confirm="cancelled",
            result=note or "已取消",
        )
        self._clear_confirm()
        self.bubble.end_confirm()
        self.orb.set_state("idle")
        if self.bubble.isVisible():
            self.bubble.close_bubble()
        self._wake_start()

    def _retry_confirm(self) -> None:
        self._clear_confirm()
        self.bubble.end_confirm()
        self.bubble.begin(self._current_game)
        self._listen(prewarm=False)

    def _poll_confirm_mic(self) -> None:
        """确认阶段：朗读时就盯着有没有抢话，读完了才开始收你的回答。"""
        if self.speaker.busy:
            if self.recorder.level > 0.55:
                self._barge_hits += 1
                if self._barge_hits >= 3:
                    self._barge_hits = 0
                    self._barge_used = True
                    self.speaker.stop()
                    self.recorder.request_stop()  # 别丢：先把已经说的话断句送识别
                    self.bubble.set_status("在听…")
            else:
                self._barge_hits = 0
            return

        result = self.recorder.poll()
        if result is None:
            return
        self._mic_timer.stop()
        self._listening = False
        self.orb.set_level(0.0)
        kind, audio = result
        if kind == "cancel":
            if self._confirm_pending is not None:
                self._cancel_confirm()
            else:
                self._end_post_listen()
            return
        if kind in ("silent", "timeout") or audio is None or len(audio) < 4800:
            if self._confirm_pending is not None:
                self._confirm_listen()  # 没听到，继续等
            else:
                self._end_post_listen()
            return
        self._transcribe(audio)

    def _end_post_listen(self) -> None:
        self._post_listen = False
        self.orb.set_state("idle")
        self._wake_start()

    def _listen_after_task(self) -> None:
        """任务播报时也开着麦：说一句就是新任务，不说就算了。"""
        if not (self.settings.call_mode and self.settings.voice_enabled and self.asr.ready):
            self._wake_start()
            return
        self._post_listen = True
        self._barge_used = False
        self._barge_hits = 0
        self._listen(prewarm=False)

    def _confirm_listen(self) -> None:
        if self._confirm_pending is None:
            return
        self._listen(prewarm=False)

    def _handle_confirm_words(self, heard: str) -> None:
        flat = heard.replace(" ", "").replace("，", "").replace("。", "")
        if len(flat) > CONFIRM_MAX_CHARS:
            # 太长：多半是回声或自言自语，继续听
            self._confirm_listen()
            return
        if any(word in flat for word in CONFIRM_RETRY):
            self._retry_confirm()
            return
        # 否定优先：带「不」的一律当拒绝，"不可以""不确定"都别放过去
        if "不" in flat or any(word in flat for word in CONFIRM_NO):
            self._cancel_confirm("已取消")
            return
        if any(word in flat for word in CONFIRM_YES):
            self._accept_confirm()
            return
        self.bubble.set_status("没听清，说「执行」或「取消」")
        QTimer.singleShot(600, self._confirm_listen)

    # ---------- 办公模式 ----------

    def _ask_office(self, question: str, confirmed: bool = False) -> None:
        self._audit_confirm = "accepted" if confirmed else "not-needed"
        if not self.bridge.available:
            self.bubble.show_error("办公模式需要内置执行组件（vendor 目录缺失）")
            self._wake_start()
            return
        if not self.settings.ready:
            self.bubble.show_error(NO_KEY_HINT)
            self._wake_start()
            return
        if self.office_worker is not None and self.office_worker.isRunning():
            self._wake_start()
            return

        self._office_stop = False
        self._office_running = True
        self._pending_question = question
        self._current_game = "办公"
        self._task_steps = []
        self._audit_steps = []
        self._task_footer = None
        self._task_start = time.time()
        self.orb.set_state("thinking")
        self._task_timer.start()

        self.office_worker = OfficeWorker(
            self.bridge,
            question,
            self.settings.workspace,
            self.settings.api_key,
            self.settings.office_permission,
            self.settings.office_timeout,
            lambda: self._office_stop,
        )
        self.office_worker.step.connect(self._on_office_step)
        self.office_worker.done.connect(self._on_office_done)
        self.office_worker.fail.connect(self._on_office_fail)
        self.office_worker.start()

    def _record_audit(self, result: str = "", error: str = "") -> None:
        if self._task_start <= 0:
            return
        self.audit.record(
            self._pending_question,
            source="voice" if self._voice_mode else "typed",
            permission=self.settings.office_permission,
            workspace=str(self.settings.workspace),
            confirm=self._audit_confirm,
            steps=list(self._audit_steps),
            result=result,
            duration=time.time() - self._task_start,
            error=error,
        )

    def _show_task_card(self) -> None:
        """任务在后台跑时，点球看进度。"""
        if not self.bubble.isHidden():
            self.bubble.close_bubble()
            return
        self._prev_hwnd = foreground_hwnd()
        self.bubble.begin("办公模式")
        geo = self.orb.screen().availableGeometry()
        anchor = self.orb.mapToGlobal(QPoint(self.orb.width() // 2, 0))
        self.bubble.place_near(anchor, geo)
        self.bubble.begin_task()
        self._tick_task()

    def _tick_task(self) -> None:
        if self.bubble.isHidden():
            return
        elapsed = _mmss(time.time() - self._task_start) if self._task_start else "00:00"
        self.bubble.render_task(
            self._task_steps, elapsed, self._office_running, self._task_footer
        )

    def _on_office_step(self, step) -> None:
        if step.kind == "tool":
            self._task_steps.append(["◐", step.text])
            self._audit_steps.append({"text": step.text, "ok": None})
        elif step.kind == "result":
            for row in reversed(self._task_steps):
                if row[0] == "◐":
                    row[0] = "✓" if step.ok else "✗"
                    break
            for row in reversed(self._audit_steps):
                if row["ok"] is None:
                    row["ok"] = step.ok
                    break
        elif step.kind == "final":
            self.orb.set_state("speaking")
        self._tick_task()

    def _on_office_done(self, final: str) -> None:
        self._office_running = False
        self._task_timer.stop()
        self._task_footer = ("结果", final) if final else None
        self._record_audit(result=final)
        self._tick_task()
        self.bubble.end_task()
        self.orb.set_state("idle")
        if final:
            self.history.add("办公", self._pending_question, final)
            if self.settings.tts_enabled:
                self.speaker.say(spoken_summary(final))
                # 状态交给 speechStarted 驱动，别在这里抢
        self._listen_after_task()

    def _on_office_fail(self, message: str) -> None:
        self._office_running = False
        self._task_timer.stop()
        self._task_footer = ("没做成", message)
        self._record_audit(error=message)
        self._tick_task()
        self.bubble.end_task()
        self.orb.set_state("error")
        QTimer.singleShot(2600, lambda: self.orb.set_state("idle"))
        self._wake_start()

    def _on_delta(self, chunk: str) -> None:
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
        # 不走 open_bubble：任务在跑时那儿是任务卡，错误别去占它
        if not self.bubble.isVisible():
            self._open_plain_bubble(prewarm=False)
        self.bubble.show_error(message)

    def _restore_focus(self) -> None:
        if self._confirm_pending is not None:
            self._clear_confirm()  # 气泡被关掉 = 不执行
            self._wake_start()
        if self._post_listen:
            self._post_listen = False
            self._wake_start()
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
        if self.speaker.device != self.settings.output_device:
            self.speaker.device = self.settings.output_device
            self.speaker._warmed = False
            QTimer.singleShot(400, self.speaker.warmup)
        self.recorder.device = self.settings.input_device
        if self.asr.model_size != self.settings.asr_model:
            self.asr = WhisperASR(self.settings.asr_model)
        self._sync_call_mode()
        self._apply_mode()
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

    def _on_typed_submit(self, text: str) -> None:
        """打字进来的：明确是人的意思，不走语音确认。"""
        self._voice_mode = False
        self.ask(text)

    def _apply_mode(self) -> None:
        self.orb.set_mode(self.settings.mode)

    def _toggle_mode(self) -> None:
        self._on_toggle("office", self.settings.mode != "office")

    def _stop_office(self) -> None:
        if self.office_worker is not None and self.office_worker.isRunning():
            self._office_stop = True
            self.bridge.cancel()
            self.bubble.set_status("正在停止…")

    def _sync_voice_info(self) -> None:
        self.orb.set_voice_info(
            "call" if self.settings.call_mode else "push",
            self.settings.hotkey,
            self.settings.wake_word,
        )
        self.orb.set_mode_hotkey(self.settings.mode_hotkey)

    def _sync_toggles(self) -> None:
        self._refresh_tray_menu()
        self._sync_voice_info()
        self.orb.set_toggles(
            {
                "voice": self.settings.voice_enabled,
                "tts": self.settings.tts_enabled,
                "call": self.settings.call_mode,
                "office": self.settings.mode == "office",
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
        elif key == "office":
            self.settings.mode = "office" if enabled else "game"
            self._apply_mode()
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

        dialog = HistoryDialog(self.history, self.audit, on_clear=self._reset_memory)
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
        if self.office_worker is not None and self.office_worker.isRunning():
            self._office_stop = True
            self.bridge.cancel()
            self.office_worker.wait(2000)
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(1500)
        for worker in list(self._workers):
            worker.wait(1200)
        self.qt_app.quit()


def main() -> int:
    app = QApplication(sys.argv)
    if _already_running():
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(None, "语音助手", "已经在运行了，看系统托盘里的图标。")
        return 0
    app.setApplicationName("语音助手")
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Microsoft YaHei UI", 10))

    settings = Settings.load()
    controller = AssistantApp(app, settings)
    app._controller = controller  # 防 GC
    return app.exec()
