import QtQuick
import "../theme"
import "Constants.js" as C

// v0.16 可复用下拉弹出列表（字体 / AI 服务商 / AI 模型 / 更新下载源共用）
// - 覆盖父页面，贴 anchorItem 下方展开；下方空间不足时自动向上翻转
// - 高度 = min(内容高度, 最大高度, 可用空间)，内容超出时右侧显示细滚动条
// - 打开时禁用外层 Flickable，滚轮只滚列表、不会带动页面
// - 点击空白 / Esc 关闭；点击选项发出 selected(value)
Item {
    id: root
    anchors.fill: parent
    z: 600
    visible: opened
    objectName: "ScrollablePopup"

    property bool opened: false
    property var model: []
    property string valueKey: "value"
    property string labelKey: "label"
    property string currentValue: ""

    property int rowHeight: 32
    property int maxPopupHeight: 260
    property int minPopupHeight: 96
    property int minPopupWidth: 160

    property Item anchorItem: null
    property Item outerFlick: null

    // 可选项：给条目右侧加一个小徽标（如 AI 服务商的「免配置」）
    property string badgeText: ""
    property var badgeWhen: null
    // 模型列表用等宽字体
    property bool mono: false
    // 字体列表预览：每行用该字体自身渲染（CW2 风格），未知字体自动回退
    property bool previewFontFamily: false
    // 列表为空时显示的文案（空字符串则不显示）
    property string emptyText: ""

    property bool flipped: false
    property real popupX: 0
    property real popupY: 0
    property real popupW: 200
    property real popupH: 200
    property bool savedInteractive: true

    signal selected(var value)

    readonly property int itemCount: (root.model === null || root.model === undefined
                                     || root.model.length === undefined) ? 0 : root.model.length
    readonly property real contentHeight: root.itemCount * root.rowHeight + 8

    function itemValue(item) {
        if (item === null || item === undefined) return ""
        if (typeof item === "object" && item[root.valueKey] !== undefined) return String(item[root.valueKey])
        return String(item)
    }
    function itemLabel(item) {
        if (item === null || item === undefined) return ""
        if (typeof item === "object" && item[root.labelKey] !== undefined) return String(item[root.labelKey])
        return String(item)
    }
    function itemBadge(item) {
        if (root.badgeWhen === null || typeof root.badgeWhen !== "function") return false
        try { return root.badgeWhen(item) === true } catch (err) { return false }
    }
    function indexOfValue(value) {
        for (var i = 0; i < root.itemCount; i++)
            if (root.itemValue(root.model[i]) === String(value)) return i
        return -1
    }

    function open() {
        if (root.anchorItem === null) return
        root.opened = true
        root.positionPopup()
        if (root.outerFlick !== null) {
            root.savedInteractive = root.outerFlick.interactive
            root.outerFlick.interactive = false
        }
        root.ensureCurrentVisible()
    }
    function close() {
        if (!root.opened) return
        root.opened = false
        if (root.outerFlick !== null) root.outerFlick.interactive = root.savedInteractive
    }
    function toggle() { root.opened ? root.close() : root.open() }

    function positionPopup() {
        var point = root.anchorItem.mapToItem(root, 0, root.anchorItem.height + 4)
        var desired = Math.min(root.contentHeight, root.maxPopupHeight)
        root.popupW = Math.max(root.minPopupWidth, root.anchorItem.width)
        var spaceBelow = root.height - point.y - 12
        var spaceAbove = point.y - root.anchorItem.height - 12
        root.flipped = false
        if (spaceBelow >= Math.min(desired, root.minPopupHeight) || spaceAbove <= spaceBelow) {
            root.popupH = Math.max(root.minPopupHeight, Math.min(desired, spaceBelow))
            root.popupY = point.y
        } else {
            root.flipped = true
            root.popupH = Math.max(root.minPopupHeight, Math.min(desired, spaceAbove))
            root.popupY = Math.max(8, point.y - root.anchorItem.height - 8 - root.popupH)
        }
        root.popupX = Math.max(8, Math.min(Math.max(8, root.width - root.popupW - 10), point.x))
    }

    function ensureCurrentVisible() {
        if (root.currentValue === "") return
        var index = root.indexOfValue(root.currentValue)
        if (index < 0) return
        var content = listFlick.contentHeight
        var view = listFlick.height
        if (content <= view) return
        var top = index * root.rowHeight
        listFlick.contentY = Math.max(0, Math.min(content - view, top - (view - root.rowHeight) / 2))
    }

    onOpenedChanged: {
        if (!root.opened && root.outerFlick !== null) root.outerFlick.interactive = root.savedInteractive
    }

    Shortcut {
        sequence: "Escape"
        enabled: root.opened
        onActivated: root.close()
    }

    // 点击空白关闭
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        onClicked: root.close()
    }

    // 兜底：滚轮落在弹出层任意位置都不再传给下层页面
    WheelHandler {
        onWheel: (wheel) => { wheel.accepted = true }
    }

    Rectangle {
        id: popup
        x: root.popupX
        y: root.popupY
        width: root.popupW
        height: root.popupH
        radius: 12
        color: AppTheme.cardBg
        border.width: 1
        border.color: AppTheme.cardBorderStrong

        // 吃掉弹层内部点击，避免点到空白关闭
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onClicked: {}
        }

        Item {
            id: listArea
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.margins: 5

            Flickable {
                id: listFlick
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.rightMargin: 9
                contentWidth: width
                contentHeight: root.contentHeight - 8
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                pressDelay: 0
                flickableDirection: Flickable.VerticalFlick

                Column {
                    id: listColumn
                    width: listFlick.width

                    Repeater {
                        model: root.model

                        delegate: Item {
                            width: listColumn.width
                            height: root.rowHeight
                            readonly property bool current: root.itemValue(modelData) === String(root.currentValue)
                            readonly property bool showBadge: root.itemBadge(modelData)
                            function previewableFamily(name) {
                                var lower = String(name).toLowerCase()
                                var iconHints = ["icon", "symbol", "mdl2", "awesome", "material",
                                                 "wingding", "webding", "emoji", "segmdl2"]
                                for (var i = 0; i < iconHints.length; i++) {
                                    if (lower.indexOf(iconHints[i]) >= 0) return false
                                }
                                return true
                            }
                            readonly property string previewFamily: root.previewFontFamily
                                && root.itemValue(modelData) !== ""
                                && previewableFamily(root.itemValue(modelData))
                                ? String(root.itemValue(modelData))
                                : (root.mono ? C.monoFont : AppTheme.fontFamily)

                            Rectangle {
                                anchors.fill: parent
                                anchors.leftMargin: 2
                                anchors.rightMargin: 2
                                anchors.topMargin: 1
                                anchors.bottomMargin: 1
                                radius: 8
                                color: current ? AppTheme.accentSoft
                                                : (rowArea.containsMouse ? AppTheme.buttonBgAlt : "transparent")
                                opacity: current ? 0.24 : 1
                                Behavior on color { ColorAnimation { duration: 90 } }
                            }

                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                width: parent.width - 20 - (showBadge ? 52 : 0)
                                text: root.itemLabel(modelData)
                                color: current ? AppTheme.accent : AppTheme.textSecondary
                                font.pixelSize: AppTheme.fs(root.mono ? 10 : 11)
                                font.family: parent.previewFamily
                                elide: Text.ElideRight
                            }

                            Rectangle {
                                visible: showBadge
                                width: 40
                                height: 15
                                radius: 7
                                anchors.right: parent.right
                                anchors.rightMargin: 8
                                anchors.verticalCenter: parent.verticalCenter
                                color: "#1FA36B"
                                Text {
                                    anchors.centerIn: parent
                                    text: root.badgeText
                                    color: "#FFFFFF"
                                    font.pixelSize: AppTheme.fs(8)
                                    font.family: AppTheme.fontFamily
                                }
                            }

                            MouseArea {
                                id: rowArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    var value = root.itemValue(modelData)
                                    root.close()
                                    root.selected(value)
                                }
                            }
                        }
                    }
                }
            }

            // 右侧细滚动条（自绘，不使用 ScrollBar 原生样式，避免样式警告）
            Item {
                id: scrollTrack
                width: 4
                anchors.right: parent.right
                anchors.rightMargin: 1
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                visible: listFlick.contentHeight > listFlick.height + 1

                Rectangle {
                    id: scrollThumb
                    width: 4
                    radius: 2
                    color: dragArea.pressed ? "#CCFFFFFF" : "#66FFFFFF"
                    height: Math.max(28, scrollTrack.height * listFlick.height
                                     / Math.max(1, listFlick.contentHeight))
                    y: (scrollTrack.height - height) * Math.max(0, Math.min(1,
                        listFlick.contentY / Math.max(1, listFlick.contentHeight - listFlick.height)))
                }

                MouseArea {
                    id: dragArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    property real startY: 0
                    property real startContentY: 0
                    onPressed: (mouse) => {
                        dragArea.startY = mouse.y
                        dragArea.startContentY = listFlick.contentY
                    }
                    onPositionChanged: (mouse) => {
                        if (!dragArea.pressed) return
                        var maxContent = Math.max(0, listFlick.contentHeight - listFlick.height)
                        var delta = (mouse.y - dragArea.startY) * maxContent
                                    / Math.max(1, scrollTrack.height - scrollThumb.height)
                        listFlick.contentY = Math.max(0, Math.min(maxContent, dragArea.startContentY + delta))
                    }
                }
            }
        }

        Text {
            visible: root.itemCount === 0 && root.emptyText !== ""
            anchors.centerIn: parent
            width: parent.width - 24
            horizontalAlignment: Text.AlignHCenter
            text: root.emptyText
            color: AppTheme.textTertiary
            font.pixelSize: AppTheme.fs(11)
            font.family: AppTheme.fontFamily
            wrapMode: Text.WordWrap
        }
    }
}
