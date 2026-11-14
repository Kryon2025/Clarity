"""常量与产品级默认值。"""

from __future__ import annotations

from enum import Enum

APP_NAME = "深清"
#: 英文名（v0.4 起对外统一用 Clarity；「身轻」不再展示）
APP_ALIAS = "Clarity"
APP_ID = "ShenQing"
APP_VERSION = "0.18.2"

#: v0.18 自定义主题 id 前缀：theme_mode = "custom:<id>"
CUSTOM_THEME_PREFIX = "custom:"

#: GitHub 仓库（自动更新与反馈入口用）
GITHUB_REPO = "Kryon2025/Clarity"

#: 唯一空间的名字（不可改名）
SPACE_NAME = "清空间"

#: 三档强度（界面文案；枚举值仍是 light/medium/heavy）
MODE_LABELS = {"light": "浅清", "medium": "覆清", "heavy": "深清"}

#: 主题：纯色（默认）/ 清空间浅色 / 液态玻璃（实验性）/ 海洋（静态波浪）
THEMES = [
    {"value": "solid", "label": "纯色", "desc": "平面纯色，无需 GPU 特效", "experimental": False},
    {
        "value": "light",
        "label": "清空间浅色",
        "desc": "浅色底的清空间主题",
        "experimental": False,
    },
    {
        "value": "glass",
        "label": "液态玻璃",
        "desc": "折射玻璃与拖拽高光（实验性）",
        "experimental": True,
    },
    {
        "value": "ocean",
        "label": "海洋",
        "desc": "深海渐变与静态浪花",
        "experimental": False,
    },
]
DEFAULT_THEME = "solid"

#: v0.17：CW2 风格字体下拉 —— 精选中文字体优先。
#: 只有系统里真正安装了的字体才会出现在列表顶部（按下面的固定顺序）；
#: 未安装的自动跳过，其余系统字体按名称排序跟在后面。
PREFERRED_CJK_FONTS = (
    "微软雅黑",
    "Microsoft YaHei UI",
    "等线",
    "DengXian",
    "思源黑体",
    "Source Han Sans SC",
    "思源宋体",
    "Source Han Serif SC",
    "霞鹜文楷",
    "LXGW WenKai",
    "得意黑",
    "Smiley Sans",
    "HarmonyOS Sans SC",
    "MiSans",
    "苹方",
    "PingFang SC",
    "微软正黑体",
)

#: 字体下拉最多返回的条目数
MAX_FONT_FAMILIES = 200

#: 更新日志（最新在前；en 为空时用中文兜底）
CHANGELOG = [
    {
        "version": "0.18.2",
        "date": "2025-11-14",
        "tag": "",
        "items": [
            "商店目录改为真实在线目录（上传 catalog.json 到 store 分支），打开商店即可看到在线条目",
            "新增启动参数 --store theme|plugin，可直接打开主题/插件商店；重复启动会切换到对应商店页",
        ],
        "items_en": [
            "Store catalog is now served online (catalog.json on the store branch)",
            "New --store theme|plugin argument opens the theme or plugin store directly",
        ],
    },
    {
        "version": "0.18.1",
        "date": "2025-11-14",
        "tag": "",
        "items": [
            "新手引导改为普通窗口（居中、可移动），不再全屏显示",
        ],
        "items_en": ["Getting-started guide is now a normal centered window instead of fullscreen"],
    },
    {
        "version": "0.18.0",
        "date": "2025-11-14",
        "tag": "",
        "items": [
            "商店后端：主题/插件目录在线拉取（6 秒超时，失败回退内置 6 主题 + 4 插件），结果缓存 10 分钟",
            "自定义主题包：settings 保存 custom_themes，theme_mode 支持 custom:<id>，安装/删除后即时生效",
            "商店评论：新评论默认审核中，仅 approved 展示，同一项目每分钟最多 3 条",
            "插件商店安装：zip 下载 + plugin.json 校验 + 防路径穿越解压到用户插件目录并热重载",
        ],
        "items_en": [
            "Store backend: online theme/plugin catalog (6s timeout, builtin fallback with 6 themes + 4 plugins), cached for 10 minutes",
            "Custom theme packages: custom_themes in settings, theme_mode supports custom:<id>, install/remove applies immediately",
            "Store comments: new comments start pending, only approved are shown, max 3 per item per minute",
            "Plugin store install: zip download + plugin.json validation + traversal-safe extraction into the user plugin dir with hot reload",
        ],
    },
    {
        "version": "0.17.4",
        "date": "2025-11-14",
        "tag": "",
        "items": [
            "左侧导航列文字跟随全局字号调整",
        ],
        "items_en": ["Left navigation labels now follow the global font-scale setting"],
    },
    {
        "version": "0.17.3",
        "date": "2025-11-14",
        "tag": "",
        "items": [
            "设置页滚动条细节修正：移除旧自绘细线、宽度 6px、悬停加深",
        ],
        "items_en": ["Settings scrollbar polish: removed the old hand-drawn bar, 6px width, hover emphasis"],
    },
    {
        "version": "0.17.2",
        "date": "2025-11-14",
        "tag": "",
        "items": [
            "修复设置页滚动条使用原生样式导致的 QML 警告（改用 Basic 控件样式，恢复细圆角滚动条外观）",
        ],
        "items_en": ["Fixed QML warnings from the settings scrollbar by using the Basic controls style (slim rounded scrollbar restored)"],
    },
    {
        "version": "0.17.1",
        "date": "2025-11-14",
        "tag": "",
        "items": [
            "设置页：新增可拖动细滚动条，卡片与字体行在窄窗口不再被裁切",
            "默认背景改为近均匀深色，滚到底部不再明显发黑",
        ],
        "items_en": [
            "Settings: draggable slim scrollbar; cards and the font row no longer clip in narrow windows",
            "Default background is now near-uniform dark, so the bottom no longer looks darker",
        ],
    },
    {
        "version": "0.17.0",
        "date": "2025-11-14",
        "tag": "",
        "items": [
            "默认外观恢复原样，海洋波浪改为第 4 个内置主题（静态浪花，不再有动态背景）",
            "数据页标题改为「空间的心事」，分类切换改为与空间页一致的下划线 tab",
            "清番提到离浅清相同的位置并排第一：空间页首个档位、速启面板第一个，点开即番茄钟",
            "速启面板重做：去图标、档位横向滑动可露出还清、关闭/重启/管理员重启同位置纯图标（管理员时隐藏管理员重启）",
            "覆清控制面板重做（control 图标 + 音量滑块 + 关机/重启二次确认）",
            "重复打开深清会直接激活主界面（单实例）；字体列表精选中文字体优先（微软雅黑/等线/思源黑体/霞鹜文楷/得意黑等）",
        ],
        "items_en": [
            "Default look restored; the ocean wave style is now a 4th built-in theme (static foam, no animated background)",
            "Stats title now reads Whispers of your space; category switch uses the same underline tabs as Spaces",
            "Pomodoro (Qingfan) now sits first, in the same slot as Light, on both Spaces and the quick panel; tap to open the timer",
            "Quick panel redesign: no logo, draggable tier strip revealing Huanqing, icon-only close/restart/restart-as-admin in one spot (admin restart hidden when elevated)",
            "Veil control panel redesigned (control icon + volume slider + shutdown/restart with confirmation)",
            "Launching ShenQing again activates the main window (single instance); curated Chinese fonts first in the font list",
        ],
    },
    {
        "version": "0.16.3",
        "date": "2025-11-14",
        "tag": "",
        "items": [
            "全新海洋波浪视觉：深海渐变 + 分层浪花背景，强调色统一为海洋蓝青",
            "清空间 / 数据 / 设置 / AI / 主题页头加入波浪底纹，引导、锁屏、加载环、速启面板与结束卡片同步海洋主题",
            "应用图标更换为水彩海浪（安装包/窗口/托盘同步）",
        ],
        "items_en": [
            "New ocean-wave visual language: deep-sea gradients, layered foam backdrops and ocean-teal accents throughout",
            "Wave headers on Spaces/Stats/Settings/AI/Themes, plus onboarding, lock overlay, loading ring, quick panel and summary card",
            "New watercolor-wave application icon (installer, window and tray)",
        ],
    },
    {
        "version": "0.16.2",
        "date": "2025-11-14",
        "tag": "",
        "items": [
            "安装程序改为全中文界面（不再出现英文向导页）",
        ],
        "items_en": ["Installer is now fully Chinese (no English wizard pages)"],
    },
    {
        "version": "0.16.1",
        "date": "2025-11-14",
        "tag": "",
        "items": [
            "更换应用图标（水彩海浪）与速启（控制）面板图标（白色胶囊图形）",
        ],
        "items_en": ["New application icon (watercolor waves) and quick-panel/control icon (white capsule glyph)"],
    },
    {
        "version": "0.16.0",
        "date": "2025-11-14",
        "tag": "",
        "items": [
            "更新下载源：内置 GitHub / GitLink / Gitee，支持自定义 JSON 更新源（可带 Token），失败信息可读并可在关于页切换",
            "覆清与深清一样不再提供暂停 / 退出；连续点击时间显示 10 次（6 秒内）弹出警告，确认后强制结束并标记 interrupted",
            "新增「清番」番茄钟：置顶悬浮，25 分钟专注 / 5 分钟短休息 / 4 轮后 15 分钟长休息，可暂停、跳过、退出",
            "首次使用引导取代主界面显示：引导完成前隐藏主窗口，完成后再进主界面",
            "速启面板新增「重启」与「以管理员身份重启」，移除无用按钮",
        ],
        "items_en": [
            "Update sources: built-in GitHub / GitLink / Gitee plus custom JSON sources (optional token); readable errors and source switching on the About page",
            "Veil no longer offers pause/exit, like Deep; clicking the time display 10 times within 6 seconds shows a warning and a confirmed forced exit is recorded as interrupted",
            "New Qingfan pomodoro: always-on-top timer with 25-minute focus / 5-minute break / 15-minute long break every 4 rounds, with pause, skip and exit",
            "First-run onboarding replaces the main window: the main window stays hidden until the guide is finished",
            "Quick panel gained Restart and Restart as administrator, and dropped unused buttons",
        ],
    },
    {
        "version": "0.15.0",
        "date": "2025-11-08",
        "tag": "",
        "items": [
            "设置新增网址屏蔽：专注期间通过 hosts 屏蔽指定网站（需要管理员权限），支持开关与域名列表",
            "结束卡片背景支持上传本地图片，默认使用必应每日壁纸，可一键恢复默认",
            "还清并入档位：清空间档位变为 浅清 / 覆清 / 深清 / 还清，不再单独放按钮",
            "入场倒计时改为干净的加载环动画（移除全部粒子与游离光点）",
        ],
        "items_en": [
            "Website blocking: blocks chosen sites via the hosts file during focus (requires administrator rights), with a switch and domain list",
            "Summary card background can use a local image; Bing daily wallpaper is the default with one-click restore",
            "Huanqing is now a tier: Light / Veil / Deep / Huanqing, no separate button",
            "Entry countdown is now a clean loading ring (all particles and stray light dots removed)",
        ],
    },
    {
        "version": "0.14.0",
        "date": "2025-11-08",
        "tag": "",
        "items": [
            "设置新增数据与备份：一键导出/导入备份（含设置、空间、统计、应用使用、AI 对话、睡眠与插件数据），导入前二次确认并自动重启",
            "字号改为 CW2 风格滑块（80%–140%，实时预览）",
            "专注被关掉后重新打开会自动恢复锁定；已完成则补记统计",
            "统计本次专注鼠标点击次数，锁屏、结束卡片与数据页均可查看",
            "新增「卡皮巴拉敲木鱼」遮罩组件插件",
        ],
        "items_en": [
            "Settings gained Data & backup: export/import a backup (settings, spaces, stats, app usage, AI chats, sleep and plugin data) with confirmation and automatic restart",
            "Font size is now a CW2-style slider (80%–140%, live preview)",
            "If ShenQing is closed during focus, reopening it restores the lock automatically; completed sessions are recorded",
            "Per-session mouse click counting, shown on the lock screen, summary card and stats page",
            "New Capybara wooden-fish overlay widget plugin",
        ],
    },
    {
        "version": "0.13.0",
        "date": "2025-11-07",
        "tag": "",
        "items": [
            "数据页改为 Patina 式横向分类：概览 / 应用 / 分类 / 热力图 / 会话，一次只显示一个分类",
            "新增应用分类管理：按 exe 自动检测类别，可手动修改或恢复自动",
            "新增 GitHub 风格 90 天热力图与 24 小时使用分布",
            "还清（睡眠模式）入口移到清空间页顶部，设置里改为迁移说明",
        ],
        "items_en": [
            "Stats page now uses Patina-style horizontal tabs: Overview / Apps / Categories / Heatmap / Sessions, one at a time",
            "App category management: automatic detection by exe, with manual override and restore",
            "GitHub-style 90-day heatmap and 24-hour usage distribution",
            "Sleep mode (Huanqing) entry moved to the top of the Clarity Space page; Settings now shows a migration note",
        ],
    },
    {
        "version": "0.12.1",
        "date": "2025-11-07",
        "tag": "",
        "items": [
            "修复 AI 页发送消息后输入框文字不清空的问题",
        ],
        "items_en": ["Fixed the AI input field not clearing after sending a message"],
    },
    {
        "version": "0.12.0",
        "date": "2025-11-07",
        "tag": "",
        "items": [
            "导航默认展开并收窄：展开 140px / 仅图标 64px，菜单项更紧凑、间距收紧，高亮只大一圈",
            "设置 → 外观 新增导航展开方式：自动 / 始终展开 / 仅图标",
            "设置 → 外观 新增全局字号（小 / 标准 / 大 / 特大）与字体选择，实时生效无需重启",
        ],
        "items_en": [
            "Navigation is expanded by default and narrower: 140px expanded / 64px icons-only, tighter items and spacing, highlight only slightly larger",
            "Appearance settings: navigation display mode (Auto / Always expanded / Icons only)",
            "Appearance settings: global font size (Small / Standard / Large / Extra large) and font family, applied immediately without restart",
        ],
    },
    {
        "version": "0.11.2",
        "date": "2025-11-07",
        "tag": "",
        "items": [
            "CI：单测失败时自动把日志发到提交注释，便于排查；锁定 PySide6 版本",
        ],
        "items_en": ["CI: automatically post unit-test failure logs as a commit comment; pin PySide6 version"],
    },
    {
        "version": "0.11.1",
        "date": "2025-11-07",
        "tag": "",
        "items": [
            "修复 AI 页布局错位：服务商/模型下拉贴输入框展开并夹紧在页面内，配置与对话区不再重叠",
            "恢复页面打开/关闭动画：AI、更新、主题、关于页统一 200ms 淡入上移 / 160ms 淡出下移",
            "全局搜索框居中移到窗口顶部，页面内容预留顶部空间",
            "DeepSeek 旧模型名（deepseek-chat / deepseek-reasoner）自动迁移为 deepseek-flash",
        ],
        "items_en": [
            "Fixed AI page layout: provider/model dropdowns now open below their fields and stay inside the page; config and chat cards no longer overlap",
            "Restored page open/close animations for AI, Updates, Themes and About (200ms fade-in, 160ms fade-out)",
            "Global search moved to the horizontal center of the window top",
            "Legacy DeepSeek model names (deepseek-chat / deepseek-reasoner) migrate to deepseek-flash",
        ],
    },
    {
        "version": "0.11.0",
        "date": "2025-11-07",
        "tag": "",
        "items": [
            "AI 新增免配置服务商「免费直连」：无需 API Key，选好模型即可直接聊天",
            "AI 对话历史持久化：会话列表、新建/切换/删除、消息与思考内容保存",
            "深度思考可选：DeepSeek thinking 开关与 reasoning_effort，回答里的思考过程可折叠查看",
            "联网搜索：DeepSeek tools/search、智谱 GLM web_search，按服务商能力显示开关",
            "AI 用量与费用估算：今日 tokens、估算金额、最近一次回复用量；对话使用真实 token 统计",
            "DeepSeek 模型更新为 deepseek-flash / deepseek-v4-pro（旧模型名已下线）",
        ],
        "items_en": [
            "New no-setup AI provider Free direct: no API key needed, pick a model and chat",
            "Persistent AI chat history: conversation list, new/switch/delete, messages and reasoning saved",
            "Optional deep thinking: DeepSeek thinking switch and reasoning_effort; reasoning shown in a collapsible block",
            "Web search: DeepSeek tools/search and Zhipu GLM web_search, shown only when the provider supports it",
            "AI usage and estimated cost: today tokens, estimated amount, last reply usage; real token counts per chat",
            "DeepSeek models updated to deepseek-flash / deepseek-v4-pro (old model IDs retired)",
        ],
    },
    {
        "version": "0.10.1",
        "date": "2025-11-07",
        "tag": "",
        "items": [
            "AI 错误提示更友好：404 会提示检查 API Base（如 DeepSeek 应为 https://api.deepseek.com/v1），401/403 提示 Key 无效，429 限流提示，5xx 服务端错误",
        ],
        "items_en": [
            "Friendlier AI errors: 404 suggests checking the API base (DeepSeek should be https://api.deepseek.com/v1), 401/403 means invalid key, 429 rate limit, 5xx server error",
        ],
    },
    {
        "version": "0.10.0",
        "date": "2025-11-07",
        "tag": "",
        "items": [
            "导航新增 AI 页（数据下方）与更新页（设置上方）；AI 配置与对话迁到独立页面",
            "AI 服务商新增 DeepSeek、小米 MiMo、ChatGPT，并支持自动获取最新模型列表（24 小时缓存，可手动刷新）",
            "更新页：检查更新、查看更新说明、下载进度、安装并重启、最近更新日志",
            "入场动画改为持续流场粒子：水光拖尾、三层视差、中心可读性优化，结束光波扩散",
            "修复 CI 单测在 UTC 时区下因硬编码日期失败的问题",
        ],
        "items_en": [
            "New AI page (below Stats) and Updates page (above Settings); AI configuration and chat moved to their own page",
            "AI providers now include DeepSeek, Xiaomi MiMo and ChatGPT, with automatic latest-model fetching (24h cache, manual refresh)",
            "Updates page: check for updates, release notes, download progress, install-and-restart, recent changelog",
            "Entry animation reworked into a continuous flow field: light trails, three depth layers, readable center, final light wave",
            "Fixed CI unit tests failing under UTC due to a hard-coded date",
        ],
    },
    {
        "version": "0.9.0",
        "date": "2025-11-07",
        "tag": "",
        "items": [
            "Patina 式应用使用时长统计：前台应用每 5 秒采样，自动跳过空闲/锁屏/休眠，分类与颜色可自定义，数据页可看今日 / 本周 / 历史",
            "AI 助手：支持 Groq、智谱 GLM、硅基流动与自定义 OpenAI 兼容接口，异步问答、测试连接，Key 只保存在本机",
            "数据页新增「应用使用时长」卡片：类别横向 chips + 堆叠条、应用排行与比例条",
            "设置页新增 AI 助手配置卡片；右上角新增 AI 助手浮层（问问题、复制回答、未配置引导）",
            "AI 可做设置语义搜索（自然语言找设置项），失败自动回退本地模糊匹配",
            "NOTICE 增加 Patina（MIT）设计参考说明",
        ],
        "items_en": [
            "Patina-style app usage tracking: foreground app sampled every 5 seconds, idle/lock/sleep skipped, custom categories and colors, today / this week / history on the stats page",
            "AI assistant: Groq, Zhipu GLM, SiliconFlow and custom OpenAI-compatible endpoints; async chat, connection test, API key stored locally only",
            "New App usage card on the stats page: category chips, stacked bar, app ranking with proportion bars",
            "AI assistant card in settings; global AI assistant panel in the top-right corner (ask, copy answer, setup hint)",
            "AI-powered semantic settings search with local fuzzy fallback",
            "NOTICE now credits Patina (MIT) as a design reference",
        ],
    },
    {
        "version": "0.8.0",
        "date": "2025-11-07",
        "tag": "",
        "items": [
            "进入前动画升级：1000+ 透明水光点汇聚成发光圆圈，结束时光点展开为今日专注卡片",
            "今日专注卡片：Bing 每日壁纸背景、Windows 账户头像、分享 / 保存 / 延长 20 分钟",
            "新用户引导：欢迎、三档空间、主题、插件、完成",
            "数据页 Patina 风格：今日时长/会话、连续打卡、最近 7 天与最近会话",
            "覆清白名单应用可见：白名单应用前台时遮罩自动隐藏，任务栏全程隐藏",
            "睡眠模式「还清」：多段锁定时间、提前提醒、每月解锁次数、点击时钟 10 次解锁",
            "dock 设置面板：系统音量、关机 / 重启（二次确认）",
            "联网校时 + 专注期间禁止熄屏/休眠；托盘右键面板、速启空间项修复",
            "法语 / 日语界面，GitHub Actions 可用 AI 机器人自动翻译",
            "许可证改为 GPL-3.0-only，新增 NOTICE 列出第三方组件与素材资源",
            "移除 CW2 组件插件，全屏组件改为左时钟 / 右自定义区域（时钟、每日一言、倒数日等）",
        ],
        "items_en": [
            "New entry animation: 1000+ transparent light points converge into a glowing ring; at the end they expand into a focus summary card",
            "Focus summary card: Bing daily wallpaper, Windows avatar, share / save / extend 20 minutes",
            "New-user onboarding: welcome, tiers, themes, plugins, finish",
            "Patina-style stats page: today duration/sessions, streak, last 7 days and recent sessions",
            "Allowed apps stay visible in Veil: the overlay hides while an allowlisted app is focused; the taskbar stays hidden",
            "Sleep mode (Huanqing): multiple lock times, advance reminders, monthly unlock chances, unlock by clicking the clock 10 times",
            "Dock settings panel: system volume, shutdown / restart with confirmation",
            "Network time sync and no display sleep during focus; tray right-click and quick-panel space entry fixes",
            "Japanese / French UI with AI-assisted translation via GitHub Actions",
            "License changed to GPL-3.0-only with a NOTICE file listing third-party components and resources",
            "Removed the CW2 widget plugin; the overlay now has a clock on the left and custom widgets on the right (clock, daily quote, countdown and more)",
        ],
    },
    {
        "version": "0.7.0",
        "date": "2025-11-05",
        "tag": "",
        "items": [
            "新增进入前的 10 秒「水滴凝聚」倒计时：水滴凭空出现、向圆心汇聚并凝结为发光圆环，进入时圆环扩散至全屏；期间可随时取消，取消时水滴向外散开",
            "深清空间默认时长改为 1 分钟（旧数据自动迁移），时长滑块最短 1 分钟",
            "支持从 GitHub 自动更新：启动后自动检查新版本，关于页可手动检查 / 下载 / 安装",
            "关于页新增「许可证」「第三方组件」入口；仓库新增 LICENSE.txt、THIRD_PARTY_NOTICES.md、CHANGELOG.md",
            "新增发布流程：推送 v* 标签自动运行测试、打包绿色版与安装包，并把更新日志作为 Release 正文",
        ],
        "items_en": [
            "New 10-second droplet countdown before focus: droplets appear from nothing, converge and condense into a glowing ring, which expands to fullscreen on entry; cancel anytime and the droplets scatter outward",
            "Deep space now defaults to 1 minute (existing data migrates automatically); the duration slider minimum is 1 minute",
            "GitHub auto-update: checks for new releases after startup, with manual check / download / install on the About page",
            "About page gained License and Third-party buttons; the repo now ships LICENSE.txt, THIRD_PARTY_NOTICES.md and CHANGELOG.md",
            "New release pipeline: pushing a v* tag runs tests, packages the portable zip and installer, and uses the changelog as the release body",
        ],
    },
    {
        "version": "0.6.0",
        "date": "2025-11-03",
        "tag": "beta",
        "items": [
            "空间页改为浅清 / 覆清 / 深清三个标签页，卡片两列列表式布局，支持新增 / 删除 / 就地改名空间",
            "深清固定一个空间：不可增删改名，只能改时长与白名单，专注时只显示倒计时",
            "全局搜索：窗口右上角常驻，支持空间 / 主题 / 模式 / 插件 / 设置（Ctrl+K）",
            "保活看门狗：进程被杀约 2 秒后自动拉起；新安装默认最高权限运行",
            "新增反馈入口：功能请求 / Bug 反馈 / 参与讨论跳转 GitHub",
            "完善全局动画：页面切换、标签指示器、卡片增删、浮层、遮罩与主题切换过渡",
        ],
        "items_en": [
            "Spaces page now uses three tabs (Light / Veil / Deep) with a two-column card list; add, delete and rename spaces inline",
            "Deep has one fixed space: no add/remove/rename, only duration and allowlist; focus mode shows only the countdown",
            "Global search in the top-right corner on every page (Ctrl+K): spaces, themes, modes, plugins and settings",
            "Keeper watchdog relaunches the app about 2s after the process is killed; new installs run with highest privileges",
            "Feedback entry: feature request / bug report / discussions link to GitHub",
            "Polished global animations: page transitions, tab indicator, card add/remove, overlays, lock screen and theme switch",
        ],
    },
    {
        "version": "0.5.0",
        "date": "2025-11-03",
        "tag": "",
        "items": [
            "三档空间模型：浅清 / 覆清 / 深清各一个空间",
            "移除预览 / 体验按钮，时长滑块最短 1 分钟即体验",
            "导航分组：上组 空间 / 数据 / 插件 / 主题，下组 设置 / 关于",
            "新增关于页；移除番茄插件导航入口",
            "液态玻璃高亮块超出菜单项，长按可拖拽",
        ],
        "items_en": [
            "Three-tier space model: one space per Light / Veil / Deep tier",
            "Removed preview/trial buttons; the 1-minute minimum on the slider is the quick trial",
            "Navigation split into two groups: spaces/stats/plugins/themes and settings/about",
            "New About page; removed the TomaToDo plugin nav entry",
            "Liquid glass highlight is larger than the nav item and can be dragged on long press",
        ],
    },
    {
        "version": "0.4.0",
        "date": "2025-11-01",
        "tag": "",
        "items": [
            "品牌英文名改为 Clarity，界面不再显示「身轻」",
            "主题体系：纯色（默认）/ 清空间浅色 / 液态玻璃（实验性）",
            "顶部菜单栏 + 全局搜索；单空间「清空间」，时长就地设置",
            "深清不可提前结束；覆清全屏 dock 软件栏",
            "插件 SDK：schema、模板、validate 命令，插件可注册导航入口与遮罩组件",
        ],
        "items_en": [
            "English brand name is now Clarity; the old alias is no longer shown",
            "Themes: Solid (default) / Clarity Light / Liquid Glass (experimental)",
            "Top menu bar + global search; single space with inline duration",
            "Deep cannot end early; Veil shows a full-screen app dock",
            "Plugin SDK: schema, templates, validate command; plugins can register nav entries and overlay widgets",
        ],
    },
    {
        "version": "0.3.0",
        "date": "2025-10-28",
        "tag": "",
        "items": [
            "插件系统与插件页；内置番茄同步、专注统计",
            "防退出加固：锁定期间隐藏任务栏、屏蔽系统快捷键",
            "以管理员身份运行与最高权限开机自启",
            "英文界面（i18n）与 GitHub Actions 自动翻译",
        ],
        "items_en": [
            "Plugin system and plugins page; built-in TomaToDo sync and focus stats",
            "Lock hardening: hides the taskbar and blocks system shortcuts during focus",
            "Run as administrator and elevated autostart",
            "English UI (i18n) with automatic translation via GitHub Actions",
        ],
    },
    {
        "version": "0.2.0",
        "date": "2025-10-20",
        "tag": "",
        "items": [
            "多空间模型与全屏专注遮罩",
            "液态玻璃渲染管线（GLSL / qsb）",
            "托盘速启面板、灵动岛、SMTC 媒体控制",
            "专注统计与通知",
        ],
        "items_en": [
            "Multi-space model and full-screen focus overlay",
            "Liquid glass rendering pipeline (GLSL / qsb)",
            "Tray quick panel, dynamic island, SMTC media controls",
            "Focus stats and notifications",
        ],
    },
]

#: 项目仓库与反馈地址
GITHUB_URL = "https://github.com/Kryon2025/Clarity"
FEEDBACK_URLS = {
    "request": f"{GITHUB_URL}/issues/new?labels=enhancement",
    "bug": f"{GITHUB_URL}/issues/new?labels=bug",
    "discuss": f"{GITHUB_URL}/discussions",
}

#: 专注时长预设（分钟）
PRESET_MINUTES = (25, 45, 90)
MIN_MINUTES = 1
MAX_MINUTES = 240

#: 空间（Space）时长范围（分钟）——单空间固定，仅可调时长
SPACE_MIN_MINUTES = 1
SPACE_MAX_MINUTES = 240
SPACE_MINUTE_STEP = 1

#: 空间名长度上限
SPACE_NAME_LIMIT = 20

#: 体验模式的最短时长（分钟）
TRIAL_MINUTES = 1


class Atmosphere:
    """氛围 preset：v0.2 只影响视觉色调，音效留给 v0.3。"""

    VALUE = "value"
    LABEL = "label"
    COLOR = "color"
    DESC = "desc"


#: 空间氛围列表（QML 直接消费）
ATMOSPHERES: list[dict] = [
    {"value": "静谧", "label": "静谧", "color": "#4F7CFF", "desc": "深蓝夜色，适合睡眠与长时段专注"},
    {"value": "秩序", "label": "秩序", "color": "#22D3EE", "desc": "冷青网格，适合工作学习"},
    {"value": "探索", "label": "探索", "color": "#A78BFA", "desc": "紫调光雾，适合阅读与灵感"},
    {"value": "专注", "label": "专注", "color": "#34D399", "desc": "墨绿聚焦，适合刷题与写作"},
]

ATMOSPHERE_VALUES = [item["value"] for item in ATMOSPHERES]


def atmosphere_color(value: str) -> str:
    for item in ATMOSPHERES:
        if item["value"] == value:
            return item["color"]
    return ATMOSPHERES[0]["color"]


class LockLevel(str, Enum):
    """锁机强度。"""

    LIGHT = "light"    # 轻度：只结束黑名单进程
    MEDIUM = "medium"  # 中度：进程 + 网站域名屏蔽（需管理员才真正生效）
    HEAVY = "heavy"    # 重度：进程 + 全屏遮罩 + 屏蔽退出手段

    @property
    def label(self) -> str:
        return {"light": "轻度", "medium": "中度", "heavy": "重度"}[self.value]

    @property
    def description(self) -> str:
        return {
            "light": "只结束黑名单进程，可以正常暂停与退出",
            "medium": "结束后台干扰进程，并屏蔽黑名单网站（需管理员权限）",
            "heavy": "全屏遮罩锁机，屏蔽退出手段，必须等计时结束",
        }[self.value]


#: QML 中展示用的锁机强度列表
LOCK_LEVEL_CHOICES = [
    {"value": level.value, "label": level.label, "description": level.description}
    for level in LockLevel
]

#: 会话状态（与 core/session.py 的 SessionState 对应，避免 QML 侧引用 Python 枚举）
STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_PAUSED = "paused"

#: 睡眠模式：每月可用的提前解锁次数
SLEEP_UNLOCK_CHANCES = 3

#: 睡眠模式提醒（提前分钟数）
SLEEP_REMINDER_MINUTES = (60, 30, 1)

#: 结束卡片随机文案（按日期轮换）
QUOTES = (
    "把注意力放回眼前这一件事。",
    "安静地做，时间会替你记账。",
    "慢一点，也是在向前。",
    "专注不是用力，而是不分心。",
    "先完成，再完美。",
    "今天的一小步，是明天的底气。",
    "屏幕之外，还有生活。",
    "你已经比昨天的自己更专注了一点。",
)


def quote_for(day) -> str:  # noqa: ANN001
    """按日期轮换一条结束卡片文案。"""
    try:
        index = int(getattr(day, "toordinal", lambda: 0)()) % len(QUOTES)
    except (TypeError, ValueError):
        index = 0
    return QUOTES[index]
