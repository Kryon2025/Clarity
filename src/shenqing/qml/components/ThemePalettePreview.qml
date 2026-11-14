import QtQuick
import "../theme"

// 主题配色预览块（v0.18）：主题页卡片 / 主题商店卡片与详情页共用。
// - style: solid / glass / ocean（v0.21 起浅色/深色由配色决定，不再是独立样式）
// - palette: 商店条目 / 自定义主题的 palette（含 bgTop/bgMid/bgBottom/accent/cardBg/textPrimary）
// - live: true 时直接使用 AppTheme 当前配色（「当前样式」卡片）
// - scheme: "light" / "dark"，空串时跟随 AppTheme.effectiveScheme（预览在两种配色下的样子）
Item {
    id: root

    property string style: "solid"
    property var themePalette: ({})
    property bool live: false
    property string scheme: ""
    property real corner: 14
    property color borderColor: "#2BFFFFFF"

    readonly property bool darkPreview: root.scheme === "dark"
                                        || (root.scheme !== "light" && AppTheme.dark)
    readonly property bool usesPalette: !root.live && root.themePalette !== undefined && root.themePalette !== null
                                        && root.themePalette.bgTop !== undefined

    readonly property color cTop: {
        if (root.live) return AppTheme.bgTop
        if (root.usesPalette) return String(root.themePalette.bgTop)
        if (root.style === "ocean") return root.darkPreview ? "#1B5A73" : "#DFF2F8"
        if (root.style === "glass") return root.darkPreview ? "#1F6FD0" : "#EAF2FF"
        return root.darkPreview ? "#0E2A38" : "#FFFFFF"
    }
    readonly property color cMid: {
        if (root.live) return AppTheme.bgMid
        if (root.usesPalette) return String(root.themePalette.bgMid !== undefined ? root.themePalette.bgMid : root.themePalette.bgTop)
        if (root.style === "ocean") return root.darkPreview ? "#0E3546" : "#CBE7F0"
        if (root.style === "glass") return root.darkPreview ? "#2ED3C6" : "#D8E6FF"
        return root.darkPreview ? "#071F2A" : "#EAF2F5"
    }
    readonly property color cBottom: {
        if (root.live) return AppTheme.bgBottom
        if (root.usesPalette) return String(root.themePalette.bgBottom !== undefined ? root.themePalette.bgBottom : root.themePalette.bgMid)
        if (root.style === "ocean") return root.darkPreview ? "#071E29" : "#B7DCE8"
        if (root.style === "glass") return root.darkPreview ? "#0A2A36" : "#C9DCF7"
        return root.darkPreview ? "#04121C" : "#D8E7EB"
    }
    readonly property color cAccent: {
        if (root.live) return AppTheme.accent
        if (root.usesPalette && root.themePalette.accent !== undefined) return String(root.themePalette.accent)
        if (root.style === "ocean") return root.darkPreview ? "#4FD0E0" : "#0E8CA6"
        if (root.style === "glass") return root.darkPreview ? "#8FC7FF" : "#3A6BE0"
        return root.darkPreview ? "#2ED3C6" : "#0E9E95"
    }
    readonly property color cCard: {
        if (root.live) return AppTheme.cardBg
        if (root.usesPalette && root.themePalette.cardBg !== undefined) return String(root.themePalette.cardBg)
        if (root.style === "ocean") return root.darkPreview ? "#0C2E3C" : "#FFFFFF"
        return root.darkPreview ? "#123243" : "#FFFFFF"
    }
    readonly property color cInk: {
        if (root.live) return AppTheme.textPrimary
        if (root.usesPalette && root.themePalette.textPrimary !== undefined) return String(root.themePalette.textPrimary)
        if (root.style === "ocean") return root.darkPreview ? "#EAF8FC" : "#0B3444"
        return root.darkPreview ? "#EFF9FF" : "#0C2831"
    }
    readonly property bool isGlass: !root.live && !root.usesPalette && root.style === "glass"
    readonly property bool isOcean: !root.live && !root.usesPalette && root.style === "ocean"

    Rectangle {
        anchors.fill: parent
        radius: root.corner
        gradient: Gradient {
            GradientStop { position: 0.0; color: root.cTop }
            GradientStop { position: 0.55; color: root.cMid }
            GradientStop { position: 1.0; color: root.cBottom }
        }
        border.width: 1
        border.color: root.borderColor
    }

    // 海洋：静态分层浪花（浅色配色用白色浪花，深色配色用浪花白）
    Item {
        anchors.fill: parent
        visible: root.isOcean
        clip: true

        readonly property real foamOpacity: root.darkPreview ? 1.0 : 0.55

        Rectangle {
            x: 4; y: parent.height * 0.52; width: parent.width - 8; height: parent.height * 0.18
            radius: height / 2
            color: root.darkPreview ? "#334FD0E0" : "#5510A5C0"
            opacity: parent.foamOpacity
        }
        Rectangle {
            x: 0; y: parent.height * 0.64; width: parent.width; height: parent.height * 0.2
            radius: height / 2
            color: root.darkPreview ? "#4D2E9FBF" : "#662E9FBF"
            opacity: parent.foamOpacity
        }
        Rectangle {
            x: 6; y: parent.height * 0.77; width: parent.width - 12; height: parent.height * 0.18
            radius: height / 2
            color: root.darkPreview ? "#6655C7DA" : "#88FFFFFF"
            opacity: parent.foamOpacity
        }
        Rectangle { x: parent.width * 0.1; y: parent.height * 0.5; width: parent.width * 0.7; height: 2; radius: 1; color: root.darkPreview ? "#BEEFF6" : "#FFFFFF"; opacity: 0.55 }
        Rectangle { x: parent.width * 0.05; y: parent.height * 0.63; width: parent.width * 0.82; height: 2; radius: 1; color: root.darkPreview ? "#BEEFF6" : "#FFFFFF"; opacity: 0.42 }
        Rectangle { x: parent.width * 0.12; y: parent.height * 0.76; width: parent.width * 0.62; height: 2; radius: 1; color: root.darkPreview ? "#DFF8FC" : "#FFFFFF"; opacity: 0.35 }
    }

    // 液态玻璃：模糊色块 + 玻璃内框 + 星光
    Item {
        anchors.fill: parent
        visible: root.isGlass
        clip: true

        // 渐变玻璃色块：浅色配色偏冰蓝紫，深色配色偏亮玻璃
        Rectangle {
            x: parent.width * 0.02
            y: parent.height * 0.06
            width: parent.width * 0.58
            height: parent.height * 0.5
            radius: height / 2
            color: root.darkPreview ? "#668FC7FF" : "#553A6BE0"
            opacity: 0.75
        }
        Rectangle {
            x: parent.width * 0.36
            y: parent.height * 0.44
            width: parent.width * 0.62
            height: parent.height * 0.46
            radius: height / 2
            color: root.darkPreview ? "#55A48CFF" : "#447C5CFF"
            opacity: 0.7
        }
        Rectangle {
            anchors.fill: parent
            anchors.margins: parent.width * 0.11
            radius: Math.max(6, root.corner - 4)
            color: root.darkPreview ? "#1FFFFFFF" : "#55FFFFFF"
            border.width: 1
            border.color: root.darkPreview ? "#66FFFFFF" : "#88FFFFFF"
        }
        Glyph {
            anchors.centerIn: parent
            kind: "sparkle"
            size: Math.max(14, Math.min(root.width, root.height) * 0.3)
            color: root.darkPreview ? "#FFFFFF" : "#FFFFFF"
        }
    }

    // 普通 / 自定义配色：示意用的迷你卡片 + 强调块
    // 尺寸按 min(宽,高) 收敛，避免在详情页大预览里出现「粗条」。
    Item {
        anchors.fill: parent
        visible: !root.isGlass && !root.isOcean

        readonly property real unit: Math.min(parent.width, parent.height)
        readonly property real barH1: Math.max(4, Math.min(12, unit * 0.1))
        readonly property real barH2: Math.max(3, Math.min(8, unit * 0.07))
        readonly property real barH3: Math.max(3, Math.min(7, unit * 0.06))
        readonly property real pillH: Math.max(9, Math.min(26, unit * 0.19))

        Rectangle {
            x: parent.width * 0.1
            y: parent.height * 0.14
            width: parent.width * 0.34
            height: parent.barH1
            radius: height / 2
            color: root.cAccent
        }
        Rectangle {
            x: parent.width * 0.1
            y: parent.height * 0.31
            width: parent.width * 0.6
            height: parent.barH2
            radius: height / 2
            color: Qt.rgba(root.cInk.r, root.cInk.g, root.cInk.b, 0.34)
        }
        Rectangle {
            x: parent.width * 0.1
            y: parent.height * 0.43
            width: parent.width * 0.46
            height: parent.barH3
            radius: height / 2
            color: Qt.rgba(root.cInk.r, root.cInk.g, root.cInk.b, 0.18)
        }
        Rectangle {
            x: parent.width * 0.1
            y: parent.height * 0.63
            width: parent.width * 0.36
            height: parent.pillH
            radius: height / 2
            color: root.cAccent
            opacity: 0.9
        }
        Rectangle {
            x: parent.width * 0.58
            y: parent.height * 0.56
            width: Math.min(parent.width * 0.3, 150)
            height: Math.min(parent.height * 0.32, 64)
            radius: Math.max(4, root.corner * 0.3)
            color: root.cCard
            opacity: 0.92
            border.width: 1
            border.color: Qt.rgba(root.cInk.r, root.cInk.g, root.cInk.b, 0.22)
        }
    }
}
