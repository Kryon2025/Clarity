import QtQuick
import "../theme"
import "Constants.js" as C

// 商店入口横幅（v0.18）：主题页 / 插件页顶部共用。
// 玻璃卡：图标 + 标题 + 副标题 + 箭头，点击进入对应商店。
GlassCard {
    id: root

    property string title: qsTr("主题商店")
    property string subtitle: qsTr("发现更多配色与浪花")
    property string iconKind: "sparkle"

    height: 74
    radius: 20
    interactive: true
    hoverLiftEnabled: true

    Item {
        anchors.fill: parent
        anchors.margins: 14

        Rectangle {
            id: iconBox
            width: 46
            height: 46
            radius: 15
            anchors.verticalCenter: parent.verticalCenter
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: AppTheme.gradA }
                GradientStop { position: 0.55; color: AppTheme.gradB }
                GradientStop { position: 1.0; color: AppTheme.gradC }
            }

            Glyph {
                anchors.centerIn: parent
                kind: root.iconKind
                size: 22
                color: AppTheme.onAccent
            }
        }

        Column {
            anchors.left: iconBox.right
            anchors.leftMargin: 14
            anchors.verticalCenter: parent.verticalCenter
            spacing: 3

            Text {
                text: root.title
                color: AppTheme.textPrimary
                font.pixelSize: AppTheme.fs(16)
                font.weight: Font.DemiBold
                font.family: AppTheme.fontFamily
            }
            Text {
                text: root.subtitle
                color: AppTheme.textSecondary
                font.pixelSize: AppTheme.fs(11)
                font.family: AppTheme.fontFamily
            }
        }

        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: qsTr("去逛逛")
                color: AppTheme.accent
                font.pixelSize: AppTheme.fs(11)
                font.family: AppTheme.fontFamily
            }
            Glyph {
                anchors.verticalCenter: parent.verticalCenter
                kind: "chevron"
                size: 15
                color: AppTheme.accent
            }
        }
    }
}
