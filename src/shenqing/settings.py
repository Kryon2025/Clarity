"""用户设置持久化（%APPDATA%\\ShenQing\\settings.json）。"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

from .consts import (
    CUSTOM_THEME_PREFIX,
    DEFAULT_THEME_SCHEME,
    DEFAULT_THEME_STYLE,
    OVERLAY_WIDGET_DEFAULT_LAYOUT,
    LockLevel,
)
from .paths import app_data_dir

#: 旧版单一主题键：v0.21 起只用于一次性迁移，不再写入
LEGACY_THEME_KEY = "theme_mode"


def migrate_theme_mode(value: Any) -> tuple[str, str]:
    """把旧 theme_mode 映射成 (样式, 配色)。

    light→(solid, light)；solid/未知值→(solid, dark)；glass/ocean→(自身, dark)；
    custom:<id>→(custom:<id>, auto)。未知值保留旧版深色 chrome，避免升级后界面突变。
    """
    text = str(value or "").strip()
    if text == "light":
        return (DEFAULT_THEME_STYLE, "light")
    if text in ("glass", "ocean"):
        return (text, "dark")
    if text.startswith(CUSTOM_THEME_PREFIX) and len(text) > len(CUSTOM_THEME_PREFIX):
        return (text, "auto")
    return (DEFAULT_THEME_STYLE, "dark")


DEFAULTS: dict[str, Any] = {
    "theme": "Auto",            # 窗口 chrome：Auto / Light / Dark（旧键，保留兼容）
    # v0.21 外观拆成两个正交维度：样式（solid/glass/ocean/custom:<id>）+ 配色（auto/light/dark）
    "theme_style": DEFAULT_THEME_STYLE,
    "theme_scheme": DEFAULT_THEME_SCHEME,
    "custom_themes": {},        # v0.18 自定义主题包：id -> {name, description, palette}
    "store_catalog_url": (      # v0.18 商店目录 JSON 地址（留空 = 只用内置目录）
        "https://raw.githubusercontent.com/Kryon2025/Clarity/store/catalog.json"
    ),
    "store_comments": {},       # v0.18 商店评论：item_id -> [{id,author,rating,text,created_at,status}]
    "default_mode": "medium",   # 默认强度：light / medium / heavy
    "language": "auto",  # auto / zh_CN / en_US
    "autostart": False,
    "hardening": True,      # 防退出加固：隐藏任务栏 + 屏蔽系统快捷键
    "keep_alive": True,     # 不杀进程：只隐藏窗口 + 静音（保留未保存工作）
    "admin_mode": False,    # 以管理员身份运行（启动时 UAC 提权）
    "auto_update": True,    # 启动后自动检查 GitHub Releases 更新
    "ai_enabled": False,    # AI 集成（v0.9 真实接入，云端免费 API）
    "ai_provider": "groq",  # groq / glm / siliconflow / custom
    "ai_api_base": "",
    "ai_api_key": "",
    "ai_model": "",
    "ai_models_cache": {},  # provider -> {models:[...], fetchedAt}（24h 过期）
    "ai_reasoning_enabled": True,   # 思考模式（DeepSeek thinking / OpenAI reasoning_effort）
    "ai_web_search_enabled": False,  # 联网检索（DeepSeek / GLM）
    "ai_reasoning_effort": "",       # 可选：low / medium / high（OpenAI/DeepSeek）
    "ui_font_family": "",            # 界面字体（空 = 内置默认字体）
    "ui_font_scale": 1.0,            # 界面字号缩放 0.8-1.4（步进 0.05）
    "nav_mode": "expanded",          # 导航模式：auto / expanded / icons / custom
    "app_usage_heatmap_days": 90,    # 应用热力图天数：30 / 90 / 180
    "volume_panel": 50,     # dock 设置面板上次的系统音量（0-100）
    "onboarding_done": False,  # 首次使用引导是否完成
    "update_source": "github",  # v0.16 更新下载源：github / gitlink / gitee / 自定义源 id
    "custom_update_sources": [],  # v0.16 自定义更新源：[{id,name,url,token}]
    "pomodoro_work_minutes": 25,          # v0.16 清番：专注分钟数
    "pomodoro_break_minutes": 5,          # v0.16 清番：短休息分钟数
    "pomodoro_long_break_minutes": 15,    # v0.16 清番：长休息分钟数
    "pomodoro_rounds_before_long": 4,     # v0.16 清番：几轮后长休息
    "countdown_date": "",      # 倒数日目标日期 YYYY-MM-DD（空=不显示）
    "overlay_widget_order": [],  # 全屏遮罩自定义组件顺序 ["pluginId:itemId"]
    "default_minutes": 25,
    "lock_level": LockLevel.MEDIUM.value,
    "guard_interval_ms": 1000,
    "pause_limit": 2,           # 一次会话允许的暂停次数
    "cooldown_minutes": 5,      # 提前结束后再次开始前的冷却
    "pin_enabled": False,
    "pin": "",                  # 明文仅作占位，正式版改哈希
    "hosts_block_enabled": False,  # 旧版占位开关（保留兼容，不再使用）
    "blocked_sites": [],           # 专注期间屏蔽的网站域名（v0.15）
    "site_block_enabled": True,
    "hide_desktop_icons": True,      # 浅清/覆清专注期间隐藏桌面图标
    "update_channel": "stable",      # 更新渠道：stable 正式版 / preview 预览版    # 是否启用 hosts 网站屏蔽
    "card_background": "",         # 结束卡片背景：空=必应每日壁纸；否则本地图片绝对路径
    "web_admin_enabled": False,    # v0.19 网页管理：浏览器里打开本地管理页
    "web_admin_port": 8765,        # v0.19 网页管理端口（被占用时自动 +1，最多 20 次）
    "web_admin_token": "",         # v0.19 网页管理 token（首次启用时生成并持久化）
    "cloud_sync_url": "",          # v0.20 账户同步：商店服务器地址（留空 = 未配置）
    "cloud_sync_email": "",        # v0.20 账户同步：登录邮箱（不存密码）
    "cloud_sync_token": "",        # v0.20 账户同步：登录令牌（只在登录后保存）
    "cloud_sync_device": "",       # v0.20 账户同步：本机名称（空 = 取电脑名）
    "cloud_sync_revision": 0,      # v0.20 账户同步：本机上次同步到的远端 revision
    "cloud_sync_last_at": "",      # v0.20 账户同步：上次成功同步时间
    # v0.21 右侧组件（「组件预览」自定义右半屏）：布局项 {id,type,x,y,w,h,visible,props}
    "overlay_widgets": copy.deepcopy(OVERLAY_WIDGET_DEFAULT_LAYOUT),
    "overlay_widgets_enabled": True,  # 右半屏组件总开关
    "weather_city_id": "58362",       # 天气组件城市编号（中央气象台站点，58362 = 北京）
}


class Settings:
    """极简 JSON 设置容器（读写都在主线程，够用且好调试）。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (app_data_dir() / "settings.json")
        #: 首次运行（配置文件尚不存在）——app.py 用它决定默认最高权限
        self.is_new = not self.path.exists()
        # 深拷贝：DEFAULTS 里的 list / dict 不能在所有 Settings 实例之间共享
        self._data: dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            if self.path.exists():
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data.update(loaded)
                    # v0.21：旧 theme_mode 一次性迁移到 theme_style / theme_scheme
                    if self._migrate_theme_keys(loaded):
                        self.save()
        except (OSError, json.JSONDecodeError):
            # 配置坏了就用默认值，不让启动失败
            self._data = copy.deepcopy(DEFAULTS)

    def _migrate_theme_keys(self, loaded: dict[str, Any]) -> bool:
        """把旧 theme_mode 迁移成新键并清理旧键；返回是否需要写回。

        仅当新键缺省时才按旧值推断；旧键无论是否迁移都从内存/磁盘里清掉。
        """
        dirty = False
        has_style = "theme_style" in loaded
        has_scheme = "theme_scheme" in loaded
        if not has_style and not has_scheme:
            style, scheme = migrate_theme_mode(loaded.get(LEGACY_THEME_KEY))
            self._data["theme_style"] = style
            self._data["theme_scheme"] = scheme
            dirty = True
        else:
            if not has_style:
                self._data["theme_style"] = DEFAULT_THEME_STYLE
                dirty = True
            if not has_scheme:
                self._data["theme_scheme"] = DEFAULT_THEME_SCHEME
                dirty = True
        if LEGACY_THEME_KEY in self._data:
            self._data.pop(LEGACY_THEME_KEY, None)
            dirty = True
        return dirty

    def save(self) -> None:
        """原子写：先写 .tmp 再 os.replace，避免断电/并发写坏 settings.json。"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(self.path.name + ".tmp")
            temp.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temp, self.path)
        except OSError:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any, *, save: bool = True) -> None:
        self._data[key] = value
        if save:
            self.save()
