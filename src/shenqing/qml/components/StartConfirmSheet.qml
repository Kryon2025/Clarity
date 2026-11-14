import QtQuick
import "../theme"

// v0.21 开始专注前的二次确认卡（玻璃卡 / Sheet）
// - 全屏浮层：半透明遮罩 + 居中玻璃卡，点遮罩 / Esc 等价于「取消」
// - 内容：空间名 / 档位 / 时长 / 白名单摘要
// - 按钮：「确认开始」「取消」，由调用方在 confirmed / cancelled 里关闭（opened = false）
// - 窄容器（如 340 宽的速启面板）自动切换紧凑排版
Item {
    id: sheet
    objectName: "StartConfirmSheet"

    property bool opened: false
    property bool animationsEnabled: true
    property Item glassSource: null

    property string spaceName: ""
    property string mode: "medium"
    property string modeLabel: ""
    property int minutes: 0
    property int whitelistCount: -1
    // 后端若直接给摘要文本（如「白名单 · 5 个应用」），优先显示
    property string whitelistSummary: ""

    signal confirmed()
    signal cancelled()

    readonly property bool compact: sheet.width < 420
    readonly property string modeIcon: sheet.mode === "heavy" ? "lock"
                                          : (sheet.mode === "light" ? "moon" : "wave")
    readonly property string modeText: sheet.modeLabel !== "" ? sheet.modeLabel : String(sheet.mode)
    readonly property string whitelistText: {
        if (sheet.whitelistSummary !== "") return sheet.whitelistSummary
        if (String(sheet.mode) === "heavy") return qsTr("深清固定不含白名单")
        if (sheet.whitelistCount > 0) return qsTr("%1 个应用").arg(sheet.whitelistCount)
        return qsTr("未设置")
    }
    readonly property var infoRows: [
        { label: qsTr("空间"), value: sheet.spaceName !== "" ? sheet.spaceName : qsTr("清空间") },
        { label: qsTr("档位"), value: sheet.modeText },
        { label: qsTr("时长"), value: sheet.minutes > 0 ? qsTr("%1 分钟").arg(sheet.minutes) : qsTr("按空间设置") },
        { label: qsTr("白名单"), value: sheet.whitelistText }
    ]

    visible: sheet.opened || sheet.opacity > 0.01
    opacity: sheet.opened ? 1 : 0
    focus: sheet.visible
    z: 70

    onOpenedChanged: {
        if (sheet.opened) sheet.forceActiveFocus()
    }

    Behavior on opacity {
        enabled: sheet.animationsEnabled
        NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
    }

    Keys.onEscapePressed: sheet.cancelled()

    // 遮罩：点空白处 = 取消
    Rectangle {
        anchors.fill: parent
        color: AppTheme.scrimMedium
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        onClicked: sheet.cancelled()
    }

    Rectangle {
        id: card
        objectName: "StartConfirmCard"
        width: Math.min(sheet.compact ? 320 : 430, sheet.width - 28)
        height: cardColumn.height + (sheet.compact ? 28 : 40)
        anchors.centerIn: parent
        radius: 22
        color: AppTheme.glass ? AppTheme.dialogBg : AppTheme.cardBg
        border.width: 1
        border.color: AppTheme.glass ? "#4DFFFFFF" : AppTheme.cardBorderStrong

        scale: sheet.opened ? 1 : 0.97
        Behavior on scale {
            enabled: sheet.animationsEnabled
            NumberAnimation { duration: 170; easing.type: Easing.OutCubic }
        }

        // 吃掉卡内点击，避免误触取消
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onClicked: {}
        }

        Column {
            id: cardColumn
            x: sheet.compact ? 18 : 24
            y: sheet.compact ? 14 : 20
            width: parent.width - x * 2
            spacing: sheet.compact ? 8 : 10

            Row {
                width: parent.width
                spacing: 9

                Glyph {
                    anchors.verticalCenter: parent.verticalCenter
                    kind: sheet.modeIcon
                    size: sheet.compact ? 15 : 17
                    color: AppTheme.accent
                }

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: qsTr("确认开始")
                    color: AppTheme.textPrimary
                    font.pixelSize: AppTheme.fs(sheet.compact ? 16 : 18)
                    font.weight: Font.DemiBold
                    font.family: AppTheme.fontFamily
                }
            }

            Text {
                width: parent.width
                text: qsTr("即将进入专注，确认后开始计时")
                color: AppTheme.textSecondary
                font.pixelSize: AppTheme.fs(sheet.compact ? 10 : 11)
                font.family: AppTheme.fontFamily
                wrapMode: Text.WordWrap
            }

            Rectangle {
                width: parent.width
                height: 1
                color: AppTheme.divider
            }

            Repeater {
                model: sheet.infoRows

                delegate: Item {
                    width: cardColumn.width
                    height: sheet.compact ? 20 : 24

                    Text {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: sheet.compact ? 46 : 56
                        text: String(modelData.label)
                        color: AppTheme.textTertiary
                        font.pixelSize: AppTheme.fs(sheet.compact ? 10 : 11)
                        font.family: AppTheme.fontFamily
                    }

                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: sheet.compact ? 46 : 56
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        text: String(modelData.value)
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(sheet.compact ? 11 : 12)
                        font.family: AppTheme.fontFamily
                        elide: Text.ElideRight
                    }
                }
            }

            Text {
                visible: !sheet.compact
                width: parent.width
                text: qsTr("开始后本轮专注立即计时；「深清」开始后不可暂停、不可提前结束。")
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
                    width: Math.max(0, parent.width - cancelButton.width - confirmButton.width - 20)
                    height: 1
                }

                GlassButton {
                    id: cancelButton
                    objectName: "StartConfirmCancel"
                    text: qsTr("取消")
                    tone: "ghost"
                    fontSize: sheet.compact ? 12 : 13
                    padH: sheet.compact ? 16 : 18
                    minHeight: sheet.compact ? 34 : 38
                    onClicked: sheet.cancelled()
                }

                GlassButton {
                    id: confirmButton
                    objectName: "StartConfirmConfirm"
                    text: qsTr("确认开始")
                    tone: "accent"
                    fontSize: sheet.compact ? 12 : 13
                    padH: sheet.compact ? 20 : 24
                    minHeight: sheet.compact ? 34 : 38
                    onClicked: sheet.confirmed()
                }
            }
        }
    }
}
