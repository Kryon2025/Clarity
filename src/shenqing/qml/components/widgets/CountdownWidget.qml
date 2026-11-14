import QtQuick
import "../../theme"
import "../Constants.js" as C
import ".."

// v24 专注倒计时组件：剩余时间大数字 + 进度环。
// 数据：App.remainingSeconds / App.totalSeconds / App.progress / App.state（idle|running|paused）。
// 统一接口：props（mode，只读占位）、compact、app。
Item {
    id: widget
    property var props: ({})
    property bool compact: false
    property var app: null

    readonly property var bridge: (app !== null && app !== undefined) ? app
                                   : (typeof App !== "undefined" ? App : null)
    readonly property bool dense: compact || width < 240 || height < 104

    readonly property int remaining: {
        if (widget.bridge === null || widget.bridge.remainingSeconds === undefined) return 0
        var value = Number(widget.bridge.remainingSeconds)
        return isFinite(value) ? Math.max(0, Math.round(value)) : 0
    }
    readonly property int total: {
        if (widget.bridge === null || widget.bridge.totalSeconds === undefined) return 0
        var value = Number(widget.bridge.totalSeconds)
        return isFinite(value) ? Math.max(0, Math.round(value)) : 0
    }
    readonly property real progress: {
        if (widget.bridge !== null && widget.bridge.progress !== undefined) {
            var value = Number(widget.bridge.progress)
            if (isFinite(value)) return Math.max(0, Math.min(1, value))
        }
        if (widget.total > 0) return Math.max(0, Math.min(1, 1 - widget.remaining / widget.total))
        return 0
    }
    readonly property string stateName: (widget.bridge !== null
                                         && widget.bridge.state !== undefined)
                                        ? String(widget.bridge.state) : "idle"
    readonly property bool running: widget.stateName === "running"
    readonly property bool paused: widget.stateName === "paused"
    readonly property bool idle: !widget.running && !widget.paused

    readonly property string timeText: {
        if (widget.idle) return "--:--"
        var seconds = widget.remaining
        var hours = Math.floor(seconds / 3600)
        var minutes = Math.floor((seconds % 3600) / 60)
        var rest = seconds % 60
        var pad = function (value) { return value < 10 ? "0" + value : String(value) }
        if (hours > 0) return hours + ":" + pad(minutes) + ":" + pad(rest)
        return pad(minutes) + ":" + pad(rest)
    }
    readonly property string stateText: widget.running ? qsTr("专注中")
                                          : (widget.paused ? qsTr("已暂停") : qsTr("未开始"))

    WidgetCard {
        anchors.fill: parent
        title: qsTr("专注倒计时")
        icon: "timer"
        compact: widget.dense

        Row {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: widget.dense ? 8 : 14

            Canvas {
                id: ring
                width: Math.max(22, Math.min(widget.height * 0.34, widget.dense ? 34 : 64))
                height: width
                anchors.verticalCenter: parent.verticalCenter
                antialiasing: true
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()
                    var size = Math.min(ring.width, ring.height)
                    if (size <= 0) return
                    var line = Math.max(2, size * 0.11)
                    var radius = (size - line) / 2
                    var cx = size / 2
                    var cy = size / 2
                    ctx.lineWidth = line
                    ctx.lineCap = "round"
                    ctx.strokeStyle = Qt.rgba(AppTheme.textSecondary.r,
                                              AppTheme.textSecondary.g,
                                              AppTheme.textSecondary.b, 0.28)
                    ctx.beginPath()
                    ctx.arc(cx, cy, radius, 0, Math.PI * 2)
                    ctx.stroke()
                    var arc = Math.max(0, Math.min(1, widget.progress))
                    if (arc > 0.002) {
                        ctx.strokeStyle = widget.paused ? AppTheme.textSecondary : AppTheme.accent
                        ctx.beginPath()
                        ctx.arc(cx, cy, radius, -Math.PI / 2,
                                -Math.PI / 2 + Math.PI * 2 * arc)
                        ctx.stroke()
                    }
                }
                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()
                Connections {
                    target: widget
                    function onProgressChanged() { ring.requestPaint() }
                    function onPausedChanged() { ring.requestPaint() }
                }
            }

            Column {
                anchors.verticalCenter: parent.verticalCenter
                width: Math.max(0, parent.width - ring.width - parent.spacing)
                spacing: widget.dense ? 0 : 2

                Text {
                    width: parent.width
                    text: widget.timeText
                    color: widget.idle ? AppTheme.textSecondary
                                       : (widget.paused ? AppTheme.textSecondary : AppTheme.accent)
                    font.family: C.monoFont
                    font.pixelSize: Math.min(64, Math.max(15, widget.height * 0.30))
                    font.weight: Font.Light
                    font.letterSpacing: 1
                    elide: Text.ElideRight
                }

                Text {
                    width: parent.width
                    text: widget.stateText
                    color: AppTheme.textTertiary
                    font.pixelSize: Math.min(13, Math.max(9, widget.height * 0.075))
                    font.family: AppTheme.fontFamily
                    font.letterSpacing: 1
                    elide: Text.ElideRight
                }
            }
        }
    }
}
