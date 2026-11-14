import QtQuick
import "../../theme"
import "../Constants.js" as C
import ".."

// v24 时钟组件：大号 HH:mm + 日期 / 星期。
// 统一接口：props（showSeconds / format）、compact、app（AppBridge，时钟不需要，仅占位保持接口一致）。
Item {
    id: widget
    property var props: ({})
    property bool compact: false
    property var app: null

    readonly property bool dense: compact || width < 240 || height < 108
    readonly property string timeFormat: (props && props.format !== undefined) ? String(props.format) : "24h"
    readonly property bool showSeconds: (props && props.showSeconds === true)

    property string timeText: "--:--"
    property string dateText: ""
    property string weekText: ""

    function pad2(value) {
        return value < 10 ? "0" + value : String(value)
    }

    function refresh() {
        var now = new Date()
        var hours = now.getHours()
        var suffix = ""
        if (widget.timeFormat === "12h") {
            suffix = hours >= 12 ? " PM" : " AM"
            hours = hours % 12
            if (hours === 0) hours = 12
        }
        var text = widget.pad2(hours) + ":" + widget.pad2(now.getMinutes())
        if (widget.showSeconds) text += ":" + widget.pad2(now.getSeconds())
        widget.timeText = text + suffix
        widget.dateText = now.getFullYear() + "/" + widget.pad2(now.getMonth() + 1)
                           + "/" + widget.pad2(now.getDate())
        var weekNames = [qsTr("周日"), qsTr("周一"), qsTr("周二"), qsTr("周三"),
                         qsTr("周四"), qsTr("周五"), qsTr("周六")]
        widget.weekText = weekNames[now.getDay()]
    }

    Timer {
        interval: 1000
        repeat: true
        running: true
        onTriggered: widget.refresh()
    }

    Component.onCompleted: widget.refresh()

    WidgetCard {
        anchors.fill: parent
        title: qsTr("时钟")
        icon: "clock"
        compact: widget.dense

        Column {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: widget.dense ? 0 : 2

            Text {
                width: parent.width
                text: widget.timeText
                color: AppTheme.textPrimary
                font.family: C.monoFont
                font.pixelSize: Math.min(76, Math.max(16, widget.height * 0.34))
                font.weight: Font.Light
                font.letterSpacing: widget.dense ? 1 : 2
                elide: Text.ElideRight
            }

            Text {
                width: parent.width
                text: widget.dateText + (widget.weekText !== "" ? " · " + widget.weekText : "")
                color: AppTheme.textSecondary
                font.pixelSize: Math.min(15, Math.max(9, widget.height * 0.085))
                font.family: AppTheme.fontFamily
                font.letterSpacing: 1
                elide: Text.ElideRight
            }
        }
    }
}
