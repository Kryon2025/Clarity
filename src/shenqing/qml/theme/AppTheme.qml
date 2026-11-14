pragma Singleton
import QtQuick
import "../components/Constants.js" as C

// 全局主题状态：solid（纯色，默认）/ light（浅色）/ glass（液态玻璃）/ ocean（海洋）
// v0.12：fontScale / fontFamily / fs() 供全局字号与字体缩放使用。
// v0.17：海洋视觉不再默认生效 —— 默认 solid 恢复 v0.16.3 之前的深海背景与青绿强调色；
//        海洋配色改为第 4 个内置主题（mode === "ocean"），使用海洋蓝青调色板。
QtObject {
    id: t

    property string mode: "solid"

    // ---------- 字体 ----------
    property real fontScale: 1.0
    property string fontFamily: C.numFont
    property string navMode: "expanded"

    function fs(basePixelSize) {
        var value = Number(basePixelSize)
        if (!isFinite(value)) value = 0
        return Math.round(value * t.fontScale)
    }

    readonly property bool solid: mode === "solid"
    readonly property bool light: mode === "light"
    readonly property bool glass: mode === "glass"
    readonly property bool ocean: mode === "ocean"

    // ---------- 海洋调色板（第 4 个内置主题，供 WaveBackdrop / 图表共用） ----------
    readonly property color oceanDeep: "#0B2B3A"      // 深海
    readonly property color oceanMid: "#144F66"       // 中层海
    readonly property color oceanLight: "#2E9FBF"     // 浅海
    readonly property color oceanFoam: "#BEEFF6"      // 浪花白
    readonly property color oceanAccent: "#4FD0E0"    // 海洋蓝青（主强调）

    // ---------- 背景 ----------
    // 非海洋：v0.16.3 之前的深海渐变；海洋：上浅下深的深海渐变
    readonly property color bgTop: ocean ? "#123F52" : (light ? "#F1F6F8" : "#061C26")
    readonly property color bgMid: ocean ? "#0C2E3D" : (light ? "#E4EEF1" : "#071F2A")
    readonly property color bgBottom: ocean ? "#071E29" : (light ? "#D5E5E9" : "#08222E")
    // 三段渐变实际取色：非海洋沿用旧顺序（0=bgMid / 0.55=bgTop / 1=bgBottom），海洋为上浅下深
    readonly property color bgStart: ocean ? bgTop : bgMid
    readonly property color bgCenter: ocean ? bgMid : bgTop

    // ---------- 文本 ----------
    readonly property color textPrimary: ocean ? "#EAF8FC" : (light ? "#0C2831" : "#EFF9FF")
    readonly property color textSecondary: ocean ? "#A6C8D6" : (light ? "#3D626E" : "#A9C6D2")
    readonly property color textTertiary: ocean ? "#6D8F9F" : (light ? "#5F7E89" : "#6E8C99")
    readonly property color textOnLight: "#06222B"

    // ---------- 强调色：非海洋=青绿，海洋=海洋蓝青 ----------
    readonly property color accent: ocean ? "#4FD0E0" : (light ? "#0E9E95" : "#2ED3C6")
    readonly property color accentSoft: ocean ? "#2E9FBF" : (light ? "#1E7FA8" : "#2B86FF")
    readonly property color accentDeep: ocean ? "#144F66" : (light ? "#2C8FA8" : "#1F6FD0")
    readonly property color danger: "#E2555F"
    readonly property color success: light ? "#15855F" : "#6FE3B0"

    // ---------- 强调渐变 / 图标底色（各组件图标底、徽标、进度条共用） ----------
    readonly property color gradA: ocean ? "#BEEFF6" : "#7FE7DA"       // 亮
    readonly property color gradB: ocean ? "#4FD0E0" : "#2ED3C6"       // 中
    readonly property color gradC: ocean ? "#2E9FBF" : "#2B86FF"       // 蓝
    readonly property color gradDeep: ocean ? "#144F66" : "#1F6FD0"    // 深
    readonly property color onAccent: ocean ? "#0B2B3A" : "#04222B"    // 强调底上的文字/图标

    // ---------- 卡片 / 玻璃 ----------
    readonly property color cardBg: ocean ? "#0C2E3C" : (light ? "#FFFFFF" : "#0E2A38")
    readonly property color cardBgAlt: ocean ? "#103C4F" : (light ? "#F4F9FA" : "#123243")
    readonly property color cardBorder: ocean ? "#26BEEFF6" : (light ? "#260E2831" : "#2BFFFFFF")
    readonly property color cardBorderStrong: ocean ? "#45BEEFF6" : (light ? "#400E2831" : "#47FFFFFF")
    readonly property color glassTint: ocean ? "#071D27" : (light ? "#FFFFFF" : "#071A24")
    readonly property color divider: ocean ? "#14BEEFF6" : (light ? "#140E2831" : "#14FFFFFF")

    // ---------- 平面按钮 ----------
    readonly property color buttonBg: ocean ? "#12465C" : (light ? "#FFFFFF" : "#14405A")
    readonly property color buttonBgAlt: ocean ? "#0E3444" : (light ? "#EAF3F5" : "#0F2E3E")
    readonly property color buttonBorder: ocean ? "#3DBEEFF6" : (light ? "#2E0E2831" : "#3DFFFFFF")
    readonly property color chipBg: ocean ? "#123A4C" : (light ? "#E6F0F3" : "#12303E")

    // ---------- 遮罩 ----------
    readonly property color overlayTop: ocean ? "#0E3446" : (light ? "#E8F2F4" : "#04121C")
    readonly property color overlayBottom: ocean ? "#071C27" : (light ? "#CFE3E7" : "#0B3340")

    // ---------- 弹窗 / 遮罩色（避免各页面硬编码海洋色） ----------
    readonly property color scrimSoft: ocean ? "#99050F18" : "#99040A10"
    readonly property color scrimMedium: ocean ? "#AA051620" : "#AA040A10"
    readonly property color scrimStrong: ocean ? "#B3051620" : "#B3040A10"
    readonly property color chipScrim: ocean ? "#66051620" : "#66040A10"
    readonly property color chipScrimGlass: ocean ? "#26051620" : "#26040A10"
    readonly property color shadowDeep: ocean ? "#88040F17" : "#88020A10"
    readonly property color hintScrim: ocean ? "#5A041018" : "#5A040A10"
    readonly property color dialogBg: ocean ? "#F2082430" : "#F20A1B26"

    // ---------- 卡片浮层 / 细描边 ----------
    readonly property color cardOverlay: ocean ? "#22061620" : "#22050A12"
    readonly property color cardOverlayHover: ocean ? "#28061721" : "#28050A12"
    readonly property color cardOverlaySelected: ocean ? "#2A06141D" : "#2A050A14"
    readonly property color hairlineStrong: ocean ? "#66BEEFF6" : "#66FFFFFF"
    readonly property color hairlineHover: ocean ? "#4DBEEFF6" : "#4DFFFFFF"
    readonly property color hairlineSoft: ocean ? "#2EBEEFF6" : "#2EFFFFFF"

    // ---------- 玻璃按钮染色 ----------
    readonly property color tintLight: ocean ? "#E2F8FC" : "#E2F8F6"
    readonly property color tintBorderLight: ocean ? "#5CDFF8FF" : "#5CFFFFFF"
    readonly property color tintBorderSoft: ocean ? "#38BEEFF6" : "#38FFFFFF"
    readonly property color sheenHighlight: ocean ? "#CCEAFEFF" : "#CCFFFFFF"

    // ---------- 专注结束卡片 ----------
    readonly property color summaryTop: ocean ? "#144F66" : "#16405A"
    readonly property color summaryMid: ocean ? "#0C2E3C" : "#0E2A38"
    readonly property color summaryBottom: ocean ? "#0B2B3A" : "#081C28"
    readonly property color summaryPanelBg: ocean ? "#F20C2E3C" : "#F20E2A38"
    readonly property color summaryChipBg: ocean ? "#CC08242F" : "#CC0A1B26"
    readonly property color summaryBackdropTop: ocean ? "#144F66" : "#1B4258"
    readonly property color summaryBackdropBottom: ocean ? "#071E29" : "#08131B"

    // ---------- 图表 ----------
    readonly property color chartA: ocean ? "#4FD0E0" : "#2ED3C6"
    readonly property color chartB: ocean ? "#7FD8EA" : "#7FB6FF"
    readonly property color heatMid: ocean ? "#2E9FBF" : "#1E9E95"
    readonly property color heatLow: ocean ? "#0B5E73" : "#176B68"
    readonly property var heatLegend: ocean ? ["#0B5E73", "#2E9FBF", "#4FD0E0"]
                                             : ["#176B68", "#1E9E95", "#2ED3C6"]
    readonly property var appUsageColors: ocean
        ? ["#4FD0E0", "#7FD8EA", "#F2C879", "#C9A7FF", "#F27E7E", "#8FD1A8", "#E8B86B", "#7ED7E8"]
        : ["#2ED3C6", "#7FB6FF", "#F2C879", "#C9A7FF", "#F27E7E", "#8FD1A8", "#E8B86B", "#7ED7E8"]

    // ---------- 波浪背景（WaveBackdrop 的 Canvas 取色） ----------
    readonly property color waveDeepTop: "#BEEFF6"    // 深海模式：浪尖偏浪花白
    readonly property color waveDeepBottom: "#2E9FBF" // 深海模式：浪底偏浅海蓝
    readonly property color waveLightTop: "#FFFFFF"   // 浅色模式：白色浪花
    readonly property color waveLightBottom: "#7FD8EA"// 浅色模式：浪底浅蓝
}
