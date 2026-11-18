import QtQuick
import "../../theme"
import ".."

// v24 内置组件统一玻璃卡：AppTheme.cardBg 半透明底 + 1px 描边 + 18 圆角，
// 标题小字（图标 + 文字）+ 内容区。6 个内置组件共用，锁屏与「组件与布局」预览页样式一致。
// compact = true 时收紧内边距与标题字号（预览缩小、小尺寸组件时使用）。
Item {
    id: card

    // 内容区（默认属性：子元素自动进入内容区，不再参与标题行排版）
    default property alias content: contentHost.data

    property string title: ""
    property string icon: ""
    property bool compact: false
    property color accentColor: AppTheme.accent
    property bool dimmed: false            // 预览页「已隐藏」时压暗
    property bool selected: false

    readonly property real corner: 18
    // v0.29：内边距与标题间距收紧，避免「框大字小、四周空」
    readonly property real padH: compact ? 8 : 11
    readonly property real padV: compact ? 6 : 8
    readonly property real titleGap: compact ? 3 : 4
    readonly property real titlePixel: AppTheme.fs(compact ? 9.5 : 10)
    readonly property real titleRowHeight: Math.max(compact ? 11 : 13, titlePixel + 2)
    readonly property real titleRowWidth: Math.max(0, card.width - card.padH * 2)

    clip: true

    // 底：半透明卡片色 + 细描边
    Rectangle {
        id: fill
        anchors.fill: parent
        radius: card.corner
        color: Qt.rgba(AppTheme.cardBg.r, AppTheme.cardBg.g, AppTheme.cardBg.b,
                       card.compact ? 0.72 : 0.84)
        border.width: 1
        border.color: card.selected ? AppTheme.accent : AppTheme.cardBorder
        opacity: card.dimmed ? 0.42 : 1.0
        Behavior on opacity { NumberAnimation { duration: 140 } }
    }

    // 顶部镜面高光：两端渐隐的亮线（玻璃厚度感）
    Rectangle {
        visible: !card.compact
        x: card.corner * 0.9
        y: 1
        width: Math.max(0, card.width * 0.6)
        height: 1
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "#00FFFFFF" }
            GradientStop { position: 0.5; color: "#3DFFFFFF" }
            GradientStop { position: 1.0; color: "#00FFFFFF" }
        }
    }

    // 标题行：小图标 + 小字
    Row {
        id: titleRow
        x: card.padH
        y: card.padV
        width: card.titleRowWidth
        height: card.titleRowHeight
        spacing: card.compact ? 4 : 6

        Glyph {
            anchors.verticalCenter: parent.verticalCenter
            visible: card.icon !== ""
            kind: card.icon
            size: card.compact ? 10 : 12
            color: card.selected ? AppTheme.accent : AppTheme.textTertiary
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: card.title !== ""
            width: Math.max(0, titleRow.width - (card.icon !== "" ? (card.compact ? 14 : 18) : 0))
            text: card.title
            color: AppTheme.textTertiary
            font.pixelSize: card.titlePixel
            font.family: AppTheme.fontFamily
            font.letterSpacing: 0.3
            elide: Text.ElideRight
        }
    }

    Item {
        id: contentHost
        x: card.padH
        y: titleRow.y + titleRow.height + card.titleGap
        width: Math.max(0, card.width - card.padH * 2)
        height: Math.max(0, card.height - y - card.padV)
        clip: true
    }
}
