"""应用引导：QApplication + RinUIWindow + AppBridge。"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QLockFile,
    QObject,
    QTimer,
    Qt,
    QtMsgType,
    Signal,
    qInstallMessageHandler,
)
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication
from RinUI import RinUIWindow
from RinUI.core.config import Theme

from .bridge.app_bridge import AppBridge
from .i18n import Translator
from .consts import APP_ALIAS, APP_ID, APP_NAME, APP_VERSION, CUSTOM_THEME_PREFIX
from .paths import app_data_dir, qml_dir, qml_file
from .services import elevation, keeper, power, store, timesync
from .services.dock_reveal import DockRevealController
from .services.lock_hardening import restore_taskbars
from .services.logging_setup import setup_logging
from .services.quick_panel import QuickPanelController
from .services.tray import TrayController, app_icon_path
from .settings import Settings

_LOG: list[str] = []
_QML_PROBLEMS: list[str] = []
_SMOKE_DONE = False

#: 已知无害的 Qt / RinUI 噪音（不参与冒烟判定）
_BENIGN_MARKERS = (
    "overrides a member of the base object",
    "QFontDatabase: Cannot find font directory",
    "ScrollBar attached property must be attached",
    "DPI Scale Factor",
    "HiDPI note",
    "Font Source:",
    "Font Family:",
)


def _is_problem(message: str, mode) -> bool:  # noqa: ANN001
    if any(marker in message for marker in _BENIGN_MARKERS):
        return False
    lowered = message.lower()
    if "qml:" in lowered or "typeerror" in lowered or "referenceerror" in lowered:
        return True
    return mode in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)


def _message_handler(mode, context, message: str) -> None:  # noqa: ANN001
    text = str(message)
    if _SMOKE_DONE:
        return
    _LOG.append(text)
    if _is_problem(text, mode):
        _QML_PROBLEMS.append(text)
    print(text, file=sys.stderr)


def _parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(prog=APP_NAME, description=f"{APP_NAME}（{APP_ALIAS}）专注锁机工具")
    parser.add_argument("--smoke", action="store_true", help="离屏冒烟测试：加载界面、截图后退出")
    parser.add_argument("--restarted", action="store_true", help="由保活看门狗重新拉起")
    parser.add_argument("--autostart", action="store_true", help="由计划任务/开机自启拉起")
    parser.add_argument("--theme", choices=["Auto", "Light", "Dark"], default=None)
    # v0.18：启动即打开商店（theme / plugin），用于给用户直接展示线上商店
    parser.add_argument("--store", choices=["theme", "plugin"], default=None)
    return parser.parse_known_args(argv[1:] if argv else [])


# ================= v0.17 单实例（QLocalServer / QLocalSocket） =================

#: 主实例监听的本地套接字名
SINGLE_INSTANCE_NAME = f"{APP_ID}-SingleInstance"
#: 第二个实例发给主实例的消息：激活主界面
SHOW_MAIN_MESSAGE = "show-main"
STORE_MESSAGE_PREFIX = "show-store:"


class SingleInstanceServer(QObject):
    """主实例的本地套接字服务端：收到 show-main 时通知主窗口激活。"""

    showMainRequested = Signal()
    showStoreRequested = Signal(str)  # v0.18：show-store:<theme|plugin>
    messageReceived = Signal(str)

    def __init__(self, name: str = SINGLE_INSTANCE_NAME, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._name = str(name or SINGLE_INSTANCE_NAME)
        self._sockets: list[QLocalSocket] = []
        #: 单实例锁（QLockFile 被回收会自动解锁，由服务端持有到进程退出）
        self._instance_lock: QLockFile | None = None
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._accept_connections)

    @property
    def name(self) -> str:
        return self._name

    @property
    def listening(self) -> bool:
        return bool(self._server.isListening())

    def start(self) -> bool:
        """开始监听；同名服务端已存在说明已有主实例，返回 False。"""
        if self._server.isListening():
            return True
        if self._server.listen(self._name):
            return True
        # 异常退出可能留下同名服务端文件：清理后再试一次（调用方此时已持有单实例锁）
        try:
            QLocalServer.removeServer(self._name)
        except Exception:  # noqa: BLE001
            pass
        return bool(self._server.listen(self._name))

    def stop(self) -> None:
        for socket in list(self._sockets):
            try:
                socket.abort()
            except (RuntimeError, AttributeError):
                pass
        self._sockets.clear()
        self._server.close()
        # 释放单实例锁（进程退出时也会自动解锁，这里让测试/重启可以立刻再次启动）
        if self._instance_lock is not None:
            try:
                self._instance_lock.unlock()
            except (RuntimeError, AttributeError):
                pass
            self._instance_lock = None

    def errorString(self) -> str:
        try:
            return str(self._server.errorString())
        except Exception:  # noqa: BLE001
            return ""

    def _accept_connections(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                break
            self._sockets.append(socket)
            socket.readyRead.connect(lambda sock=socket: self._read_socket(sock))
            socket.disconnected.connect(lambda sock=socket: self._drop_socket(sock))

    def _read_socket(self, socket: QLocalSocket) -> None:
        try:
            payload = bytes(socket.readAll())
        except (RuntimeError, AttributeError):
            return
        if not payload:
            return
        text = payload.decode("utf-8", errors="replace")
        for line in text.splitlines():
            message = line.strip()
            if not message:
                continue
            self.messageReceived.emit(message)
            if message == SHOW_MAIN_MESSAGE:
                self.showMainRequested.emit()
            elif message.startswith(STORE_MESSAGE_PREFIX):
                self.showStoreRequested.emit(message[len(STORE_MESSAGE_PREFIX) :].strip())

    def _drop_socket(self, socket: QLocalSocket) -> None:
        # socket 是 QLocalServer 的子对象，随服务端一起销毁；这里只丢掉 Python 引用
        if socket in self._sockets:
            self._sockets.remove(socket)


def _send_single_instance_message(
    message: str = SHOW_MAIN_MESSAGE,
    name: str = SINGLE_INSTANCE_NAME,
    timeout_ms: int = 400,
) -> bool:
    """连上已有主实例并发送一条消息；没有主实例/连接失败时返回 False。"""
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(max(1, int(timeout_ms))):
        return False
    try:
        socket.write(str(message).encode("utf-8"))
        socket.flush()
        if not socket.waitForBytesWritten(max(1, int(timeout_ms))):
            # 同进程/无事件循环（单元测试）时写事件要靠事件循环派发，否则数据会随对象回收丢失
            for _ in range(3):
                QCoreApplication.processEvents()
                time.sleep(0.005)
            socket.waitForBytesWritten(max(1, int(timeout_ms)))
    except (RuntimeError, AttributeError, OSError):
        return False
    finally:
        try:
            socket.disconnectFromServer()
        except (RuntimeError, AttributeError):
            pass
    return True


def _notify_existing_instance(
    name: str = SINGLE_INSTANCE_NAME, timeout_ms: int = 400, message: str = SHOW_MAIN_MESSAGE
) -> bool:
    """第二个实例：让已有主实例激活主界面（发送 show-main / show-store:<kind>）。"""
    return _send_single_instance_message(message, name, timeout_ms)


def _single_instance_enabled(args) -> bool:  # noqa: ANN001
    """冒烟模式禁用单实例逻辑，避免测试/截图进程互相抢占。"""
    return not bool(getattr(args, "smoke", False))


def _single_instance_lock(
    retries: int = 12,
    interval_ms: int = 400,
    restarted: bool = False,
    notify: Callable[[], bool] | None = None,
) -> QLockFile | None:
    """拿单实例锁；提权重启时旧进程还在退出，所以重试几秒。

    --restarted 表示本进程由看门狗拉起，旧进程是被强杀的，锁文件大概率已失效：
    首次失败时主动清理一次陈旧锁，避免保活变成「反复拉起又退出」。
    v0.17：等待期间顺带尝试连接已有主实例（notify 返回 True 时立即结束等待）。
    """
    lock = QLockFile(str(app_data_dir() / "shenqing.lock"))
    lock.setStaleLockTime(0)
    for attempt in range(max(1, retries)):
        if lock.tryLock(100):
            return lock
        if notify is not None:
            try:
                if notify():
                    return None
            except Exception:  # noqa: BLE001 - 通知失败不能影响拿锁
                pass
        if restarted and attempt == 0:
            try:
                lock.removeStaleLockFile()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(interval_ms / 1000.0)
    return None


def acquire_single_instance(
    args,  # noqa: ANN001
    name: str = SINGLE_INSTANCE_NAME,
) -> tuple[bool, SingleInstanceServer | None]:
    """v0.17 单实例入口：已有主实例时通知它 show-main，并返回「不要启动第二窗口」。

    返回值 (should_start, server)：
    - (False, None)：已有主实例（已请求它激活主界面），调用方应立即返回 0；
    - (True, None)：冒烟模式，单实例逻辑禁用；
    - (True, server)：本进程就是主实例，server 由调用方持有并连接 showMainRequested。
    """
    if not _single_instance_enabled(args):
        return True, None

    restarted = bool(getattr(args, "restarted", False))
    notified = {"value": False}

    store_kind = str(getattr(args, "store", "") or "")
    message = f"{STORE_MESSAGE_PREFIX}{store_kind}" if store_kind else SHOW_MAIN_MESSAGE

    def _notify() -> bool:
        if _notify_existing_instance(name, message=message):
            notified["value"] = True
            return True
        return False

    if not restarted and _notify():
        print("深清已经在运行了，已激活主界面", file=sys.stderr)
        return False, None
    lock = _single_instance_lock(restarted=restarted, notify=None if restarted else _notify)
    if lock is None:
        if notified["value"]:
            print("深清已经在运行了，已激活主界面", file=sys.stderr)
        else:
            print("深清已经在运行了（单实例模式）", file=sys.stderr)
        return False, None

    server = SingleInstanceServer(name)
    if not server.start():
        print(f"单实例服务端启动失败：{server.errorString()}", file=sys.stderr)
        return True, None
    # QLockFile 一旦被回收就会自动解锁，必须由主实例服务端持有到进程退出
    server._instance_lock = lock  # type: ignore[attr-defined]
    return True, server


def _window_state_value(state) -> int:  # noqa: ANN001
    """把 Qt.WindowState 枚举/标志位转成 int（PySide6 的枚举实例不能直接 int()）。"""
    raw = getattr(state, "value", state)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _raise_window(root) -> None:  # noqa: ANN001
    """尽力把窗口提到最前（QWindow 用 raise/requestActivate，QWidget 用 activateWindow）。"""
    for name in ("raise_", "raise", "activateWindow", "requestActivate"):
        method = getattr(root, name, None)
        if not callable(method):
            continue
        try:
            method()
        except (RuntimeError, TypeError, AttributeError):
            pass


def _open_store_page(window, kind: str) -> bool:  # noqa: ANN001
    """v0.18：打开商店页（kind: theme / plugin）。"""
    root = getattr(window, "root_window", None) if window is not None else None
    if root is None:
        return False
    kind = str(kind or "").strip()
    if kind not in ("theme", "plugin"):
        return False
    try:
        _show_window(window)
    except (RuntimeError, AttributeError, TypeError):
        pass
    try:
        from PySide6.QtCore import Q_ARG, QMetaObject, Qt

        QMetaObject.invokeMethod(
            root,
            "openStorePage",
            Qt.ConnectionType.DirectConnection,
            Q_ARG("QVariant", kind),
        )
        return True
    except (RuntimeError, AttributeError, TypeError) as exc:  # noqa: BLE001
        logging.warning("打开商店页失败：%s", exc)
        return False


def _activate_main_window(window, bridge=None) -> str:  # noqa: ANN001
    """第二个实例请求 show-main 时激活主界面。

    返回 "activated" / "locked" / "onboarding" / "none"，方便单测断言。
    专注锁定或首次引导进行中只做置顶提示，不打断当前流程（不 show 主窗口）。
    """
    root = getattr(window, "root_window", None) if window is not None else None
    if root is None:
        return "none"
    locked = False
    onboarding = False
    if bridge is not None:
        try:
            locked = bool(bridge.busy)
        except (RuntimeError, AttributeError, TypeError):
            locked = False
        try:
            onboarding = bool(getattr(bridge, "needsOnboarding", False))
        except (RuntimeError, AttributeError, TypeError):
            onboarding = False
    if locked or onboarding:
        _raise_window(root)
        if locked:
            message = QCoreApplication.translate(
                "ShenQing", "深清正在专注中，结束后自动恢复主界面"
            )
        else:
            message = QCoreApplication.translate(
                "ShenQing", "首次使用引导进行中，请先完成引导"
            )
        toast = getattr(bridge, "toast", None)
        if toast is not None:
            try:
                toast.emit(message)
            except (RuntimeError, AttributeError, TypeError):
                pass
        return "locked" if locked else "onboarding"

    state = None
    try:
        state = root.windowState()
    except (RuntimeError, AttributeError, TypeError):
        state = None
    minimized = False
    if state is not None:
        minimized = bool(_window_state_value(state) & _window_state_value(Qt.WindowState.WindowMinimized))
    try:
        if minimized:
            root.showNormal()
        else:
            root.show()
    except (RuntimeError, AttributeError, TypeError):
        pass
    if state is not None:
        try:
            # 取消最小化（WindowActive 由系统设置，这里只清掉最小化位）
            root.setWindowState(state & ~Qt.WindowState.WindowMinimized)
        except (RuntimeError, AttributeError, TypeError):
            pass
    _raise_window(root)
    return "activated"


def _install_crash_safety() -> None:
    """兜底：进程退出/未捕获异常时把任务栏恢复出来（防退出加固期间任务栏是隐藏的）。"""
    import atexit

    atexit.register(restore_taskbars)
    previous_hook = sys.excepthook

    def _excepthook(exc_type, exc, tb):  # noqa: ANN001
        try:
            restore_taskbars()
        finally:
            previous_hook(exc_type, exc, tb)

    sys.excepthook = _excepthook


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 GBK，RinUI 会打印 emoji，先切到 UTF-8 避免 UnicodeEncodeError
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    logging = setup_logging()
    _install_crash_safety()
    args, qt_args = _parse_args(list(sys.argv if argv is None else argv))

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(f"{APP_NAME}（{APP_ALIAS}）")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_ID)
    # 关窗只收托盘，不退出后台
    app.setQuitOnLastWindowClosed(False)

    icon = app_icon_path()
    if icon is not None:
        app.setWindowIcon(QIcon(str(icon)))

    qInstallMessageHandler(_message_handler)

    # v0.17：单实例 —— 第二个实例连主实例的本地套接字发送 show-main 后立即以 0 退出，
    # 主实例收到后激活主界面；--restarted（重启自己）不复用这条「已有实例」路径。
    pending_show_main = {"value": False}
    main_window: dict[str, object] = {"window": None, "bridge": None}

    pending_store = {"value": ""}

    def _request_show_main() -> None:
        if main_window["window"] is None:
            pending_show_main["value"] = True
            return
        _activate_main_window(main_window["window"], main_window["bridge"])

    def _request_show_store(kind: str) -> None:
        if main_window["window"] is None:
            pending_store["value"] = str(kind or "")
            return
        _open_store_page(main_window["window"], str(kind or ""))

    should_start, instance_server = acquire_single_instance(args)
    if not should_start:
        return 0
    if instance_server is not None:
        instance_server.showMainRequested.connect(_request_show_main)
        instance_server.showStoreRequested.connect(_request_show_store)
        app.aboutToQuit.connect(instance_server.stop)

    settings = Settings()
    if args.smoke:
        os.environ.setdefault("SHENQING_NO_SCAN", "1")
    else:
        _apply_first_run_defaults(settings)

    # 管理员模式：以最高权限启动（UAC 确认一次），失败则按普通权限继续
    if bool(settings.get("admin_mode", False)) and not elevation.is_admin() and not args.smoke:
        logging.info("管理员模式已开启，正在以管理员身份重启…")
        if elevation.relaunch_as_admin():
            return 0

    # 翻译必须在加载 QML 之前装好（QML 里的 qsTr 在加载时求值）
    # 联网时间校准：后台线程，失败不影响启动（已缓存偏移兜底）
    timesync.load_cache()
    if not args.smoke:
        threading.Thread(target=timesync.sync_now, name="shenqing-timesync", daemon=True).start()

    translator = Translator(app, str(settings.get("language", "auto")))
    bridge = AppBridge(translator=translator)
    window = RinUIWindow()  # 先建引擎，绑定上下文对象后再加载 QML
    window.engine.rootContext().setContextProperty("App", bridge)

    theme_mode = str(settings.get("theme_mode", "solid"))
    if args.theme:
        theme_name = args.theme
    elif theme_mode.startswith(CUSTOM_THEME_PREFIX):
        # v0.18：自定义主题按 palette 亮度决定窗口 chrome，浅色主题也能配对
        custom = store.normalize_custom_themes(settings.get("custom_themes", {}))
        custom_item = custom.get(theme_mode[len(CUSTOM_THEME_PREFIX) :])
        is_light = bool(custom_item and store.palette_is_light(custom_item["palette"]))
        theme_name = "Light" if is_light else "Dark"
    else:
        theme_name = "Light" if theme_mode == "light" else "Dark"
    try:
        window.setTheme(Theme(theme_name))
    except (ValueError, KeyError):
        logging.warning("未知主题：%s", theme_name)

    try:
        window.load(qml_file("Main.qml"))
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"界面加载失败：{exc}", file=sys.stderr)
        if _QML_PROBLEMS:
            for problem in _QML_PROBLEMS[-5:]:
                print(f"  {problem}", file=sys.stderr)
        return 2

    bridge.themeChanged.connect(lambda name: window.setTheme(Theme(name)))

    # v0.16 onboarding test marker
    bridge.onboardingFinished.connect(lambda: _show_window(window))
    if not args.smoke and not bool(settings.get("onboarding_done", False)):
        _hide_window(window)

    # v0.17：窗口就绪；若启动期间第二个实例已经发来 show-main，补一次激活
    main_window["window"] = window
    main_window["bridge"] = bridge
    if pending_show_main["value"]:
        pending_show_main["value"] = False
        _activate_main_window(window, bridge)
    initial_store = pending_store["value"] or str(getattr(args, "store", "") or "")
    if initial_store:
        pending_store["value"] = ""
        QTimer.singleShot(700, lambda kind=initial_store: _open_store_page(window, kind))

    tray: TrayController | None = None
    quick_panel: QuickPanelController | None = None

    def _retranslate(locale: str) -> None:
        engine = window.engine
        try:
            retranslate = getattr(engine, "retranslate", None)
            if callable(retranslate):
                retranslate()
        except Exception as exc:  # noqa: BLE001
            logging.warning("QML 重译失败：%s", exc)
        if tray is not None:
            tray.set_tooltip_text(APP_NAME)

    bridge.languageChanged.connect(_retranslate)

    def hide_panel() -> None:
        if quick_panel is not None:
            quick_panel.hide()

    def open_quick_panel() -> None:
        """托盘右键：每次都要打开/重新定位；实在失败回退到系统托盘菜单。"""
        ok = quick_panel.toggle() if quick_panel is not None else False
        if not ok and tray is not None:
            tray.show_menu()

    if not args.smoke:
        tray = TrayController(app)
        quick_panel = QuickPanelController(window, tray, parent=app)
        tray.showRequested.connect(lambda: _show_window(window))
        tray.startRequested.connect(lambda: bridge.startLevel(bridge.lockLevel))
        tray.quickPanelRequested.connect(open_quick_panel)
        tray.quitRequested.connect(app.quit)
        tray.show()
        # 速启面板里的「打开主界面 / 设置 / 退出」按钮
        bridge.showMainRequested.connect(lambda: (_show_window(window), hide_panel()))
        bridge.settingsRequested.connect(
            lambda: (_show_window(window), _goto_settings(window), hide_panel())
        )
        bridge.quitRequested.connect(app.quit)
        bridge.toast.connect(lambda text: tray.message(APP_NAME, text))
        # 速启面板里点空间/档位 → 打开主界面并切到空间页（不直接开始专注）
        bridge.spacesPageRequested.connect(
            lambda mode: (_show_window(window), _goto_spaces(window, mode), hide_panel())
        )
        # 开始专注后自动收起速启面板
        bridge.stateChanged.connect(
            lambda: quick_panel is not None and bridge.busy and quick_panel.hide()
        )

    if not args.smoke:
        # v0.15：先清理上次崩溃残留的 hosts 屏蔽段，再恢复专注
        try:
            bridge.cleanup_stale_site_block()
        except Exception as exc:  # noqa: BLE001
            logging.warning("清理残留网站屏蔽失败：%s", exc)
        # v0.14：有未完成的专注先恢复（重新锁定/补记统计），再起看门狗
        try:
            if bridge.restore_session_if_needed():
                logging.info("已恢复未完成的专注会话")
        except Exception as exc:  # noqa: BLE001 - 恢复失败不能阻止启动
            logging.warning("恢复未完成专注失败：%s", exc)
        # 保活：写 keeper.json 并起独立看门狗；正常退出时结束看门狗
        if keeper.start_keeper():
            logging.info("保活看门狗已启动")
        else:
            logging.info("保活看门狗未启动")
        app.aboutToQuit.connect(keeper.stop_keeper)
        # 覆清 dock：白名单应用启动后要显示在 always-on-top 遮罩之上（不退出专注）
        dock_reveal = setup_dock_reveal(app, bridge)
        logging.info("覆清 dock 显示控制器已就绪：%s", dock_reveal is not None)
        # 首次运行提示：默认最高权限 + 最高权限自启
        if settings.get("elevated_bootstrap"):
            _bootstrap_elevated(settings, bridge)
        # 自动更新：启动 6 秒后检查一次 GitHub Releases（auto_update 可关）
        if bool(settings.get("auto_update", True)):
            QTimer.singleShot(6000, bridge.checkUpdate)

    if args.smoke:
        QTimer.singleShot(3000, lambda: _smoke_finish(app, window))
    else:
        logging.info("深清启动完成，数据目录：%s", app_data_dir())

    app.aboutToQuit.connect(bridge.overlayClosed)
    app.aboutToQuit.connect(power.allow_sleep)

    code = app.exec()
    return int(code) if not args.smoke else (1 if _QML_PROBLEMS else 0)


def _goto_settings(window: RinUIWindow) -> None:
    """切到设置页（新版导航：空间/数据/插件/设置 → 设置是第 4 项，navIndex = 3）。"""
    root = window.root_window
    if root is not None:
        root.setProperty("navIndex", 3)


def _goto_spaces(window: RinUIWindow, mode: str = "") -> None:
    """速启面板点空间/档位：打开主界面并切到空间页对应标签。"""
    root = window.root_window
    if root is None:
        return
    try:
        from PySide6.QtCore import Q_ARG, QMetaObject, Qt

        item = {"kind": "space", "payload": {"mode": str(mode or "")}}
        QMetaObject.invokeMethod(
            root,
            "handleSearchResult",
            Qt.ConnectionType.DirectConnection,
            Q_ARG("QVariant", item),
        )
    except Exception as exc:  # noqa: BLE001 - QML 接口缺失时退化为只切页
        print(f"跳转空间页失败：{exc}", file=sys.stderr)
    try:
        root.setProperty("navIndex", 0)
        root.setProperty("pendingSpaceMode", str(mode or ""))
    except (RuntimeError, TypeError):
        pass


def _show_window(window: RinUIWindow) -> None:
    root = window.root_window
    if root is None:
        return
    root.show()
    root.requestActivate()


def _hide_window(window: RinUIWindow) -> None:
    """v0.16 首次使用引导期间隐藏主窗口（引导是独立的 QML 全屏窗口）。"""
    root = window.root_window
    if root is None:
        return
    try:
        root.hide()
    except (RuntimeError, TypeError):
        pass


def setup_dock_reveal(app: QApplication, bridge: AppBridge) -> DockRevealController:
    """把「覆清 dock 应用显示到遮罩之上」的控制器接到桥上（lifecycle 挂在 app 下）。"""
    controller = DockRevealController(bridge, parent=app)
    bridge.appLaunched.connect(controller.handle_app_launched)
    bridge.stateChanged.connect(controller.sync_session)
    bridge.lockedChanged.connect(controller.sync_session)
    app.aboutToQuit.connect(controller.restore)
    return controller


def _apply_first_run_defaults(settings: Settings) -> bool:
    """v0.6：首次运行默认以最高权限运行，并标记待登记最高权限自启。

    返回是否首次运行。提权与登记计划任务都在主流程里做（失败静默）。
    """
    if not getattr(settings, "is_new", False):
        return False
    settings.set("admin_mode", True)
    settings.set("elevated_bootstrap", True)
    return True


def _bootstrap_elevated(settings: Settings, bridge: AppBridge) -> None:
    """首次运行：登记最高权限开机自启（失败静默），并 toast 说明默认最高权限。"""
    ok = False
    message = ""
    try:
        ok, message = elevation.set_elevated_autostart(True)
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
    settings.set("elevated_bootstrap", False)
    if not ok:
        # 这里不在 main() 里，不能复用它的局部 logger，按需取配置好的 logger
        setup_logging().warning("最高权限自启登记失败（静默）：%s", message)
    admin = elevation.is_admin()
    if admin and ok:
        text = QCoreApplication.translate(
            "ShenQing", "已默认以最高权限运行，并开启最高权限开机自启"
        )
    elif admin:
        text = QCoreApplication.translate(
            "ShenQing", "已默认以最高权限运行（最高权限自启登记失败，可在设置里重试）"
        )
    elif ok:
        text = QCoreApplication.translate(
            "ShenQing", "已默认开启管理员模式，并登记最高权限开机自启"
        )
    else:
        text = QCoreApplication.translate(
            "ShenQing", "已默认开启管理员模式（下次启动会请求提权）"
        )
    bridge.toast.emit(text)


_SMOKE_PAGES = (
    "pages/SpacesPage.qml",
    "pages/WhitelistPage.qml",
    "pages/PluginsPage.qml",
    "pages/ThemesPage.qml",
    "pages/StatsPage.qml",
    "pages/SettingsPage.qml",
)


def _instantiate_pages(window: RinUIWindow) -> None:
    """逐页实例化，确保导航里每个页面在没有点击时也不是坏的。"""
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent

    qml_root = qml_dir()
    for relative in _SMOKE_PAGES:
        path = qml_root / relative
        component = QQmlComponent(window.engine, QUrl.fromLocalFile(str(path)))
        instance = component.create()
        if component.isError():
            message = component.errorString()
            _QML_PROBLEMS.append(f"{relative}: {message}")
            print(f"[smoke] {relative} 加载失败：{message}", file=sys.stderr)
        elif instance is not None:
            instance.deleteLater()
        else:
            print(f"[smoke] {relative} 未创建实例", file=sys.stderr)


def _smoke_finish(app: QApplication, window: RinUIWindow) -> None:
    """离屏冒烟：逐页实例化 + 抓一张窗口截图（失败不致命），然后退出。"""
    global _SMOKE_DONE
    _instantiate_pages(window)
    root = window.root_window
    if root is not None:
        try:
            image = root.grabWindow()
            out_dir = Path.cwd() / "build"
            out_dir.mkdir(parents=True, exist_ok=True)
            image.save(str(out_dir / "smoke.png"))
            print(f"[smoke] 截图已保存：{out_dir / 'smoke.png'}", file=sys.stderr)
        except (RuntimeError, AttributeError) as exc:  # pragma: no cover
            print(f"[smoke] 截图失败：{exc}", file=sys.stderr)
    for problem in _QML_PROBLEMS:
        print(f"[smoke] 问题：{problem}", file=sys.stderr)
    print(f"[smoke] QML 问题数：{len(_QML_PROBLEMS)}", file=sys.stderr)
    _SMOKE_DONE = True
    app.quit()
