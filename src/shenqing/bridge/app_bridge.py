"""暴露给 QML 的应用桥（上下文对象名：App）。

v0.2：数据模型改为「空间（Space）」，会话围绕空间展开：
开始某空间 → 守卫按「全局黑名单 + 空间白名单」工作 → 结束写统计并通知插件。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    Property,
    QObject,
    QRunnable,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
    Slot,
)

from ..consts import (
    APP_ALIAS,
    CHANGELOG,
    APP_NAME,
    APP_VERSION,
    ATMOSPHERES,
    CUSTOM_THEME_PREFIX,
    DEFAULT_THEME_SCHEME,
    DEFAULT_THEME_STYLE,
    FEEDBACK_URLS,
    MAX_FONT_FAMILIES,
    MAX_MINUTES,
    MIN_MINUTES,
    MODE_LABELS,
    PREFERRED_CJK_FONTS,
    PRESET_MINUTES,
    QUOTES,
    SPACE_MAX_MINUTES,
    SPACE_MIN_MINUTES,
    SPACE_MINUTE_STEP,
    THEME_SCHEMES,
    THEME_STYLES,
    THEMES,
    TRIAL_MINUTES,
    LockLevel,
)
from ..core.app_catalog import load_cached, load_catalog
from ..core.blocklist import Blocklist
from ..core.guard import ProcessGuard
from ..core.session import SessionController, SessionState
from ..core.spaces import SpaceManager
from ..core.stats import StatsStore
from ..services import elevation, power, store, timesync, updater, webadmin
from ..services import ai as ai_service
from ..services import ai_actions as ai_actions_service
from ..services import app_usage
from ..services import backup as backup_service
from ..services import click_counter
from ..services import cloud_sync as cloud_sync_service
from ..services import overlay_widgets as overlay_widgets_service
from ..services import pomodoro as pomodoro_service
from ..services import desktop_icons, site_blocker
from ..services import sleep_mode, system_control, wallpaper
from ..services import theme as theme_service
from ..services.autostart import AutostartManager
from ..services.lock_hardening import LockHardening
from ..services.media_smtc import MediaSmtcService
from ..services.notifications import NotificationService
from ..paths import app_data_dir, license_file, notice_file
from ..settings import Settings

logger = logging.getLogger("shenqing.bridge")

#: v0.16：连点时间显示退出的判定窗口（秒）与次数
TIME_CLICK_WINDOW_SECONDS = 6.0
TIME_CLICK_LIMIT = 10

try:  # 插件系统由独立模块提供，缺失时降级为空实现
    from ..plugins.manager import PluginManager
except Exception:  # noqa: BLE001 - 插件模块可能尚未就绪
    PluginManager = None  # type: ignore[assignment,misc]


class _CatalogScan(QRunnable):
    """后台线程扫描本机应用清单，完成后通过信号回主线程。"""

    def __init__(self, bridge: "AppBridge") -> None:
        super().__init__()
        self._bridge = bridge

    def run(self) -> None:  # noqa: D401 - QRunnable 接口
        try:
            items = load_catalog(force=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("扫描应用清单失败：%s", exc)
            items = []
        try:
            self._bridge._catalogScanned.emit(items)
        except RuntimeError:  # 宿主已销毁
            pass


class _CloudTask(QRunnable):
    """账户同步后台任务：联网 / 写文件都在线程池里跑，结果通过信号回主线程。"""

    def __init__(self, bridge: "AppBridge", kind: str, job) -> None:  # noqa: ANN001
        super().__init__()
        self._bridge = bridge
        self._kind = str(kind)
        self._job = job

    def run(self) -> None:  # noqa: D401 - QRunnable 接口
        try:
            result = self._job()
        except Exception as exc:  # noqa: BLE001 - 后台任务不能把异常抛给线程池
            logger.warning("账户同步任务异常：%s", exc)
            result = {"ok": False, "error": str(exc) or "同步失败"}
        if not isinstance(result, dict):
            result = {"ok": False, "error": "同步失败"}
        try:
            self._bridge._cloudTaskResult.emit(self._kind, result)
        except RuntimeError:  # 宿主已销毁
            pass


class _WidgetDataTask(QRunnable):
    """v0.21 右侧组件数据：后台拉天气 + 每日一言，结果通过信号回主线程。

    网络与缓存（15 分钟 / 当天）都在 services.overlay_widgets 里，这里只负责切线程，
    避免 QML 首帧被 DNS / HTTPS 拖住。
    """

    def __init__(self, bridge: "AppBridge", city_id: str, quote_category: str) -> None:
        super().__init__()
        self._bridge = bridge
        self._city_id = str(city_id or "")
        self._quote_category = str(quote_category or "")

    def run(self) -> None:  # noqa: D401 - QRunnable 接口
        weather: dict = {}
        quote: dict = {}
        try:
            weather = overlay_widgets_service.fetch_weather(self._city_id)
        except Exception as exc:  # noqa: BLE001 - 后台任务不能把异常抛给线程池
            logger.warning("刷新天气组件失败：%s", exc)
            weather = {"ok": False, "error": f"天气获取失败：{exc}"}
        try:
            quote = overlay_widgets_service.fetch_quote(category=self._quote_category)
        except Exception as exc:  # noqa: BLE001
            logger.warning("刷新每日一言失败：%s", exc)
            quote = {}
        try:
            self._bridge._widgetDataReady.emit({"weather": weather, "quote": quote})
        except RuntimeError:  # 宿主已销毁
            pass


def _path_to_url(path: object) -> str:
    if not path:
        return ""
    try:
        return Path(str(path)).as_uri()
    except Exception:  # noqa: BLE001
        return str(path)


class AppBridge(QObject):
    """QML 只能看到这个对象：属性负责状态，Slot 负责动作。"""

    spacesChanged = Signal()
    stateChanged = Signal()
    tickChanged = Signal()
    statsChanged = Signal()
    catalogChanged = Signal()
    pluginsChanged = Signal()
    lockedChanged = Signal()
    settingsChanged = Signal()
    themeChanged = Signal(str)
    toast = Signal(str)
    guardEvent = Signal(str)
    #: v0.6：从覆清 dock 启动白名单应用成功（携带 exe 名/路径），供主程序把应用窗口提到遮罩之上
    appLaunched = Signal(str)
    mediaChanged = Signal()
    showMainRequested = Signal()
    spacesPageRequested = Signal(str)
    settingsRequested = Signal()
    quitRequested = Signal()
    wallpaperChanged = Signal()
    sleepChanged = Signal()
    appUsageChanged = Signal()
    aiChanged = Signal()
    aiModelsChanged = Signal()
    aiChatsChanged = Signal()
    aiUsageChanged = Signal()
    backupChanged = Signal()
    languageChanged = Signal(str)
    _catalogScanned = Signal(list)
    #: 自动更新：后台线程 → 主线程
    _updateChecked = Signal(object, str)
    _updateProgress = Signal(int)
    _updateDownloaded = Signal(bool, str)
    #: v0.9 AI：线程池回调 → 主线程（token 防止旧回答覆盖新问题）
    _aiAsyncResult = Signal(int, object)
    #: v0.10 模型列表拉取结果：provider, models, error
    _aiModelsFetched = Signal(str, object, str)
    #: v0.21 AI 动作（待确认动作 / 执行结果 / 日志）变化
    aiActionChanged = Signal()
    #: v0.21 开始专注二次确认：待确认信息变化
    confirmationChanged = Signal()
    #: v0.21 AI 请求跳页：spaces|stats|ai|plugins|themes|settings|update|about|store
    pageRequested = Signal(str)

    #: v0.16 连点 10 次时间显示 → 请求显示退出警告（QML 弹确认框）
    exitWarningRequested = Signal()
    #: v0.16 首次使用引导完成（主窗口可以显示了）
    onboardingFinished = Signal()
    #: v0.16 清番番茄钟状态变化
    pomodoroChanged = Signal()
    #: v0.18 宿主请求打开商店页（theme/plugin）
    storePageRequested = Signal(str)
    #: v0.18 自定义主题包（商店安装）列表变化
    customThemesChanged = Signal()
    #: v0.18 商店目录 / 状态变化
    storeChanged = Signal()
    #: v0.18 某个 item 的评论变化（携带 item id）
    storeCommentsChanged = Signal(str)
    #: v0.19 网页管理状态变化（开关 / 地址 / 错误）
    webAdminChanged = Signal()
    #: v0.20 账户同步状态变化（登录态 / 地址 / 状态 / 上次同步时间 / 错误）
    cloudChanged = Signal()
    #: v0.20 账户同步后台任务完成：任务名 + 结果字典（QThreadPool → 主线程）
    _cloudTaskResult = Signal(str, object)
    #: v0.21 右侧组件：布局 / 总开关变化（overlayWidgets、overlayWidgetsEnabled 的 notify）
    overlayWidgetsChanged = Signal()
    #: v0.21 右侧组件数据变化（天气 / 每日一言）
    widgetDataChanged = Signal()
    #: v0.21 组件数据后台任务完成：{"weather": {...}, "quote": {...}}（QThreadPool → 主线程）
    _widgetDataReady = Signal(object)

    def __init__(
        self,
        parent: QObject | None = None,
        translator: object | None = None,
    ) -> None:
        super().__init__(parent)
        self._translator = translator
        self._settings = Settings()
        self._stats = StatsStore()
        self._blocklist = Blocklist()
        self._spaces = SpaceManager()
        self._guard = ProcessGuard(self)
        self._session = SessionController(self)
        self._autostart = AutostartManager()
        self._hardening = LockHardening(self)
        self._active_space_id = ""
        self._session_level = ""
        self._session_started_at = timesync.now()
        self._trial_active = False
        self._trial_times: list[float] = []
        self._preview_active = False
        self._preview_level = ""
        # 进入前的 10 秒倒计时（水滴凝聚）
        self._prepare_active = False
        self._prepare_remaining = 0
        self._prepare_space_id = ""
        self._prepare_mode = ""
        self._prepare_minutes: int | None = None
        self._prepare_timer = QTimer(self)
        self._prepare_timer.setInterval(1000)
        self._prepare_timer.timeout.connect(self._tick_prepare)
        # 自动更新状态（idle/checking/available/downloading/ready/error）
        self._update_state = "idle"
        self._update_info: dict | None = None
        self._update_progress = 0
        self._update_error = ""
        self._update_download_path: Path | None = None
        self._update_cancel: updater.CancelToken | None = None
        # v0.16：更新源错误（可读文案，QML 展示）
        self._update_source_error = ""
        # v0.8：睡眠模式 / 系统控制 / 壁纸 / AI 骨架
        self._sleep = sleep_mode.SleepManager()
        self._ai = ai_service.AIService(self._settings)
        # v0.9 AI 异步状态
        self._ai_state = "idle"
        self._ai_answer = ""
        self._ai_error = ""
        self._ai_token = 0
        self._ai_mode = ""
        # v0.10：当前服务商模型列表（fetch /models）
        self._ai_models: list[str] = []
        self._ai_models_state = "idle"
        self._ai_models_error = ""
        # v0.11：费用用量 + 对话历史
        self._ai_chats_path = app_data_dir() / "ai_chats.json"
        self._ai_usage_path = app_data_dir() / "ai_usage.json"
        self._ai_chats: dict = {"currentId": "", "conversations": []}
        self._ai_usage: dict = {}
        self._ai_last_usage: dict = {}
        self._ai_usage_currency = ""
        self._ai_pending_conv = ""
        self._load_ai_chats()
        self._load_ai_usage()
        # v0.21 AI 动作：解析回复里的动作块后执行（start_space 先挂 pending）
        self._ai_action_pending: dict = {}
        self._ai_action_result: dict = {}
        self._ai_action_log: list[dict] = []
        # v0.21 开始专注二次确认：待确认的开局信息（空 dict = 无）
        self._start_pending: dict = {}
        # v0.21 AI 请求打开的页面（QML 绑定）
        self._last_requested_page = ""
        # v0.9 应用使用时长统计（前台应用 5s 采样）
        self._app_usage = app_usage.AppUsageTracker(
            now_provider=timesync.now, parent=self
        )
        self._app_usage_date = ""
        self._app_usage_hourly_range = "today"
        # v0.14 备份/恢复
        self._backup_busy = False
        self._last_backup_path = ""
        self._last_backup_error = ""
        # v0.14 专注恢复 + 点击计数
        self._session_state_path = app_data_dir() / "session_state.json"
        self._session_clicks = 0
        self._last_session_clicks = 0
        self._click_counter = click_counter.ClickCounter(self)
        self._click_counter.changed.connect(self._on_click_count_changed)
        # v0.15 网站屏蔽 / 结束卡片背景
        self._site_blocker = site_blocker.HostsSiteBlocker()
        self._site_block_applied = False
        #: v0.22：浅清/覆清期间隐藏桌面图标
        self._desktop_icons_hidden = False
        self._volume = -1
        # v0.17：系统音量定时刷新（用户在系统里改音量时，遮罩/面板的滑杆能跟上）
        self._volume_timer = QTimer(self)
        self._volume_timer.setInterval(2000)
        self._volume_timer.timeout.connect(self._refresh_system_volume)
        self._volume_timer.start()
        self._sleep_lock_active = False
        self._clock_clicks: deque[float] = deque()
        # v0.16：覆清/深清连点时间显示 10 次 → 退出警告；标记强制结束写 interrupted
        self._time_clicks: deque[float] = deque()
        self._exit_warning = False
        self._force_interrupt = False
        # v0.16 清番（置顶番茄钟）：与锁机 / guard 完全独立
        self._pomodoro = pomodoro_service.PomodoroTimer(self._settings, parent=self)
        self._pomodoro.changed.connect(self.pomodoroChanged)
        self._pomodoro.notify.connect(self._on_pomodoro_notify)
        self._bing_url = wallpaper.cached_bing_url()
        self._avatar_url = ""
        self._sleep_timer = QTimer(self)
        self._sleep_timer.setInterval(20000)
        self._sleep_timer.timeout.connect(self._tick_sleep)
        self._media_info: dict = {}
        # v0.22：当前曲目专辑封面的本地缓存路径（给灵动岛），无封面时为 ""
        self._media_art = ""
        self._catalog: list[dict] = load_cached()
        self._catalog_scanning = False
        # v0.18 商店：目录缓存 / 评论审核 / 插件安装串行保护
        self._store = store.CatalogService(self._settings)
        self._comments = store.CommentService(self._settings)
        self._store_installing = False
        self._plugins = self._init_plugins()
        if self._plugins is not None and hasattr(self._plugins, "set_notifier"):
            try:
                self._plugins.set_notifier(
                    lambda title, body: self.toast.emit(f"{title} · {body}" if title else str(body))
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("插件通知通道挂接失败：%s", exc)

        # v0.19：网页管理（浏览器里管理深清）——app.py 启动时按设置拉起
        self._web_admin = webadmin.WebAdminService(
            self._settings, self._build_web_admin_host()
        )

        # v0.20：账户同步（设置页「账户同步」卡片）——联网在 QThreadPool 里跑
        self._cloud_busy = False
        self._cloud_status = ""
        self._cloud_error = ""
        self._cloud_last_at = str(self._settings.get("cloud_sync_last_at", "") or "")
        self._cloud_device = ""

        # v0.21：右侧组件（「组件预览」自定义右半屏）——天气 / 一言在 QThreadPool 里拉
        self._widget_weather: dict = {}
        self._widget_weather_error = ""
        self._widget_quote_text = ""
        self._widget_quote_source = ""
        self._widget_quote_from = ""
        self._widget_quote_error = ""
        self._widget_refreshing = False

        self._media = MediaSmtcService(self)
        self._media.changed.connect(self._on_media_changed)
        # 冒烟/测试模式下不起 WinRT 轮询线程（离屏环境没有媒体会话，也没必要）
        if os.environ.get("SHENQING_NO_SCAN") != "1":
            self._media.start()
        self._notifications = NotificationService(parent=self)
        self._notifications.register()
        # v0.8：清理已移除的 CW2 组件插件；启动睡眠模式轮询 + 壁纸预取（测试/冒烟跳过）
        self._purge_legacy_plugins()
        if os.environ.get("SHENQING_NO_SCAN") != "1":
            self._sleep_timer.start()
            self._app_usage.start()
            threading.Thread(
                target=self._load_wallpaper_assets,
                name="shenqing-wallpaper",
                daemon=True,
            ).start()
        application = QCoreApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self._shutdown_services)

        self._catalogScanned.connect(self._apply_catalog)
        self._updateChecked.connect(self._on_update_checked)
        self._updateProgress.connect(self._on_update_progress)
        self._updateDownloaded.connect(self._on_update_downloaded)
        self._aiAsyncResult.connect(self._on_ai_result)
        self._aiModelsFetched.connect(self._on_ai_models_fetched)
        self._cloudTaskResult.connect(self._on_cloud_task_result)
        self._widgetDataReady.connect(self._on_widget_data_ready)
        self._app_usage.changed.connect(self._on_app_usage_changed)
        self._session.stateChanged.connect(self.stateChanged)
        self._session.stateChanged.connect(self.lockedChanged)
        self._session.tick.connect(self._on_tick)
        self._session.finished.connect(self._on_finished)
        self._guard.processKilled.connect(self._on_process_killed)
        # v0.21：监听系统深浅切换（scheme=auto 时重算窗口 chrome / 界面配色）
        self._install_theme_listener()

        # 没有缓存时后台补一次扫描，避免启动被 1–5 秒的扫描拖住；
        # 冒烟模式（SHENQING_NO_SCAN=1）跳过，保证离屏测试快速稳定
        if not self._catalog and os.environ.get("SHENQING_NO_SCAN") != "1":
            QTimer.singleShot(1500, self.refreshAppCatalog)

        # v0.21：启动后拉一次天气 / 每日一言（冒烟与单测跳过，避免联网拖慢）
        if os.environ.get("SHENQING_NO_SCAN") != "1":
            QTimer.singleShot(2500, self.refreshWidgetData)

    # ================= 插件 =================
    def _init_plugins(self):  # noqa: ANN202
        if PluginManager is None:
            return None
        try:
            try:
                manager = PluginManager(
                    self._settings,
                    state_listener=lambda plugin_id, state: self.pluginsChanged.emit(),
                )
            except TypeError:
                manager = PluginManager()  # type: ignore[call-arg]
            logger.info("插件系统已加载")
            return manager
        except Exception as exc:  # noqa: BLE001 - 插件系统失败不能拖垮主程序
            logger.warning("插件系统初始化失败：%s", exc)
            return None

    def _dispatch(self, event: str, *args: object) -> None:
        if self._plugins is None:
            return
        try:
            self._plugins.dispatch(event, *args)
        except Exception as exc:  # noqa: BLE001
            logger.warning("插件事件 %s 分发失败：%s", event, exc)

    @Property(str, constant=True)
    def appIconUrl(self) -> str:
        """应用图标：assets/icon.png（窗口/引导页使用）。"""
        import sys as _sys

        candidates = []
        bundled = getattr(_sys, "_MEIPASS", None)
        if bundled:
            candidates.append(Path(bundled) / "assets" / "icon.png")
        candidates.append(Path(__file__).resolve().parents[3] / "assets" / "icon.png")
        for path in candidates:
            try:
                if path.exists():
                    return path.as_uri()
            except OSError:
                continue
        return ""

    @Slot(str)
    def requestStorePage(self, kind: str) -> None:
        """v0.18：宿主（命令行/单实例消息）请求打开主题或插件商店。"""
        self.storePageRequested.emit("plugin" if str(kind) == "plugin" else "theme")

    @Property(str, constant=True)
    def controlPanelIconUrl(self) -> str:
        """速启（控制）面板使用的图标：assets/control_panel.png。"""
        import sys as _sys

        candidates = []
        bundled = getattr(_sys, "_MEIPASS", None)
        if bundled:
            candidates.append(Path(bundled) / "assets" / "control_panel.png")
        candidates.append(Path(__file__).resolve().parents[3] / "assets" / "control_panel.png")
        for path in candidates:
            try:
                if path.exists():
                    return path.as_uri()
            except OSError:
                continue
        return ""

    @Property(list, notify=pluginsChanged)
    def plugins(self) -> list[dict]:
        if self._plugins is None:
            return []
        try:
            return list(self._plugins.list_plugins())
        except Exception:  # noqa: BLE001
            return []

    @Property(list, notify=pluginsChanged)
    def pluginNavItems(self) -> list[dict]:
        """插件注册的导航入口（导航「插件」展开后的子项）。"""
        if self._plugins is None:
            return []
        getter = getattr(self._plugins, "list_nav_items", None)
        if getter is None:
            return []
        try:
            items = list(getter())
        except Exception:  # noqa: BLE001
            return []
        return [
            {
                "id": str(item.get("itemId") or item.get("id") or ""),
                "title": str(item.get("title") or ""),
                "icon": str(item.get("icon") or "grid"),
                "qmlPath": _path_to_url(item.get("qmlPath")),
                "pluginId": str(item.get("pluginId") or ""),
            }
            for item in items
        ]

    @Property(list, notify=pluginsChanged)
    def pluginWidgets(self) -> list[dict]:
        """插件注册的全屏遮罩组件。"""
        if self._plugins is None:
            return []
        getter = getattr(self._plugins, "list_widgets", None)
        if getter is None:
            return []
        try:
            widgets = list(getter())
        except Exception:  # noqa: BLE001
            return []
        return [
            {
                "id": str(item.get("itemId") or item.get("id") or ""),
                "title": str(item.get("title") or ""),
                "qmlPath": _path_to_url(item.get("qmlPath")),
                "anchor": str(item.get("anchor") or "topRight"),
                "width": int(item.get("width") or 240),
                "height": int(item.get("height") or 120),
                "pluginId": str(item.get("pluginId") or ""),
            }
            for item in widgets
        ]

    @Slot(str, bool)
    def setPluginEnabled(self, plugin_id: str, enabled: bool) -> None:
        if self._plugins is None:
            return
        try:
            self._plugins.set_enabled(plugin_id, bool(enabled))
        except Exception as exc:  # noqa: BLE001
            logger.warning("切换插件 %s 失败：%s", plugin_id, exc)
            self.toast.emit(QCoreApplication.translate("ShenQing", "插件操作失败"))
        self.pluginsChanged.emit()

    @Slot()
    def restartPlugins(self) -> None:
        if self._plugins is not None:
            try:
                self._plugins.reload()
            except Exception as exc:  # noqa: BLE001
                logger.warning("重载插件失败：%s", exc)
        self.pluginsChanged.emit()

    # ================= 空间 =================
    def _space_view(self, space: dict) -> dict:
        view = dict(space)
        mode = str(space.get("mode", ""))
        view["mode"] = mode
        view["fixedName"] = mode == "heavy"
        view["allowedCount"] = len(space.get("allowed_apps", []))
        view["atmosphereLabel"] = str(space.get("atmosphere", ""))
        for item in ATMOSPHERES:
            if item["value"] == space.get("atmosphere"):
                view["atmosphereColor"] = item["color"]
                break
        else:
            view["atmosphereColor"] = ATMOSPHERES[0]["color"]
        return view

    @Property(list, notify=spacesChanged)
    def spaces(self) -> list[dict]:
        return [self._space_view(space) for space in self._spaces.all()]

    @Property(list, notify=spacesChanged)
    def spacesLight(self) -> list[dict]:
        return [self._space_view(space) for space in self._spaces.light()]

    @Property(str, notify=spacesChanged)
    def superSpaceId(self) -> str:
        return self._spaces.super_id

    @Property(str, notify=stateChanged)
    def activeSpaceId(self) -> str:
        return self._active_space_id

    @Property(str, notify=stateChanged)
    def activeSpaceName(self) -> str:
        space = self._spaces.get(self._active_space_id)
        return str(space["name"]) if space else ""

    @Property(list, notify=stateChanged)
    def sessionWhitelist(self) -> list[str]:
        """当前专注空间的白名单（小写 exe 名）；主程序判断前台窗口是否属于 dock 白名单。"""
        space = self._spaces.get(self._active_space_id)
        if space is None:
            return []
        return [str(item).lower() for item in space.get("allowed_apps", [])]

    # ---------- v0.6 多空间 API ----------
    @Slot(str, result=str)
    def addSpaceFor(self, mode: str) -> str:
        """新增一张空间（浅清/覆清）；深清固定一张，失败返回空串。"""
        space = self._spaces.add(mode)
        if space is None:
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "深清只有一张固定空间，不能新增")
                if str(mode) == "heavy"
                else QCoreApplication.translate("ShenQing", "无法新增空间")
            )
            return ""
        self.spacesChanged.emit()
        self.toast.emit(QCoreApplication.translate("ShenQing", "已新增空间"))
        return str(space["id"])

    @Slot(str, str, result=bool)
    def deleteSpaceFor(self, mode: str, space_id: str) -> bool:
        """删除一张空间；深清 / 每档最后一张 / 专注中的空间不可删。"""
        space = self._spaces.get(space_id)
        if space is None or str(space.get("mode")) != str(mode):
            return False
        if str(mode) == "heavy":
            self.toast.emit(QCoreApplication.translate("ShenQing", "深清空间不可删除"))
            return False
        if self._busy_space(space_id):
            self.toast.emit(QCoreApplication.translate("ShenQing", "专注中不能删除当前空间"))
            return False
        if len(self._spaces.by_mode(mode)) <= 1:
            self.toast.emit(QCoreApplication.translate("ShenQing", "每档至少保留一个空间"))
            return False
        if not self._spaces.delete(space_id):
            return False
        self.spacesChanged.emit()
        return True

    def _busy_space(self, space_id: str) -> bool:
        return bool(space_id) and self._active_space_id == space_id and self.busy

    @Slot(str, str, result=bool)
    def setSpaceName(self, space_id: str, name: str) -> bool:
        if not self._spaces.set_name(space_id, name):
            space = self._spaces.get(space_id)
            if space is not None and str(space.get("mode")) == "heavy":
                self.toast.emit(QCoreApplication.translate("ShenQing", "深清空间名不可修改"))
            return False
        self.spacesChanged.emit()
        return True

    @Slot(str, int, result=bool)
    def setSpaceMinutes(self, space_id: str, minutes: int) -> bool:
        if self._spaces.set_minutes(space_id, minutes) is None:
            return False
        self.spacesChanged.emit()
        return True

    @Slot(str, str, bool, result=bool)
    def toggleSpaceAllowedApp(self, space_id: str, exe: str, enabled: bool) -> bool:
        space = self._spaces.get(space_id) or self._spaces.get_by_mode(str(space_id))
        if space is not None and str(space.get("mode")) == "heavy":
            self.toast.emit(QCoreApplication.translate("ShenQing", "深清空间不设置白名单"))
            return False
        if not self._spaces.toggle_allowed_app(space_id, exe, bool(enabled)):
            return False
        self.spacesChanged.emit()
        self.catalogChanged.emit()
        return True

    @Slot(str, list, result=bool)
    def setSpaceAllowedApps(self, space_id: str, apps: list) -> bool:
        if not self._spaces.set_allowed_apps(space_id, [str(a) for a in apps]):
            return False
        self.spacesChanged.emit()
        return True

    # ---------- 旧 QML 浮层兼容（SpaceSettingsSheet 仍可能被加载） ----------
    @Property(list, constant=True)
    def atmospheres(self) -> list[dict]:
        return ATMOSPHERES

    @Property(dict, notify=spacesChanged)
    def draftSpace(self) -> dict:
        return {}

    @Slot(str)
    def beginEditSpace(self, space_id: str) -> None:
        self.spacesChanged.emit()

    @Slot(str, str, int, str)
    def updateSpace(self, space_id: str, name: str, minutes: int, atmosphere: str) -> None:
        space = self._spaces.get(space_id)
        if space is None:
            return
        if str(space.get("mode")) != "heavy":
            self._spaces.set_name(space_id, name)
        self._spaces.set_minutes(space_id, minutes)
        self.spacesChanged.emit()

    @Slot()
    def commitEditSpace(self) -> None:
        self.spacesChanged.emit()

    @Slot()
    def cancelEditSpace(self) -> None:
        self.spacesChanged.emit()

    @Slot(str)
    def deleteSpace(self, space_id: str) -> None:
        space = self._spaces.get(space_id)
        if space is None:
            return
        self.deleteSpaceFor(str(space.get("mode")), space_id)

    # ================= 会话 =================
    @Property(str, notify=stateChanged)
    def state(self) -> str:
        return self._session.state.value

    @Property(int, notify=tickChanged)
    def remainingSeconds(self) -> int:
        return self._session.remaining

    @Property(int, notify=stateChanged)
    def totalSeconds(self) -> int:
        return self._session.total

    @Property(float, notify=tickChanged)
    def progress(self) -> float:
        total = self._session.total
        if total <= 0:
            return 0.0
        return max(0.0, min(1.0, 1.0 - self._session.remaining / total))

    @Property(str, notify=tickChanged)
    def remainingText(self) -> str:
        seconds = max(0, self._session.remaining)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    @Property(bool, notify=stateChanged)
    def busy(self) -> bool:
        return self._session.state is not SessionState.IDLE

    @Property(bool, notify=lockedChanged)
    def locked(self) -> bool:
        """v0.3：任何专注会话都进全屏遮罩（不只是超禅）。"""
        return self.busy

    @Property(str, notify=stateChanged)
    def sessionLevel(self) -> str:
        return self._session_level

    @Property(int, notify=stateChanged)
    def pauseCount(self) -> int:
        return self._session.pauses

    @Property(int, notify=stateChanged)
    def pauseLimit(self) -> int:
        return self._session.pause_limit

    @Property(bool, notify=stateChanged)
    def canPause(self) -> bool:
        """v0.16：只有浅清可以暂停；覆清 / 深清与「还清」一样没有暂停。"""
        return self._session.can_pause and self._session_level == LockLevel.LIGHT.value

    # ================= 媒体（SMTC） =================
    @Property(str, notify=mediaChanged)
    def mediaTitle(self) -> str:
        return str(self._media_info.get("title", ""))

    @Property(str, notify=mediaChanged)
    def mediaArtist(self) -> str:
        return str(self._media_info.get("artist", ""))

    @Property(str, notify=mediaChanged)
    def mediaAlbum(self) -> str:
        return str(self._media_info.get("album", ""))

    @Property(str, notify=mediaChanged)
    def mediaApp(self) -> str:
        return str(self._media_info.get("app", ""))

    @Property(bool, notify=mediaChanged)
    def mediaPlaying(self) -> bool:
        return bool(self._media_info.get("playing", False))

    @Property(float, notify=mediaChanged)
    def mediaPosition(self) -> float:
        return float(self._media_info.get("position", 0.0))

    @Property(float, notify=mediaChanged)
    def mediaDuration(self) -> float:
        return float(self._media_info.get("duration", 0.0))

    @Property(str, notify=mediaChanged)
    def mediaArt(self) -> str:
        """v0.22：当前曲目专辑封面的本地文件路径；取不到时为 ""。"""
        return self._media_art

    @Property(str, notify=mediaChanged)
    def mediaArtUrl(self) -> str:
        """v0.22：mediaArt 对应的 file:// URL，QML Image.source 直接可用；无封面为 ""。"""
        path = self._media_art
        if not path:
            return ""
        return QUrl.fromLocalFile(path).toString()

    @Property(bool, notify=mediaChanged)
    def mediaHasSession(self) -> bool:
        return bool(self._media_info.get("has", False))

    @Slot()
    def mediaToggle(self) -> None:
        self._media.toggle()

    @Slot()
    def mediaNext(self) -> None:
        self._media.next()

    @Slot()
    def mediaPrev(self) -> None:
        self._media.previous()

    def _on_media_changed(self, payload: dict) -> None:
        info = dict(payload or {})
        self._media_info = info
        # 切歌/无媒体时一起更新（清空）封面，避免灵动岛显示上一首的封面
        art = str(info.get("art", "") or "")
        self._media_art = art if info.get("has", False) else ""
        self.mediaChanged.emit()

    # ================= 主窗口 / 退出（速启面板用） =================
    @Slot()
    def showMainWindow(self) -> None:
        self.showMainRequested.emit()

    @Slot()
    def gotoSettings(self) -> None:
        self.settingsRequested.emit()

    @Slot()
    def quitApp(self) -> None:
        self.quitRequested.emit()

    @Slot(str, str)
    def notify(self, title: str, body: str) -> None:
        """发一条系统通知（失败回退托盘气泡）。"""
        try:
            self._notifications.notify(title, body)
        except Exception as exc:  # noqa: BLE001
            logger.warning("系统通知失败：%s", exc)
            self.toast.emit(f"{title} · {body}")

    # ================= v0.8：时间 / 睡眠 / 系统 / 壁纸 / 结束卡片 =================
    @Property(int, notify=statsChanged)
    def todaySessions(self) -> int:
        return int(self._stats.today_sessions(timesync.today()))

    @Property(dict, notify=statsChanged)
    def todayFocusCard(self) -> dict:
        """结束卡片：{date, timeRange, spaceName, minutes, sessions, quote}。"""
        day = timesync.today()
        sessions = self._stats.sessions_on(day)
        starts: list = []
        ends: list = []
        for item in sessions:
            raw = str(item.get("start") or item.get("ts") or "")
            try:
                started = datetime.fromisoformat(raw)
            except (TypeError, ValueError):
                continue
            starts.append(started)
            ends.append(started + timedelta(minutes=float(item.get("minutes", 0) or 0)))
        time_range = ""
        if starts and ends:
            time_range = f"{min(starts):%H:%M} - {max(ends):%H:%M}"
        space_name = ""
        for item in reversed(sessions):
            if str(item.get("space") or ""):
                space_name = str(item.get("space"))
                break
        total_minutes = round(
            sum(float(item.get("minutes", 0) or 0) for item in sessions), 1
        )
        total_clicks = sum(int(item.get("clicks", 0) or 0) for item in sessions)
        return {
            "date": day.isoformat(),
            "timeRange": time_range,
            "spaceName": space_name,
            "minutes": total_minutes,
            "sessions": len(sessions),
            "clicks": total_clicks,
            "quote": QUOTES[day.toordinal() % len(QUOTES)] if QUOTES else "",
        }

    @Slot(int, result=bool)
    def extendSession(self, minutes: int) -> bool:
        if not self._session.extend(minutes):
            return False
        self._write_session_state()
        self.toast.emit(
            QCoreApplication.translate("ShenQing", "已延长 {0} 分钟").format(int(minutes))
        )
        return True

    # ---------- 速启面板 → 空间页 ----------
    @Slot(str)
    def openSpacesPage(self, mode: str) -> None:
        """速启面板点空间/档位：打开主界面并切到空间页（不开始专注）。"""
        value = str(mode or "")
        if value not in {item.value for item in LockLevel}:
            value = ""
        self.showMainRequested.emit()
        self.spacesPageRequested.emit(value)

    # ---------- 系统音量 / 关机重启 ----------
    @Property(int, notify=settingsChanged)
    def systemVolume(self) -> int:
        if self._volume < 0:
            self._volume = system_control.get_volume()
        return self._volume

    @Slot(int)
    def setSystemVolume(self, value: int) -> None:
        try:
            level = max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return
        if system_control.set_volume(level):
            self._volume = level
            self._settings.set("volume_panel", level)
        self.settingsChanged.emit()

    def _refresh_system_volume(self) -> int:
        """v0.17：定时读取系统音量；值有变化才 emit settingsChanged（避免 QML 抖动）。"""
        try:
            value = system_control.get_volume()
        except Exception as exc:  # noqa: BLE001 - 音量读取失败不能影响定时器
            logger.info("定时读取系统音量失败：%s", exc)
            return self._volume
        if value < 0:
            return self._volume
        if value != self._volume:
            self._volume = value
            self.settingsChanged.emit()
        return value

    @Slot(str)
    def systemPower(self, action: str) -> None:
        value = str(action or "").lower()
        if value not in ("shutdown", "restart"):
            return
        if system_control.power_action(value):
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "系统将在 1 秒内{0}").format(
                    QCoreApplication.translate("ShenQing", "关机")
                    if value == "shutdown"
                    else QCoreApplication.translate("ShenQing", "重启")
                )
            )
        else:
            self.toast.emit(QCoreApplication.translate("ShenQing", "电源操作失败"))

    # ---------- 睡眠模式 ----------
    @Property(list, notify=sleepChanged)
    def sleepSchedules(self) -> list[str]:
        return self._sleep.schedule_times()

    @Property(str, notify=sleepChanged)
    def sleepModeSummary(self) -> str:
        """第 4 档「还清」卡片摘要：作息时间 · 本月剩余解锁次数。"""
        times = self._sleep.schedule_times()
        if not times:
            return QCoreApplication.translate("ShenQing", "未设置作息时间")
        return "{} · {}".format(
            " / ".join(times),
            QCoreApplication.translate("ShenQing", "本月剩余 {0} 次").format(
                self._sleep.unlock_chances
            ),
        )

    @Property(list, notify=sleepChanged)
    def sleepScheduleItems(self) -> list[dict]:
        return self._sleep.schedules()

    @Slot(str, result=str)
    def addSleepSchedule(self, time_text: str) -> str:
        new_id = self._sleep.add_schedule(time_text)
        if new_id:
            self.sleepChanged.emit()
            self.toast.emit(QCoreApplication.translate("ShenQing", "已添加睡眠锁定时间"))
        else:
            self.toast.emit(QCoreApplication.translate("ShenQing", "时间格式不正确或已存在"))
        return new_id

    @Slot(str, result=bool)
    def removeSleepSchedule(self, key: str) -> bool:
        ok = self._sleep.remove_schedule(key)
        if ok:
            self.sleepChanged.emit()
        return ok

    @Property(bool, notify=sleepChanged)
    def sleepRemindersEnabled(self) -> bool:
        return self._sleep.reminders_enabled

    @Slot(bool)
    def setSleepReminders(self, enabled: bool) -> None:
        self._sleep.set_reminders(bool(enabled))
        self.sleepChanged.emit()

    @Property(int, notify=sleepChanged)
    def unlockChances(self) -> int:
        return self._sleep.unlock_chances

    @Property(str, notify=sleepChanged)
    def unlockChanceLabel(self) -> str:
        return self._sleep.unlock_chance_label

    @Slot(result=bool)
    def clickClockForUnlock(self) -> bool:
        """连续点时钟 10 次（5 秒内）→ 消耗一次本月机会解锁睡眠锁定。"""
        now = time.monotonic()
        while self._clock_clicks and now - self._clock_clicks[0] > 5.0:
            self._clock_clicks.popleft()
        self._clock_clicks.append(now)
        if len(self._clock_clicks) < 10:
            remain = 10 - len(self._clock_clicks)
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "再点 {0} 次可解锁").format(remain)
            )
            return False
        self._clock_clicks.clear()
        if not self._sleep_lock_active:
            self.toast.emit(QCoreApplication.translate("ShenQing", "当前没有睡眠锁定"))
            return False
        if not self._sleep.try_unlock():
            self.sleepChanged.emit()
            self.toast.emit(QCoreApplication.translate("ShenQing", "本月解锁机会已用完"))
            return False
        self._sleep_lock_active = False
        self.sleepChanged.emit()
        if self._session.state is not SessionState.IDLE:
            self._session.stop()
        self.toast.emit(QCoreApplication.translate("ShenQing", "已解锁，提前结束本次睡眠锁定"))
        return True

    def _tick_sleep(self) -> None:
        try:
            now = timesync.now()
            for due in self._sleep.due_reminders(now):
                schedule = due["schedule"]
                offset = int(due["offset"])
                self._sleep.mark_fired(
                    now.strftime("%Y-%m-%d"), schedule["time"], offset
                )
                self.notify(
                    QCoreApplication.translate("ShenQing", "睡眠提醒"),
                    QCoreApplication.translate(
                        "ShenQing", "{0} 分钟后将进入深清锁定（{1}）"
                    ).format(offset, schedule["time"]),
                )
            if self._session.state is not SessionState.IDLE or self._prepare_active:
                return
            due_lock = self._sleep.due_lock(now)
            if due_lock is None:
                return
            heavy = self._spaces.get_by_mode("heavy")
            minutes = int(heavy.get("minutes", 180)) if heavy else 180
            self._sleep.mark_fired(
                now.strftime("%Y-%m-%d"), due_lock["time"], sleep_mode.LOCK_KIND
            )
            self._sleep_lock_active = True
            self._begin_space_session(heavy, "heavy", minutes)
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "睡眠模式：已自动进入深清锁定")
            )
        except Exception as exc:  # noqa: BLE001 - 睡眠调度失败不能拖垮主程序
            logger.warning("睡眠模式调度失败：%s", exc)

    # ---------- Bing 壁纸 / 用户头像 ----------
    @Property(str, notify=wallpaperChanged)
    def bingWallpaperUrl(self) -> str:
        if self._bing_url:
            return self._bing_url
        return wallpaper.cached_bing_url()

    @Property(str, notify=wallpaperChanged)
    def userAvatarUrl(self) -> str:
        return self._avatar_url

    def _load_wallpaper_assets(self) -> None:
        try:
            url = wallpaper.refresh_bing_wallpaper()
            avatar = wallpaper.user_avatar_url()
            changed = False
            if url and url != self._bing_url:
                self._bing_url = url
                changed = True
            if avatar != self._avatar_url:
                self._avatar_url = avatar
                changed = True
            if changed:
                self.wallpaperChanged.emit()
                # cardBackgroundUrl 默认回退必应壁纸，URL 变化也要通知设置绑定
                self.settingsChanged.emit()
        except Exception as exc:  # noqa: BLE001
            logger.info("壁纸/头像加载失败：%s", exc)

    # ================= v0.9 AI 集成 =================
    @Property(bool, notify=settingsChanged)
    def aiConfigured(self) -> bool:
        return self._ai.configured()

    @Property(bool, notify=settingsChanged)
    def aiEnabled(self) -> bool:
        return self._ai.enabled()

    @Slot(bool)
    def setAIEnabled(self, enabled: bool) -> None:
        self._settings.set("ai_enabled", bool(enabled))
        self.settingsChanged.emit()

    @Property(bool, notify=settingsChanged)
    def aiNeedsKey(self) -> bool:
        return self._ai.needs_key()

    @Property(bool, notify=settingsChanged)
    def aiSupportsReasoning(self) -> bool:
        return self._ai.supports_reasoning()

    @Property(bool, notify=settingsChanged)
    def aiSupportsWebSearch(self) -> bool:
        return self._ai.supports_web_search()

    @Property(bool, notify=settingsChanged)
    def aiReasoningEnabled(self) -> bool:
        return self._ai.reasoning_enabled()

    @Slot(bool)
    def setAIReasoningEnabled(self, enabled: bool) -> None:
        self._settings.set("ai_reasoning_enabled", bool(enabled))
        self.settingsChanged.emit()

    @Property(bool, notify=settingsChanged)
    def aiWebSearchEnabled(self) -> bool:
        return self._ai.web_search_enabled()

    @Slot(bool)
    def setAIWebSearchEnabled(self, enabled: bool) -> None:
        self._settings.set("ai_web_search_enabled", bool(enabled))
        self.settingsChanged.emit()

    @Property(str, notify=settingsChanged)
    def aiReasoningEffort(self) -> str:
        return self._ai.reasoning_effort()

    @Slot(str)
    def setAIReasoningEffort(self, effort: str) -> None:
        self._settings.set("ai_reasoning_effort", str(effort or "").strip())
        self.settingsChanged.emit()

    @Property(list, constant=True)
    def aiProviders(self) -> list[dict]:
        providers = ai_service.provider_list()
        for item in providers:
            if item.get("value") == "custom":
                # 自定义服务商的思考/联网能力由用户开关决定
                item["supports_reasoning"] = bool(
                    self._settings.get("ai_reasoning_enabled", True)
                )
                item["supports_web_search"] = bool(
                    self._settings.get("ai_web_search_enabled", False)
                )
        return providers

    @Property(str, notify=settingsChanged)
    def aiProvider(self) -> str:
        return self._ai.provider()

    @Slot(str)
    def setAIProvider(self, value: str) -> None:
        old_provider = self._ai.provider()
        if not self._ai.set_provider(str(value or "")):
            return
        if self._ai.provider() == old_provider:
            self.settingsChanged.emit()
            return
        # 切换服务商：清空旧模型列表，带出默认 base/model；有 Key 则自动拉取新列表
        self._ai_models = []
        self._ai_models_state = "idle"
        self._ai_models_error = ""
        self.aiModelsChanged.emit()
        self.settingsChanged.emit()
        if (not self._ai.needs_key()) or self._ai.has_key():
            QTimer.singleShot(0, self.fetchAIModels)

    # ---------- 模型列表（/models） ----------
    def _models_cache(self) -> dict:
        raw = self._settings.get("ai_models_cache", {})
        return dict(raw) if isinstance(raw, dict) else {}

    @Property(list, notify=aiModelsChanged)
    def aiModels(self) -> list[str]:
        if self._ai_models:
            return list(self._ai_models)
        cached = ai_service.cached_models(
            self._models_cache(), self._ai.provider()
        )
        if cached:
            return cached
        return list(self._ai.preset().get("models") or [])

    @Property(str, notify=aiModelsChanged)
    def aiModelsState(self) -> str:
        return self._ai_models_state

    @Property(str, notify=aiModelsChanged)
    def aiModelsError(self) -> str:
        return self._ai_models_error

    @Slot()
    def fetchAIModels(self) -> None:
        if self._ai_models_state == "loading":
            return
        key = self._ai.api_key()
        base = self._ai.api_base()
        if not base or (self._ai.needs_key() and not key):
            self._ai_models = []
            self._ai_models_state = "error"
            self._ai_models_error = (
                "请先填写 API Key 与 API Base"
                if self._ai.needs_key()
                else "请先填写 API Base"
            )
            self.aiModelsChanged.emit()
            return
        provider = self._ai.provider()
        self._ai_models_state = "loading"
        self._ai_models_error = ""
        self.aiModelsChanged.emit()
        threading.Thread(
            target=self._fetch_models_worker,
            args=(provider, base, key),
            name="shenqing-ai-models",
            daemon=True,
        ).start()

    def _fetch_models_worker(self, provider: str, base: str, key: str) -> None:
        error = ""
        models: list[str] = []
        try:
            models = ai_service.fetch_models(base, key, provider)
        except Exception as exc:  # noqa: BLE001 - fetch_models 本身不抛异常，双保险
            error = self._ai.sanitize(exc)
        if not models and not error:
            error = "未获取到模型列表"
        try:
            self._aiModelsFetched.emit(provider, models, error)
        except RuntimeError:  # 宿主已销毁
            pass

    @Slot(str, object, str)
    def _on_ai_models_fetched(
        self, provider: str, models: object, error: str
    ) -> None:
        fetched = [str(item) for item in models] if isinstance(models, list) else []
        if fetched:
            cache = ai_service.cache_models(self._models_cache(), provider, fetched)
            self._settings.set("ai_models_cache", cache)
        if str(provider) != self._ai.provider():
            # 旧服务商的迟到结果：只更新缓存，不影响当前 UI
            return
        if fetched:
            self._ai_models = fetched
            self._ai_models_state = "ok"
            self._ai_models_error = ""
        else:
            self._ai_models = []
            self._ai_models_state = "error"
            self._ai_models_error = self._ai.sanitize(error or "未获取到模型列表")
        self.aiModelsChanged.emit()

    @Property(str, notify=settingsChanged)
    def aiBase(self) -> str:
        return self._ai.api_base()

    @Slot(str)
    def setAIBase(self, url: str) -> None:
        self._settings.set("ai_api_base", str(url or "").strip())
        self.settingsChanged.emit()

    @Property(str, notify=settingsChanged)
    def aiModel(self) -> str:
        return self._ai.model()

    @Slot(str)
    def setAIModel(self, model: str) -> None:
        self._settings.set("ai_model", str(model or "").strip())
        self.settingsChanged.emit()

    @Property(bool, notify=settingsChanged)
    def aiHasKey(self) -> bool:
        return self._ai.has_key()

    @Slot(str)
    def setAIKey(self, key: str) -> None:
        self._settings.set("ai_api_key", str(key or "").strip())
        self.settingsChanged.emit()

    @Property(str, notify=aiChanged)
    def aiState(self) -> str:
        return self._ai_state

    @Property(str, notify=aiChanged)
    def aiAnswer(self) -> str:
        return self._ai_answer

    @Property(str, notify=aiChanged)
    def aiError(self) -> str:
        return self._ai_error

    def _ai_settings_items(self) -> list[dict]:
        return [
            {"key": "theme_style", "title": "主题样式", "hint": "纯色 / 液态玻璃 / 海洋"},
            {"key": "theme_scheme", "title": "主题配色", "hint": "跟随系统 / 浅色 / 深色"},
            {"key": "theme", "title": "窗口外观", "hint": "Auto / Light / Dark"},
            {"key": "language", "title": "语言", "hint": "跟随系统 / 中文 / English"},
            {"key": "autostart", "title": "开机自启", "hint": "登录时启动深清"},
            {"key": "hardening", "title": "防退出加固", "hint": "隐藏任务栏、屏蔽系统快捷键"},
            {"key": "keep_alive", "title": "保留进程", "hint": "不结束进程，只隐藏窗口与静音"},
            {"key": "admin_mode", "title": "管理员权限", "hint": "以最高权限运行 / UAC"},
            {"key": "auto_update", "title": "自动更新", "hint": "启动后检查 GitHub Releases"},
            {"key": "default_mode", "title": "默认强度", "hint": "浅清 / 覆清 / 深清"},
            {"key": "default_minutes", "title": "默认时长", "hint": "速启默认分钟数"},
            {"key": "lock_level", "title": "锁定强度", "hint": "轻度 / 中度 / 重度"},
            {"key": "pause_limit", "title": "暂停次数", "hint": "一次会话允许的暂停上限"},
            {"key": "volume_panel", "title": "系统音量", "hint": "dock 设置面板音量"},
            {"key": "sleepRemindersEnabled", "title": "睡眠提醒", "hint": "提前 60/30/1 分钟提醒"},
            {"key": "countdown_date", "title": "倒数日", "hint": "目标日期 YYYY-MM-DD"},
            {"key": "ai_enabled", "title": "AI 助手", "hint": "启用 AI 问答与设置搜索"},
            {"key": "ai_provider", "title": "AI 服务商", "hint": "Groq / 智谱 / SiliconFlow"},
            {"key": "onboarding_done", "title": "新手引导", "hint": "首次使用欢迎页"},
            {"key": "guard_interval_ms", "title": "巡检间隔", "hint": "进程守护轮询毫秒数"},
            {"key": "hosts_block_enabled", "title": "网站屏蔽", "hint": "写 hosts 屏蔽网站"},
        ]

    @Slot(str)
    def askAI(self, prompt: str) -> None:
        text = str(prompt or "").strip()
        if not text:
            return
        if not self._ai.configured():
            self._ai_state = "error"
            self._ai_error = "AI 未启用或未配置"
            self._ai_answer = ""
            self.aiChanged.emit()
            return
        conversation = self._ensure_current_conversation()
        self._ai_pending_conv = str(conversation.get("id") or "")
        self._append_ai_message(conversation, "user", text)
        self._start_ai_job("ask", text)

    @Slot(str)
    def aiAsk(self, prompt: str) -> None:
        """UI 别名：与 askAI 相同。"""
        self.askAI(prompt)

    @Slot()
    def aiCancel(self) -> None:
        self._ai_token += 1
        self._ai_state = "idle"
        self._ai_answer = ""
        self._ai_error = ""
        self._ai_mode = ""
        self._ai_pending_conv = ""
        self.aiChanged.emit()

    @Slot()
    def testAIConnection(self) -> None:
        if not self._ai.configured():
            self._ai_state = "error"
            self._ai_error = "AI 未启用或未配置"
            self._ai_answer = ""
            self.aiChanged.emit()
            self.toast.emit(QCoreApplication.translate("ShenQing", "请先启用并填写 AI 配置"))
            return
        self._start_ai_job("test", "")

    def _start_ai_job(self, mode: str, prompt: str) -> None:
        self._ai_token += 1
        token = self._ai_token
        self._ai_mode = str(mode)
        self._ai_state = "loading"
        self._ai_answer = ""
        self._ai_error = ""
        self.aiChanged.emit()

        def _callback(result: object) -> None:
            try:
                self._aiAsyncResult.emit(token, result)
            except RuntimeError:  # 宿主已销毁
                pass

        if mode == "test":
            self._ai.submit_test(_callback)
        else:
            self._ai.submit_ask(prompt, _callback)

    @Slot(int, object)
    def _on_ai_result(self, token: int, result: object) -> None:
        if int(token) != self._ai_token:
            return
        data = result if isinstance(result, dict) else {}
        mode = self._ai_mode
        if data.get("ok"):
            self._ai_state = "ok"
            answer = str(data.get("text") or "")
            self._ai_error = ""
            if mode == "ask":
                # v0.21：回复里带动作块时先执行（start_space 只挂 pending），
                # 再把动作块从展示文案里去掉（动作由 aiActionLog 单独呈现）。
                self._run_ai_actions(answer)
                cleaned = ai_actions_service.strip_action_blocks(answer)
                if cleaned.strip():
                    self._ai_answer = cleaned
                elif cleaned != answer:
                    self._ai_answer = QCoreApplication.translate(
                        "ShenQing", "已按你的要求执行。"
                    )
                else:
                    self._ai_answer = answer
            else:
                self._ai_answer = answer
            if mode == "test":
                self.toast.emit(QCoreApplication.translate("ShenQing", "AI 连接正常"))
        else:
            self._ai_state = "error"
            self._ai_answer = ""
            self._ai_error = self._ai.sanitize(data.get("error") or "AI 请求失败")
            if mode == "test":
                self.toast.emit(
                    QCoreApplication.translate("ShenQing", "AI 连接失败：{0}").format(
                        self._ai_error[:80]
                    )
                )
        usage = data.get("usage")
        if isinstance(usage, dict) and usage:
            self._record_ai_usage(usage)
        if mode == "ask":
            conversation = self._find_conversation(self._ai_pending_conv)
            self._ai_pending_conv = ""
            if conversation is not None and data.get("ok"):
                self._append_ai_message(
                    conversation,
                    "assistant",
                    self._ai_answer,
                    reasoning=str(data.get("reasoning") or ""),
                    tokens=int((usage or {}).get("total_tokens") or 0),
                )
        self.aiChanged.emit()

    @Slot(str, result=list)
    def aiSearchSettings(self, query: str) -> list[dict]:
        """设置语义搜索；未配置/失败时回退本地模糊匹配。"""
        text = str(query or "").strip()
        if not text:
            return []
        items = self._ai_settings_items()
        try:
            return self._ai.search_settings(text, items)
        except Exception as exc:  # noqa: BLE001
            logger.info("AI 设置搜索失败，回退本地匹配：%s", self._ai.sanitize(exc))
            return ai_service.local_search(text, items)

    # ================= v0.11 对话历史 / 费用用量 =================
    def _load_ai_chats(self) -> None:
        data = None
        try:
            if self._ai_chats_path.exists():
                data = json.loads(self._ai_chats_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            data = None
        conversations: list[dict] = []
        current_id = ""
        if isinstance(data, dict):
            raw = data.get("conversations")
            if isinstance(raw, list):
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    conversation_id = str(item.get("id") or "").strip()
                    if not conversation_id:
                        continue
                    messages = []
                    for message in item.get("messages") or []:
                        if not isinstance(message, dict):
                            continue
                        messages.append(
                            {
                                "role": str(message.get("role") or "user"),
                                "content": str(message.get("content") or ""),
                                "reasoning": str(message.get("reasoning") or ""),
                                "time": str(message.get("time") or ""),
                                "tokens": int(message.get("tokens") or 0),
                            }
                        )
                    conversations.append(
                        {
                            "id": conversation_id,
                            "title": str(item.get("title") or "新对话"),
                            "createdAt": str(item.get("createdAt") or ""),
                            "updatedAt": str(item.get("updatedAt") or ""),
                            "messages": messages,
                        }
                    )
            current_id = str(data.get("currentId") or "")
        if not any(conversation["id"] == current_id for conversation in conversations):
            current_id = conversations[0]["id"] if conversations else ""
        self._ai_chats = {"currentId": current_id, "conversations": conversations}

    def _save_ai_chats(self) -> None:
        try:
            self._ai_chats_path.parent.mkdir(parents=True, exist_ok=True)
            self._ai_chats_path.write_text(
                json.dumps(self._ai_chats, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("保存 AI 对话历史失败：%s", exc)

    def _find_conversation(self, conversation_id: str) -> dict | None:
        target = str(conversation_id or "")
        if not target:
            return None
        for conversation in self._ai_chats.get("conversations", []):
            if str(conversation.get("id")) == target:
                return conversation
        return None

    def _current_conversation(self) -> dict | None:
        return self._find_conversation(self._ai_chats.get("currentId", ""))

    def _new_conversation(self, title: str = "新对话") -> dict:
        import uuid

        now = timesync.now().isoformat(timespec="seconds")
        conversation = {
            "id": "chat_" + uuid.uuid4().hex[:10],
            "title": str(title or "新对话")[:24],
            "createdAt": now,
            "updatedAt": now,
            "messages": [],
        }
        self._ai_chats.setdefault("conversations", []).append(conversation)
        return conversation

    def _ensure_current_conversation(self) -> dict:
        conversation = self._current_conversation()
        if conversation is not None:
            return conversation
        conversation = self._new_conversation()
        self._ai_chats["currentId"] = conversation["id"]
        self._save_ai_chats()
        self.aiChatsChanged.emit()
        return conversation

    def _append_ai_message(
        self,
        conversation: dict,
        role: str,
        content: str,
        *,
        reasoning: str = "",
        tokens: int = 0,
    ) -> None:
        now = timesync.now().isoformat(timespec="seconds")
        message = {
            "role": str(role),
            "content": str(content or ""),
            "reasoning": str(reasoning or ""),
            "time": now,
            "tokens": int(tokens or 0),
        }
        conversation.setdefault("messages", []).append(message)
        conversation["updatedAt"] = now
        if role == "user":
            if str(conversation.get("title") or "") in ("", "新对话"):
                title = str(content or "").strip().replace("\n", " ")[:24]
                conversation["title"] = title or "新对话"
        self._save_ai_chats()
        self.aiChatsChanged.emit()

    @Property(list, notify=aiChatsChanged)
    def aiConversations(self) -> list[dict]:
        items = []
        for conversation in self._ai_chats.get("conversations", []):
            items.append(
                {
                    "id": str(conversation.get("id") or ""),
                    "title": str(conversation.get("title") or "新对话"),
                    "updatedAt": str(conversation.get("updatedAt") or ""),
                    "count": len(conversation.get("messages") or []),
                }
            )
        items.sort(key=lambda item: item["updatedAt"], reverse=True)
        return items

    @Property(list, notify=aiChatsChanged)
    def aiMessages(self) -> list[dict]:
        conversation = self._current_conversation()
        if conversation is None:
            return []
        return [dict(message) for message in conversation.get("messages") or []]

    @Slot()
    def newAIConversation(self) -> None:
        conversation = self._new_conversation()
        self._ai_chats["currentId"] = conversation["id"]
        self._save_ai_chats()
        self.aiChatsChanged.emit()

    @Slot(str, result=bool)
    def selectAIConversation(self, conversation_id: str) -> bool:
        conversation = self._find_conversation(conversation_id)
        if conversation is None:
            return False
        self._ai_chats["currentId"] = conversation["id"]
        self._save_ai_chats()
        self.aiChatsChanged.emit()
        return True

    @Slot(str, result=bool)
    def deleteAIConversation(self, conversation_id: str) -> bool:
        conversation = self._find_conversation(conversation_id)
        if conversation is None:
            return False
        self._ai_chats["conversations"].remove(conversation)
        if str(self._ai_chats.get("currentId")) == str(conversation["id"]):
            remaining = self._ai_chats.get("conversations") or []
            self._ai_chats["currentId"] = str(remaining[0]["id"]) if remaining else ""
        self._save_ai_chats()
        self.aiChatsChanged.emit()
        return True

    # ---------- 费用 / 用量 ----------
    def _load_ai_usage(self) -> None:
        try:
            data = json.loads(self._ai_usage_path.read_text(encoding="utf-8")) if self._ai_usage_path.exists() else None
        except (OSError, json.JSONDecodeError, ValueError):
            data = None
        self._ai_usage = data if isinstance(data, dict) else {}
        self._ai_last_usage = {}
        self._ai_usage_currency = ""

    def _save_ai_usage(self) -> None:
        try:
            self._ai_usage_path.parent.mkdir(parents=True, exist_ok=True)
            self._ai_usage_path.write_text(
                json.dumps(self._ai_usage, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("保存 AI 用量失败：%s", exc)

    def _record_ai_usage(self, usage: dict) -> None:
        model = str(usage.get("model") or self._ai.model())
        provider = str(usage.get("provider") or self._ai.provider())
        try:
            tokens_in = max(0, int(usage.get("prompt_tokens") or 0))
            tokens_out = max(0, int(usage.get("completion_tokens") or 0))
            cost = max(0.0, float(usage.get("cost") or 0.0))
        except (TypeError, ValueError):
            tokens_in = tokens_out = 0
            cost = 0.0
        currency = str(usage.get("currency") or "CNY")
        day = timesync.today().isoformat()
        entry = self._ai_usage.setdefault(
            day, {"tokens_in": 0, "tokens_out": 0, "cost": 0.0, "by_provider": {}}
        )
        entry["tokens_in"] = int(entry.get("tokens_in", 0)) + tokens_in
        entry["tokens_out"] = int(entry.get("tokens_out", 0)) + tokens_out
        entry["cost"] = round(float(entry.get("cost", 0.0)) + cost, 8)
        by_provider = entry.setdefault("by_provider", {})
        provider_entry = by_provider.setdefault(
            provider, {"tokens_in": 0, "tokens_out": 0, "cost": 0.0, "currency": currency}
        )
        provider_entry["tokens_in"] = int(provider_entry.get("tokens_in", 0)) + tokens_in
        provider_entry["tokens_out"] = int(provider_entry.get("tokens_out", 0)) + tokens_out
        provider_entry["cost"] = round(float(provider_entry.get("cost", 0.0)) + cost, 8)
        provider_entry["currency"] = currency
        self._ai_last_usage = {
            "model": model,
            "provider": provider,
            "prompt_tokens": tokens_in,
            "completion_tokens": tokens_out,
            "cost": round(cost, 6),
            "currency": currency,
        }
        self._ai_usage_currency = currency
        self._save_ai_usage()
        self.aiUsageChanged.emit()

    def _today_usage(self) -> dict:
        return self._ai_usage.get(timesync.today().isoformat(), {})

    @Property(int, notify=aiUsageChanged)
    def aiTodayTokens(self) -> int:
        entry = self._today_usage()
        return int(entry.get("tokens_in", 0)) + int(entry.get("tokens_out", 0))

    @Property(float, notify=aiUsageChanged)
    def aiTodayCost(self) -> float:
        return round(float(self._today_usage().get("cost", 0.0)), 6)

    @Property(str, notify=aiUsageChanged)
    def aiCurrency(self) -> str:
        if self._ai_usage_currency:
            return self._ai_usage_currency
        return str(
            ai_service.provider_pricing(self._ai.provider(), self._ai.model()).get("currency")
            or "CNY"
        )

    @Property(dict, notify=aiUsageChanged)
    def aiLastUsage(self) -> dict:
        return dict(self._ai_last_usage)

    @Slot()
    def resetAIUsage(self) -> None:
        self._ai_usage = {}
        self._ai_last_usage = {}
        self._ai_usage_currency = ""
        self._save_ai_usage()
        self.aiUsageChanged.emit()

    # ================= v0.21 AI 动作（直接打开所需空间 / 调整设置） =================
    #: aiActionLog 最多保留的条数（QML 用来渲染系统小字）
    AI_ACTION_LOG_LIMIT = 20

    @Property(bool, notify=aiActionChanged)
    def aiActionPendingActive(self) -> bool:
        """是否有等待用户确认的 AI 动作（start_space）。"""
        return bool(self._ai_action_pending)

    @Property(dict, notify=aiActionChanged)
    def aiActionPending(self) -> dict:
        """待确认动作（空 dict = 没有）；字段见 ai_actions.pending_summary。"""
        return dict(self._ai_action_pending)

    @Property(dict, notify=aiActionChanged)
    def aiActionResult(self) -> dict:
        """最近一次动作结果：{ok, type, text, at}；空 dict = 还没执行过。"""
        return dict(self._ai_action_result)

    @Property(list, notify=aiActionChanged)
    def aiActionLog(self) -> list[dict]:
        """动作结果日志（最新在末尾，最多 AI_ACTION_LOG_LIMIT 条）。"""
        return [dict(item) for item in self._ai_action_log]

    @Property(str, notify=aiActionChanged)
    def lastRequestedPage(self) -> str:
        """AI 最近一次请求打开的页面（spaces|stats|ai|plugins|themes|settings|update|about|store）。"""
        return self._last_requested_page

    def _ai_action_now(self) -> str:
        return timesync.now().isoformat(timespec="seconds")

    def _new_ai_action_id(self) -> str:
        import uuid

        return "act_" + uuid.uuid4().hex[:10]

    def _push_ai_action_results(self, results: list[dict]) -> None:
        if not results:
            return
        for item in results:
            self._ai_action_log.append(dict(item))
        limit = max(1, int(self.AI_ACTION_LOG_LIMIT))
        if len(self._ai_action_log) > limit:
            del self._ai_action_log[: len(self._ai_action_log) - limit]
        self._ai_action_result = dict(results[-1])
        self.aiActionChanged.emit()

    @Slot(str, result=list)
    def aiExecuteReply(self, text: str) -> list[dict]:
        """解析 AI 回复里的动作块并执行（安全动作直接执行 + toast；start_space 置 pending）。"""
        return self._run_ai_actions(text)

    def _run_ai_actions(self, text: str) -> list[dict]:
        parsed = ai_actions_service.parse_reply(str(text or ""))
        results: list[dict] = []
        for action in parsed.get("actions") or []:
            results.append(self._execute_ai_action(action))
        for error in parsed.get("errors") or []:
            message = str(error or "")
            if not message:
                continue
            results.append(
                {
                    "ok": False,
                    "type": "",
                    "text": message,
                    "at": self._ai_action_now(),
                }
            )
            self.toast.emit(message)
        self._push_ai_action_results(results)
        return results

    def _execute_ai_action(self, action: dict) -> dict:
        if ai_actions_service.requires_confirmation(action):
            return self._stage_ai_action(action)
        ok, text, toast = self._apply_ai_action(action)
        if toast and text:
            self.toast.emit(text)
        return ai_actions_service.result_entry(action, ok, text, self._ai_action_now())

    def _resolve_action_space(self, action: dict) -> dict | None:
        """按 spaceId / mode 找到动作对应的空间（找不到返回 None）。"""
        space_id = str(action.get("spaceId") or "")
        mode = str(action.get("mode") or "")
        space = self._spaces.get(space_id) if space_id else None
        if space is None and mode:
            space = self._spaces.get_by_mode(mode)
        return space

    def _stage_ai_action(self, action: dict) -> dict:
        """需要确认的动作：补全空间信息后置 pending，等 aiConfirmAction。"""
        space = self._resolve_action_space(action)
        if space is None:
            text = QCoreApplication.translate("ShenQing", "空间不存在")
            self.toast.emit(text)
            return ai_actions_service.result_entry(action, False, text, self._ai_action_now())
        resolved = dict(action)
        resolved["spaceId"] = str(space.get("id") or "")
        resolved["mode"] = str(space.get("mode") or resolved.get("mode") or "")
        resolved["spaceName"] = str(space.get("name") or "")
        if not int(resolved.get("minutes") or 0):
            resolved["minutes"] = self._space_start_minutes(space)
        pending = ai_actions_service.pending_summary(resolved, self._new_ai_action_id())
        self._ai_action_pending = dict(pending)
        self._ai_action_pending["action"] = resolved
        self.aiActionChanged.emit()
        text = QCoreApplication.translate("ShenQing", "需要你确认：{0}").format(
            str(pending.get("summary") or pending.get("title") or "")
        )
        return {
            "ok": True,
            "pending": True,
            "type": str(pending.get("type") or ""),
            "text": text,
            "at": self._ai_action_now(),
        }

    @Slot(result=bool)
    def aiConfirmAction(self) -> bool:
        """确认并执行待确认的 AI 动作（start_space → 真正开始专注）。"""
        pending = dict(self._ai_action_pending)
        action = pending.get("action") if isinstance(pending.get("action"), dict) else {}
        if not action:
            return False
        self._ai_action_pending = {}
        self.aiActionChanged.emit()
        ok, text, toast = self._apply_ai_action(action)
        if toast and text:
            self.toast.emit(text)
        self._push_ai_action_results(
            [ai_actions_service.result_entry(action, ok, text, self._ai_action_now())]
        )
        return ok

    @Slot(result=bool)
    def aiCancelAction(self) -> bool:
        """取消待确认的 AI 动作。"""
        pending = dict(self._ai_action_pending)
        if not pending:
            return False
        self._ai_action_pending = {}
        self.aiActionChanged.emit()
        text = QCoreApplication.translate("ShenQing", "已取消：{0}").format(
            str(pending.get("summary") or pending.get("title") or "")
        )
        self.toast.emit(text)
        self._push_ai_action_results(
            [
                {
                    "ok": True,
                    "type": str(pending.get("type") or ""),
                    "text": text,
                    "at": self._ai_action_now(),
                }
            ]
        )
        return True

    def _apply_ai_action(self, action: dict) -> tuple[bool, str, bool]:
        """执行一条已归一化的动作；返回 (ok, 文案, 是否由这里 toast)。"""
        kind = str(action.get("type") or "")
        if kind == "start_space":
            return self._ai_start_space(action)
        if kind == "open_space":
            mode = str(action.get("mode") or "")
            self._last_requested_page = "spaces"
            self.showMainRequested.emit()
            self.spacesPageRequested.emit(mode)
            return True, QCoreApplication.translate(
                "ShenQing", "已为你打开{0}空间"
            ).format(ai_actions_service.mode_label(mode)), True
        if kind == "set_setting":
            return self._ai_apply_setting(action)
        if kind == "open_page":
            page = str(action.get("page") or "")
            self._last_requested_page = page
            self.pageRequested.emit(page)
            self.showMainRequested.emit()
            return True, QCoreApplication.translate("ShenQing", "已打开{0}页").format(
                ai_actions_service.PAGE_LABELS.get(page, page)
            ), True
        if kind in ("add_blocked_site", "remove_blocked_site"):
            return self._ai_apply_blocked_site(action)
        return False, QCoreApplication.translate("ShenQing", "不支持的动作"), True

    def _ai_start_space(self, action: dict) -> tuple[bool, str, bool]:
        denial = self._start_denial()
        if denial:
            return False, denial, True
        space = self._resolve_action_space(action)
        if space is None:
            return False, QCoreApplication.translate("ShenQing", "空间不存在"), True
        minutes = self._space_start_minutes(space, int(action.get("minutes") or 0))
        self._begin_prepare(space, minutes)
        return True, QCoreApplication.translate(
            "ShenQing", "已为你开始专注：{0} · {1} 分钟"
        ).format(str(space.get("name") or ""), minutes), True

    def _ai_apply_blocked_site(self, action: dict) -> tuple[bool, str, bool]:
        kind = str(action.get("type") or "")
        domain = str(action.get("domain") or "")
        if kind == "add_blocked_site":
            if domain in self.blockedSites:
                return False, QCoreApplication.translate(
                    "ShenQing", "该网站已在屏蔽列表：{0}"
                ).format(domain), True
            # addBlockedSite 自己会发 toast（域名非法 / 已存在 / 已添加）
            ok = self.addBlockedSite(domain)
            return bool(ok), QCoreApplication.translate(
                "ShenQing", "已添加屏蔽网站：{0}"
            ).format(domain), False
        if domain not in self.blockedSites:
            return False, QCoreApplication.translate(
                "ShenQing", "该网站不在屏蔽列表：{0}"
            ).format(domain), True
        ok = self.removeBlockedSite(domain)
        return bool(ok), QCoreApplication.translate(
            "ShenQing", "已移除屏蔽网站：{0}"
        ).format(domain), False

    def _ai_apply_setting(self, action: dict) -> tuple[bool, str, bool]:
        """把 set_setting 动作落到既有 setter 上（副作用 / 信号与手动设置一致）。"""
        key = str(action.get("key") or "")
        # 再校验一次：外部构造的 action 不能绕过白名单
        ok, value, error = ai_actions_service.normalize_setting_value(key, action.get("value"))
        if not ok:
            return False, str(error or "设置值不正确"), True
        title = ai_actions_service.setting_title(key)
        value_text = ai_actions_service.setting_value_text(key, value)
        if key == "theme_style":
            style = self._normalize_style(value)
            if not style:
                return False, QCoreApplication.translate(
                    "ShenQing", "主题样式不存在：{0}"
                ).format(value_text), True
            self.setThemeStyle(style)
        elif key == "theme_scheme":
            self.setThemeScheme(str(value))
        elif key == "language":
            self.setLanguage(str(value))
        elif key == "ui_font_scale":
            self.setUIFontScale(float(value))
        elif key == "ui_font_family":
            self.setUIFontFamily(str(value))
        elif key == "nav_mode":
            self.setNavMode(str(value))
        elif key == "default_minutes":
            self.setDefaultMinutes(int(value))
        elif key == "auto_update":
            self.setAutoUpdate(bool(value))
        elif key == "site_block_enabled":
            self.setSiteBlockEnabled(bool(value))
        elif key == "hide_desktop_icons":
            self.setHideDesktopIcons(bool(value))
            self.settingsChanged.emit()
        elif key == "update_source":
            # setUpdateSource 自己会 toast（未知更新源 / 已切换更新源）
            if not self.setUpdateSource(str(value)):
                return False, QCoreApplication.translate(
                    "ShenQing", "未知的更新源：{0}"
                ).format(value_text), False
            return True, QCoreApplication.translate(
                "ShenQing", "已把 {0} 改为 {1}"
            ).format(title, value_text), False
        elif key == "update_channel":
            if not self.setUpdateChannel(str(value)):
                return False, QCoreApplication.translate(
                    "ShenQing", "未知的更新渠道：{0}"
                ).format(value_text), False
            return True, QCoreApplication.translate(
                "ShenQing", "已把 {0} 改为 {1}"
            ).format(title, value_text), False
        elif key == "blocked_sites":
            sites = value if isinstance(value, list) else []
            self._settings.set("blocked_sites", list(sites))
            self.settingsChanged.emit()
        else:
            return False, QCoreApplication.translate("ShenQing", "不支持的设置项"), True
        return True, QCoreApplication.translate("ShenQing", "已把 {0} 改为 {1}").format(
            title, value_text
        ), True

    # ================= v0.9 应用使用时长 =================
    @Property(str, notify=statsChanged)
    def appUsageDate(self) -> str:
        return self._app_usage_date or timesync.today().isoformat()

    @Slot(str)
    def setAppUsageDate(self, date_text: str) -> None:
        text = str(date_text or "").strip()
        if text:
            try:
                datetime.strptime(text, "%Y-%m-%d")
            except ValueError:
                return
        self._app_usage_date = text
        self.statsChanged.emit()
        self.appUsageChanged.emit()

    def _usage_day(self) -> str:
        return self._app_usage_date or timesync.today().isoformat()

    @Property(list, notify=statsChanged)
    def appUsageToday(self) -> list[dict]:
        return self._app_usage.usage_for(self._usage_day())

    @Property(list, notify=statsChanged)
    def appUsageWeek(self) -> list[dict]:
        return self._app_usage.week_usage()

    @Property(int, notify=statsChanged)
    def appUsageTotalMinutes(self) -> int:
        return int(round(self._app_usage.total_minutes(self._usage_day())))

    @Property(int, notify=statsChanged)
    def appUsageTotalToday(self) -> int:
        return int(round(self._app_usage.total_minutes(self._usage_day())))

    @Property(int, notify=statsChanged)
    def appUsageTotalWeek(self) -> int:
        return int(round(sum(item["minutes"] for item in self._app_usage.week_usage(limit=1000))))

    @Property(list, notify=statsChanged)
    def appCategories(self) -> list[dict]:
        return [
            {
                "category": item["category"],
                "name": item.get("label", item["category"]),
                "label": item.get("label", item["category"]),
                "minutes": item["minutes"],
                "color": item["color"],
            }
            for item in self._app_usage.category_totals(self._usage_day())
        ]

    @Slot(str, str, result=bool)
    def setAppCategory(self, exe: str, category: str) -> bool:
        ok = self._app_usage.set_category(exe, category)
        if ok:
            self.statsChanged.emit()
            self.appUsageChanged.emit()
        return ok

    @Slot(str, str, result=bool)
    def setAppColor(self, exe: str, color: str) -> bool:
        ok = self._app_usage.set_color(exe, color)
        if ok:
            self.statsChanged.emit()
            self.appUsageChanged.emit()
        return ok

    def _on_app_usage_changed(self) -> None:
        self.statsChanged.emit()
        self.appUsageChanged.emit()

    # ---------- v0.13 热力图 / 小时分布 / 应用分类 ----------
    @Property(list, notify=appUsageChanged)
    def appUsageHeatmap(self) -> list[dict]:
        """最近 N 天每日总分钟（无记录补 0），画日历热力图。"""
        return self._app_usage.heatmap(self.appUsageHeatmapDays)

    @Property(list, notify=appUsageChanged)
    def appUsageHourly(self) -> list[dict]:
        return self._app_usage.hourly(self._app_usage_hourly_range)

    @Property(str, notify=appUsageChanged)
    def appUsageHourlyRange(self) -> str:
        return self._app_usage_hourly_range

    @Slot(str)
    def setAppUsageHourlyRange(self, value: str) -> None:
        text = str(value or "").strip().lower()
        if text not in ("today", "week"):
            return
        self._app_usage_hourly_range = text
        self.appUsageChanged.emit()

    @Property(int, notify=appUsageChanged)
    def appUsageHeatmapDays(self) -> int:
        value = self._settings.get("app_usage_heatmap_days", 90)
        try:
            days = int(value)
        except (TypeError, ValueError):
            days = 90
        return days if days in (30, 90, 180) else 90

    @Slot(int)
    def setAppUsageHeatmapDays(self, days: int) -> None:
        try:
            value = int(days)
        except (TypeError, ValueError):
            return
        if value not in (30, 90, 180):
            return
        self._settings.set("app_usage_heatmap_days", value)
        self.appUsageChanged.emit()

    @Property(list, notify=appUsageChanged)
    def appUsageApps(self) -> list[dict]:
        return self._app_usage.all_apps()

    @Slot(str, result=bool)
    def resetAppCategory(self, exe: str) -> bool:
        ok = self._app_usage.reset_category(exe)
        if ok:
            self.statsChanged.emit()
            self.appUsageChanged.emit()
        return ok

    @Property(list, constant=True)
    def appCategoryOptions(self) -> list[dict]:
        return [
            {"value": item["value"], "label": item["label"]}
            for item in app_usage.CATEGORIES
        ]

    # ================= v0.14 备份 / 恢复 =================
    @Property(bool, notify=backupChanged)
    def backupBusy(self) -> bool:
        return bool(self._backup_busy)

    @Property(str, notify=backupChanged)
    def lastBackupPath(self) -> str:
        return self._last_backup_path

    @Property(str, notify=backupChanged)
    def lastBackupError(self) -> str:
        return self._last_backup_error

    def _set_backup_state(
        self, busy: bool, path: str = "", error: str = ""
    ) -> None:
        self._backup_busy = bool(busy)
        self._last_backup_path = str(path or "")
        self._last_backup_error = str(error or "")
        self.backupChanged.emit()

    @Slot(result=str)
    def exportBackup(self) -> str:
        """弹保存对话框导出备份；返回实际路径（取消/失败返回空串）。"""
        from PySide6.QtWidgets import QFileDialog

        try:
            default_path = str(Path.home() / backup_service.default_backup_name())
            selected, _filter = QFileDialog.getSaveFileName(
                None,
                QCoreApplication.translate("ShenQing", "导出深清备份"),
                default_path,
                QCoreApplication.translate("ShenQing", "深清备份 (*.zip)"),
            )
        except Exception as exc:  # noqa: BLE001 - 无 GUI 环境
            logger.warning("打开导出对话框失败：%s", exc)
            return ""
        if not selected:
            return ""
        return selected if self.exportBackupTo(selected) else ""

    @Slot(str, result=bool)
    def exportBackupTo(self, path: str) -> bool:
        text = str(path or "").strip()
        if not text:
            self._set_backup_state(False, "", "未选择保存路径")
            return False
        self._set_backup_state(True)
        ok, message = backup_service.create_backup(text)
        if ok:
            self._set_backup_state(False, text)
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "已导出到 {0}").format(text)
            )
        else:
            self._set_backup_state(False, "", message)
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "导出失败：{0}").format(message)
            )
        return ok

    @Slot(result=str)
    def pickBackupFile(self) -> str:
        """只选备份文件（覆盖确认交给 QML）。"""
        from PySide6.QtWidgets import QFileDialog

        try:
            selected, _filter = QFileDialog.getOpenFileName(
                None,
                QCoreApplication.translate("ShenQing", "选择深清备份"),
                str(Path.home()),
                QCoreApplication.translate("ShenQing", "深清备份 (*.zip)"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("打开导入对话框失败：%s", exc)
            return ""
        return str(selected or "")

    @Slot(result=bool)
    def importBackup(self) -> bool:
        """选文件 + 二次确认 + 恢复（QML 也可只调 pickBackupFile/restoreBackupFile）。"""
        path = self.pickBackupFile()
        if not path:
            return False
        try:
            from PySide6.QtWidgets import QMessageBox

            answer = QMessageBox.question(
                None,
                QCoreApplication.translate("ShenQing", "导入备份"),
                QCoreApplication.translate(
                    "ShenQing", "导入会覆盖当前设置与数据，是否继续？"
                ),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        except Exception as exc:  # noqa: BLE001
            logger.warning("确认导入失败：%s", exc)
            return False
        return self.restoreBackupFile(path)

    @Slot(str, result=bool)
    def restoreBackupFile(self, path: str) -> bool:
        text = str(path or "").strip()
        if not text:
            self._set_backup_state(False, "", "未选择备份文件")
            return False
        self._set_backup_state(True)
        ok, message = backup_service.restore_backup(text)
        if not ok:
            self._set_backup_state(False, "", message)
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "恢复失败：{0}").format(message)
            )
            return False
        self._set_backup_state(False, text)
        self.toast.emit(
            QCoreApplication.translate("ShenQing", "备份已恢复，正在重启深清…")
        )
        self._restart_after_restore()
        return True

    def _restart_after_restore(self) -> bool:
        """恢复后：停看门狗 → 重新拉起应用 → 退出当前进程。"""
        started = False
        try:
            from ..services import keeper

            keeper.stop_keeper()
            from PySide6.QtCore import QProcess

            command = list(keeper.main_command())
            if command:
                program = command[0]
                args = command[1:]
                if "--restarted" not in args:
                    args.append("--restarted")
                started = bool(
                    QProcess.startDetached(
                        program, args, keeper.working_directory()
                    )
                )
        except Exception as exc:  # noqa: BLE001 - 重启失败也要避免留在旧状态
            logger.warning("恢复后重启应用失败：%s", exc)
        application = QCoreApplication.instance()
        if application is not None:
            QTimer.singleShot(300, application.quit)
        return started

    # ================= v0.19：网页管理（浏览器里管理深清） =================
    def _build_web_admin_host(self) -> webadmin.WebAdminHost:
        """把主程序能力注入网页管理服务（默认实现只够脱离 GUI 的单测）。"""
        return webadmin.WebAdminHost(
            self._settings,
            self._spaces,
            self._stats,
            store_service=self._store,
            plugins_provider=lambda: self.plugins,
            store_items_provider=lambda: self._store.items(),
            session_snapshot=self._web_admin_session,
            session_start=self._web_admin_start_session,
            session_stop=self._web_admin_stop_session,
            install_store_item=self._web_admin_install_item,
            on_settings_changed=self._on_web_admin_setting,
            on_spaces_changed=self.spacesChanged.emit,
        )

    def _web_admin_session(self) -> dict:
        """当前专注状态（管理页概览卡片用）。"""
        space = self._spaces.get(self._active_space_id) if self._active_space_id else None
        return {
            "state": str(self.state),
            "remainingSeconds": int(self.remainingSeconds),
            "spaceName": str(space.get("name", "")) if space else "",
            "level": str(self._session_level or ""),
        }

    def _web_admin_start_session(
        self, mode: str, minutes: object, space_id: str
    ) -> tuple[bool, str]:
        """网页端开始专注：立即开始（不像桌面端还有 10 秒倒计时）。"""
        if self._session.state is not SessionState.IDLE:
            return False, "已经有正在进行的专注"
        space = self._spaces.get(space_id) if space_id else self._spaces.get_by_mode(mode)
        if space is None:
            return False, "空间不存在"
        level = str(space.get("mode") or mode or "")
        if level not in {item.value for item in LockLevel}:
            return False, "档位不正确"
        try:
            value = int(minutes) if minutes not in (None, "") else int(space.get("minutes") or 25)
        except (TypeError, ValueError):
            return False, "时长不正确"
        value = max(SPACE_MIN_MINUTES, min(SPACE_MAX_MINUTES, value))
        self._begin_space_session(space, level, value, trial=False)
        return True, f"已开始专注（{value} 分钟）"

    def _web_admin_stop_session(self) -> tuple[bool, str]:
        """网页端结束专注：和桌面端一样受档位约束（覆清 / 深清不可提前结束）。"""
        if self._session.state is SessionState.IDLE:
            return False, "当前没有正在进行的专注"
        self.stopSession()
        if self._session.state is not SessionState.IDLE:
            return False, "当前档位不可提前结束，等计时走完"
        return True, "已结束专注"

    def _web_admin_install_item(self, item_id: str) -> tuple[bool, str]:
        """网页端安装商店条目（主题复用 installCustomTheme，插件复用安装流程）。"""
        item = self._store.get(item_id)
        if not item:
            return False, "商店里没有这个条目"
        name = str(item.get("name") or item_id)
        if str(item.get("kind")) == "theme":
            ok = self.installCustomTheme(
                str(item.get("id") or ""),
                name,
                str(item.get("summary") or ""),
                item.get("palette") or {},
            )
            return (True, f"已安装主题：{name}") if ok else (False, "主题安装失败")
        result = self.installStorePlugin(item_id) or {}
        if isinstance(result, dict):
            return bool(result.get("ok")), str(result.get("message") or "")
        return False, "插件安装失败"

    def _on_web_admin_setting(self, key: str, value: object) -> None:
        """网页改了设置：调用对应 Slot，让桌面端即时生效。"""
        if key == "theme_style":
            self.setThemeStyle(str(value))
        elif key == "theme_scheme":
            self.setThemeScheme(str(value))
        elif key == "theme_mode":
            # 兼容旧网页管理页：旧主题值映射成 样式 + 配色
            self.setThemeMode(str(value))
        elif key == "language":
            self.setLanguage(str(value))
        elif key == "ui_font_scale":
            self.setUIFontScale(float(value or 1.0))
        elif key == "ui_font_family":
            self.setUIFontFamily(str(value or ""))
        elif key == "nav_mode":
            self.setNavMode(str(value))
        elif key == "default_minutes":
            self.setDefaultMinutes(int(value or 25))
        elif key == "auto_update":
            self.setAutoUpdate(bool(value))
        elif key == "site_block_enabled":
            self.setSiteBlockEnabled(bool(value))
        elif key == "web_admin_enabled":
            # 从管理页里关自己：设置已写入，真正的停止交给 WebAdminService 延迟执行
            # （不能在请求线程里关掉正在回包的 HTTP 服务）
            self.settingsChanged.emit()
            self.webAdminChanged.emit()
        else:
            self.settingsChanged.emit()

    @Property(bool, notify=webAdminChanged)
    def webAdminEnabled(self) -> bool:
        """网页管理开关（设置项；不代表服务一定已成功启动）。"""
        return bool(self._settings.get("web_admin_enabled", False))

    @Property(str, notify=webAdminChanged)
    def webAdminUrl(self) -> str:
        """带 token 的管理页地址；服务未运行返回空字符串。"""
        running, url, _error = self._web_admin.status()
        return url if running else ""

    @Property(str, notify=webAdminChanged)
    def webAdminError(self) -> str:
        """网页管理最近一次错误（空 = 没有错误）。"""
        return self._web_admin.status()[2]

    def startWebAdmin(self) -> bool:
        """按设置启动服务（app.py 启动时调用；冒烟模式不调用）。"""
        if not self.webAdminEnabled:
            return False
        ok = self._web_admin.start()
        if ok:
            logger.info("网页管理已启动：%s", self._web_admin.url)
        else:
            logger.warning("网页管理启动失败：%s", self.webAdminError)
        self.webAdminChanged.emit()
        return ok

    def stopWebAdmin(self) -> None:
        self._web_admin.stop()
        self.webAdminChanged.emit()

    @Slot(bool)
    def setWebAdminEnabled(self, enabled: bool) -> None:
        """设置页开关：写入设置并即时启停服务。"""
        self._settings.set("web_admin_enabled", bool(enabled))
        ok = self._web_admin.set_enabled(bool(enabled))
        self.webAdminChanged.emit()
        if enabled and not ok:
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "网页管理启动失败：{0}").format(
                    self.webAdminError
                )
            )
        elif enabled:
            self.toast.emit(QCoreApplication.translate("ShenQing", "网页管理已启动"))
        else:
            self.toast.emit(QCoreApplication.translate("ShenQing", "网页管理已关闭"))
        self.settingsChanged.emit()

    @Slot()
    def openWebAdmin(self) -> None:
        """在系统浏览器里打开管理页。"""
        if not self._web_admin.running:
            self.startWebAdmin()
        url = self._web_admin.url
        if not url:
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "网页管理未启动：{0}").format(
                    self.webAdminError or "端口不可用"
                )
            )
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(url))

    @Slot(result=str)
    def regenerateWebAdminToken(self) -> str:
        """重新生成 token（旧的管理页地址立即失效）。"""
        token = self._web_admin.regenerate_token()
        self.webAdminChanged.emit()
        self.toast.emit(QCoreApplication.translate("ShenQing", "网页管理 token 已更新"))
        return token

    # ================= v0.20：账户同步（本机数据同步到深清商店服务器） =================
    # 后端接口：POST /api/auth/login、GET/PUT /api/sync（见 services/cloud_sync.py）。
    # 所有联网操作都在 QThreadPool 里跑，结果经 _cloudTaskResult 回主线程；
    # 拉取写回前自动备份当前数据（backups/cloud-pre-pull-*.json），写回后重新加载内存数据。
    @Property(str, notify=cloudChanged)
    def cloudSyncUrl(self) -> str:
        """商店服务器地址（空 = 未配置）。"""
        return str(self._settings.get("cloud_sync_url", "") or "")

    @Property(str, notify=cloudChanged)
    def cloudSyncEmail(self) -> str:
        """已登录 / 上次登录的邮箱（不存密码）。"""
        return str(self._settings.get("cloud_sync_email", "") or "")

    @Property(bool, notify=cloudChanged)
    def cloudSyncLoggedIn(self) -> bool:
        """是否已持有可用的登录令牌。"""
        return bool(str(self._settings.get("cloud_sync_token", "") or "").strip())

    @Property(str, notify=cloudChanged)
    def cloudSyncStatus(self) -> str:
        """最近一次同步动作的结果文案（空 = 还没同步过）。"""
        return self._cloud_status

    @Property(str, notify=cloudChanged)
    def cloudSyncLastAt(self) -> str:
        """上次成功同步时间（YYYY-MM-DD HH:MM）。"""
        return self._cloud_last_at

    @Property(str, notify=cloudChanged)
    def cloudSyncError(self) -> str:
        """最近一次失败原因（空 = 没有错误）。"""
        return self._cloud_error

    @Property(bool, notify=cloudChanged)
    def cloudSyncBusy(self) -> bool:
        """是否有同步任务在跑。"""
        return self._cloud_busy

    @Property(str, notify=cloudChanged)
    def cloudSyncDevice(self) -> str:
        """设备名：设置里有就用手填的，否则取电脑名。"""
        saved = str(self._settings.get("cloud_sync_device", "") or "").strip()
        if saved:
            return saved
        if not self._cloud_device:
            self._cloud_device = cloud_sync_service.default_device_name()
        return self._cloud_device

    # ---- 内部状态 ----
    def _cloud_url(self) -> str:
        return str(self._settings.get("cloud_sync_url", "") or "").strip()

    def _cloud_token(self) -> str:
        return str(self._settings.get("cloud_sync_token", "") or "").strip()

    def _cloud_revision(self) -> int:
        try:
            return max(0, int(self._settings.get("cloud_sync_revision", 0) or 0))
        except (TypeError, ValueError):
            return 0

    def _set_cloud_state(
        self,
        *,
        busy: bool | None = None,
        status: str | None = None,
        error: str | None = None,
        last_at: str | None = None,
    ) -> None:
        if busy is not None:
            self._cloud_busy = bool(busy)
        if status is not None:
            self._cloud_status = str(status or "")
        if error is not None:
            self._cloud_error = str(error or "")
        if last_at is not None:
            self._cloud_last_at = str(last_at or "")
        self.cloudChanged.emit()

    def _cloud_fail(self, message: object) -> None:
        """统一的失败处理：写错误、结束忙碌、弹 toast（不抛异常）。"""
        text = str(message or "").strip() or QCoreApplication.translate(
            "ShenQing", "同步失败"
        )
        self._set_cloud_state(busy=False, status="", error=text)
        logger.warning("账户同步失败：%s", text)
        self.toast.emit(text)

    def _mark_cloud_synced(self) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        self._settings.set("cloud_sync_last_at", stamp)
        self._cloud_last_at = stamp

    def _cloud_payload(self) -> dict:
        """导出同步快照（设置白名单 + 空间 + 专注统计）。"""
        try:
            return cloud_sync_service.build_payload(
                self._settings, self._spaces, self._stats
            )
        except Exception as exc:  # noqa: BLE001 - 导出失败也要给可读原因
            logger.warning("导出同步快照失败：%s", exc)
            return {}

    def _start_cloud_task(self, kind: str, job) -> None:  # noqa: ANN001
        QThreadPool.globalInstance().start(_CloudTask(self, kind, job))

    def _reload_after_cloud_pull(self) -> None:
        """拉取写回后重新读盘：设置 / 空间 / 统计立即生效（不需要重启）。"""
        try:
            self._settings.load()
        except Exception as exc:  # noqa: BLE001
            logger.warning("重新加载设置失败：%s", exc)
        try:
            self._spaces.load()
        except Exception as exc:  # noqa: BLE001
            logger.warning("重新加载空间失败：%s", exc)
        try:
            self._stats.load()
        except Exception as exc:  # noqa: BLE001
            logger.warning("重新加载统计失败：%s", exc)
        self.settingsChanged.emit()
        self.spacesChanged.emit()
        self.statsChanged.emit()
        # 云端的样式/配色可能变了：重新算窗口 chrome 与界面配色
        self.themeChanged.emit(self._chrome_theme())

    # ---- QML 动作 ----
    @Slot(str)
    def setCloudSyncUrl(self, url: str) -> None:
        """保存服务器地址（允许带或不带 https://）。"""
        text = str(url or "").strip()
        self._settings.set("cloud_sync_url", text)
        self._set_cloud_state()
        self.settingsChanged.emit()

    @Slot(str)
    def setCloudSyncDevice(self, name: str) -> None:
        """保存设备名（空 = 回到电脑名）。"""
        text = str(name or "").strip()[: cloud_sync_service.DEVICE_NAME_LIMIT]
        self._settings.set("cloud_sync_device", text)
        self._cloud_device = text or cloud_sync_service.default_device_name()
        self._set_cloud_state()

    @Slot(str, str, result=bool)
    def cloudLogin(self, email: str, password: str) -> bool:
        """登录商店账号：异步，返回是否已发起请求。"""
        if self._cloud_busy:
            return False
        url = self._cloud_url()
        email_text = str(email or "").strip() or self.cloudSyncEmail
        password_text = str(password or "")
        if not url:
            self._cloud_fail(QCoreApplication.translate("ShenQing", "请先填写商店服务器地址"))
            return False
        if not email_text or not password_text:
            self._cloud_fail(QCoreApplication.translate("ShenQing", "请填写邮箱和密码"))
            return False
        self._settings.set("cloud_sync_email", email_text)
        self._set_cloud_state(
            busy=True,
            status=QCoreApplication.translate("ShenQing", "正在登录…"),
            error="",
        )

        def _job() -> dict:
            try:
                token = cloud_sync_service.login(url, email_text, password_text)
            except Exception as exc:  # noqa: BLE001 - 网络/校验错误都给可读文案
                return {"ok": False, "error": str(exc) or "登录失败"}
            return {"ok": True, "token": token, "email": email_text}

        self._start_cloud_task("login", _job)
        return True

    @Slot()
    def cloudLogout(self) -> None:
        """退出登录：清掉本地令牌（不动云端数据）。"""
        self._settings.set("cloud_sync_token", "")
        self._settings.set("cloud_sync_revision", 0)
        self._set_cloud_state(
            busy=False,
            status=QCoreApplication.translate("ShenQing", "已退出登录"),
            error="",
        )
        self.toast.emit(QCoreApplication.translate("ShenQing", "已退出商店账号"))

    @Slot()
    def cloudPush(self) -> None:
        """仅上传：把本机快照推到云端。"""
        if self._cloud_busy:
            return
        url = self._cloud_url()
        token = self._cloud_token()
        if not url or not token:
            self._cloud_fail(
                QCoreApplication.translate("ShenQing", "请先填写服务器地址并登录")
            )
            return
        payload = self._cloud_payload()
        if not payload:
            self._cloud_fail(QCoreApplication.translate("ShenQing", "导出同步快照失败"))
            return
        revision = self._cloud_revision()
        device = self.cloudSyncDevice
        self._set_cloud_state(
            busy=True,
            status=QCoreApplication.translate("ShenQing", "正在上传…"),
            error="",
        )

        def _job() -> dict:
            try:
                ok, remote_revision = cloud_sync_service.push(
                    url, token, payload, revision, device
                )
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc) or "上传失败"}
            if not ok:
                return {"ok": False, "conflict": True, "revision": remote_revision}
            return {"ok": True, "revision": remote_revision}

        self._start_cloud_task("push", _job)

    @Slot()
    def cloudPull(self) -> None:
        """仅下载：拉取云端快照并写回本机（写前自动备份）。"""
        if self._cloud_busy:
            return
        url = self._cloud_url()
        token = self._cloud_token()
        if not url or not token:
            self._cloud_fail(
                QCoreApplication.translate("ShenQing", "请先填写服务器地址并登录")
            )
            return
        self._set_cloud_state(
            busy=True,
            status=QCoreApplication.translate("ShenQing", "正在下载…"),
            error="",
        )

        def _job() -> dict:
            try:
                remote = cloud_sync_service.pull(url, token)
                payload = remote.get("payload") or {}
                if not payload:
                    return {"ok": True, "empty": True, "revision": remote.get("revision", 0)}
                backup = cloud_sync_service.backup_current()
                applied = cloud_sync_service.apply_payload(payload)
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc) or "下载失败"}
            return {
                "ok": True,
                "revision": remote.get("revision", 0),
                "updated_at": remote.get("updated_at", ""),
                "backup": str(backup),
                "applied": applied,
            }

        self._start_cloud_task("pull", _job)

    @Slot()
    def cloudSyncNow(self) -> None:
        """立即同步：先拉取远端，远端更新则覆盖本机，否则上传；409 时以远端 revision 重试一次。"""
        if self._cloud_busy:
            return
        url = self._cloud_url()
        token = self._cloud_token()
        if not url or not token:
            self._cloud_fail(
                QCoreApplication.translate("ShenQing", "请先填写服务器地址并登录")
            )
            return
        payload = self._cloud_payload()
        if not payload:
            self._cloud_fail(QCoreApplication.translate("ShenQing", "导出同步快照失败"))
            return
        local_revision = self._cloud_revision()
        device = self.cloudSyncDevice
        self._set_cloud_state(
            busy=True,
            status=QCoreApplication.translate("ShenQing", "正在同步…"),
            error="",
        )

        def _job() -> dict:
            try:
                remote = cloud_sync_service.pull(url, token)
                remote_revision = max(0, int(remote.get("revision") or 0))
                remote_payload = remote.get("payload") or {}
                if remote_revision > local_revision and remote_payload:
                    backup = cloud_sync_service.backup_current()
                    applied = cloud_sync_service.apply_payload(remote_payload)
                    return {
                        "ok": True,
                        "action": "pull",
                        "revision": remote_revision,
                        "backup": str(backup),
                        "applied": applied,
                    }
                ok, new_revision = cloud_sync_service.push(
                    url, token, payload, local_revision, device
                )
                if ok:
                    return {"ok": True, "action": "push", "revision": new_revision}
                # 409：远端刚被别的设备更新过，用远端 revision 重试一次（覆盖远端）
                ok, new_revision = cloud_sync_service.push(
                    url, token, payload, new_revision, device
                )
                if ok:
                    return {"ok": True, "action": "push", "revision": new_revision}
                return {"ok": False, "conflict": True, "revision": new_revision}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc) or "同步失败"}

        self._start_cloud_task("now", _job)

    @Slot()
    def openCloudServer(self) -> None:
        """在系统浏览器里打开商店服务器的同步接口地址。"""
        url = self._cloud_url()
        if not url:
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "请先填写商店服务器地址")
            )
            return
        try:
            target = cloud_sync_service.api_url(url, cloud_sync_service.SYNC_PATH)
        except cloud_sync_service.CloudSyncError as exc:
            self.toast.emit(str(exc))
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(target))

    # ---- 后台任务结果（主线程） ----
    @Slot(str, object)
    def _on_cloud_task_result(self, kind: str, result: object) -> None:
        data = result if isinstance(result, dict) else {}
        handler = getattr(self, f"_on_cloud_{str(kind)}_done", None)
        if handler is None:
            self._set_cloud_state(busy=False)
            return
        try:
            handler(data)
        except Exception as exc:  # noqa: BLE001 - 回调异常不能让主线程崩
            logger.warning("处理账户同步结果失败：%s", exc)
            self._set_cloud_state(busy=False)

    def _on_cloud_login_done(self, data: dict) -> None:
        if not data.get("ok"):
            self._cloud_fail(str(data.get("error") or "登录失败"))
            return
        token = str(data.get("token") or "")
        if not token:
            self._cloud_fail("登录响应里没有 token，请检查服务器版本")
            return
        self._settings.set("cloud_sync_token", token)
        email = str(data.get("email") or "")
        if email:
            self._settings.set("cloud_sync_email", email)
        self._set_cloud_state(
            busy=False,
            status=QCoreApplication.translate("ShenQing", "已登录，可以同步了"),
            error="",
        )
        self.toast.emit(QCoreApplication.translate("ShenQing", "已登录商店账号"))

    def _on_cloud_push_done(self, data: dict) -> None:
        if not data.get("ok"):
            if data.get("conflict"):
                revision = int(data.get("revision") or 0)
                self._set_cloud_state(
                    busy=False,
                    status="",
                    error=QCoreApplication.translate(
                        "ShenQing",
                        "云端已有更新版本（revision {0}），请先「仅下载」再上传",
                    ).format(revision),
                )
                self.toast.emit(
                    QCoreApplication.translate(
                        "ShenQing", "上传已取消：云端有更新的数据，请先下载"
                    )
                )
                return
            self._cloud_fail(str(data.get("error") or "上传失败"))
            return
        revision = max(0, int(data.get("revision") or 0))
        self._settings.set("cloud_sync_revision", revision)
        self._mark_cloud_synced()
        self._set_cloud_state(
            busy=False,
            status=QCoreApplication.translate("ShenQing", "已上传（revision {0}）").format(
                revision
            ),
            error="",
        )
        self.toast.emit(QCoreApplication.translate("ShenQing", "已上传到云端"))

    def _on_cloud_pull_done(self, data: dict) -> None:
        if not data.get("ok"):
            self._cloud_fail(str(data.get("error") or "下载失败"))
            return
        if data.get("empty"):
            self._set_cloud_state(
                busy=False,
                status=QCoreApplication.translate(
                    "ShenQing", "云端还没有数据，先点「仅上传」"
                ),
                error="",
            )
            return
        revision = max(0, int(data.get("revision") or 0))
        self._reload_after_cloud_pull()
        self._settings.set("cloud_sync_revision", revision)
        self._mark_cloud_synced()
        applied = data.get("applied") if isinstance(data.get("applied"), dict) else {}
        self._set_cloud_state(
            busy=False,
            status=QCoreApplication.translate(
                "ShenQing", "已从云端恢复（revision {0}）"
            ).format(revision),
            error="",
        )
        logger.info(
            "账户同步：已从云端写回（设置 %s 项 / 空间 %s 个 / 记录 %s 条，备份 %s）",
            applied.get("settings", 0),
            applied.get("spaces", 0),
            applied.get("stats", 0),
            data.get("backup", ""),
        )
        self.toast.emit(
            QCoreApplication.translate("ShenQing", "已从云端恢复设置、空间与统计")
        )

    def _on_cloud_now_done(self, data: dict) -> None:
        if not data.get("ok"):
            if data.get("conflict"):
                self._set_cloud_state(
                    busy=False,
                    status="",
                    error=QCoreApplication.translate(
                        "ShenQing", "云端版本冲突，请稍后重试"
                    ),
                )
                self.toast.emit(
                    QCoreApplication.translate("ShenQing", "同步失败：云端版本冲突")
                )
                return
            self._cloud_fail(str(data.get("error") or "同步失败"))
            return
        revision = max(0, int(data.get("revision") or 0))
        action = str(data.get("action") or "push")
        if action == "pull":
            self._reload_after_cloud_pull()
        self._settings.set("cloud_sync_revision", revision)
        self._mark_cloud_synced()
        status = (
            QCoreApplication.translate("ShenQing", "已从云端恢复（revision {0}）")
            if action == "pull"
            else QCoreApplication.translate("ShenQing", "已上传（revision {0}）")
        )
        self._set_cloud_state(busy=False, status=status.format(revision), error="")
        self.toast.emit(
            QCoreApplication.translate("ShenQing", "已从云端恢复设置、空间与统计")
            if action == "pull"
            else QCoreApplication.translate("ShenQing", "已同步到云端")
        )

    # ================= 服务退出清理 =================
    def _shutdown_services(self) -> None:
        try:
            self._restore_site_block(force=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("退出恢复网站屏蔽失败：%s", exc)
        try:
            self._web_admin.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning("停止网页管理失败：%s", exc)
        try:
            self._click_counter.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning("停止点击统计失败：%s", exc)
        try:
            self._pomodoro.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning("停止清番番茄钟失败：%s", exc)
        try:
            self._restore_desktop_icons(force=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("恢复桌面图标失败：%s", exc)
        try:
            self._volume_timer.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning("停止系统音量刷新失败：%s", exc)
        try:
            self._app_usage.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("停止应用使用统计失败：%s", exc)
        try:
            self._save_ai_chats()
            self._save_ai_usage()
        except Exception as exc:  # noqa: BLE001
            logger.warning("保存 AI 历史/用量失败：%s", exc)
        try:
            self._ai.shutdown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("停止 AI 线程池失败：%s", exc)


    def _purge_legacy_plugins(self) -> None:
        """移除已下线的内置组件插件（含已安装数据）。"""
        legacy = ("com.shenqing.cw2widgets",)
        try:
            import shutil

            for plugin_id in legacy:
                for folder in (
                    app_data_dir() / "plugins" / plugin_id,
                    app_data_dir() / "plugin_data" / plugin_id,
                ):
                    if folder.exists():
                        shutil.rmtree(folder, ignore_errors=True)
                        logger.info("已移除旧插件数据：%s", folder)
            disabled = self._settings.get("disabled_plugins", [])
            if isinstance(disabled, list) and any(item in legacy for item in disabled):
                self._settings.set(
                    "disabled_plugins", [item for item in disabled if item not in legacy]
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("清理旧插件失败：%s", exc)

    @Property(str, notify=statsChanged)
    def dailyQuote(self) -> str:
        day = timesync.today()
        return QUOTES[day.toordinal() % len(QUOTES)] if QUOTES else ""

    @Property(dict, notify=statsChanged)
    def lastSession(self) -> dict:
        """最近一次专注：{spaceName, level, minutes, startMs, endMs, quote, avatarUrl, wallpaperUrl}。"""
        sessions = self._stats.sessions
        if not sessions:
            return {}
        item = sessions[-1]
        start_raw = str(item.get("start") or item.get("ts") or "")
        end_raw = str(item.get("ts") or "")
        start_dt = None
        end_dt = None
        try:
            start_dt = datetime.fromisoformat(start_raw)
        except (TypeError, ValueError):
            pass
        try:
            end_dt = datetime.fromisoformat(end_raw)
        except (TypeError, ValueError):
            end_dt = None
        if start_dt is None and end_dt is not None:
            start_dt = end_dt - timedelta(minutes=float(item.get("minutes", 0) or 0))
        if end_dt is None and start_dt is not None:
            end_dt = start_dt + timedelta(minutes=float(item.get("minutes", 0) or 0))
        day = start_dt.date() if start_dt is not None else timesync.today()
        return {
            "spaceName": str(item.get("space") or ""),
            "level": str(item.get("level") or ""),
            "minutes": float(item.get("minutes", 0) or 0),
            "startMs": int(start_dt.timestamp() * 1000) if start_dt else 0,
            "endMs": int(end_dt.timestamp() * 1000) if end_dt else 0,
            "clicks": int(item.get("clicks", 0) or 0),
            "quote": QUOTES[day.toordinal() % len(QUOTES)] if QUOTES else "",
            "avatarUrl": self.userAvatarUrl,
            "wallpaperUrl": self.bingWallpaperUrl,
        }

    @Slot(result=str)
    def shareSummary(self) -> str:
        """结束卡片分享文本（复制到剪贴板用）。"""
        card = self.todayFocusCard
        quote = str(card.get("quote") or "")
        return (
            f"深清 · {card.get('date', '')}\n"
            f"{card.get('timeRange', '')}  {card.get('spaceName', '')}\n"
            f"专注 {card.get('minutes', 0)} 分钟 · {card.get('sessions', 0)} 次\n"
            f"{quote}"
        )

    @Property(str, constant=True)
    def dataDir(self) -> str:
        """用户数据目录（%APPDATA%/ShenQing），供 QML 保存图片等。"""
        return str(app_data_dir())

    @Slot(result=str)
    def newSummaryImagePath(self) -> str:
        """生成一个可写的「今日专注卡片」PNG 路径（QML grabToImage 用）。"""
        from datetime import datetime

        folder = app_data_dir() / "summary"
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return ""
        return str(folder / f"focus-{datetime.now():%Y%m%d-%H%M%S}.png")

    @Slot(result=str)
    def saveSummaryImage(self) -> str:
        """预留：结束卡片图片保存由 QML 的 grabToImage 完成，后端暂不渲染。"""
        return ""

    @Property(bool, notify=settingsChanged)
    def onboardingDone(self) -> bool:
        return bool(self._settings.get("onboarding_done", False))

    @Slot(bool)
    def setOnboardingDone(self, done: bool) -> None:
        """旧接口（兼容旧 QML）：完成时等价于 finishOnboarding。"""
        if done:
            self.finishOnboarding()
            return
        self._settings.set("onboarding_done", False)
        self.settingsChanged.emit()

    @Property(bool, notify=settingsChanged)
    def needsOnboarding(self) -> bool:
        """v0.16：首次使用引导未完成时为 True（app.py 启动时先隐藏主窗口）。"""
        return not bool(self._settings.get("onboarding_done", False))

    @Slot()
    def finishOnboarding(self) -> None:
        """v0.16：引导完成：写 settings 并通知 app.py 显示主窗口。"""
        self._settings.set("onboarding_done", True)
        self.settingsChanged.emit()
        self.onboardingFinished.emit()

    @Property(list, notify=pluginsChanged)
    def pluginOverlayWidgets(self) -> list[dict]:
        """（兼容 v0.8）插件组件；按 overlayWidgetOrder 排序（未排的排后面）。

        v0.21 起 App.overlayWidgets 是「右侧组件布局」，插件组件用 App.pluginWidgets /
        本属性访问；LockOverlay 渲染插件组件时读 pluginWidgets 即可。
        """
        widgets = list(self.pluginWidgets)
        order = self.overlayWidgetOrder
        if not order:
            return widgets
        rank = {value: index for index, value in enumerate(order)}

        def _key(item: dict) -> int:
            key = f"{item.get('pluginId', '')}:{item.get('id', '')}"
            return rank.get(key, len(order))

        return sorted(widgets, key=_key)

    # ================= 右侧组件（v0.21，「组件预览」自定义右半屏） =================
    def _overlay_layout(self) -> list[dict]:
        """当前布局：设置缺失 / 类型不对时回退内置默认布局；空列表表示用户全删了。"""
        raw = self._settings.get("overlay_widgets", None)
        if not isinstance(raw, list):
            return overlay_widgets_service.default_layout()
        return overlay_widgets_service.normalize_layout(raw)

    def _save_overlay_layout(self, layout: list[dict]) -> None:
        self._settings.set("overlay_widgets", layout)
        self.overlayWidgetsChanged.emit()

    @Property(list, notify=overlayWidgetsChanged)
    def overlayWidgets(self) -> list[dict]:
        """右半屏组件布局：[{id,type,x,y,w,h,visible,props}]（坐标归一化到右半屏）。"""
        return self._overlay_layout()

    @Property(bool, notify=overlayWidgetsChanged)
    def overlayWidgetsEnabled(self) -> bool:
        """右半屏组件总开关。"""
        return bool(self._settings.get("overlay_widgets_enabled", True))

    @Property(list, constant=True)
    def widgetCatalog(self) -> list[dict]:
        """内置组件目录：type / name / desc / defaultSize / propsSchema（6 种）。"""
        return overlay_widgets_service.widget_catalog()

    @Slot(bool)
    def setOverlayWidgetsEnabled(self, enabled: bool) -> None:
        self._settings.set("overlay_widgets_enabled", bool(enabled))
        self.overlayWidgetsChanged.emit()

    @Slot(str, result=str)
    def addOverlayWidget(self, widget_type: str) -> str:
        """加一个组件，返回新组件 id；未知 type 或已满 12 个返回空串。"""
        before = self._overlay_layout()
        after = overlay_widgets_service.add_widget(before, widget_type)
        if len(after) <= len(before):
            return ""
        before_ids = {item.get("id") for item in before}
        new_id = ""
        for item in after:
            if item.get("id") not in before_ids:
                new_id = str(item.get("id") or "")
                break
        self._save_overlay_layout(after)
        return new_id

    @Slot(str, result=bool)
    def removeOverlayWidget(self, widget_id: str) -> bool:
        """删掉一个组件；id 不存在返回 False。"""
        before = self._overlay_layout()
        after = overlay_widgets_service.remove_widget(before, widget_id)
        if len(after) == len(before):
            return False
        self._save_overlay_layout(after)
        return True

    @Slot(str, str, result=bool)
    def updateOverlayWidgetJson(self, widget_id: str, patch_json: str) -> bool:
        """局部更新（QML 专用）：patch 只收 JSON 字符串。

        QML 无法调用参数类型为 object 的 PySide 槽（object = PyObjectWrapper，只接受
        Python 侧对象），因此 QML 走这个方法；Python 侧 / 单测继续用 updateOverlayWidget。
        """
        return self._apply_overlay_patch(widget_id, patch_json)

    @Slot(str, object, result=bool)
    def updateOverlayWidget(self, widget_id: str, patch: object) -> bool:
        """局部更新（Python API）：patch 支持 dict 或 JSON 字符串。"""
        return self._apply_overlay_patch(widget_id, patch)

    def _apply_overlay_patch(self, widget_id: str, patch: object) -> bool:
        """x / y / w / h / visible / props 局部更新（props 浅合并），非法 patch 返回 False。"""
        data: object = patch
        if isinstance(data, str):
            text = data.strip()
            if not text:
                return False
            try:
                data = json.loads(text)
            except (TypeError, ValueError):
                return False
        if not isinstance(data, dict):
            return False
        before = self._overlay_layout()
        after = overlay_widgets_service.update_widget(before, widget_id, data)
        if after == before:
            return False
        self._save_overlay_layout(after)
        return True

    @Slot()
    def resetOverlayWidgets(self) -> None:
        """恢复内置默认布局（clock / today / quote）。"""
        self._save_overlay_layout(overlay_widgets_service.reset_layout())

    # ---------- 天气组件（NMC，15 分钟缓存） ----------
    @Property(dict, notify=widgetDataChanged)
    def weatherWidgetData(self) -> dict:
        """天气卡片数据：{temp, tempValue, weather, city, updated}。"""
        if self._widget_weather:
            return dict(self._widget_weather)
        return {"temp": "", "tempValue": None, "weather": "", "city": "", "updated": ""}

    @Property(str, notify=widgetDataChanged)
    def weatherWidgetError(self) -> str:
        """天气失败文案（正常为空串）。"""
        return self._widget_weather_error

    @Property(str, notify=settingsChanged)
    def weatherCityId(self) -> str:
        """天气城市编号（设置项 weather_city_id，默认 58362 = 北京）。"""
        raw = self._settings.get("weather_city_id", overlay_widgets_service.DEFAULT_WEATHER_CITY)
        return str(raw or overlay_widgets_service.DEFAULT_WEATHER_CITY)

    @Slot(str)
    def setWeatherCityId(self, city_id: str) -> None:
        text = str(city_id or "").strip()
        self._settings.set(
            "weather_city_id", text or overlay_widgets_service.DEFAULT_WEATHER_CITY
        )
        self.settingsChanged.emit()
        self.refreshWidgetData()

    # ---------- 每日一言组件（hitokoto，失败回退内置文案） ----------
    @Property(str, notify=widgetDataChanged)
    def quoteWidgetText(self) -> str:
        return self._widget_quote_text

    @Property(str, notify=widgetDataChanged)
    def quoteWidgetSource(self) -> str:
        """来源："hitokoto"（在线）/"builtin"（内置回退）；未取到为空串。"""
        return self._widget_quote_source

    @Property(str, notify=widgetDataChanged)
    def quoteWidgetFrom(self) -> str:
        """一言出处（作者 / 书名），内置文案为「深清」。"""
        return self._widget_quote_from

    @Property(str, notify=widgetDataChanged)
    def quoteWidgetError(self) -> str:
        """一言在线失败原因（回退内置文案时非空）。"""
        return self._widget_quote_error

    def _widget_city_id(self) -> str:
        """天气城市：优先天气组件 props.cityId，其次设置 weather_city_id。"""
        for item in self._overlay_layout():
            if item.get("type") != "weather":
                continue
            props = item.get("props") if isinstance(item.get("props"), dict) else {}
            city = str(props.get("cityId") or "").strip()
            if city:
                return city
        raw = self._settings.get("weather_city_id", overlay_widgets_service.DEFAULT_WEATHER_CITY)
        return str(raw or overlay_widgets_service.DEFAULT_WEATHER_CITY)

    def _widget_quote_category(self) -> str:
        """一言分类：取自一言组件的 props.category（为空则用接口默认分类）。"""
        for item in self._overlay_layout():
            if item.get("type") != "quote":
                continue
            props = item.get("props") if isinstance(item.get("props"), dict) else {}
            category = str(props.get("category") or "").strip()
            if category:
                return category
        return ""

    @Slot()
    def refreshWidgetData(self) -> None:
        """后台（QThreadPool）刷新天气 + 每日一言，完成后 emit widgetDataChanged。"""
        if os.environ.get("SHENQING_NO_SCAN") == "1":  # 冒烟 / 单测不联网
            return
        if self._widget_refreshing:
            return
        self._widget_refreshing = True
        try:
            QThreadPool.globalInstance().start(
                _WidgetDataTask(self, self._widget_city_id(), self._widget_quote_category())
            )
        except Exception as exc:  # noqa: BLE001 - 线程池异常不能让组件永久卡在「刷新中」
            logger.warning("启动组件数据刷新失败：%s", exc)
            self._widget_refreshing = False

    @Slot(object)
    def _on_widget_data_ready(self, payload: object) -> None:
        """后台任务回主线程：保存天气 / 一言结果并通知 QML。"""
        data = payload if isinstance(payload, dict) else {}
        weather = data.get("weather")
        if isinstance(weather, dict):
            if weather.get("ok"):
                self._widget_weather = {
                    "temp": str(weather.get("temp") or ""),
                    "tempValue": weather.get("tempValue"),
                    "weather": str(weather.get("weather") or ""),
                    "city": str(weather.get("city") or ""),
                    "updated": str(weather.get("updated") or ""),
                }
                self._widget_weather_error = ""
            else:
                self._widget_weather_error = str(weather.get("error") or "天气获取失败")
        quote = data.get("quote")
        if isinstance(quote, dict) and quote.get("text"):
            self._widget_quote_text = str(quote.get("text") or "")
            self._widget_quote_source = str(quote.get("source") or "")
            self._widget_quote_from = str(quote.get("from") or "")
            self._widget_quote_error = str(quote.get("error") or "")
        self._widget_refreshing = False
        self.widgetDataChanged.emit()

    @Property(list, notify=statsChanged)
    def recentSessions(self) -> list[dict]:
        """最近会话明细（数据页列表用，最多 30 条，倒序）。"""
        items = self._stats.sessions[-30:]
        result: list[dict] = []
        for item in reversed(items):
            start_raw = str(item.get("start") or item.get("ts") or "")
            end_raw = str(item.get("ts") or "")
            start_dt = None
            end_dt = None
            try:
                start_dt = datetime.fromisoformat(start_raw)
            except (TypeError, ValueError):
                pass
            try:
                end_dt = datetime.fromisoformat(end_raw)
            except (TypeError, ValueError):
                end_dt = None
            result.append(
                {
                    "date": str(item.get("date") or ""),
                    "spaceName": str(item.get("space") or ""),
                    "level": str(item.get("level") or ""),
                    "minutes": float(item.get("minutes", 0) or 0),
                    "completed": bool(item.get("completed", False)),
                    "startMs": int(start_dt.timestamp() * 1000) if start_dt else 0,
                    "endMs": int(end_dt.timestamp() * 1000) if end_dt else 0,
                }
            )
        return result

    @Property(list, notify=settingsChanged)
    def overlayWidgetOrder(self) -> list[str]:
        raw = self._settings.get("overlay_widget_order", [])
        return [str(item) for item in raw] if isinstance(raw, list) else []

    @Slot(list)
    def setOverlayWidgetOrder(self, ids: list) -> None:
        self._settings.set("overlay_widget_order", [str(item) for item in ids])
        self.settingsChanged.emit()
        self.pluginsChanged.emit()

    @Property(int, notify=settingsChanged)
    def countdownDays(self) -> int:
        """倒数日剩余天数；未设置返回 -1。"""
        raw = str(self._settings.get("countdown_date", "") or "")
        if not raw:
            return -1
        try:
            target = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            return -1
        return (target - timesync.today()).days

    @Property(str, notify=settingsChanged)
    def countdownDate(self) -> str:
        return str(self._settings.get("countdown_date", "") or "")

    @Slot(str)
    def setCountdownDate(self, date_text: str) -> None:
        text = str(date_text or "").strip()
        if text:
            try:
                datetime.strptime(text, "%Y-%m-%d")
            except ValueError:
                self.toast.emit(QCoreApplication.translate("ShenQing", "日期格式应为 YYYY-MM-DD"))
                return
        self._settings.set("countdown_date", text)
        self.settingsChanged.emit()

    def _begin_space_session(
        self,
        space: dict | None,
        level: str,
        minutes: int,
        *,
        trial: bool = False,
        seconds: int | None = None,
        persist_state: bool = True,
        end_at_ms: int | None = None,
        started_at_ms: int | None = None,
        paused: bool = False,
        recovered: bool = False,
    ) -> None:
        """以某张空间为载体开始一轮专注（时长/白名单取该空间，档位由调用方决定）。"""
        if self._session.state is not SessionState.IDLE:
            self.toast.emit(QCoreApplication.translate("ShenQing", "已经有正在进行的专注"))
            return
        if level not in {item.value for item in LockLevel}:
            return
        self._active_space_id = str(space.get("id") or "") if space else ""
        self._session_level = level
        self._trial_active = bool(trial)
        self._preview_active = False
        self._preview_level = ""
        # 深清空间不设置白名单：heavy 会话只保留系统进程（DEFAULT_WHITELIST），
        # 即使旧数据里残留 allowed_apps 也不加载。
        if level == LockLevel.HEAVY.value:
            whitelist: list[str] = []
        else:
            whitelist = [str(a) for a in (space.get("allowed_apps", []) if space else [])]
        self._guard.configure(
            blacklist=self._blocklist.processes,
            whitelist=whitelist,
            strict=level == LockLevel.HEAVY.value,
            keep_alive=bool(self._settings.get("keep_alive", True)),
        )
        self._guard.set_interval(int(self._settings.get("guard_interval_ms", 1000)))
        self._guard.start()
        if started_at_ms:
            try:
                self._session_started_at = datetime.fromtimestamp(
                    int(started_at_ms) / 1000.0
                ).astimezone()
            except (OverflowError, OSError, ValueError):
                self._session_started_at = timesync.now()
        else:
            self._session_started_at = timesync.now()
        power.keep_awake()
        pause_limit = int(self._settings.get("pause_limit", 2))
        if seconds is not None:
            self._session.start_seconds(
                max(1, int(seconds)),
                pause_limit,
                total_seconds=max(1, int(minutes)) * 60 if minutes else None,
                paused=bool(paused),
            )
        else:
            self._session.start(int(minutes), pause_limit)
        # 点击计数从 0 开始（会话中统计全局左键点击）
        self._reset_click_tracking()
        self._time_clicks.clear()
        self._exit_warning = False
        self._force_interrupt = False
        self.lockedChanged.emit()
        if persist_state and not trial:
            self._write_session_state(end_at_ms=end_at_ms)
        self._apply_site_block()
        self._apply_desktop_icons(str(level))
        if recovered:
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "检测到未完成的专注，已恢复锁定")
            )
        payload = (
            self._space_view(space)
            if space
            else {"name": QCoreApplication.translate("ShenQing", "速启")}
        )
        payload["level"] = level
        payload["trial"] = bool(trial)
        self._dispatch("session_start", payload)

    # ================= v0.22 桌面图标隐藏 =================
    @Property(bool, notify=settingsChanged)
    def hideDesktopIcons(self) -> bool:
        return bool(self._settings.get("hide_desktop_icons", True))

    @Slot(bool)
    def setHideDesktopIcons(self, enabled: bool) -> None:
        self._settings.set("hide_desktop_icons", bool(enabled))

    def _apply_desktop_icons(self, level: str) -> None:
        """浅清 / 覆清开始专注时隐藏桌面图标（深清由遮罩全屏覆盖，无需处理）。"""
        if not self.hideDesktopIcons or level not in ("light", "medium"):
            return
        if desktop_icons.hide_desktop_icons():
            self._desktop_icons_hidden = True

    def _restore_desktop_icons(self, force: bool = False) -> None:
        if not (force or self._desktop_icons_hidden):
            return
        desktop_icons.show_desktop_icons()
        self._desktop_icons_hidden = False

    # ================= v0.15 网站屏蔽（hosts） =================
    @Property(list, notify=settingsChanged)
    def blockedSites(self) -> list[str]:
        values = self._settings.get("blocked_sites", [])
        return site_blocker.normalize_domains(values if isinstance(values, list) else [])

    @Slot(str, result=bool)
    def addBlockedSite(self, value: str) -> bool:
        domain = site_blocker.normalize_domain(value)
        if not domain:
            self.toast.emit(QCoreApplication.translate("ShenQing", "域名格式不正确"))
            return False
        sites = self.blockedSites
        if domain in sites:
            self.toast.emit(QCoreApplication.translate("ShenQing", "该网站已在屏蔽列表"))
            return False
        sites.append(domain)
        self._settings.set("blocked_sites", sites)
        self.settingsChanged.emit()
        self.toast.emit(
            QCoreApplication.translate("ShenQing", "已添加屏蔽网站：{0}").format(domain)
        )
        return True

    @Slot(str, result=bool)
    def removeBlockedSite(self, value: str) -> bool:
        domain = site_blocker.normalize_domain(value)
        if not domain:
            return False
        sites = self.blockedSites
        if domain not in sites:
            return False
        sites.remove(domain)
        self._settings.set("blocked_sites", sites)
        self.settingsChanged.emit()
        return True

    @Property(bool, notify=settingsChanged)
    def siteBlockEnabled(self) -> bool:
        return bool(self._settings.get("site_block_enabled", True))

    @Slot(bool)
    def setSiteBlockEnabled(self, enabled: bool) -> None:
        self._settings.set("site_block_enabled", bool(enabled))
        if self.busy:
            if enabled:
                self._apply_site_block()
            else:
                self._restore_site_block(force=True)
        self.settingsChanged.emit()

    def _apply_site_block(self) -> None:
        sites = self.blockedSites
        if not self.siteBlockEnabled or not sites:
            return
        ok, message = self._site_blocker.apply(sites)
        self._site_block_applied = ok
        if ok:
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "已屏蔽 {0} 个网站").format(len(sites))
            )
        else:
            self.toast.emit(message)

    def _restore_site_block(self, force: bool = False) -> None:
        if not force and not self._site_block_applied:
            return
        ok, message = self._site_blocker.restore()
        self._site_block_applied = False
        if not ok:
            logger.warning("恢复网站屏蔽失败：%s", message)

    def cleanup_stale_site_block(self) -> bool:
        """应用启动时清理上次崩溃残留的 hosts 屏蔽段。"""
        ok, message = self._site_blocker.cleanup_stale()
        if not ok:
            logger.warning("清理残留网站屏蔽失败：%s", message)
        return ok

    # ================= v0.15 结束卡片背景 =================
    @Property(str, notify=settingsChanged)
    def cardBackgroundUrl(self) -> str:
        custom = str(self._settings.get("card_background", "") or "")
        return wallpaper.card_background_url(custom, self.bingWallpaperUrl)

    @Slot(result=str)
    def pickCardBackground(self) -> str:
        from PySide6.QtWidgets import QFileDialog

        try:
            selected, _filter = QFileDialog.getOpenFileName(
                None,
                QCoreApplication.translate("ShenQing", "选择结束卡片背景"),
                str(Path.home()),
                QCoreApplication.translate("ShenQing", "图片 (*.png *.jpg *.jpeg *.webp)"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("打开背景选择对话框失败：%s", exc)
            return ""
        if not selected:
            return ""
        saved = wallpaper.save_card_background(selected)
        if not saved:
            self.toast.emit(QCoreApplication.translate("ShenQing", "背景图片无效"))
            return ""
        self._settings.set("card_background", saved)
        self.settingsChanged.emit()
        return saved

    @Slot(str, result=bool)
    def setCardBackground(self, path: str) -> bool:
        saved = wallpaper.save_card_background(path)
        if not saved:
            self.toast.emit(QCoreApplication.translate("ShenQing", "背景图片无效"))
            return False
        self._settings.set("card_background", saved)
        self.settingsChanged.emit()
        return True

    @Slot()
    def clearCardBackground(self) -> None:
        self._settings.set("card_background", "")
        self.settingsChanged.emit()

    # ================= v0.14 点击计数 / 专注恢复 =================
    @Property(int, notify=tickChanged)
    def sessionClicks(self) -> int:
        if self.busy:
            return int(self._session_clicks)
        return int(self._last_session_clicks)

    @Property(int, notify=statsChanged)
    def todayClicks(self) -> int:
        return int(self._stats.clicks_on(timesync.today()))

    @Property(int, notify=statsChanged)
    def lastSessionClicks(self) -> int:
        stored = int(self._stats.last_session().get("clicks", 0) or 0)
        return int(self._last_session_clicks or stored)

    def _reset_click_tracking(self) -> None:
        self._session_clicks = 0
        try:
            if os.environ.get("SHENQING_NO_SCAN") == "1":
                # 冒烟/单测环境不安装全局鼠标钩子
                self._click_counter.reset()
            else:
                self._click_counter.start()
        except Exception as exc:  # noqa: BLE001
            logger.warning("启动点击统计失败：%s", exc)
        self.tickChanged.emit()

    def _stop_click_tracking(self) -> int:
        try:
            clicks = int(self._click_counter.stop())
        except Exception as exc:  # noqa: BLE001
            logger.warning("停止点击统计失败：%s", exc)
            clicks = int(self._session_clicks)
        self._session_clicks = clicks
        self._last_session_clicks = clicks
        return clicks

    def _on_click_count_changed(self, count: int) -> None:
        self._session_clicks = int(count)
        if self.busy:
            self.tickChanged.emit()

    # ---------- 会话状态持久化（崩溃/被杀恢复） ----------
    def _write_session_state(self, end_at_ms: int | None = None) -> None:
        try:
            now = timesync.now()
            remaining = max(0, int(self._session.remaining))
            end_at = int(end_at_ms) if end_at_ms else int(now.timestamp() * 1000) + remaining * 1000
            payload = {
                "spaceId": self._active_space_id,
                "mode": self._session_level,
                "endAt": end_at,
                "startedAt": int(self._session_started_at.timestamp() * 1000),
                "planSeconds": int(self._session.total),
                "paused": self._session.state is SessionState.PAUSED,
                "remainingSeconds": remaining,
            }
            self._session_state_path.parent.mkdir(parents=True, exist_ok=True)
            self._session_state_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001 - 状态持久化失败不能影响专注
            logger.warning("写入会话状态失败：%s", exc)

    def _delete_session_state(self) -> None:
        try:
            self._session_state_path.unlink()
        except OSError:
            pass

    def _read_session_state(self) -> dict | None:
        try:
            data = json.loads(self._session_state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def restore_session_if_needed(self) -> bool:
        """启动时恢复未完成的专注：未到期重新锁定，已到期补记统计并清理。"""
        state = self._read_session_state()
        if not state:
            return False
        try:
            end_at = int(state.get("endAt") or 0)
            started_at = int(state.get("startedAt") or 0)
            plan_seconds = int(state.get("planSeconds") or 0)
        except (TypeError, ValueError):
            self._delete_session_state()
            return False
        if end_at <= 0:
            self._delete_session_state()
            return False
        level = str(state.get("mode") or self.lockLevel)
        now = timesync.now()
        if int(now.timestamp() * 1000) >= end_at:
            # 已到期：按原时长补记统计，不锁屏
            minutes = round(plan_seconds / 60.0, 1)
            if minutes <= 0 and started_at:
                minutes = round(max(0, end_at - started_at) / 60000.0, 1)
            space = self._spaces.get(str(state.get("spaceId") or ""))
            if space is None:
                space = self._spaces.get_by_mode(level)
            space_name = str(space.get("name")) if space else ""
            try:
                ended_at = datetime.fromtimestamp(end_at / 1000.0).astimezone()
                started_dt = (
                    datetime.fromtimestamp(started_at / 1000.0).astimezone()
                    if started_at
                    else ended_at - timedelta(minutes=minutes)
                )
                if minutes >= 1:
                    self._stats.record(
                        minutes,
                        level,
                        True,
                        0,
                        space=space_name,
                        when=ended_at,
                        started_at=started_dt,
                        clicks=0,
                        recovered=True,
                    )
                    self.statsChanged.emit()
                    self.toast.emit(
                        QCoreApplication.translate(
                            "ShenQing", "上次专注已完成，已补记统计"
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("补记恢复会话统计失败：%s", exc)
            self._delete_session_state()
            self.stateChanged.emit()
            return False
        # 未到期：恢复锁定
        space = self._spaces.get(str(state.get("spaceId") or ""))
        if space is None:
            space = self._spaces.get_by_mode(level)
        remaining = max(1, int(round((end_at - int(now.timestamp() * 1000)) / 1000.0)))
        if bool(state.get("paused")):
            try:
                remaining = max(1, int(state.get("remainingSeconds") or remaining))
            except (TypeError, ValueError):
                pass
        minutes = max(1, int(round(plan_seconds / 60.0))) if plan_seconds else max(
            1, int(round(remaining / 60.0))
        )
        self._begin_space_session(
            space,
            level,
            minutes,
            seconds=remaining,
            persist_state=True,
            end_at_ms=end_at,
            started_at_ms=started_at or None,
            paused=bool(state.get("paused")),
            recovered=True,
        )
        return True

    @Slot(str)
    def startSpace(self, space_id: str) -> None:
        """按该空间自己的时长 / 白名单 / 档位开始一轮专注。"""
        space = self._spaces.get(space_id)
        if space is None:
            self.toast.emit(QCoreApplication.translate("ShenQing", "空间不存在"))
            return
        if self._session.state is not SessionState.IDLE:
            self.toast.emit(QCoreApplication.translate("ShenQing", "已经有正在进行的专注"))
            return
        # 先进入 10 秒倒计时（水滴凝聚），期间可取消
        self._begin_prepare(space)

    @Slot(str)
    def startLevel(self, level: str) -> None:
        """速启面板：不选空间，直接按强度开始一轮专注。"""
        if level not in {item.value for item in LockLevel}:
            return
        minutes = int(self._settings.get("default_minutes", 45))
        # 速启用该档第一张空间做载体（白名单取它，时长仍按设置）
        space = self._spaces.get_by_mode(level) or self._spaces.get_by_mode("medium")
        if self._session.state is not SessionState.IDLE:
            self.toast.emit(QCoreApplication.translate("ShenQing", "已经有正在进行的专注"))
            return
        self._begin_prepare(space, minutes)

    # ================= v0.21 开始专注二次确认 =================
    #: 白名单摘要在确认卡里最多列几个应用
    CONFIRM_WHITELIST_PREVIEW = 6

    def _start_denial(self) -> str:
        """当前能不能开始：返回中文拒绝原因，空串表示可以。"""
        if self._session.state is not SessionState.IDLE:
            return QCoreApplication.translate("ShenQing", "已经有正在进行的专注")
        return ""

    def _space_start_minutes(self, space: dict, minutes: int = 0) -> int:
        """本次专注时长：显式指定 > 空间自己的时长 > 默认时长。"""
        if int(minutes or 0) > 0:
            return int(minutes)
        try:
            value = int((space or {}).get("minutes") or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
        try:
            return max(MIN_MINUTES, int(self._settings.get("default_minutes", MIN_MINUTES)))
        except (TypeError, ValueError):
            return MIN_MINUTES

    def _whitelist_summary(self, space: dict) -> str:
        """确认卡里的白名单摘要（深清不设白名单，返回空串）。"""
        mode = str((space or {}).get("mode") or "")
        if mode == "heavy":
            return ""
        apps = [str(app) for app in ((space or {}).get("allowed_apps") or []) if str(app)]
        if not apps:
            return QCoreApplication.translate("ShenQing", "不限制应用（白名单为空）")
        shown = apps[: max(1, int(self.CONFIRM_WHITELIST_PREVIEW))]
        text = "、".join(shown)
        if len(apps) > len(shown):
            text += QCoreApplication.translate("ShenQing", " 等 {0} 个").format(len(apps))
        return QCoreApplication.translate("ShenQing", "允许 {0} 个应用：{1}").format(
            len(apps), text
        )

    def _confirmation_payload(self, space: dict, minutes: int) -> dict:
        mode = str((space or {}).get("mode") or "")
        allowed = 0
        if mode != "heavy":
            allowed = len((space or {}).get("allowed_apps") or [])
        return {
            "spaceId": str((space or {}).get("id") or ""),
            "spaceName": str((space or {}).get("name") or ""),
            "mode": mode,
            "modeLabel": MODE_LABELS.get(mode, mode),
            "minutes": int(minutes),
            "allowedCount": int(allowed),
            "whitelistSummary": self._whitelist_summary(space),
        }

    @Property(bool, notify=confirmationChanged)
    def confirmationActive(self) -> bool:
        """是否有等待确认的开局（QML 确认卡的显隐开关）。"""
        return bool(self._start_pending)

    @Property(dict, notify=confirmationChanged)
    def confirmationPending(self) -> dict:
        """待确认的开局信息（空 dict = 没有）。"""
        return dict(self._start_pending)

    @Property(dict, notify=confirmationChanged)
    def confirmationSummary(self) -> dict:
        """confirmationPending 的别名（QML 确认卡读它）。"""
        return dict(self._start_pending)

    def _pending_start(
        self, space_id: str = "", mode: str = "", minutes: int = 0
    ) -> bool:
        """登记一次待确认开局（不开始倒计时）。"""
        denial = self._start_denial()
        if denial:
            self.toast.emit(denial)
            return False
        space = self._spaces.get(str(space_id or "")) if space_id else None
        if space is None and mode:
            space = self._spaces.get_by_mode(mode)
        if space is None:
            self.toast.emit(QCoreApplication.translate("ShenQing", "空间不存在"))
            return False
        resolved = self._space_start_minutes(space, minutes)
        self._start_pending = self._confirmation_payload(space, resolved)
        self.confirmationChanged.emit()
        self.stateChanged.emit()
        return True

    @Slot(str, result=bool)
    def requestStart(self, space_id: str) -> bool:
        """QML「开始」第一步：按空间登记待确认（确认后走 confirmStart）。"""
        return self._pending_start(space_id=str(space_id or ""))

    @Slot(str, result=bool)
    def requestStartMode(self, mode: str) -> bool:
        """QML 速启面板：按档位登记待确认（取该档第一张空间）。"""
        value = str(mode or "")
        if value not in {item.value for item in LockLevel}:
            return False
        return self._pending_start(mode=value)

    @Slot(str, result=bool)
    def requestStartLevel(self, level: str) -> bool:
        """按档位登记待确认，时长取 default_minutes（与 startLevel 一致）。"""
        value = str(level or "")
        if value not in {item.value for item in LockLevel}:
            return False
        try:
            minutes = max(MIN_MINUTES, int(self._settings.get("default_minutes", MIN_MINUTES)))
        except (TypeError, ValueError):
            minutes = MIN_MINUTES
        return self._pending_start(mode=value, minutes=minutes)

    @Slot(result=bool)
    def confirmStart(self) -> bool:
        """确认开局：真正进入 10 秒倒计时并开始专注。"""
        info = dict(self._start_pending)
        if not info:
            return False
        self._clear_start_pending()
        denial = self._start_denial()
        if denial:
            self.toast.emit(denial)
            return False
        space = self._spaces.get(str(info.get("spaceId") or ""))
        if space is None:
            space = self._spaces.get_by_mode(str(info.get("mode") or ""))
        if space is None:
            self.toast.emit(QCoreApplication.translate("ShenQing", "空间不存在"))
            return False
        minutes = int(info.get("minutes") or 0)
        self._begin_prepare(space, minutes or None)
        return True

    @Slot(result=bool)
    def cancelStart(self) -> bool:
        """取消待确认开局（不开始专注）。"""
        if not self._start_pending:
            return False
        self._clear_start_pending()
        return True

    def _clear_start_pending(self) -> None:
        if not self._start_pending:
            return
        self._start_pending = {}
        self.confirmationChanged.emit()
        self.stateChanged.emit()

    @Slot()
    def pauseSession(self) -> None:
        """v0.16：只有浅清可暂停；覆清 / 深清与还清一样没有暂停。"""
        if self._session_level == LockLevel.MEDIUM.value:
            self.toast.emit(QCoreApplication.translate("ShenQing", "覆清没有暂停，等计时走完"))
            return
        if self._session_level == LockLevel.HEAVY.value:
            self.toast.emit(QCoreApplication.translate("ShenQing", "重度模式不可暂停"))
            return
        if self._session_level != LockLevel.LIGHT.value:
            self.toast.emit(QCoreApplication.translate("ShenQing", "当前档位不可暂停"))
            return
        if not self._session.pause():
            self.toast.emit(QCoreApplication.translate("ShenQing", "暂停次数已用完"))
            return
        if self._session.state is SessionState.PAUSED:
            self._write_session_state()

    @Slot()
    def resumeSession(self) -> None:
        if self._session.resume():
            self._write_session_state()

    @Slot()
    def stopSession(self) -> None:
        """v0.16：覆清 / 深清不可提前结束（体验模式仍允许退出）。"""
        if self._session.state is SessionState.IDLE:
            return
        if self._session_level in (
            LockLevel.MEDIUM.value,
            LockLevel.HEAVY.value,
        ) and not self._trial_active:
            if self._session_level == LockLevel.MEDIUM.value:
                self.toast.emit(
                    QCoreApplication.translate("ShenQing", "覆清不可提前结束，等计时走完")
                )
            else:
                self.toast.emit(
                    QCoreApplication.translate("ShenQing", "深清档不可提前结束，等计时走完")
                )
            return
        self._session.stop()

    # ================= v0.16 连点时间显示 10 次 → 警告退出 =================
    @Property(bool, notify=stateChanged)
    def exitWarningPending(self) -> bool:
        """是否已弹出「确认退出」警告（QML 用来显示确认框）。"""
        return self._exit_warning

    @Slot(result=bool)
    def registerTimeClick(self) -> bool:
        """时间显示连点计数：6 秒内第 10 次 emit exitWarningRequested。

        只有覆清 / 深清生效（浅清本来就能暂停/退出，不需要这条通道）。
        返回是否触发了退出警告。
        """
        if not self.busy or self._session_level not in (
            LockLevel.MEDIUM.value,
            LockLevel.HEAVY.value,
        ):
            return False
        now = time.monotonic()
        while self._time_clicks and now - self._time_clicks[0] > TIME_CLICK_WINDOW_SECONDS:
            self._time_clicks.popleft()
        self._time_clicks.append(now)
        if len(self._time_clicks) < TIME_CLICK_LIMIT:
            return False
        self._time_clicks.clear()
        if self._exit_warning:
            return False
        self._exit_warning = True
        self.exitWarningRequested.emit()
        self.stateChanged.emit()
        return True

    @Slot()
    def cancelExitWarning(self) -> None:
        """取消退出警告并清空连点计数。"""
        self._time_clicks.clear()
        if self._exit_warning:
            self._exit_warning = False
            self.stateChanged.emit()

    @Slot()
    def confirmExitSession(self) -> None:
        """确认退出：强制结束当前覆清 / 深清会话，统计标记 interrupted。"""
        if not self.busy:
            self.cancelExitWarning()
            return
        if self._session_level not in (
            LockLevel.MEDIUM.value,
            LockLevel.HEAVY.value,
        ):
            self.cancelExitWarning()
            return
        self.cancelExitWarning()
        self._force_interrupt = True
        self._session.stop()

    # ================= 统计 / 设置 =================
    @Property(float, notify=statsChanged)
    def todayMinutes(self) -> float:
        return self._stats.today_minutes(timesync.today())

    @Property(float, notify=statsChanged)
    def weekMinutes(self) -> float:
        return self._stats.week_minutes(timesync.today())

    @Property(int, notify=statsChanged)
    def streakDays(self) -> int:
        return self._stats.streak_days(timesync.today())

    @Property(int, notify=statsChanged)
    def sessionCount(self) -> int:
        return self._stats.total_sessions()

    @Property(list, notify=statsChanged)
    def last7Days(self) -> list[dict]:
        return self._stats.last_7_days(timesync.today())

    @Property(list, constant=True)
    def presetMinutes(self) -> list[int]:
        return list(PRESET_MINUTES)

    @Property(int, constant=True)
    def minMinutes(self) -> int:
        return MIN_MINUTES

    @Property(int, constant=True)
    def maxMinutes(self) -> int:
        return MAX_MINUTES

    @Property(str, notify=settingsChanged)
    def lockLevel(self) -> str:
        return str(self._settings.get("lock_level", LockLevel.MEDIUM.value))

    @Property(int, notify=settingsChanged)
    def defaultMinutes(self) -> int:
        return int(self._settings.get("default_minutes", 25))

    @Property(bool, notify=settingsChanged)
    def autostartEnabled(self) -> bool:
        return self._autostart.is_enabled()

    # ---------- 权限 / 防退出 ----------
    @Property(bool, notify=settingsChanged)
    def isAdmin(self) -> bool:
        return elevation.is_admin()

    @Property(bool, notify=settingsChanged)
    def hardeningEnabled(self) -> bool:
        return bool(self._settings.get("hardening", True))

    @Property(bool, notify=settingsChanged)
    def navExpanded(self) -> bool:
        return bool(self._settings.get("nav_expanded", False))

    @Slot(bool)
    def setNavExpanded(self, expanded: bool) -> None:
        self._settings.set("nav_expanded", bool(expanded))
        self.settingsChanged.emit()

    # ---------- v0.12 UI 字体 / 字号 / 导航模式 ----------
    @Property(str, notify=settingsChanged)
    def uiFontFamily(self) -> str:
        return str(self._settings.get("ui_font_family", "") or "")

    @Slot(str)
    def setUIFontFamily(self, family: str) -> None:
        self._settings.set("ui_font_family", str(family or "").strip())
        self.settingsChanged.emit()

    @Property(list, constant=True)
    def uiFontFamilies(self) -> list[str]:
        """CW2 风格字体列表：精选中文字体（已安装才加，按固定顺序）→ 其他系统字体（排序）。

        - 过滤 @ 开头的竖排字体、去重、最多 MAX_FONT_FAMILIES 条；
        - 离屏/无字体目录环境枚举为空时，仍返回默认字体兜底，避免下拉框空白。
        """
        try:
            from PySide6.QtGui import QFontDatabase

            available = {
                str(name).strip()
                for name in QFontDatabase.families()
                if name and not str(name).startswith("@")
            }
            if not available:
                # 离屏/无字体目录环境可能枚举为空：至少返回默认字体，避免下拉框空白
                fallback = str(self.defaultFontFamily or "Sans Serif")
                return [fallback]
            result: list[str] = []
            seen: set[str] = set()
            # 1) 精选中文字体：已安装的才加，按固定顺序排在顶部
            for family in PREFERRED_CJK_FONTS:
                if family in available and family not in seen:
                    result.append(family)
                    seen.add(family)
            # 2) 其余系统字体：按名称排序跟在后面
            for family in sorted(available):
                if family in seen:
                    continue
                result.append(family)
                seen.add(family)
                if len(result) >= MAX_FONT_FAMILIES:
                    break
            return result[:MAX_FONT_FAMILIES]
        except Exception:  # noqa: BLE001 - 字体枚举失败不能影响界面
            return []

    #: 内置默认字体（v0.17：默认仍是微软雅黑）
    DEFAULT_FONT_FAMILY = "Microsoft YaHei UI"
    DEFAULT_FONT_FAMILY_ALIASES = ("Microsoft YaHei UI", "微软雅黑")

    @Property(str, constant=True)
    def defaultFontFamily(self) -> str:
        """内置默认字体（QML 在 ui_font_family 为空时使用）：优先微软雅黑 UI。"""
        try:
            from PySide6.QtGui import QFontDatabase

            installed = {str(name) for name in QFontDatabase.families()}
            for family in self.DEFAULT_FONT_FAMILY_ALIASES:
                if family in installed:
                    return family
        except Exception:  # noqa: BLE001 - 字体枚举失败不致命
            pass
        try:
            from PySide6.QtWidgets import QApplication

            application = QApplication.instance()
            if application is not None:
                return str(application.font().family())
            return str(
                QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()
            )
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _normalized_font_scale(value: object) -> float:
        """夹紧到 0.8–1.4，并四舍五入到 0.05 步进。"""
        try:
            scale = float(value)
        except (TypeError, ValueError):
            scale = 1.0
        scale = max(0.8, min(1.4, scale))
        steps = round((scale - 0.8) / 0.05)
        return round(0.8 + steps * 0.05, 2)

    @Property(float, notify=settingsChanged)
    def uiFontScale(self) -> float:
        return self._normalized_font_scale(self._settings.get("ui_font_scale", 1.0))

    @Slot(float)
    def setUIFontScale(self, scale: float) -> None:
        self._settings.set("ui_font_scale", self._normalized_font_scale(scale))
        self.settingsChanged.emit()

    @Property(list, constant=True)
    def uiFontScaleOptions(self) -> list[float]:
        return [0.85, 1.0, 1.15, 1.3]

    NAV_MODES = ("auto", "expanded", "icons", "custom")

    @Property(str, notify=settingsChanged)
    def navMode(self) -> str:
        value = str(self._settings.get("nav_mode", "expanded") or "expanded")
        return value if value in self.NAV_MODES else "expanded"

    @Slot(str)
    def setNavMode(self, mode: str) -> None:
        value = str(mode or "")
        if value not in self.NAV_MODES:
            return
        self._settings.set("nav_mode", value)
        self.settingsChanged.emit()

    @Property(bool, notify=settingsChanged)
    def keepAlive(self) -> bool:
        """True = 不杀进程，只隐藏窗口 + 静音。"""
        return bool(self._settings.get("keep_alive", True))

    @Slot(bool)
    def setKeepAlive(self, enabled: bool) -> None:
        self._settings.set("keep_alive", bool(enabled))
        self.settingsChanged.emit()
        self.toast.emit(
            QCoreApplication.translate("ShenQing", "不再结束进程，只屏蔽界面与声音")
            if enabled
            else QCoreApplication.translate("ShenQing", "已改为直接结束进程")
        )

    @Property(bool, notify=settingsChanged)
    def adminMode(self) -> bool:
        return bool(self._settings.get("admin_mode", False))

    @Property(bool, notify=settingsChanged)
    def elevatedAutostart(self) -> bool:
        try:
            return elevation.elevated_autostart_enabled()
        except Exception:  # noqa: BLE001
            return False

    @Slot(bool)
    def setHardeningEnabled(self, enabled: bool) -> None:
        self._settings.set("hardening", bool(enabled))
        self.settingsChanged.emit()
        self.toast.emit(
            QCoreApplication.translate("ShenQing", "防退出加固已开启")
            if enabled
            else QCoreApplication.translate("ShenQing", "防退出加固已关闭")
        )

    @Slot(bool)
    def setAdminMode(self, enabled: bool) -> None:
        """开启时以管理员身份重启（UAC 确认一次）。"""
        self._settings.set("admin_mode", bool(enabled))
        if not enabled:
            self.settingsChanged.emit()
            return
        if elevation.is_admin():
            self.settingsChanged.emit()
            self.toast.emit(QCoreApplication.translate("ShenQing", "当前已是管理员权限"))
            return
        self.toast.emit(QCoreApplication.translate("ShenQing", "正在请求管理员权限…"))
        if elevation.relaunch_as_admin():
            self.quitRequested.emit()
        else:
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "提权失败：用户取消了 UAC 或策略禁止")
            )

    @Slot(bool)
    def setElevatedAutostart(self, enabled: bool) -> None:
        if enabled and not elevation.is_admin():
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "最高权限自启需要先以管理员身份运行")
            )
            self.settingsChanged.emit()
            return
        ok, message = elevation.set_elevated_autostart(bool(enabled))
        if not ok:
            logger.warning("计划任务操作失败：%s", message)
            self.toast.emit(QCoreApplication.translate("ShenQing", "设置失败，请检查权限"))
        else:
            if enabled:
                # 两者互斥：开了最高权限自启就关掉普通自启
                try:
                    self._autostart.disable()
                    self._settings.set("autostart", False)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("关闭普通自启失败：%s", exc)
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "已开启最高权限自启")
                if enabled
                else QCoreApplication.translate("ShenQing", "已关闭最高权限自启")
            )
        self.settingsChanged.emit()

    # ---------- 遮罩加固（QML 调用） ----------
    @Slot(bool)
    def setOverlayTopmostEnabled(self, enabled: bool) -> None:
        """覆清 dock：拉起白名单应用时暂停/恢复遮罩的定时置顶（不影响防退出加固）。"""
        try:
            self._hardening.set_topmost_enabled(bool(enabled))
        except Exception as exc:  # noqa: BLE001
            logger.warning("切换遮罩置顶失败：%s", exc)

    @Slot()
    def overlayOpened(self) -> None:
        hwnd = 0
        instance = QCoreApplication.instance()
        if instance is not None:
            for window in instance.topLevelWindows():
                if window.objectName() == "LockOverlay":
                    hwnd = int(window.winId())
                    break
        if hwnd:
            # v0.8：任务栏在所有档位的专注期间都保持隐藏；
            # 键盘钩子仍受「防退出加固」设置控制。
            self._hardening.activate(
                hwnd, hide_taskbar=True, block_keys=self.hardeningEnabled
            )

    @Slot()
    def overlayClosed(self) -> None:
        self._hardening.deactivate()

    @Property(str, notify=settingsChanged)
    def language(self) -> str:
        """设置里的语言：auto / zh_CN / en_US。"""
        return str(self._settings.get("language", "auto"))

    @Property(list, constant=True)
    def languages(self) -> list[dict]:
        from ..i18n import LOCALES

        result = [{"code": "auto", "label": QCoreApplication.translate("ShenQing", "跟随系统")}]
        for item in LOCALES:
            result.append({"code": item["code"], "label": item["label"]})
        return result

    @Slot(str)
    def setLanguage(self, code: str) -> None:
        try:
            from ..i18n import supported_codes

            allowed = set(supported_codes()) | {"auto"}
        except Exception:  # noqa: BLE001
            allowed = {"auto", "zh_CN", "en_US"}
        if code not in allowed:
            return
        self._settings.set("language", code)
        if self._translator is not None:
            try:
                locale = self._translator.apply(code)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                logger.warning("切换语言失败：%s", exc)
                locale = ""
        else:
            locale = code
        self.languageChanged.emit(locale)
        self.settingsChanged.emit()

    @Property(str, notify=themeChanged)
    def theme(self) -> str:
        return str(self._settings.get("theme", "Auto"))

    @Property(str, constant=True)
    def appName(self) -> str:
        return APP_NAME

    @Property(str, constant=True)
    def appAlias(self) -> str:
        return APP_ALIAS

    @Property(str, constant=True)
    def version(self) -> str:
        return APP_VERSION

    @Property(list, notify=catalogChanged)
    def appCatalog(self) -> list[dict]:
        return self._catalog

    @Slot()
    def refreshAppCatalog(self) -> None:
        """异步扫描（1–6 秒），避免卡住界面；结果回主线程再 emit。"""
        if self._catalog_scanning:
            return
        self._catalog_scanning = True
        self.toast.emit(QCoreApplication.translate("ShenQing", "正在扫描本机应用…"))
        QThreadPool.globalInstance().start(_CatalogScan(self))

    def _apply_catalog(self, items: list) -> None:
        self._catalog_scanning = False
        if items:
            self._catalog = list(items)
        self.catalogChanged.emit()

    @Slot(int)
    def setDefaultMinutes(self, minutes: int) -> None:
        self._settings.set("default_minutes", max(MIN_MINUTES, min(MAX_MINUTES, int(minutes))))
        self.settingsChanged.emit()
        self._dispatch("settings_changed", "default_minutes", int(minutes))

    @Slot(str)
    def setLockLevel(self, level: str) -> None:
        if level not in {item.value for item in LockLevel}:
            return
        self._settings.set("lock_level", level)
        self.settingsChanged.emit()
        self.lockedChanged.emit()
        self._dispatch("settings_changed", "lock_level", level)

    @Slot(bool)
    def setAutostart(self, enabled: bool) -> None:
        if enabled and self.elevatedAutostart:
            if elevation.is_admin():
                elevation.set_elevated_autostart(False)
            else:
                self.toast.emit(
                    QCoreApplication.translate("ShenQing", "已开启最高权限自启，普通自启不再需要")
                )
                self.settingsChanged.emit()
                return
        if enabled and not self._autostart.is_enabled() and not elevation.is_admin():
            # 普通自启写 HKCU Run，不需要管理员
            pass
        self._autostart.set(bool(enabled))
        self._settings.set("autostart", bool(enabled))
        self.settingsChanged.emit()
        self._dispatch("settings_changed", "autostart", bool(enabled))

    @Slot(str)
    def setTheme(self, theme: str) -> None:
        if theme not in {"Auto", "Light", "Dark"}:
            return
        self._settings.set("theme", theme)
        self.themeChanged.emit()
        self.settingsChanged.emit()
        self._dispatch("settings_changed", "theme", theme)

    @Slot()
    def refreshStats(self) -> None:
        self.statsChanged.emit()

    @Slot(result=str)
    def exportStats(self) -> str:
        try:
            path = self._stats.export_csv()
        except OSError as exc:
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "导出失败：{0}").format(exc)
            )
            return ""
        self.toast.emit(
            QCoreApplication.translate("ShenQing", "已导出：{0}").format(path.name)
        )
        return str(path)

    # ================= v0.4：单空间 / 三档 / 主题 / 预览体验 / dock / 搜索 =================
    @Property(dict, notify=spacesChanged)
    def space(self) -> dict:
        return self._space_view(self._spaces.space)

    @Property(int, constant=True)
    def spaceMinMinutes(self) -> int:
        return SPACE_MIN_MINUTES

    @Property(int, constant=True)
    def spaceMaxMinutes(self) -> int:
        return SPACE_MAX_MINUTES

    @Property(int, constant=True)
    def spaceMinuteStep(self) -> int:
        return SPACE_MINUTE_STEP

    @Property(int, notify=spacesChanged)
    def spaceMinutes(self) -> int:
        return int(self._spaces.space.get("minutes", 45))

    @Slot(str, int)
    def setSpaceMinutesFor(self, mode: str, minutes: int) -> None:
        """v0.5 兼容：按档位改时长（映射到该档第一张空间）。"""
        self._spaces.set_minutes(mode, minutes)
        self.spacesChanged.emit()

    @Slot(str, str)
    def setSpaceNameFor(self, mode: str, name: str) -> None:
        """v0.5 兼容：按档位改名（映射到该档第一张空间）。"""
        if self._spaces.set_name(mode, name):
            self.spacesChanged.emit()
        elif str(mode) == "heavy":
            self.toast.emit(QCoreApplication.translate("ShenQing", "深清空间名不可修改"))

    @Slot(str, str, bool, result=bool)
    def toggleSpaceAllowedAppFor(self, mode: str, exe: str, enabled: bool) -> bool:
        """v0.5 兼容：按档位改白名单（映射到该档第一张空间）；深清拒绝。"""
        if str(mode) == "heavy":
            self.toast.emit(QCoreApplication.translate("ShenQing", "深清空间不设置白名单"))
            return False
        if self._spaces.toggle_allowed_app(mode, exe, bool(enabled)):
            self.spacesChanged.emit()
            self.catalogChanged.emit()
            return True
        return False

    @Property(list, constant=True)
    def modes(self) -> list[dict]:
        result = []
        for level in (LockLevel.LIGHT, LockLevel.MEDIUM, LockLevel.HEAVY):
            result.append(
                {
                    "value": level.value,
                    "label": QCoreApplication.translate("ShenQing", MODE_LABELS[level.value]),
                    "desc": self._mode_desc(level.value),
                }
            )
        # v0.15：还清作为第 4 档（仅 UI 展示，不进入 LockLevel 枚举）
        result.append(
            {
                "value": "sleep",
                "label": QCoreApplication.translate("ShenQing", "还清"),
                "desc": QCoreApplication.translate("ShenQing", "按作息时间自动锁定"),
            }
        )
        return result

    @staticmethod
    def _mode_desc(value: str) -> str:
        if value == "light":
            return QCoreApplication.translate("ShenQing", "只屏蔽黑名单应用的窗口与声音")
        if value == "medium":
            return QCoreApplication.translate("ShenQing", "屏蔽干扰并显示允许使用的应用 dock")
        return QCoreApplication.translate("ShenQing", "白名单之外的应用全部屏蔽，不可提前结束")

    @Property(str, notify=settingsChanged)
    def defaultMode(self) -> str:
        return str(self._settings.get("default_mode", LockLevel.MEDIUM.value))

    @Slot(str)
    def setDefaultMode(self, mode: str) -> None:
        if mode not in {item.value for item in LockLevel}:
            return
        self._settings.set("default_mode", mode)
        self.settingsChanged.emit()

    # ================= v0.21：外观（样式 + 配色两个正交维度） =================
    def _theme_style(self) -> str:
        """当前样式：内置样式或已安装的 custom:<id>；非法 / 已失效值回落到 solid。"""
        value = str(self._settings.get("theme_style", DEFAULT_THEME_STYLE) or "").strip()
        return self._normalize_style(value) or DEFAULT_THEME_STYLE

    def _normalize_style(self, value: object) -> str:
        """校验样式值：合法返回原值，非法返回空字符串。"""
        text = str(value or "").strip()
        if text.startswith(CUSTOM_THEME_PREFIX):
            theme_id = text[len(CUSTOM_THEME_PREFIX) :]
            return text if theme_id and theme_id in self._custom_theme_map() else ""
        return text if text in {item["value"] for item in THEME_STYLES} else ""

    def _theme_scheme(self) -> str:
        """当前配色配置：auto / light / dark；非法值回落到 auto。"""
        value = str(self._settings.get("theme_scheme", DEFAULT_THEME_SCHEME) or "")
        return theme_service.normalize_scheme(value) or DEFAULT_THEME_SCHEME

    def _effective_scheme(self) -> str:
        """解析后的实际深浅（auto 跟随系统）。"""
        return theme_service.resolve_scheme(self._theme_scheme())

    def _chrome_theme(self) -> str:
        """窗口 chrome：只由实际深浅决定（与样式无关）。"""
        return "Light" if self._effective_scheme() == theme_service.SCHEME_LIGHT else "Dark"

    def _install_theme_listener(self) -> None:
        """监听系统深浅切换：scheme=auto 时重新发 themeChanged。"""
        theme_service.connect_color_scheme_changed(self._on_system_scheme_changed)

    def _on_system_scheme_changed(self, *_args: object) -> None:
        """系统深浅变化：auto 模式下通知界面重算配色。"""
        if self._theme_scheme() != theme_service.SCHEME_AUTO:
            return
        try:
            self.themeChanged.emit(self._chrome_theme())
        except RuntimeError:  # 宿主已销毁
            pass

    @Property(str, notify=themeChanged)
    def themeStyle(self) -> str:
        """外观样式：solid / glass / ocean / custom:<id>。"""
        return self._theme_style()

    @Property(str, notify=themeChanged)
    def themeScheme(self) -> str:
        """配色方案：auto / light / dark（auto 跟随系统）。"""
        return self._theme_scheme()

    @Property(str, notify=themeChanged)
    def effectiveScheme(self) -> str:
        """解析后的实际配色：light / dark。"""
        return self._effective_scheme()

    @Property(str, notify=themeChanged)
    def systemScheme(self) -> str:
        """系统当前深浅：light / dark。"""
        return theme_service.system_scheme()

    @Property(list, constant=True)
    def themeStyles(self) -> list[dict]:
        """内置样式列表：[{value,name,desc,experimental}]（自定义主题单独在 customThemes）。"""
        return [
            {
                "value": item["value"],
                "name": QCoreApplication.translate("ShenQing", item["label"]),
                "desc": QCoreApplication.translate("ShenQing", item["desc"]),
                "experimental": bool(item.get("experimental")),
            }
            for item in THEME_STYLES
        ]

    @Property(list, constant=True)
    def themeSchemes(self) -> list[dict]:
        """配色方案列表：[{value,name}]（auto / light / dark）。"""
        return [
            {
                "value": item["value"],
                "name": QCoreApplication.translate("ShenQing", item["label"]),
            }
            for item in THEME_SCHEMES
        ]

    @Slot(str)
    def setThemeStyle(self, style: str) -> None:
        """切换外观样式（内置样式或已安装的 custom:<id>）；非法值忽略。"""
        value = self._normalize_style(style)
        if not value or value == self._theme_style():
            return
        self._settings.set("theme_style", value)
        self.settingsChanged.emit()
        self.themeChanged.emit(self._chrome_theme())

    @Slot(str)
    def setThemeScheme(self, scheme: str) -> None:
        """切换配色方案（auto / light / dark）；非法值忽略。"""
        value = theme_service.normalize_scheme(scheme)
        if value is None or value == self._theme_scheme():
            return
        self._settings.set("theme_scheme", value)
        self.settingsChanged.emit()
        self.themeChanged.emit(self._chrome_theme())

    # ---- 兼容旧接口：themeMode 等于样式（custom 原样） ----
    @Property(str, notify=themeChanged)
    def themeMode(self) -> str:
        """兼容旧属性：返回样式（custom:<id> 原样），等价于 themeStyle。"""
        return self._theme_style()

    @Slot(str)
    def setThemeMode(self, theme: str) -> None:
        """兼容旧 Slot：把旧主题值映射成 样式 + 配色。

        light→solid+light；solid→solid+dark；glass→glass+dark；ocean→ocean+dark；
        custom:<id>→custom:<id>+auto。非法值忽略。
        """
        value = str(theme or "")
        style = ""
        scheme = ""
        if value == "light":
            style, scheme = DEFAULT_THEME_STYLE, theme_service.SCHEME_LIGHT
        elif value == "solid":
            style, scheme = DEFAULT_THEME_STYLE, theme_service.SCHEME_DARK
        elif value in ("glass", "ocean"):
            style, scheme = value, theme_service.SCHEME_DARK
        elif value.startswith(CUSTOM_THEME_PREFIX):
            style = self._normalize_style(value)
            scheme = theme_service.SCHEME_AUTO
        if not style:
            return
        self._settings.set("theme_style", style)
        self._settings.set("theme_scheme", scheme)
        self.settingsChanged.emit()
        self.themeChanged.emit(self._chrome_theme())

    @Property(str, constant=True)
    def licenseText(self) -> str:
        """LICENSE 全文（关于页本地弹窗用）。"""
        try:
            return license_file().read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "GNU General Public License v3.0"


    @Property(str, constant=True)
    def noticeText(self) -> str:
        """NOTICE 全文（关于页本地弹窗用）。"""
        try:
            return notice_file().read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "Third-party notices"

    @Property(list, notify=languageChanged)
    def changelog(self) -> list[dict]:
        """更新日志（按当前语言返回中文或英文条目）。"""
        language = str(self._settings.get("language", "auto"))
        if language == "auto":
            from PySide6.QtCore import QLocale

            english = not QLocale.system().name().lower().startswith("zh")
        else:
            english = language.startswith("en")
        result: list[dict] = []
        for entry in CHANGELOG:
            items = entry.get("items_en") if english else entry.get("items")
            result.append(
                {
                    "version": str(entry.get("version", "")),
                    "date": str(entry.get("date", "")),
                    "tag": str(entry.get("tag", "")),
                    "items": list(items or entry.get("items") or []),
                }
            )
        return result

    @Property(list, constant=True)
    def themes(self) -> list[dict]:
        """兼容旧接口：样式列表（额外带 label 字段，等于 name；不含配色）。"""
        return [
            {
                "value": item["value"],
                "label": QCoreApplication.translate("ShenQing", item["label"]),
                "name": QCoreApplication.translate("ShenQing", item["label"]),
                "desc": QCoreApplication.translate("ShenQing", item["desc"]),
                "experimental": bool(item.get("experimental")),
            }
            for item in THEMES
        ]

    # ================= v0.18：自定义主题包（商店「安装主题」） =================
    def _custom_theme_map(self) -> dict[str, dict]:
        """settings 里的自定义主题（坏数据静默跳过）：{id: {id,name,description,palette}}。"""
        return store.normalize_custom_themes(self._settings.get("custom_themes", {}))

    @Property(list, notify=customThemesChanged)
    def customThemes(self) -> list[dict]:
        """已安装的自定义主题包：[{id,name,description,palette}]。"""
        return list(self._custom_theme_map().values())

    @Property(dict, notify=themeChanged)
    def customThemePalette(self) -> dict:
        """当前 custom 样式的 palette；非 custom 样式返回 {}（QML 据此覆盖 AppTheme 颜色）。"""
        value = self._theme_style()
        if not value.startswith(CUSTOM_THEME_PREFIX):
            return {}
        item = self._custom_theme_map().get(value[len(CUSTOM_THEME_PREFIX) :])
        return dict(item["palette"]) if item else {}

    @Slot(str, str, str, dict, result=bool)
    def installCustomTheme(
        self, theme_id: str, name: str, description: str, palette: dict
    ) -> bool:
        """安装（或更新）一个自定义主题包，成功后立即切换到它。"""
        try:
            wanted = store.normalize_theme_id(theme_id)
            colors = store.normalize_palette(palette)
        except store.StoreError as exc:
            self.toast.emit(str(exc))
            return False
        themes = self._custom_theme_map()
        if wanted not in themes and len(themes) >= store.MAX_CUSTOM_THEMES:
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "自定义主题最多 {0} 个").format(
                    store.MAX_CUSTOM_THEMES
                )
            )
            return False
        stored = {
            key: {
                "name": item["name"],
                "description": item["description"],
                "palette": dict(item["palette"]),
            }
            for key, item in themes.items()
        }
        stored[wanted] = {
            "name": str(name or "").strip()[:40] or wanted,
            "description": str(description or "").strip()[:200],
            "palette": colors,
        }
        self._settings.set("custom_themes", stored)
        self._settings.set("theme_style", CUSTOM_THEME_PREFIX + wanted)
        self.customThemesChanged.emit()
        self.settingsChanged.emit()
        self.themeChanged.emit(self._chrome_theme())
        self.toast.emit(
            QCoreApplication.translate("ShenQing", "已安装主题：{0}").format(
                stored[wanted]["name"]
            )
        )
        return True

    @Slot(str, result=bool)
    def removeCustomTheme(self, theme_id: str) -> bool:
        """删除自定义主题；若正在使用则回退默认 solid。"""
        wanted = str(theme_id or "").strip()
        themes = self._custom_theme_map()
        if wanted not in themes:
            return False
        del themes[wanted]
        stored = {
            key: {
                "name": item["name"],
                "description": item["description"],
                "palette": dict(item["palette"]),
            }
            for key, item in themes.items()
        }
        self._settings.set("custom_themes", stored)
        if self._theme_style() == CUSTOM_THEME_PREFIX + wanted:
            self._settings.set("theme_style", DEFAULT_THEME_STYLE)
            self.themeChanged.emit(self._chrome_theme())
        self.customThemesChanged.emit()
        self.settingsChanged.emit()
        self.toast.emit(QCoreApplication.translate("ShenQing", "已删除主题"))
        return True

    # ================= v0.18：主题 / 插件商店 =================
    @Property(str, notify=storeChanged)
    def storeCatalogStatus(self) -> str:
        """目录状态：online / builtin / error:<原因>（首次调用 storeItems 时刷新）。"""
        return self._store.status

    @Property(str, notify=storeChanged)
    def storeCatalogError(self) -> str:
        """最近一次远程目录失败原因（空 = 无错误）。"""
        return self._store.error

    def _sync_store_state(self, before: tuple[str, str]) -> None:
        if before != (self._store.status, self._store.error):
            self.storeChanged.emit()

    @Slot(str, result=list)
    @Slot(str, str, result=list)
    def storeItems(self, kind: str = "", sort: str = "") -> list[dict]:
        """商店条目列表；kind = ""/all/theme/plugin，sort = ""/rating/downloads/newest/name。"""
        before = (self._store.status, self._store.error)
        items = self._store.items()
        self._sync_store_state(before)
        return store.filter_items(items, kind, sort)

    @Slot(str, result=dict)
    def storeItem(self, item_id: str) -> dict:
        """单个商店条目；不存在返回 {}。"""
        before = (self._store.status, self._store.error)
        item = self._store.get(item_id)
        self._sync_store_state(before)
        return item or {}

    @Slot(result=str)
    def refreshStore(self) -> str:
        """强制刷新商店目录（跳过 10 分钟缓存），返回最新状态。"""
        status = self._store.refresh()
        self.storeChanged.emit()
        return status

    @Slot(str, result=dict)
    def storeComments(self, item_id: str) -> dict:
        """评论：{comments: [已审核通过], pendingCount: 审核中数量}。"""
        return self._comments.list(item_id)

    @Slot(str, int, str, result=dict)
    def addStoreComment(self, item_id: str, rating: int, text: str) -> dict:
        """提交评论（默认进入审核中）；返回 {ok, message, pendingCount}。"""
        try:
            self._comments.add(item_id, rating, text)
        except store.StoreError as exc:
            message = str(exc)
            self.toast.emit(message)
            return {"ok": False, "message": message}
        message = QCoreApplication.translate("ShenQing", "评论已提交，审核通过后展示")
        self.toast.emit(message)
        self.storeCommentsChanged.emit(str(item_id or ""))
        pending = self._comments.list(item_id).get("pendingCount", 0)
        return {"ok": True, "message": message, "pendingCount": pending}

    @Slot(str, str, result=bool)
    def approveStoreComment(self, item_id: str, comment_id: str) -> bool:
        """调试用本地审核：通过一条评论（UI 不暴露）。"""
        changed = self._comments.approve(item_id, comment_id)
        if changed:
            self.storeCommentsChanged.emit(str(item_id or ""))
        return changed

    @Slot(str, str, result=bool)
    def rejectStoreComment(self, item_id: str, comment_id: str) -> bool:
        """调试用本地审核：拒绝一条评论（UI 不暴露）。"""
        changed = self._comments.reject(item_id, comment_id)
        if changed:
            self.storeCommentsChanged.emit(str(item_id or ""))
        return changed

    @Slot(str, result=dict)
    def installStorePlugin(self, item_id: str) -> dict:
        """下载并安装插件商店条目；返回 {ok, message}。"""
        if self._store_installing:
            return {
                "ok": False,
                "message": QCoreApplication.translate("ShenQing", "正在安装插件，请稍候"),
            }
        before = (self._store.status, self._store.error)
        item = self._store.get(item_id)
        self._sync_store_state(before)
        if not item:
            return {
                "ok": False,
                "message": QCoreApplication.translate("ShenQing", "商店里没有这个条目"),
            }
        if str(item.get("kind")) != "plugin":
            return {
                "ok": False,
                "message": QCoreApplication.translate("ShenQing", "该条目不是插件"),
            }
        url = str(item.get("download_url") or "").strip()
        if not url:
            return {
                "ok": False,
                "message": QCoreApplication.translate("ShenQing", "插件缺少下载地址"),
            }
        self._store_installing = True
        temp_dir: Path | None = None
        error = ""
        try:
            temp_dir = Path(tempfile.mkdtemp(prefix="shenqing-store-"))
            zip_path = store.download_file(url, temp_dir / "plugin.zip")
            store.install_plugin_zip(zip_path, str(item.get("id") or ""))
        except store.StoreError as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001 - 下载/解压异常都要给可读提示
            error = str(exc) or "插件安装失败"
            logger.warning("插件安装异常：%s", exc)
        finally:
            self._store_installing = False
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)
        if error:
            logger.warning("插件安装失败：%s", error)
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "插件安装失败：{0}").format(error[:120])
            )
            return {"ok": False, "message": error}
        if self._plugins is not None:
            try:
                self._plugins.reload()
            except Exception as exc:  # noqa: BLE001 - 插件系统失败不能拖垮桥
                message = QCoreApplication.translate(
                    "ShenQing", "插件已解压，但重新加载失败：{0}"
                ).format(exc)
                logger.warning("安装后重载插件失败：%s", exc)
                self.pluginsChanged.emit()
                return {"ok": False, "message": message}
        self.pluginsChanged.emit()
        name = str(item.get("name") or item.get("id") or "")
        message = QCoreApplication.translate("ShenQing", "插件已安装：{0}").format(name)
        self.toast.emit(message)
        return {"ok": True, "message": message}

    # ================= 进入前 10 秒倒计时（水滴凝聚） =================
    PREPARE_SECONDS = 10

    @Property(bool, notify=stateChanged)
    def prepareActive(self) -> bool:
        return self._prepare_active

    @Property(int, notify=stateChanged)
    def prepareRemaining(self) -> int:
        return int(self._prepare_remaining)

    @Property(str, notify=stateChanged)
    def prepareLevel(self) -> str:
        return str(self._prepare_mode)

    @Property(str, notify=stateChanged)
    def prepareSpaceName(self) -> str:
        space = self._spaces.get(self._prepare_space_id) if self._prepare_space_id else None
        return str(space.get("name", "")) if space else ""

    @Slot(str)
    def prepareSpace(self, space_id: str) -> None:
        """开始 10 秒进入倒计时（可随时 cancelPrepare 取消）。"""
        space = self._spaces.get(str(space_id or ""))
        if space is None or self._session.state is not SessionState.IDLE:
            return
        self._begin_prepare(space)

    @Slot(str)
    def prepareMode(self, mode: str) -> None:
        spaces = [s for s in self._spaces.all() if str(s.get("mode")) == str(mode)]
        if not spaces:
            return
        self._begin_prepare(spaces[0])

    def _begin_prepare(self, space: dict, minutes: int | None = None) -> None:
        # 真正开始倒计时了：残留的待确认开局信息作废
        if self._start_pending:
            self._start_pending = {}
            self.confirmationChanged.emit()
        self._prepare_minutes = int(minutes) if minutes else None
        self._prepare_active = True
        self._prepare_remaining = int(self.PREPARE_SECONDS)
        self._prepare_space_id = str(space.get("id") or "")
        self._prepare_mode = str(space.get("mode") or "")
        self._prepare_timer.start()
        self.stateChanged.emit()

    @Slot()
    def cancelPrepare(self) -> None:
        if not self._prepare_active:
            return
        self._prepare_timer.stop()
        self._prepare_active = False
        self._prepare_remaining = 0
        self._prepare_space_id = ""
        self._prepare_mode = ""
        self.stateChanged.emit()

    def _tick_prepare(self) -> None:
        if not self._prepare_active:
            return
        self._prepare_remaining = max(0, self._prepare_remaining - 1)
        self.stateChanged.emit()
        if self._prepare_remaining <= 0:
            space = self._spaces.get(self._prepare_space_id)
            mode = self._prepare_mode or str((space or {}).get("mode", "medium"))
            minutes = int(self._prepare_minutes or (space or {}).get("minutes", 45))
            self._prepare_minutes = None
            self._prepare_timer.stop()
            self._prepare_active = False
            self._prepare_space_id = ""
            self._prepare_mode = ""
            self.stateChanged.emit()
            self._begin_space_session(space, mode, minutes, trial=False)

    @Property(bool, notify=stateChanged)
    def trialActive(self) -> bool:
        return self._trial_active

    @Property(bool, notify=stateChanged)
    def previewActive(self) -> bool:
        return self._preview_active

    @Property(str, notify=stateChanged)
    def previewLevel(self) -> str:
        return self._preview_level

    @Slot(str)
    def previewMode(self, mode: str) -> None:
        if mode not in {item.value for item in LockLevel}:
            return
        self._preview_active = True
        self._preview_level = mode
        self.stateChanged.emit()
        self.lockedChanged.emit()

    @Slot()
    def stopPreview(self) -> None:
        self._preview_active = False
        self._preview_level = ""
        self.stateChanged.emit()
        self.lockedChanged.emit()

    @Slot(str)
    def startMode(self, mode: str) -> None:
        """按档位开始：先进入 10 秒倒计时。"""
        space = self._spaces.get_by_mode(mode)
        if space is None:
            self.toast.emit(QCoreApplication.translate("ShenQing", "空间不存在"))
            return
        if self._session.state is not SessionState.IDLE:
            self.toast.emit(QCoreApplication.translate("ShenQing", "已经有正在进行的专注"))
            return
        self._begin_prepare(space)

    @Slot(str)
    def startTrial(self, mode: str) -> None:
        """体验模式：1 分钟真实专注；每小时最多 5 次。"""
        if mode not in {item.value for item in LockLevel}:
            return
        now = time.time()
        self._trial_times = [t for t in self._trial_times if now - t < 3600]
        if len(self._trial_times) >= 5:
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "体验次数已用完（每小时最多 5 次）")
            )
            return
        self._trial_times.append(now)
        space = self._spaces.get_by_mode(mode)
        self._begin_space_session(space, mode, TRIAL_MINUTES, trial=True)

    @Property(list, notify=spacesChanged)
    def dockApps(self) -> list[dict]:
        catalog = {str(item.get("exe", "")).lower(): item for item in self._catalog}
        result: list[dict] = []
        medium = self._spaces.get_by_mode("medium") or self._spaces.space
        for exe in medium.get("allowed_apps", []):
            item = catalog.get(str(exe).lower())
            if item is not None:
                result.append(
                    {
                        "exe": exe,
                        "name": str(item.get("name") or exe),
                        "iconUrl": str(item.get("iconUrl") or ""),
                        "path": str(item.get("path") or ""),
                    }
                )
            else:
                result.append({"exe": exe, "name": exe, "iconUrl": "", "path": ""})
        return result

    @Slot(str)
    def launchApp(self, exe: str) -> None:
        try:
            catalog = {str(item.get("exe", "")).lower(): item for item in self._catalog}
            item = catalog.get(str(exe).lower())
            path = str(item.get("path") or "") if item else ""
            if path:
                os.startfile(path)  # noqa: S606 - 用户主动启动白名单应用
            else:
                os.startfile(str(exe))  # noqa: S606
        except Exception as exc:  # noqa: BLE001
            logger.warning("启动应用失败：%s", exc)
            self.toast.emit(QCoreApplication.translate("ShenQing", "启动应用失败"))
            return
        # 通知主程序：应用已拉起，覆清 dock 需要把它显示到遮罩之上
        self.appLaunched.emit(str(exe))

    # ================= v0.16 清番（置顶番茄钟） =================
    @Property(bool, notify=pomodoroChanged)
    def pomodoroRunning(self) -> bool:
        return self._pomodoro.running

    @Property(bool, notify=pomodoroChanged)
    def pomodoroPaused(self) -> bool:
        return self._pomodoro.paused

    @Property(str, notify=pomodoroChanged)
    def pomodoroPhase(self) -> str:
        """idle / work / break（break 时长由第几轮决定：满 4 轮是长休息）。"""
        return self._pomodoro.phase

    @Property(int, notify=pomodoroChanged)
    def pomodoroRemaining(self) -> int:
        return self._pomodoro.remaining

    @Property(str, notify=pomodoroChanged)
    def pomodoroState(self) -> str:
        """兼容 QML 的合并状态：idle / work / break / paused。"""
        if not self._pomodoro.running:
            return "idle"
        if self._pomodoro.paused:
            return "paused"
        return self._pomodoro.phase

    @Property(int, notify=pomodoroChanged)
    def pomodoroPresetTotal(self) -> int:
        return self._pomodoro.preset_total

    @Property(int, notify=pomodoroChanged)
    def pomodoroTotal(self) -> int:
        """pomodoroPresetTotal 的 QML 别名。"""
        return self._pomodoro.preset_total

    @Property(int, notify=pomodoroChanged)
    def pomodoroRound(self) -> int:
        return self._pomodoro.round

    @Property(int, notify=pomodoroChanged)
    def pomodoroWorkMinutes(self) -> int:
        return self._pomodoro.work_minutes

    @Property(int, notify=pomodoroChanged)
    def pomodoroBreakMinutes(self) -> int:
        return self._pomodoro.break_minutes

    @Property(int, notify=pomodoroChanged)
    def pomodoroLongBreakMinutes(self) -> int:
        return self._pomodoro.long_break_minutes

    @Property(int, notify=pomodoroChanged)
    def pomodoroTotalRounds(self) -> int:
        """一轮清番包含的番茄个数（1~20）。"""
        return self._pomodoro.rounds_total

    @Slot(int)
    def setPomodoroTotalRounds(self, rounds: int) -> None:
        """设置番茄个数（1~20），保存后立即生效。"""
        try:
            value = max(1, min(20, int(rounds)))
        except (TypeError, ValueError):
            return
        self._settings.set("pomodoro_rounds", value)
        self._pomodoro.changed.emit()
        self.pomodoroChanged.emit()
        self.toast.emit(
            QCoreApplication.translate("ShenQing", "清番个数已设为 {0} 个").format(value)
        )

    @Property(int, notify=pomodoroChanged)
    def pomodoroRoundsBeforeLong(self) -> int:
        return self._pomodoro.rounds_before_long

    @Property(int, notify=pomodoroChanged)
    def pomodoroRounds(self) -> int:
        """pomodoroRoundsBeforeLong 的 QML 别名。"""
        return self._pomodoro.rounds_before_long

    @Slot(result=bool)
    def startPomodoro(self) -> bool:
        return self._pomodoro.start()

    @Slot(result=bool)
    def pausePomodoro(self) -> bool:
        return self._pomodoro.pause()

    @Slot(result=bool)
    def resumePomodoro(self) -> bool:
        return self._pomodoro.resume()

    @Slot(result=bool)
    def stopPomodoro(self) -> bool:
        return self._pomodoro.stop()

    @Slot(result=bool)
    def skipPomodoro(self) -> bool:
        return self._pomodoro.skip()

    def _on_pomodoro_notify(self, title: str, body: str) -> None:
        """清番到点：系统通知（不与锁机 / guard 交互）。"""
        try:
            self._notifications.notify(str(title), str(body))
        except Exception as exc:  # noqa: BLE001
            logger.warning("清番通知失败：%s", exc)

    # ================= 自动更新（多下载源） =================
    def _custom_update_sources(self) -> list[dict]:
        """已保存的自定义更新源（每项 {id,name,url,token}）。"""
        raw = self._settings.get("custom_update_sources", [])
        if not isinstance(raw, list):
            return []
        result: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("id") or "").strip()
            url = str(item.get("url") or "").strip()
            if not source_id or not url:
                continue
            result.append(
                {
                    "id": source_id,
                    "name": str(item.get("name") or "自定义源"),
                    "url": url,
                    "token": str(item.get("token") or ""),
                }
            )
        return result

    @Property(list, notify=settingsChanged)
    def updateSources(self) -> list[dict]:
        """可选更新源：[{id,name,kind}]（内置 GitHub / GitLink / Gitee + 自定义）。"""
        return updater.source_choices(self._custom_update_sources())

    @Property(list, notify=settingsChanged)
    def customUpdateSources(self) -> list[dict]:
        """自定义源列表 [{id,name,url}]（不返回 Token）。"""
        return [
            {"id": item["id"], "name": item["name"], "url": item["url"]}
            for item in self._custom_update_sources()
        ]

    @Property(str, notify=settingsChanged)
    def updateSource(self) -> str:
        """当前更新源 id（找不到时回退 GitHub）。"""
        current = updater.resolve_source_id(
            self._settings.get("update_source", updater.DEFAULT_SOURCE_ID),
            self._custom_update_sources(),
        )
        return current or updater.DEFAULT_SOURCE_ID

    @Property(str, notify=stateChanged)
    def updateSourceError(self) -> str:
        """最近一次更新源相关错误（可读中文，空 = 无错误）。"""
        return self._update_source_error

    @Slot(str, result=bool)
    def setUpdateSource(self, source_id: str) -> bool:
        """切换更新源：内置 github / gitlink / gitee 或自定义源 id。"""
        sources = self._custom_update_sources()
        resolved = updater.resolve_source_id(source_id, sources)
        if not resolved:
            self._update_source_error = "未知的更新源"
            self.toast.emit(QCoreApplication.translate("ShenQing", "未知的更新源"))
            self.stateChanged.emit()
            return False
        self._settings.set("update_source", resolved)
        self._update_source_error = ""
        source = updater.resolve_source(resolved, sources) or {}
        self.toast.emit(
            QCoreApplication.translate("ShenQing", "已切换更新源：{0}").format(
                str(source.get("name") or resolved)
            )
        )
        self.settingsChanged.emit()
        self.stateChanged.emit()
        return True

    @Slot(str, str, result=str)
    @Slot(str, str, str, result=str)
    def addCustomUpdateSource(self, name: str, url: str, token: str = "") -> str:
        """新增自定义更新源（JSON API，可带 Token），成功后自动切换过去。"""
        existing = self._custom_update_sources()
        try:
            item = updater.make_custom_source(name, url, token, existing)
        except ValueError as exc:
            self._update_source_error = str(exc)
            self.toast.emit(str(exc))
            self.stateChanged.emit()
            return ""
        existing.append(item)
        self._settings.set("custom_update_sources", existing)
        self._settings.set("update_source", item["id"])
        self._update_source_error = ""
        self.toast.emit(
            QCoreApplication.translate("ShenQing", "已添加更新源：{0}").format(item["name"])
        )
        self.settingsChanged.emit()
        self.stateChanged.emit()
        return item["id"]

    @Slot(str, result=bool)
    def removeCustomUpdateSource(self, source_id: str) -> bool:
        """删除自定义源；若正在使用则回退 GitHub。"""
        wanted = str(source_id or "").strip()
        existing = self._custom_update_sources()
        kept = [item for item in existing if str(item.get("id")) != wanted]
        if len(kept) == len(existing):
            return False
        self._settings.set("custom_update_sources", kept)
        if str(self._settings.get("update_source", "")) == wanted:
            self._settings.set("update_source", updater.DEFAULT_SOURCE_ID)
        self._update_source_error = ""
        self.toast.emit(QCoreApplication.translate("ShenQing", "已移除更新源"))
        self.settingsChanged.emit()
        self.stateChanged.emit()
        return True

    def _set_update_state(self, state: str, error: str = "") -> None:
        self._update_state = str(state)
        self._update_error = str(error or "")
        self.stateChanged.emit()

    @Property(str, notify=stateChanged)
    def updateState(self) -> str:
        return self._update_state

    @Property(bool, notify=stateChanged)
    def updateAvailable(self) -> bool:
        return self._update_info is not None

    @Property(str, notify=stateChanged)
    def updateLatestVersion(self) -> str:
        return str((self._update_info or {}).get("version", ""))

    @Property(str, notify=stateChanged)
    def updateNotes(self) -> str:
        return updater.format_notes((self._update_info or {}).get("notes", ""))

    @Property(int, notify=stateChanged)
    def updateProgress(self) -> int:
        return int(self._update_progress)

    @Property(str, notify=stateChanged)
    def updateError(self) -> str:
        return self._update_error

    @Property(str, notify=stateChanged)
    def updateAssetName(self) -> str:
        return str((self._update_info or {}).get("assetName", ""))

    @Property(bool, notify=settingsChanged)
    def autoUpdate(self) -> bool:
        return bool(self._settings.get("auto_update", True))

    @Slot(bool)
    def setAutoUpdate(self, enabled: bool) -> None:
        self._settings.set("auto_update", bool(enabled))
        self.settingsChanged.emit()

    @Property(str, notify=settingsChanged)
    def updateChannel(self) -> str:
        """更新渠道：stable 正式版 / preview 预览版。"""
        return updater.normalize_channel(self._settings.get("update_channel", "stable"))

    @Slot(str, result=bool)
    def setUpdateChannel(self, channel: str) -> bool:
        """切换更新渠道（stable / preview），切换后需重新检查更新。"""
        value = str(channel or "").strip().lower()
        if value not in updater.CHANNELS:
            self.toast.emit(QCoreApplication.translate("ShenQing", "未知的更新渠道"))
            return False
        self._settings.set("update_channel", value)
        self._update_info = None
        self._set_update_state("idle")
        self.settingsChanged.emit()
        self.toast.emit(
            QCoreApplication.translate("ShenQing", "已切换更新渠道：{0}").format(
                "预览版" if value == "preview" else "正式版"
            )
        )
        return True

    def _check_update_worker(
        self, source_id: str, custom_sources: list[dict], channel: str = "stable"
    ) -> None:
        info: dict | None = None
        error = ""
        try:
            info, error = updater.check_latest_detail(
                APP_VERSION, source_id=source_id, custom_sources=custom_sources, channel=channel
            )
        except Exception as exc:  # noqa: BLE001 - 后台线程不能崩
            error = str(exc)
            logger.warning("检查更新异常：%s", exc)
        try:
            self._updateChecked.emit(info, error)
        except RuntimeError:  # 宿主已销毁
            pass

    @Slot()
    def checkUpdate(self) -> None:
        """手动/自动检查当前下载源的最新 Release（后台线程，不阻塞界面）。"""
        if self._update_state in ("checking", "downloading"):
            return
        self._update_source_error = ""
        self._set_update_state("checking")
        threading.Thread(
            target=self._check_update_worker,
            args=(self.updateSource, self._custom_update_sources(), self.updateChannel),
            name="shenqing-update-check",
            daemon=True,
        ).start()

    @Slot(object, str)
    def _on_update_checked(self, info: object, error: str) -> None:
        if error:
            self._update_info = None
            self._update_source_error = str(error)
            self._set_update_state("error", str(error))
            logger.warning("检查更新失败：%s", error)
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "检查更新失败：{0}").format(
                    str(error)[:120]
                )
            )
            return
        self._update_info = None
        self._update_source_error = ""
        if not isinstance(info, dict) or not info:
            self._set_update_state("idle")
            return
        self._update_info = dict(info)
        self._set_update_state("available")
        self.toast.emit(
            QCoreApplication.translate("ShenQing", "发现新版本 {0}，可在关于页更新").format(
                str(info.get("version", ""))
            )
        )

    def _download_update_worker(
        self, url: str, dest: Path, cancel: updater.CancelToken
    ) -> None:
        ok = False
        try:
            ok = updater.download(
                url,
                dest,
                on_progress=lambda value: self._updateProgress.emit(int(value)),
                cancel=cancel,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("下载更新异常：%s", exc)
        try:
            self._updateDownloaded.emit(bool(ok), str(dest))
        except RuntimeError:  # 宿主已销毁
            pass

    @Slot()
    def downloadUpdate(self) -> None:
        """下载最新安装包（后台线程，可取消）。"""
        info = self._update_info or {}
        url = str(info.get("assetUrl") or "")
        if self._update_state == "downloading":
            return
        if not url:
            self._set_update_state("error", "没有可下载的安装包")
            self.toast.emit(QCoreApplication.translate("ShenQing", "没有可下载的安装包"))
            return
        name = Path(str(info.get("assetName") or "ShenQing-Setup.exe")).name
        dest = app_data_dir() / "updates" / name
        self._update_download_path = dest
        self._update_progress = 0
        self._update_cancel = updater.CancelToken()
        self._set_update_state("downloading")
        threading.Thread(
            target=self._download_update_worker,
            args=(url, dest, self._update_cancel),
            name="shenqing-update-download",
            daemon=True,
        ).start()

    @Slot()
    def cancelUpdateDownload(self) -> None:
        if self._update_cancel is not None:
            self._update_cancel.cancel()

    @Slot(int)
    def _on_update_progress(self, value: int) -> None:
        self._update_progress = max(0, min(100, int(value)))
        self.stateChanged.emit()

    @Slot(bool, str)
    def _on_update_downloaded(self, ok: bool, dest: str) -> None:
        path = Path(dest) if dest else None
        if ok and path is not None and path.exists() and path.stat().st_size > 0:
            self._update_download_path = path
            self._update_progress = 100
            self._set_update_state("ready")
            self.toast.emit(QCoreApplication.translate("ShenQing", "安装包已下载完成"))
        else:
            self._update_download_path = None
            self._set_update_state("error", "下载失败或被取消")
            self.toast.emit(QCoreApplication.translate("ShenQing", "下载失败或被取消"))

    @Slot()
    def installUpdate(self) -> None:
        """启动已下载的安装包；先停看门狗，避免安装期间被自动拉起。"""
        path = self._update_download_path
        if self._update_state != "ready" or path is None or not path.exists():
            self.toast.emit(QCoreApplication.translate("ShenQing", "安装包尚未下载完成"))
            return
        try:
            from ..services import keeper

            keeper.stop_keeper()
        except Exception as exc:  # noqa: BLE001
            logger.warning("安装前停止看门狗失败：%s", exc)
        try:
            os.startfile(str(path))  # noqa: S606 - 用户主动安装更新
        except Exception as exc:  # noqa: BLE001
            logger.warning("启动安装程序失败：%s", exc)
            self.toast.emit(QCoreApplication.translate("ShenQing", "无法启动安装程序"))
            return
        self.toast.emit(
            QCoreApplication.translate("ShenQing", "安装程序已启动，安装完成后请重新打开深清")
        )

    @Slot()
    def openReleasePage(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        page = str((self._update_info or {}).get("pageUrl") or "")
        url = updater.release_page_url(page)
        try:
            QDesktopServices.openUrl(QUrl(url))
        except Exception as exc:  # noqa: BLE001
            logger.warning("打开更新页面失败：%s", exc)
            self.toast.emit(QCoreApplication.translate("ShenQing", "无法打开浏览器"))

    # ================= v0.16 速启面板：重启 / 管理员重启 =================
    def _spawn_restart(self, extra_args: str = "") -> bool:
        """停看门狗并拉起新进程（--restarted）。成功返回 True。"""
        try:
            from ..services import keeper

            keeper.stop_keeper()
        except Exception as exc:  # noqa: BLE001 - 重启失败也要继续尝试
            logger.warning("重启前停止看门狗失败：%s", exc)
        try:
            from PySide6.QtCore import QProcess

            from ..services import keeper

            command = list(keeper.main_command())
            if not command:
                return False
            program = command[0]
            args = command[1:]
            if "--restarted" not in args:
                args.append("--restarted")
            if extra_args:
                args.extend(extra_args.split())
            return bool(
                QProcess.startDetached(program, args, keeper.working_directory())
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("拉起新进程失败：%s", exc)
            return False

    @Slot()
    def restartApp(self) -> None:
        """v0.16 速启面板：正常重启深清。"""
        if not self._spawn_restart():
            self.toast.emit(
                QCoreApplication.translate("ShenQing", "重启失败，请手动重新打开深清")
            )
            return
        self.toast.emit(QCoreApplication.translate("ShenQing", "正在重启深清…"))
        application = QCoreApplication.instance()
        if application is not None:
            QTimer.singleShot(300, application.quit)

    @Slot()
    def relaunchAsAdmin(self) -> None:
        """v0.16 速启面板：以管理员身份重启（ShellExecute runas）。"""
        if elevation.is_admin():
            self.toast.emit(QCoreApplication.translate("ShenQing", "当前已是管理员权限"))
            return
        self.toast.emit(QCoreApplication.translate("ShenQing", "正在请求管理员权限…"))
        try:
            ok = elevation.relaunch_as_admin("--restarted")
        except Exception as exc:  # noqa: BLE001
            logger.warning("管理员重启失败：%s", exc)
            ok = False
        if ok:
            self.quitRequested.emit()
        else:
            self.toast.emit(
                QCoreApplication.translate(
                    "ShenQing", "提权失败：用户取消了 UAC 或策略禁止"
                )
            )

    @Slot(str, result=list)
    def search(self, query: str) -> list[dict]:
        text = str(query or "").strip().casefold()
        if not text:
            return []
        results: list[dict] = []

        def add(title: str, sub: str, kind: str, payload: object) -> None:
            if text in title.casefold() or text in sub.casefold():
                results.append({"title": title, "sub": sub, "kind": kind, "payload": payload})

        add(QCoreApplication.translate("ShenQing", "空间"), QCoreApplication.translate("ShenQing", "清空间与专注设置"), "page", 0)
        add(QCoreApplication.translate("ShenQing", "数据"), QCoreApplication.translate("ShenQing", "专注统计"), "page", 1)
        add(QCoreApplication.translate("ShenQing", "插件"), QCoreApplication.translate("ShenQing", "插件管理"), "page", 2)
        add(QCoreApplication.translate("ShenQing", "设置"), QCoreApplication.translate("ShenQing", "偏好设置"), "page", 3)
        add(QCoreApplication.translate("ShenQing", "主题样式"), QCoreApplication.translate("ShenQing", "纯色 / 液态玻璃 / 海洋"), "theme", "")
        add(QCoreApplication.translate("ShenQing", "主题配色"), QCoreApplication.translate("ShenQing", "跟随系统 / 浅色 / 深色"), "scheme", "")
        for mode in self.modes:
            add(mode["label"], mode["desc"], "mode", mode["value"])
        # v0.6：每张空间也是一条搜索结果（payload 带 id + mode，QML 可跳到空间页）
        for space in self.spaces:
            mode = str(space.get("mode") or "")
            label = QCoreApplication.translate("ShenQing", MODE_LABELS.get(mode, mode))
            add(
                str(space.get("name") or ""),
                label,
                "space",
                {"id": str(space.get("id") or ""), "mode": mode},
            )
        for theme in self.themes:
            add(theme["label"], theme["desc"], "theme", theme["value"])
        for plugin in self.plugins:
            add(str(plugin.get("name") or ""), str(plugin.get("description") or ""), "plugin", str(plugin.get("id") or ""))
        for action, label in (
            ("hardening", QCoreApplication.translate("ShenQing", "防退出加固")),
            ("admin", QCoreApplication.translate("ShenQing", "以管理员身份运行")),
            ("autostart", QCoreApplication.translate("ShenQing", "最高权限开机自启")),
            ("feedback", QCoreApplication.translate("ShenQing", "功能请求与 Bug 反馈")),
        ):
            add(label, QCoreApplication.translate("ShenQing", "设置"), "action", action)
        return results[:20]

    @Slot(str)
    def openFeedback(self, kind: str) -> None:
        url = FEEDBACK_URLS.get(str(kind or ""), FEEDBACK_URLS["request"])
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl(url))
        except Exception as exc:  # noqa: BLE001
            logger.warning("打开反馈页面失败：%s", exc)
            self.toast.emit(QCoreApplication.translate("ShenQing", "无法打开浏览器"))

    # ================= 内部回调 =================
    def _on_tick(self, remaining: int) -> None:
        self.tickChanged.emit()
        self._dispatch("tick", int(remaining))

    def _on_finished(self, elapsed_seconds: int, completed: bool, pauses: int) -> None:
        clicks = self._stop_click_tracking()
        interrupted = bool(self._force_interrupt)
        self._force_interrupt = False
        self._time_clicks.clear()
        self._exit_warning = False
        self._delete_session_state()
        self._restore_site_block(force=True)
        self._restore_desktop_icons(force=True)
        self._guard.stop()
        power.allow_sleep()
        self._sleep_lock_active = False
        self._clock_clicks.clear()
        space = self._spaces.get(self._active_space_id)
        space_name = str(space["name"]) if space else ""
        minutes = elapsed_seconds / 60
        if self._trial_active:
            # 体验模式只做演示：不写统计、不影响连续天数
            self.toast.emit(QCoreApplication.translate("ShenQing", "体验结束"))
        elif completed or minutes >= 1 or interrupted:
            self._stats.record(
                minutes,
                self._session_level or self.lockLevel,
                completed,
                pauses,
                space=space_name,
                when=timesync.now(),
                started_at=self._session_started_at,
                clicks=clicks,
                interrupted=interrupted,
            )
            self.statsChanged.emit()
            if interrupted:
                self.toast.emit(
                    QCoreApplication.translate("ShenQing", "已强制结束本次专注")
                )
            elif completed:
                self.toast.emit(
                    QCoreApplication.translate("ShenQing", "本轮专注完成，休息一下")
                )
            else:
                self.toast.emit(
                    QCoreApplication.translate("ShenQing", "本轮专注已结束")
                )
        else:
            self.toast.emit(QCoreApplication.translate("ShenQing", "专注时间太短，未计入统计"))
        summary = {
            "space": space_name,
            "space_id": self._active_space_id,
            "space_name": space_name,
            "minutes": round(minutes, 1),
            "completed": bool(completed),
            "pauses": int(pauses),
            "clicks": int(clicks),
            "interrupted": interrupted,
        }
        self._dispatch("session_end", summary)
        try:
            if completed:
                self._notifications.notify(
                    QCoreApplication.translate("ShenQing", "专注完成"),
                    "{} · {}".format(
                        space_name or QCoreApplication.translate("ShenQing", "专注"),
                        QCoreApplication.translate("ShenQing", "休息一下"),
                    ),
                )
            elif minutes >= 1:
                self._notifications.notify(
                    QCoreApplication.translate("ShenQing", "专注结束"),
                    "{} · {}".format(
                        space_name or QCoreApplication.translate("ShenQing", "专注"),
                        QCoreApplication.translate("ShenQing", "{0} 分钟").format(round(minutes)),
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("结束通知失败：%s", exc)
        self._active_space_id = ""
        self._session_level = ""
        self._trial_active = False
        self._last_session_clicks = clicks
        self.tickChanged.emit()
        self.stateChanged.emit()
        self.lockedChanged.emit()

    def _on_process_killed(self, exe_name: str) -> None:
        self.guardEvent.emit(exe_name)
        self._dispatch("process_blocked", str(exe_name))
