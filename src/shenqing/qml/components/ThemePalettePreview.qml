import QtQuick
import "../theme"

// 主题配色预览块（v0.18）：主题页卡片 / 主题商店卡片与详情页共用。
// - style: solid / light / glass / ocean / custom
// - palette: 商店条目 / 自定义主题的 palette（含 bgTop/bgMid/bgBottom/accent/cardBg/textPrimary）
// - live: true 时直接使用 AppTheme 当前配色（「当前样式」卡片）
Item {
    id: root

    property string style: "solid"
    property var themePalette: ({})
    property bool live: false
    property real corner: 14
    property color borderColor: "#2BFFFFFF"

    readonly property bool usesPalette: !root.live && root.themePalette !== undefined && root.themePalette !== null
                                        && root.themePalette.bgTop !== undefined

    readonly property color cTop: {
        if (root.live) return AppTheme.bgTop
        if (root.usesPalette) return String(root.themePalette.bgTop)
        if (root.style === "light") return "#FFFFFF"
        if (root.style === "ocean") return "#1B5A73"
        if (root.style === "glass") return "#1F6FD0"
        return "#0E2A38"
    }
    readonly property color cMid: {
        if (root.live) return AppTheme.bgMid
        if (root.usesPalette) return String(root.themePalette.bgMid !== undefined ? root.themePalette.bgMid : root.themePalette.bgTop)
        if (root.style === "light") return "#DCEBEF"
        if (root.style === "ocean") return "#0E3546"
        if (root.style === "glass") return "#2ED3C6"
        return "#071F2A"
    }
    readonly property color cBottom: {
        if (root.live) return AppTheme.bgBottom
        if (root.usesPalette) return String(root.themePalette.bgBottom !== undefined ? root.themePalette.bgBottom : root.themePalette.bgMid)
        if (root.style === "light") return "#D5E5E9"
        if (root.style === "ocean") return "#071E29"
        if (root.style === "glass") return "#0A2A36"
        return "#04121C"
    }
    readonly property color cAccent: {
        if (root.live) return AppTheme.accent
        if (root.usesPalette && root.themePalette.accent !== undefined) return String(root.themePalette.accent)
        if (root.style === "light") return "#0E9E95"
        if (root.style === "ocean") return "#4FD0E0"
        if (root.style === "glass") return "#BEEFF6"
        return "#2ED3C6"
    }
    readonly property color cCard: {
        if (root.live) return AppTheme.cardBg
        if (root.usesPalette && root.themePalette.cardBg !== undefined) return String(root.themePalette.cardBg)
        if (root.style === "light") return "#FFFFFF"
        if (root.style === "ocean") return "#0C2E3C"
        return "#123243"
    }
    readonly property color cInk: {
        if (root.live) return AppTheme.textPrimary
        if (root.usesPalette && root.themePalette.textPrimary !== undefined) return String(root.themePalette.textPrimary)
        if (root.style === "light") return "#0C2831"
        return "#EFF9FF"
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

    // 海洋：静态分层浪花
    Item {
        anchors.fill: parent
        visible: root.isOcean
        clip: true

        Rectangle {
            x: 4; y: parent.height * 0.52; width: parent.width - 8; height: parent.height * 0.18
            radius: height / 2
            color: "#334FD0E0"
        }
        Rectangle {
            x: 0; y: parent.height * 0.64; width: parent.width; height: parent.height * 0.2
            radius: height / 2
            color: "#4D2E9FBF"
        }
        Rectangle {
            x: 6; y: parent.height * 0.77; width: parent.width - 12; height: parent.height * 0.18
            radius: height / 2
            color: "#6655C7DA"
        }
        Rectangle { x: parent.width * 0.1; y: parent.height * 0.5; width: parent.width * 0.7; height: 2; radius: 1; color: "#BEEFF6"; opacity: 0.55 }
        Rectangle { x: parent.width * 0.05; y: parent.height * 0.63; width: parent.width * 0.82; height: 2; radius: 1; color: "#BEEFF6"; opacity: 0.42 }
        Rectangle { x: parent.width * 0.12; y: parent.height * 0.76; width: parent.width * 0.62; height: 2; radius: 1; color: "#DFF8FC"; opacity: 0.35 }
    }

    // 液态玻璃：模糊色块 + 玻璃内框 + 星光
    Item {
        anchors.fill: parent
        visible: root.isGlass
        clip: true

        Rectangle {
            anchors.fill: parent
            anchors.margins: parent.width * 0.11
            radius: Math.max(6, root.corner - 4)
            color: "#1FFFFFFF"
            border.width: 1
            border.color: "#66FFFFFF"
        }
        Glyph {
            anchors.centerIn: parent
            kind: "sparkle"
            size: Math.max(14, Math.min(root.width, root.height) * 0.3)
            color: "#FFFFFF"
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
