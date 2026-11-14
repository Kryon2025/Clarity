pragma Singleton
import QtQuick
import "../components/Constants.js" as C

// 全局主题状态：solid（纯色，默认）/ light（浅色）/ glass（液态玻璃）/ ocean（海洋）
// v0.12：fontScale / fontFamily / fs() 供全局字号与字体缩放使用。
// v0.17：海洋视觉不再默认生效 —— 默认 solid 恢复 v0.16.3 之前的深海背景与青绿强调色；
//        海洋配色改为第 4 个内置主题（mode === "ocean"），使用海洋蓝青调色板。
// v0.18：商店安装的自定义主题包（mode === "custom:<id>"）通过 customPalette 覆盖颜色 token：
//        bgTop/bgMid/bgBottom/accent/accentSoft/accentDeep/cardBg/cardBgAlt/textPrimary/textSecondary
//        优先取 palette 里对应键；缺失的 token 按底色明暗自动推导回退值，保证卡片与文字对比度可读。
//        自定义主题（以及缺失 palette 时）不显示海洋波浪，Backdrop 只走渐变。
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

    // ---------- v0.18 自定义主题包（商店安装） ----------
    // customPalette 由 Main.qml 从 App.customThemePalette 同步进来
    // （QML 单例里不直接读上下文对象 App，避免单例上下文拿不到 context property）。
    property var customPalette: ({})
    readonly property bool custom: mode.length > 7 && mode.substring(0, 7) === "custom:"
    readonly property string customThemeId: custom ? mode.substring(7) : ""

    // 只接受 #RRGGBB（与后端 palette 校验一致）；缺失 / 非法时回退 fallback
    function paletteColor(key, fallback) {
        if (!t.custom) return fallback
        var palette = t.customPalette
        if (!palette) return fallback
        var value = palette[key]
        if (value === undefined || value === null) return fallback
        var text = String(value)
        if (text.length === 7 && text.charAt(0) === "#") return text
        return fallback
    }

    // 颜色亮度（0-1），用于自定义主题的浅色判定与对比度回退
    function colorLuminance(value) {
        var text = String(value === undefined || value === null ? "" : value)
        if (text.charAt(0) !== "#") return -1
        var red = 0
        var green = 0
        var blue = 0
        if (text.length === 7) {
            red = parseInt(text.substring(1, 3), 16)
            green = parseInt(text.substring(3, 5), 16)
            blue = parseInt(text.substring(5, 7), 16)
        } else if (text.length === 9) { // #AARRGGBB
            red = parseInt(text.substring(3, 5), 16)
            green = parseInt(text.substring(5, 7), 16)
            blue = parseInt(text.substring(7, 9), 16)
        } else {
            return -1
        }
        if (!isFinite(red) || !isFinite(green) || !isFinite(blue)) return -1
        return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
    }

    // 自定义主题底色是否偏浅（决定文字 / 描边 / 卡片回退色）
    readonly property bool customLight: custom && colorLuminance(paletteColor("bgTop", "#061C26")) > 0.55
    readonly property color customFallbackTextPrimary: customLight ? "#0C2831" : "#EFF9FF"
    readonly property color customFallbackTextSecondary: customLight ? "#3D626E" : "#A9C6D2"
    readonly property color customFallbackTextTertiary: customLight ? "#5F7E89" : "#6E8C99"
    readonly property color customFallbackCardBg: customLight ? "#FFFFFF" : "#0E2A38"
    readonly property color customFallbackBorder: customLight ? "#260E2831" : "#2BFFFFFF"
    readonly property color customFallbackBorderStrong: customLight ? "#400E2831" : "#47FFFFFF"
    readonly property color customFallbackDivider: customLight ? "#140E2831" : "#14FFFFFF"
    readonly property color customAccent: custom ? paletteColor("accent", "#2ED3C6") : "#2ED3C6"
    readonly property color customAccentSoft: custom ? paletteColor("accentSoft", customAccent) : "#2B86FF"
    readonly property color customAccentDeep: custom ? paletteColor("accentDeep", customAccent) : "#1F6FD0"

    // ---------- 海洋调色板（第 4 个内置主题，供 WaveBackdrop / 图表共用） ----------
    readonly property color oceanDeep: "#0B2B3A"      // 深海
    readonly property color oceanMid: "#144F66"       // 中层海
    readonly property color oceanLight: "#2E9FBF"     // 浅海
    readonly property color oceanFoam: "#BEEFF6"      // 浪花白
    readonly property color oceanAccent: "#4FD0E0"    // 海洋蓝青（主强调）

    // ---------- 背景 ----------
    // 非海洋：v0.16.3 之前的深海渐变；海洋：上浅下深的深海渐变
    // v0.18：自定义主题直接用 palette 的 bgTop / bgMid / bgBottom
    readonly property color bgTop: custom ? paletteColor("bgTop", "#061C26")
                                          : (ocean ? "#123F52" : (light ? "#F1F6F8" : "#061C26"))
    readonly property color bgMid: custom ? paletteColor("bgMid", "#071F2A")
                                          : (ocean ? "#0C2E3D" : (light ? "#E4EEF1" : "#071F2A"))
    readonly property color bgBottom: custom ? paletteColor("bgBottom", "#08222E")
                                             : (ocean ? "#071E29" : (light ? "#D5E5E9" : "#08222E"))
    // 三段渐变实际取色：非海洋沿用旧顺序（0=bgMid / 0.55=bgTop / 1=bgBottom），海洋为上浅下深；
    // 自定义主题按 palette 的自然顺序（上 bgTop → 中 bgMid → 下 bgBottom）
    readonly property color bgStart: custom ? bgTop : (ocean ? bgTop : bgMid)
    readonly property color bgCenter: custom ? bgMid : (ocean ? bgMid : bgTop)

    // ---------- 文本 ----------
    readonly property color textPrimary: custom ? paletteColor("textPrimary", customFallbackTextPrimary)
                                                : (ocean ? "#EAF8FC" : (light ? "#0C2831" : "#EFF9FF"))
    readonly property color textSecondary: custom ? paletteColor("textSecondary", customFallbackTextSecondary)
                                                  : (ocean ? "#A6C8D6" : (light ? "#3D626E" : "#A9C6D2"))
    readonly property color textTertiary: custom ? paletteColor("textTertiary", customFallbackTextTertiary)
                                                 : (ocean ? "#6D8F9F" : (light ? "#5F7E89" : "#6E8C99"))
    readonly property color textOnLight: "#06222B"

    // ---------- 强调色：非海洋=青绿，海洋=海洋蓝青，自定义主题=palette ----------
    readonly property color accent: custom ? paletteColor("accent", "#2ED3C6")
                                          : (ocean ? "#4FD0E0" : (light ? "#0E9E95" : "#2ED3C6"))
    readonly property color accentSoft: custom ? paletteColor("accentSoft", customAccent)
                                              : (ocean ? "#2E9FBF" : (light ? "#1E7FA8" : "#2B86FF"))
    readonly property color accentDeep: custom ? paletteColor("accentDeep", customAccent)
                                              : (ocean ? "#144F66" : (light ? "#2C8FA8" : "#1F6FD0"))
    readonly property color danger: "#E2555F"
    readonly property color success: custom ? (customLight ? "#15855F" : "#6FE3B0")
                                            : (light ? "#15855F" : "#6FE3B0")

    // ---------- 强调渐变 / 图标底色（各组件图标底、徽标、进度条共用） ----------
    readonly property color gradA: custom ? Qt.lighter(customAccent, 1.35)
                                          : (ocean ? "#BEEFF6" : "#7FE7DA")   // 亮
    readonly property color gradB: custom ? customAccent
                                          : (ocean ? "#4FD0E0" : "#2ED3C6")   // 中
    readonly property color gradC: custom ? customAccentSoft
                                          : (ocean ? "#2E9FBF" : "#2B86FF")   // 蓝
    readonly property color gradDeep: custom ? customAccentDeep
                                             : (ocean ? "#144F66" : "#1F6FD0") // 深
    // 强调底上的文字/图标：亮强调色配深字，暗强调色配白字
    readonly property color onAccent: custom ? (colorLuminance(customAccent) > 0.55 ? "#0A1014" : "#FFFFFF")
                                             : (ocean ? "#0B2B3A" : "#04222B")

    // ---------- 卡片 / 玻璃 ----------
    readonly property color cardBg: custom ? paletteColor("cardBg", customFallbackCardBg)
                                           : (ocean ? "#0C2E3C" : (light ? "#FFFFFF" : "#0E2A38"))
    readonly property color cardBgAlt: custom ? paletteColor("cardBgAlt", customLight ? Qt.darker(cardBg, 1.04)
                                                                                     : Qt.lighter(cardBg, 1.18))
                                              : (ocean ? "#103C4F" : (light ? "#F4F9FA" : "#123243"))
    readonly property color cardBorder: custom ? paletteColor("cardBorder", customFallbackBorder)
                                               : (ocean ? "#26BEEFF6" : (light ? "#260E2831" : "#2BFFFFFF"))
    readonly property color cardBorderStrong: custom ? paletteColor("cardBorderStrong", customFallbackBorderStrong)
                                                     : (ocean ? "#45BEEFF6" : (light ? "#400E2831" : "#47FFFFFF"))
    readonly property color glassTint: ocean ? "#071D27" : (light ? "#FFFFFF" : "#071A24")
    readonly property color divider: custom ? paletteColor("divider", customFallbackDivider)
                                            : (ocean ? "#14BEEFF6" : (light ? "#140E2831" : "#14FFFFFF"))

    // ---------- 平面按钮 ----------
    readonly property color buttonBg: custom ? paletteColor("buttonBg", customLight ? "#FFFFFF" : Qt.lighter(cardBg, 1.3))
                                             : (ocean ? "#12465C" : (light ? "#FFFFFF" : "#14405A"))
    readonly property color buttonBgAlt: custom ? paletteColor("buttonBgAlt", customLight ? Qt.darker(cardBg, 1.04)
                                                                                        : Qt.lighter(cardBg, 1.55))
                                                : (ocean ? "#0E3444" : (light ? "#EAF3F5" : "#0F2E3E"))
    readonly property color buttonBorder: custom ? paletteColor("buttonBorder", customFallbackBorderStrong)
                                                 : (ocean ? "#3DBEEFF6" : (light ? "#2E0E2831" : "#3DFFFFFF"))
    readonly property color chipBg: custom ? paletteColor("chipBg", customLight ? Qt.darker(cardBg, 1.06)
                                                                               : Qt.lighter(cardBg, 1.45))
                                           : (ocean ? "#123A4C" : (light ? "#E6F0F3" : "#12303E"))

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
    readonly property color chartA: custom ? customAccent : (ocean ? "#4FD0E0" : "#2ED3C6")
    readonly property color chartB: custom ? customAccentSoft : (ocean ? "#7FD8EA" : "#7FB6FF")
    readonly property color heatMid: ocean ? "#2E9FBF" : "#1E9E95"
    readonly property color heatLow: ocean ? "#0B5E73" : "#176B68"
    readonly property var heatLegend: ocean ? ["#0B5E73", "#2E9FBF", "#4FD0E0"]
                                             : ["#176B68", "#1E9E95", "#2ED3C6"]
    readonly property var appUsageColors: ocean
        ? ["#4FD0E0", "#7FD8EA", "#F2C879", "#C9A7FF", "#F27E7E", "#8FD1A8", "#E8B86B", "#7ED7E8"]
        : ["#2ED3C6", "#7FB6FF", "#F2C879", "#C9A7FF", "#F27E7E", "#8FD1A8", "#E8B86B", "#7ED7E8"]

    // ---------- 波浪背景（WaveBackdrop 的 Canvas 取色） ----------
    // v0.18：波浪只在海洋主题显示；自定义主题 Backdrop 不显示波浪。
    readonly property color waveDeepTop: "#BEEFF6"    // 深海模式：浪尖偏浪花白
    readonly property color waveDeepBottom: "#2E9FBF" // 深海模式：浪底偏浅海蓝
    readonly property color waveLightTop: "#FFFFFF"   // 浅色模式：白色浪花
    readonly property color waveLightBottom: "#7FD8EA"// 浅色模式：浪底浅蓝
}
