import QtQuick
import "../../theme"
import ".."

// v24 今日专注组件：今日时长 / 次数 / 连续打卡（缺失一律兜底 0）。
// 数据：App.todayFocusCard（minutes / sessions / clicks）、App.todayMinutes、App.todaySessions、App.streakDays。
// 统一接口：props（showMinutes / showCount）、compact、app。
Item {
    id: widget
    property var props: ({})
    property bool compact: false
    property var app: null

    readonly property var bridge: (app !== null && app !== undefined) ? app
                                   : (typeof App !== "undefined" ? App : null)
    readonly property bool dense: compact || width < 240 || height < 104
    readonly property bool showMinutes: !(props && props.showMinutes === false)
    readonly property bool showCount: !(props && props.showCount === false)
    readonly property var cardData: (widget.bridge !== null && widget.bridge.todayFocusCard !== undefined
                                     && widget.bridge.todayFocusCard !== null)
                                    ? widget.bridge.todayFocusCard : ({})

    readonly property real minutesValue: {
        var value = Number(widget.cardData.minutes)
        if (!isFinite(value) && widget.bridge !== null && widget.bridge.todayMinutes !== undefined)
            value = Number(widget.bridge.todayMinutes)
        return isFinite(value) ? Math.max(0, value) : 0
    }
    readonly property int sessionsValue: {
        var value = Number(widget.cardData.sessions)
        if (!isFinite(value) && widget.bridge !== null && widget.bridge.todaySessions !== undefined)
            value = Number(widget.bridge.todaySessions)
        return isFinite(value) ? Math.max(0, Math.round(value)) : 0
    }
    readonly property int streakValue: {
        if (widget.bridge === null || widget.bridge.streakDays === undefined) return 0
        var value = Number(widget.bridge.streakDays)
        return isFinite(value) ? Math.max(0, Math.round(value)) : 0
    }
    readonly property string minutesText: {
        var value = widget.minutesValue
        if (value >= 60) {
            var hours = Math.floor(value / 60)
            var rest = Math.round(value - hours * 60)
            return rest > 0 ? qsTr("%1 时 %2 分").arg(hours).arg(rest) : qsTr("%1 时").arg(hours)
        }
        return qsTr("%1 分").arg(Math.round(value))
    }

    WidgetCard {
        anchors.fill: parent
        title: qsTr("今日专注")
        icon: "waveBars"
        compact: widget.dense

        Row {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: widget.dense ? 8 : 16

            Column {
                width: widget.dense ? (parent.width - parent.spacing * 2) / 3
                                    : Math.min((parent.width - parent.spacing * 2) / 3, 168)
                anchors.verticalCenter: parent.verticalCenter
                spacing: widget.dense ? 0 : 2
                Text {
                    width: parent.width
                    text: widget.minutesText
                    color: AppTheme.textPrimary
                    font.family: AppTheme.fontFamily
                    font.pixelSize: Math.min(30, Math.max(12, widget.height * 0.16))
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    text: qsTr("今日时长")
                    color: AppTheme.textTertiary
                    font.pixelSize: Math.min(12, Math.max(9, widget.height * 0.07))
                    font.family: AppTheme.fontFamily
                    elide: Text.ElideRight
                }
            }

            Rectangle {
                width: 1
                height: Math.max(10, widget.height * 0.22)
                anchors.verticalCenter: parent.verticalCenter
                color: AppTheme.divider
            }

            Column {
                width: widget.dense ? (parent.width - parent.spacing * 2) / 3
                                    : Math.min((parent.width - parent.spacing * 2) / 3, 168)
                anchors.verticalCenter: parent.verticalCenter
                spacing: widget.dense ? 0 : 2
                Text {
                    width: parent.width
                    text: qsTr("%1 次").arg(widget.sessionsValue)
                    color: AppTheme.textPrimary
                    font.family: AppTheme.fontFamily
                    font.pixelSize: Math.min(30, Math.max(12, widget.height * 0.16))
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    text: qsTr("今日次数")
                    color: AppTheme.textTertiary
                    font.pixelSize: Math.min(12, Math.max(9, widget.height * 0.07))
                    font.family: AppTheme.fontFamily
                    elide: Text.ElideRight
                }
            }

            Rectangle {
                width: 1
                height: Math.max(10, widget.height * 0.22)
                anchors.verticalCenter: parent.verticalCenter
                color: AppTheme.divider
            }

            Column {
                width: widget.dense ? (parent.width - parent.spacing * 2) / 3
                                    : Math.min((parent.width - parent.spacing * 2) / 3, 168)
                anchors.verticalCenter: parent.verticalCenter
                spacing: widget.dense ? 0 : 2
                Text {
                    width: parent.width
                    text: qsTr("%1 天").arg(widget.streakValue)
                    color: AppTheme.accent
                    font.family: AppTheme.fontFamily
                    font.pixelSize: Math.min(30, Math.max(12, widget.height * 0.16))
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    text: qsTr("连续打卡")
                    color: AppTheme.textTertiary
                    font.pixelSize: Math.min(12, Math.max(9, widget.height * 0.07))
                    font.family: AppTheme.fontFamily
                    elide: Text.ElideRight
                }
            }

            Item { width: 1; height: 1 }
        }
    }
}
