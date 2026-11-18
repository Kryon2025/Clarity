import QtQuick
import "../../theme"
import ".."

// v24 每日一言组件：一句话 + 来源 + 刷新按钮。
// 数据：App.quoteWidgetText / App.quoteWidgetSource（hitokoto=在线 / builtin=内置）；刷新调 App.refreshWidgetData()。
// 统一接口：props、compact、app。
Item {
    id: widget
    property var props: ({})
    property bool compact: false
    property var app: null

    readonly property var bridge: (app !== null && app !== undefined) ? app
                                   : (typeof App !== "undefined" ? App : null)
    readonly property bool dense: compact || width < 240 || height < 92
    readonly property string quoteText: {
        if (widget.bridge !== null && widget.bridge.quoteWidgetText !== undefined) {
            var text = String(widget.bridge.quoteWidgetText)
            if (text !== "") return text
        }
        if (widget.bridge !== null && widget.bridge.dailyQuote !== undefined) {
            var fallback = String(widget.bridge.dailyQuote)
            if (fallback !== "") return fallback
        }
        return qsTr("把这件事做完，再抬头。")
    }
    readonly property string sourceText: {
        if (widget.bridge === null || widget.bridge.quoteWidgetSource === undefined) return ""
        var source = String(widget.bridge.quoteWidgetSource)
        if (source === "hitokoto") return qsTr("一言 · 在线")
        if (source === "builtin") return qsTr("一言 · 内置")
        return source
    }

    function refreshQuote() {
        if (widget.bridge !== null && typeof widget.bridge.refreshWidgetData === "function")
            widget.bridge.refreshWidgetData()
    }

    WidgetCard {
        anchors.fill: parent
        title: qsTr("每日一言")
        icon: "quote"
        compact: widget.dense

        Item {
            anchors.fill: parent

            Text {
                id: quoteLabel
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.rightMargin: widget.dense ? 0 : 26
                text: "“" + widget.quoteText + "”"
                color: AppTheme.textPrimary
                font.family: AppTheme.fontFamily
                font.pixelSize: Math.min(18, Math.max(10, widget.height * 0.12))
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
                lineHeight: widget.dense ? 0.9 : 1.05
            }

            Text {
                anchors.left: parent.left
                anchors.bottom: parent.bottom
                visible: !widget.dense && widget.sourceText !== ""
                text: widget.sourceText
                color: AppTheme.textTertiary
                font.pixelSize: Math.min(10, Math.max(8, widget.height * 0.065))
                font.family: AppTheme.fontFamily
            }

            // 刷新按钮：玻璃小圆钮
            Item {
                id: refreshButton
                anchors.right: parent.right
                anchors.top: parent.top
                width: widget.dense ? 18 : 24
                height: width
                visible: !widget.dense

                Rectangle {
                    anchors.fill: parent
                    radius: width / 2
                    color: refreshArea.containsMouse ? AppTheme.cardBgAlt : AppTheme.cardOverlay
                    border.width: 1
                    border.color: AppTheme.cardBorder
                }

                Glyph {
                    anchors.centerIn: parent
                    kind: "refresh"
                    size: parent.width * 0.5
                    color: refreshArea.containsMouse ? AppTheme.accent : AppTheme.textSecondary
                }

                MouseArea {
                    id: refreshArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: widget.refreshQuote()
                }
            }
        }
    }
}
