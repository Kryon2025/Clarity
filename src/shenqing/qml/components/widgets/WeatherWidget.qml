import QtQuick
import "../../theme"
import ".."

// v24 天气组件：城市 / 温度 / 天气 / 更新时间。
// 数据：App.weatherWidgetData（dict：temp / tempValue / weather / city / updated）、
//       App.weatherWidgetError（失败文案）；刷新调 App.refreshWidgetData()。
// 统一接口：props（cityId / showCity）、compact、app。
Item {
    id: widget
    property var props: ({})
    property bool compact: false
    property var app: null

    readonly property var bridge: (app !== null && app !== undefined) ? app
                                   : (typeof App !== "undefined" ? App : null)
    readonly property bool dense: compact || width < 220 || height < 96
    readonly property bool showCity: !(props && props.showCity === false)
    readonly property var weatherData: (widget.bridge !== null
                                        && widget.bridge.weatherWidgetData !== undefined
                                        && widget.bridge.weatherWidgetData !== null)
                                       ? widget.bridge.weatherWidgetData : ({})
    readonly property string errorText: (widget.bridge !== null
                                         && widget.bridge.weatherWidgetError !== undefined)
                                        ? String(widget.bridge.weatherWidgetError) : ""
    readonly property string cityText: (widget.weatherData.city !== undefined && String(widget.weatherData.city) !== "")
                                       ? String(widget.weatherData.city) : qsTr("未设置城市")
    readonly property string tempText: (widget.weatherData.temp !== undefined && String(widget.weatherData.temp) !== "")
                                       ? String(widget.weatherData.temp)
                                       : ((widget.weatherData.tempValue !== undefined
                                           && isFinite(Number(widget.weatherData.tempValue)))
                                          ? qsTr("%1°").arg(Math.round(Number(widget.weatherData.tempValue)))
                                          : "--°")
    readonly property string weatherText: {
        if (widget.weatherData.weather !== undefined && String(widget.weatherData.weather) !== "")
            return String(widget.weatherData.weather)
        if (widget.weatherData.text !== undefined && String(widget.weatherData.text) !== "")
            return String(widget.weatherData.text)
        return qsTr("暂无天气")
    }
    readonly property string updatedText: (widget.weatherData.updated !== undefined
                                           && String(widget.weatherData.updated) !== "")
                                          ? String(widget.weatherData.updated) : ""
    readonly property bool hasData: widget.weatherData.city !== undefined || widget.weatherData.temp !== undefined
                                    || widget.weatherData.weather !== undefined
    readonly property bool failed: widget.errorText !== ""

    function refreshWeather() {
        if (widget.bridge !== null && typeof widget.bridge.refreshWidgetData === "function")
            widget.bridge.refreshWidgetData()
    }

    WidgetCard {
        anchors.fill: parent
        title: qsTr("天气")
        icon: "cloud"
        compact: widget.dense

        Item {
            anchors.fill: parent

            // 失败：错误文案 + 重试
            Column {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                visible: widget.failed && !widget.hasData
                spacing: 2

                Text {
                    width: parent.width
                    text: widget.errorText
                    color: AppTheme.danger
                    font.pixelSize: Math.min(12, Math.max(9, widget.height * 0.085))
                    font.family: AppTheme.fontFamily
                    wrapMode: Text.WordWrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    text: qsTr("点击右上角刷新")
                    color: AppTheme.textTertiary
                    font.pixelSize: Math.min(11, Math.max(8, widget.height * 0.07))
                    font.family: AppTheme.fontFamily
                    elide: Text.ElideRight
                }
            }

            // 正常：温度 + 天气 + 城市/更新时间
            Row {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                visible: !(widget.failed && !widget.hasData)
                spacing: widget.dense ? 8 : 14

                Text {
                    id: tempLabel
                    anchors.verticalCenter: parent.verticalCenter
                    text: widget.tempText
                    color: AppTheme.textPrimary
                    font.family: AppTheme.fontFamily
                    font.pixelSize: Math.min(46, Math.max(15, widget.height * 0.34))
                    font.weight: Font.Light
                }

                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.max(0, parent.width - tempLabel.implicitWidth
                                       - (widget.dense ? 8 : 14))
                    spacing: widget.dense ? 0 : 2

                    Text {
                        width: parent.width
                        text: widget.weatherText
                        color: AppTheme.textPrimary
                        font.pixelSize: Math.min(15, Math.max(10, widget.height * 0.10))
                        font.family: AppTheme.fontFamily
                        elide: Text.ElideRight
                    }

                    Text {
                        width: parent.width
                        text: widget.showCity
                              ? (widget.updatedText !== ""
                                 ? qsTr("%1 · %2 更新").arg(widget.cityText).arg(widget.updatedText)
                                 : widget.cityText)
                              : (widget.updatedText !== "" ? qsTr("%1 更新").arg(widget.updatedText) : "")
                        color: AppTheme.textTertiary
                        font.pixelSize: Math.min(11, Math.max(8, widget.height * 0.07))
                        font.family: AppTheme.fontFamily
                        elide: Text.ElideRight
                    }
                }
            }

            // 刷新按钮
            Item {
                anchors.right: parent.right
                anchors.top: parent.top
                width: widget.dense ? 18 : 24
                height: width
                visible: !widget.dense

                Rectangle {
                    anchors.fill: parent
                    radius: width / 2
                    color: weatherRefresh.containsMouse ? AppTheme.cardBgAlt : AppTheme.cardOverlay
                    border.width: 1
                    border.color: AppTheme.cardBorder
                }
                Glyph {
                    anchors.centerIn: parent
                    kind: "refresh"
                    size: parent.width * 0.5
                    color: weatherRefresh.containsMouse ? AppTheme.accent : AppTheme.textSecondary
                }
                MouseArea {
                    id: weatherRefresh
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: widget.refreshWeather()
                }
            }
        }
    }
}
