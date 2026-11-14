pragma Singleton
import QtQuick
import "../components/Constants.js" as C

// 全局主题状态：solid（纯色，默认）/ light（浅色）/ glass（液态玻璃）
// v0.12：fontScale / fontFamily / fs() 供全局字号与字体缩放使用。
// v0.17：海洋波浪主题 —— 新增海洋调色板；强调色由青绿改为海洋蓝青；
//        深色背景改为深海渐变（上浅下深），浅色模式为浅海蓝白。
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

    // ---------- 海洋调色板（v0.17，供 WaveBackdrop / 图标 / 图表共用） ----------
    readonly property color oceanDeep: "#0B2B3A"      // 深海
    readonly property color oceanMid: "#144F66"       // 中层海
    readonly property color oceanLight: "#2E9FBF"     // 浅海
    readonly property color oceanFoam: "#BEEFF6"      // 浪花白
    readonly property color oceanAccent: "#4FD0E0"    // 海洋蓝青（主强调）

    // ---------- 背景：深海渐变（上浅下深）/ 浅海蓝白 ----------
    readonly property color bgTop: light ? "#F2FAFC" : "#123F52"
    readonly property color bgMid: light ? "#E2F1F6" : "#0C2E3D"
    readonly property color bgBottom: light ? "#D0E7EE" : "#071E29"

    // ---------- 文本 ----------
    readonly property color textPrimary: light ? "#0B2B3A" : "#EAF8FC"
    readonly property color textSecondary: light ? "#3A6272" : "#A6C8D6"
    readonly property color textTertiary: light ? "#5F8090" : "#6D8F9F"
    readonly property color textOnLight: "#06222B"

    // ---------- 强调色：统一为海洋蓝青 ----------
    readonly property color accent: light ? "#0E7E99" : "#4FD0E0"
    readonly property color accentSoft: light ? "#168FAA" : "#2E9FBF"
    readonly property color accentDeep: light ? "#0B5F77" : "#144F66"
    readonly property color danger: "#E2555F"
    readonly property color success: light ? "#15855F" : "#6FE3B0"

    // ---------- 卡片 / 玻璃 ----------
    readonly property color cardBg: light ? "#FFFFFF" : "#0C2E3C"
    readonly property color cardBgAlt: light ? "#F1F9FB" : "#103C4F"
    readonly property color cardBorder: light ? "#260B2B3A" : "#26BEEFF6"
    readonly property color cardBorderStrong: light ? "#400B2B3A" : "#45BEEFF6"
    readonly property color glassTint: light ? "#FFFFFF" : "#071D27"
    readonly property color divider: light ? "#140B2B3A" : "#14BEEFF6"

    // ---------- 平面按钮 ----------
    readonly property color buttonBg: light ? "#FFFFFF" : "#12465C"
    readonly property color buttonBgAlt: light ? "#E7F4F7" : "#0E3444"
    readonly property color buttonBorder: light ? "#2E0B2B3A" : "#3DBEEFF6"
    readonly property color chipBg: light ? "#E4F1F4" : "#123A4C"

    // ---------- 遮罩 ----------
    readonly property color overlayTop: light ? "#EAF6F9" : "#0E3446"
    readonly property color overlayBottom: light ? "#CFE6ED" : "#071C27"

    // ---------- 波浪背景（WaveBackdrop 的 Canvas 取色） ----------
    readonly property color waveDeepTop: "#BEEFF6"    // 深海模式：浪尖偏浪花白
    readonly property color waveDeepBottom: "#2E9FBF" // 深海模式：浪底偏浅海蓝
    readonly property color waveLightTop: "#FFFFFF"   // 浅色模式：白色浪花
    readonly property color waveLightBottom: "#7FD8EA"// 浅色模式：浪底浅蓝
}
