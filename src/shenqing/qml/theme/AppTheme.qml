pragma Singleton
import QtQuick
import "../components/Constants.js" as C

// 全局主题状态（v0.21）：样式 style 与配色 scheme 正交。
//
// 样式（决定质感与强调色倾向）：
//   solid        纯色：平面渐变 + 原青绿强调色（默认）
//   glass        液态玻璃：渐变玻璃强调色（青蓝 → 紫），背景叠加光斑 + 噪点（实验性）
//   ocean        海洋：海洋蓝青强调色 + 浪花，背景叠加静态波浪
//   custom:<id>  商店安装的自定义主题包：颜色 token 由 customPalette 覆盖
// 配色（决定明暗）：
//   auto 跟随系统（由 App.effectiveScheme 解析成 light / dark）/ light / dark
//
// 本文件只做「token 计算」：QML 单例里不直接读上下文对象 App（单例上下文拿不到
// context property），因此 style / scheme / effectiveScheme / systemScheme / customPalette
// 都由 Main.qml（以及速启面板 / 番茄面板）从桥接口推送进来。
//
// 兼容（v0.20 及更早的调用点）：
//   mode === style（只读）；light 表示「当前实际是浅色」；solid / glass / ocean 表示样式；
//   fs()/fontScale/fontFamily/navMode 保持不变；widgets 组件共用的颜色 token 全部保留。
QtObject {
    id: t

    // ---------- v0.21：样式 + 配色（由 Main.qml 推送） ----------
    property string style: "solid"            // solid / glass / ocean / custom:<id>
    property string scheme: "auto"            // auto / light / dark
    property string effectiveScheme: "dark"   // 解析后的实际配色：light / dark
    property string systemScheme: "dark"      // 系统当前深浅（仅用于「跟随系统」提示）

    readonly property bool light: effectiveScheme === "light"
    readonly property bool dark: !light
    readonly property bool solid: style === "solid"
    readonly property bool glass: style === "glass"
    readonly property bool ocean: style === "ocean"
    // 纯色 / 自定义主题：没有 GPU 特效（背景只走渐变，组件按平面绘制）
    readonly property bool flatStyle: !glass && !ocean
    // 兼容旧属性：mode 等于样式（custom:<id> 原样）
    readonly property string mode: style

    // 依据配色取深浅两套值（函数内读 t.light，QML 会自动跟踪依赖）
    function pick(lightValue, darkValue) {
        return t.light ? lightValue : darkValue
    }

    // ---------- 字体（保持不变） ----------
    property real fontScale: 1.0
    property string fontFamily: C.numFont
    property string navMode: "expanded"

    function fs(basePixelSize) {
        var value = Number(basePixelSize)
        if (!isFinite(value)) value = 0
        return Math.round(value * t.fontScale)
    }

    // ---------- v0.18 自定义主题包（商店安装） ----------
    // customPalette 由 Main.qml 从 App.customThemePalette 同步进来。
    property var customPalette: ({})
    readonly property bool custom: style.length > 7 && style.substring(0, 7) === "custom:"
    readonly property string customThemeId: custom ? style.substring(7) : ""

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

    // 颜色亮度（0-1），用于自定义主题的浅色判定与回退色选择
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

    // 颜色对象亮度（0-1）：用于 accent 上的文字取黑还是白
    function colorLuminanceValue(value) {
        if (value === undefined || value === null) return 0
        var red = Number(value.r)
        var green = Number(value.g)
        var blue = Number(value.b)
        if (!isFinite(red) || !isFinite(green) || !isFinite(blue)) return 0
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue
    }

    // 自定义主题底色是否偏浅（决定文字 / 描边 / 卡片回退色；与配色 scheme 无关）
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

    // ---------- 海洋原料色（图表 / 浪花 / 预览共用，不随配色变化） ----------
    readonly property color oceanDeep: "#0B2B3A"      // 深海
    readonly property color oceanMid: "#144F66"       // 中层海
    readonly property color oceanLight: "#2E9FBF"     // 浅海
    readonly property color oceanFoam: "#BEEFF6"      // 浪花白
    readonly property color oceanAccent: "#4FD0E0"    // 海洋蓝青（主强调）

    // ---------- 背景（配色决定明暗；海洋样式换成海色） ----------
    readonly property color bgTop: custom ? paletteColor("bgTop", "#061C26")
                                          : (ocean ? pick("#E9F6FA", "#123F52")
                                          : pick("#F1F6F8", "#061C26"))
    readonly property color bgMid: custom ? paletteColor("bgMid", "#071F2A")
                                          : (ocean ? pick("#D8EDF4", "#0C2E3D")
                                          : pick("#E4EEF1", "#071F2A"))
    readonly property color bgBottom: custom ? paletteColor("bgBottom", "#08222E")
                                             : (ocean ? pick("#C6E4EE", "#071E29")
                                             : pick("#D5E5E9", "#08222E"))
    // 三段渐变实际取色：纯色 / 玻璃沿用旧顺序（0=bgMid / 0.55=bgTop / 1=bgBottom），
    // 海洋为上浅下深；自定义主题按 palette 的自然顺序（上 bgTop → 中 bgMid → 下 bgBottom）
    readonly property color bgStart: custom ? bgTop : (ocean ? bgTop : bgMid)
    readonly property color bgCenter: custom ? bgMid : (ocean ? bgMid : bgTop)

    // ---------- 文本 ----------
    readonly property color textPrimary: custom ? paletteColor("textPrimary", customFallbackTextPrimary)
                                                : (ocean ? pick("#0B3444", "#EAF8FC")
                                                : pick("#0C2831", "#EFF9FF"))
    readonly property color textSecondary: custom ? paletteColor("textSecondary", customFallbackTextSecondary)
                                                  : (ocean ? pick("#3C6474", "#A6C8D6")
                                                  : pick("#3D626E", "#A9C6D2"))
    readonly property color textTertiary: custom ? paletteColor("textTertiary", customFallbackTextTertiary)
                                                 : (ocean ? pick("#5F8494", "#6D8F9F")
                                                 : pick("#5F7E89", "#6E8C99"))
    readonly property color textOnLight: "#06222B"

    // ---------- 强调色：样式决定倾向，配色决定深浅 ----------
    // solid=原青绿 / glass=渐变玻璃蓝紫 / ocean=海洋蓝青 / custom=palette
    readonly property color accent: custom ? paletteColor("accent", "#2ED3C6")
                                           : (ocean ? pick("#0E7F96", "#4FD0E0")
                                           : (glass ? pick("#3A6BE0", "#8FC7FF")
                                           : pick("#0E9E95", "#2ED3C6")))
    readonly property color accentSoft: custom ? paletteColor("accentSoft", customAccent)
                                               : (ocean ? pick("#1499B8", "#2E9FBF")
                                               : (glass ? pick("#6B8FFF", "#6C8CFF")
                                               : pick("#1E7FA8", "#2B86FF")))
    readonly property color accentDeep: custom ? paletteColor("accentDeep", customAccent)
                                               : (ocean ? pick("#0A6E85", "#144F66")
                                               : (glass ? pick("#7C5CFF", "#A78BFF")
                                               : pick("#2C8FA8", "#1F6FD0")))
    readonly property color danger: "#E2555F"
    readonly property color success: custom ? (customLight ? "#15855F" : "#6FE3B0")
                                            : pick("#15855F", "#6FE3B0")

    // ---------- 强调渐变 / 图标底色（图标底、徽标、进度条共用） ----------
    // solid：青绿 → 蓝；glass：冰蓝 → 紫（渐变玻璃）；ocean：浪花白 → 浅海 → 海洋蓝青
    readonly property color gradA: custom ? Qt.lighter(customAccent, 1.35)
                                          : (ocean ? pick("#7FD8EA", "#BEEFF6")
                                          : (glass ? pick("#BEE3FF", "#D9F0FF")
                                          : "#7FE7DA"))                        // 亮
    readonly property color gradB: custom ? customAccent
                                          : (ocean ? pick("#17A8C4", "#4FD0E0")
                                          : (glass ? pick("#7FB0FF", "#8FC7FF")
                                          : "#2ED3C6"))                        // 中
    readonly property color gradC: custom ? customAccentSoft
                                          : (ocean ? pick("#0E8CA6", "#2E9FBF")
                                          : (glass ? pick("#A48CFF", "#8E8CFF")
                                          : "#2B86FF"))                        // 蓝 / 紫
    readonly property color gradDeep: custom ? customAccentDeep
                                             : (ocean ? pick("#0A6E85", "#144F66")
                                             : (glass ? pick("#4F63D6", "#5B5FD6")
                                             : "#1F6FD0"))                     // 深
    // 强调底上的文字/图标：亮强调色配深字，暗强调色配白字
    readonly property color onAccent: colorLuminanceValue(t.accent) > 0.6 ? "#0A1014" : "#FFFFFF"

    // ---------- 卡片 / 玻璃 ----------
    readonly property color cardBg: custom ? paletteColor("cardBg", customFallbackCardBg)
                                           : (ocean ? pick("#FFFFFF", "#0C2E3C") : pick("#FFFFFF", "#0E2A38"))
    readonly property color cardBgAlt: custom ? paletteColor("cardBgAlt", customLight ? Qt.darker(cardBg, 1.04)
                                                                                     : Qt.lighter(cardBg, 1.18))
                                              : (ocean ? pick("#F0F9FC", "#103C4F") : pick("#F4F9FA", "#123243"))
    readonly property color cardBorder: custom ? paletteColor("cardBorder", customFallbackBorder)
                                               : (ocean ? pick("#260B3444", "#26BEEFF6") : pick("#260E2831", "#2BFFFFFF"))
    readonly property color cardBorderStrong: custom ? paletteColor("cardBorderStrong", customFallbackBorderStrong)
                                                     : (ocean ? pick("#400B3444", "#45BEEFF6") : pick("#400E2831", "#47FFFFFF"))
    readonly property color glassTint: ocean ? pick("#FFFFFF", "#071D27") : pick("#FFFFFF", "#071A24")
    readonly property color divider: custom ? paletteColor("divider", customFallbackDivider)
                                            : (ocean ? pick("#140B3444", "#14BEEFF6") : pick("#140E2831", "#14FFFFFF"))

    // ---------- 平面按钮 ----------
    readonly property color buttonBg: custom ? paletteColor("buttonBg", customLight ? "#FFFFFF" : Qt.lighter(cardBg, 1.3))
                                             : (ocean ? pick("#FFFFFF", "#12465C") : pick("#FFFFFF", "#14405A"))
    readonly property color buttonBgAlt: custom ? paletteColor("buttonBgAlt", customLight ? Qt.darker(cardBg, 1.04)
                                                                                         : Qt.lighter(cardBg, 1.55))
                                                : (ocean ? pick("#EAF6FA", "#0E3444") : pick("#EAF3F5", "#0F2E3E"))
    readonly property color buttonBorder: custom ? paletteColor("buttonBorder", customFallbackBorderStrong)
                                                 : (ocean ? pick("#2E0B3444", "#3DBEEFF6") : pick("#2E0E2831", "#3DFFFFFF"))
    readonly property color chipBg: custom ? paletteColor("chipBg", customLight ? Qt.darker(cardBg, 1.06)
                                                                               : Qt.lighter(cardBg, 1.45))
                                           : (ocean ? pick("#DDF0F6", "#123A4C") : pick("#E6F0F3", "#12303E"))

    // ---------- 遮罩 ----------
    readonly property color overlayTop: ocean ? pick("#DCF0F6", "#0E3446") : pick("#E8F2F4", "#04121C")
    readonly property color overlayBottom: ocean ? pick("#C3E1EA", "#071C27") : pick("#CFE3E7", "#0B3340")

    // ---------- 弹窗 / 遮罩色（避免各页面硬编码） ----------
    readonly property color scrimSoft: ocean ? "#99050F18" : "#99040A10"
    readonly property color scrimMedium: ocean ? "#AA051620" : "#AA040A10"
    readonly property color scrimStrong: ocean ? "#B3051620" : "#B3040A10"
    readonly property color chipScrim: ocean ? "#66051620" : "#66040A10"
    readonly property color chipScrimGlass: ocean ? "#26051620" : "#26040A10"
    readonly property color shadowDeep: ocean ? "#88040F17" : "#88020A10"
    readonly property color hintScrim: ocean ? "#5A041018" : "#5A040A10"
    readonly property color dialogBg: ocean ? pick("#F2F4FBFC", "#F2082430") : pick("#F2FFFFFF", "#F20A1B26")

    // ---------- 卡片浮层 / 细描边 ----------
    readonly property color cardOverlay: ocean ? pick("#1F0B3444", "#22061620") : pick("#1F0E2831", "#22050A12")
    readonly property color cardOverlayHover: ocean ? pick("#240B3444", "#28061721") : pick("#240E2831", "#28050A12")
    readonly property color cardOverlaySelected: ocean ? pick("#260B3444", "#2A06141D") : pick("#260E2831", "#2A050A14")
    readonly property color hairlineStrong: ocean ? pick("#400B3444", "#66BEEFF6") : pick("#330E2831", "#66FFFFFF")
    readonly property color hairlineHover: ocean ? pick("#330B3444", "#4DBEEFF6") : pick("#260E2831", "#4DFFFFFF")
    readonly property color hairlineSoft: ocean ? pick("#1F0B3444", "#2EBEEFF6") : pick("#1A0E2831", "#2EFFFFFF")

    // ---------- 玻璃按钮染色 ----------
    readonly property color tintLight: ocean ? pick("#0B3444", "#E2F8FC") : pick("#0C2831", "#E2F8F6")
    readonly property color tintBorderLight: ocean ? pick("#400B3444", "#5CDFF8FF") : pick("#400C2831", "#5CFFFFFF")
    readonly property color tintBorderSoft: ocean ? pick("#2E0B3444", "#38BEEFF6") : pick("#2E0C2831", "#38FFFFFF")
    readonly property color sheenHighlight: ocean ? "#CCEAFEFF" : "#CCFFFFFF"

    // ---------- 液态玻璃文字 / 描边 / 表面（浅色配色下白字白线会看不见，按配色给深色版本） ----------
    readonly property color glassTextSecondary: pick("#3F6373", "#CFE6EC")
    readonly property color glassTextMuted: pick("#5A7C8C", "#9AA8C4")
    readonly property color glassHairline: pick("#400E2831", "#2BFFFFFF")
    readonly property color glassHairlineStrong: pick("#4D0E2831", "#3DFFFFFF")
    readonly property color glassSurfaceSoft: pick("#0F0E2831", "#14FFFFFF")
    readonly property color glassSurfaceStrong: pick("#1A0E2831", "#33FFFFFF")
    readonly property color glassSurfaceSolid: pick("#1A0E2831", "#1FFFFFFF")
    readonly property color glassSheetBg: pick("#EAF4F8FA", "#E8070B13")

    // ---------- 液态玻璃背景（Backdrop 光斑 / 暗角 / 噪点） ----------
    readonly property color glassBlobA: pick("#7FB0FF", C.waterBlue)
    readonly property color glassBlobB: pick("#5FD8CC", C.waterTeal)
    readonly property color glassBlobC: pick("#FFCF9E", C.waterSand)
    readonly property real glassBlobScale: pick(0.70, 1.0)
    readonly property color glassVignetteTop: pick("#26FFFFFF", "#33040F18")
    readonly property color glassVignetteBottom: pick("#3D0E2831", "#3D041018")
    readonly property real glassNoiseOpacity: pick(0.06, 0.13)

    // ---------- 专注结束卡片 ----------
    readonly property color summaryTop: ocean ? pick("#FFFFFF", "#144F66") : pick("#FFFFFF", "#16405A")
    readonly property color summaryMid: ocean ? pick("#EAF6FA", "#0C2E3C") : pick("#F1F6F8", "#0E2A38")
    readonly property color summaryBottom: ocean ? pick("#D6EBF1", "#0B2B3A") : pick("#DDE9EC", "#081C28")
    readonly property color summaryPanelBg: ocean ? pick("#F2FFFFFF", "#F20C2E3C") : pick("#F2FFFFFF", "#F20E2A38")
    readonly property color summaryChipBg: ocean ? pick("#CCE3F4F8", "#CC08242F") : pick("#CCE6F0F3", "#CC0A1B26")
    readonly property color summaryBackdropTop: ocean ? pick("#DCF0F6", "#144F66") : pick("#DBE9ED", "#1B4258")
    readonly property color summaryBackdropBottom: ocean ? pick("#C3E1EA", "#071E29") : pick("#C7DDE2", "#08131B")

    // ---------- 图表 ----------
    readonly property color chartA: t.accent
    readonly property color chartB: custom ? customAccentSoft
                                           : (ocean ? pick("#1499B8", "#7FD8EA")
                                           : (glass ? pick("#7C5CFF", "#A48CFF")
                                           : pick("#1E7FA8", "#7FB6FF")))
    readonly property color heatMid: ocean ? "#2E9FBF" : "#1E9E95"
    readonly property color heatLow: ocean ? "#0B5E73" : "#176B68"
    readonly property var heatLegend: ocean ? ["#0B5E73", "#2E9FBF", "#4FD0E0"]
                                             : ["#176B68", "#1E9E95", "#2ED3C6"]
    readonly property var appUsageColors: {
        var head = t.custom ? [t.customAccent, t.customAccentSoft]
                 : (t.ocean ? ["#4FD0E0", "#7FD8EA"]
                 : (t.glass ? ["#8FC7FF", "#A48CFF"]
                 : ["#2ED3C6", "#7FB6FF"]))
        return head.concat(["#F2C879", "#C9A7FF", "#F27E7E", "#8FD1A8", "#E8B86B", "#7ED7E8"])
    }

    // ---------- 波浪背景（WaveBackdrop 的 Canvas 取色；只在样式 = 海洋 时使用） ----------
    // 深色配色 = 深海（浅蓝浪花）；浅色配色 = 浅色浪花（白色 → 浅蓝）
    readonly property color waveDeepTop: "#BEEFF6"    // 深海模式：浪尖偏浪花白
    readonly property color waveDeepBottom: "#2E9FBF" // 深海模式：浪底偏浅海蓝
    readonly property color waveLightTop: "#FFFFFF"   // 浅色模式：白色浪花
    readonly property color waveLightBottom: "#8FDCEA"// 浅色模式：浪底浅蓝
}
