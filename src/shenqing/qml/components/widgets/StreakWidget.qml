import QtQuick
import "../../theme"
import ".."

// v24 连续打卡组件：连续天数 + 小火焰。
// 数据：App.streakDays（int，notify statsChanged）。
// 统一接口：props（showBest）、compact、app。
Item {
    id: widget
    property var props: ({})
    property bool compact: false
    property var app: null

    readonly property var bridge: (app !== null && app !== undefined) ? app
                                   : (typeof App !== "undefined" ? App : null)
    readonly property bool dense: compact || width < 180 || height < 88
    readonly property bool showBest: (props && props.showBest === true)
    readonly property int streakValue: {
        if (widget.bridge === null || widget.bridge.streakDays === undefined) return 0
        var value = Number(widget.bridge.streakDays)
        return isFinite(value) ? Math.max(0, Math.round(value)) : 0
    }
    readonly property int bestValue: {
        if (widget.bridge === null || widget.bridge.streakBest === undefined) return 0
        var value = Number(widget.bridge.streakBest)
        return isFinite(value) ? Math.max(0, Math.round(value)) : 0
    }

    WidgetCard {
        anchors.fill: parent
        title: qsTr("连续打卡")
        icon: "flame"
        compact: widget.dense

        Row {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: widget.dense ? 6 : 10

            Item {
                width: Math.max(18, Math.min(widget.height * 0.42, widget.dense ? 26 : 44))
                height: width
                anchors.verticalCenter: parent.verticalCenter

                // 火焰外圈光晕
                Rectangle {
                    anchors.centerIn: parent
                    width: parent.width * 1.16
                    height: width
                    radius: width / 2
                    color: Qt.rgba(AppTheme.accent.r, AppTheme.accent.g, AppTheme.accent.b, 0.14)
                }

                Glyph {
                    anchors.centerIn: parent
                    kind: "flame"
                    size: parent.width * 0.68
                    color: AppTheme.accent
                }
            }

            Column {
                anchors.verticalCenter: parent.verticalCenter
                width: Math.max(0, parent.width - parent.spacing
                                   - Math.max(18, Math.min(widget.height * 0.42, widget.dense ? 26 : 44)))
                spacing: widget.dense ? 0 : 2

                Text {
                    width: parent.width
                    text: qsTr("%1 天").arg(widget.streakValue)
                    color: AppTheme.textPrimary
                    font.family: AppTheme.fontFamily
                    font.pixelSize: Math.min(34, Math.max(13, widget.height * 0.30))
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }

                Text {
                    width: parent.width
                    text: widget.showBest && widget.bestValue > 0
                          ? qsTr("最长 %1 天").arg(widget.bestValue)
                          : qsTr("今天也保持住")
                    color: AppTheme.textTertiary
                    font.pixelSize: Math.min(12, Math.max(9, widget.height * 0.085))
                    font.family: AppTheme.fontFamily
                    elide: Text.ElideRight
                }
            }
        }
    }
}
