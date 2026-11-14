import QtQuick
import "../theme"

// v0.21 AI 动作确认卡（玻璃卡 / Sheet）
// 后端 App.aiActionPending 存在时使用：AI 回复里要打开空间 / 改设置，先让用户确认。
// 确认 → 调用方执行 App.aiConfirmAction；取消 → App.aiCancelAction。
Item {
    id: card
    objectName: "AIActionConfirmCard"

    property bool opened: false
    property bool animationsEnabled: true
    property string title: qsTr("AI 想要执行一个动作")
    property string actionText: ""
    property string detail: ""
    property string confirmText: qsTr("确认执行")
    property string cancelText: qsTr("取消")

    signal confirmed()
    signal cancelled()

    readonly property bool compact: card.width < 420

    visible: card.opened || card.opacity > 0.01
    opacity: card.opened ? 1 : 0
    focus: card.visible
    z: 72

    onOpenedChanged: {
        if (card.opened) card.forceActiveFocus()
    }

    Behavior on opacity {
        enabled: card.animationsEnabled
        NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
    }

    Keys.onEscapePressed: card.cancelled()

    Rectangle {
        anchors.fill: parent
        color: AppTheme.scrimMedium
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        onClicked: card.cancelled()
    }

    Rectangle {
        id: base
        width: Math.min(card.compact ? 320 : 420, card.width - 28)
        height: contentColumn.height + (card.compact ? 28 : 40)
        anchors.centerIn: parent
        radius: 22
        color: AppTheme.glass ? AppTheme.dialogBg : AppTheme.cardBg
        border.width: 1
        border.color: AppTheme.glass ? "#4DFFFFFF" : AppTheme.cardBorderStrong

        scale: card.opened ? 1 : 0.97
        Behavior on scale {
            enabled: card.animationsEnabled
            NumberAnimation { duration: 170; easing.type: Easing.OutCubic }
        }

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onClicked: {}
        }

        Column {
            id: contentColumn
            x: card.compact ? 18 : 24
            y: card.compact ? 14 : 20
            width: parent.width - x * 2
            spacing: card.compact ? 8 : 10

            Row {
                width: parent.width
                spacing: 9

                Glyph {
                    anchors.verticalCenter: parent.verticalCenter
                    kind: "sparkle"
                    size: card.compact ? 15 : 17
                    color: AppTheme.accent
                }

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 30
                    text: card.title
                    color: AppTheme.textPrimary
                    font.pixelSize: AppTheme.fs(card.compact ? 15 : 17)
                    font.weight: Font.DemiBold
                    font.family: AppTheme.fontFamily
                    elide: Text.ElideRight
                }
            }

            Rectangle {
                width: parent.width
                height: 1
                color: AppTheme.divider
            }

            // 动作内容：如「打开空间「深清工作」」「修改设置：字号 120%」
            Text {
                width: parent.width
                text: card.actionText !== "" ? card.actionText : qsTr("（未提供动作说明）")
                color: AppTheme.textPrimary
                font.pixelSize: AppTheme.fs(card.compact ? 11 : 13)
                font.family: AppTheme.fontFamily
                wrapMode: Text.WordWrap
                lineHeight: 1.4
            }

            Text {
                visible: card.detail !== ""
                width: parent.width
                text: card.detail
                color: AppTheme.textSecondary
                font.pixelSize: AppTheme.fs(card.compact ? 10 : 11)
                font.family: AppTheme.fontFamily
                wrapMode: Text.WordWrap
                lineHeight: 1.3
            }

            Text {
                width: parent.width
                text: qsTr("确认后立即执行，执行结果会以系统提示留在聊天记录里。")
                color: AppTheme.textTertiary
                font.pixelSize: AppTheme.fs(10)
                font.family: AppTheme.fontFamily
                wrapMode: Text.WordWrap
                lineHeight: 1.3
            }

            Row {
                width: parent.width
                spacing: 10

                Item {
                    width: Math.max(0, parent.width - cancelAction.width - confirmAction.width - 20)
                    height: 1
                }

                GlassButton {
                    id: cancelAction
                    objectName: "AIActionCancel"
                    text: card.cancelText
                    tone: "ghost"
                    fontSize: card.compact ? 12 : 13
                    padH: card.compact ? 16 : 18
                    minHeight: card.compact ? 34 : 38
                    onClicked: card.cancelled()
                }

                GlassButton {
                    id: confirmAction
                    objectName: "AIActionConfirm"
                    text: card.confirmText
                    tone: "accent"
                    fontSize: card.compact ? 12 : 13
                    padH: card.compact ? 18 : 22
                    minHeight: card.compact ? 34 : 38
                    onClicked: card.confirmed()
                }
            }
        }
    }
}
