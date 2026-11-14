import QtQuick
import "../theme"

// v0.21 AI 聊天记录栏（可复用）
// - 顶部：「聊天记录」标题 + 新建会话按钮
// - 列表：可滚动、当前会话高亮（左侧强调条 + 选中底色）、悬停出现删除按钮
// - 空态：给一句引导文案
// 被 AIPage（左侧分栏）与 AIPanel（浮窗抽屉）共用；数据与动作全部由外层传入/承接。
Item {
    id: list
    objectName: "AIHistoryList"

    property string title: qsTr("聊天记录")
    property string newText: qsTr("新建")
    property var conversations: []
    property string currentConversationId: ""
    property bool animationsEnabled: true
    property int rowHeight: 38

    signal newRequested()
    signal selected(string conversationId)
    signal deleteRequested(string conversationId)

    function itemTitle(item) {
        if (item !== null && item !== undefined && item.title !== undefined
                && String(item.title) !== "")
            return String(item.title)
        return qsTr("新会话")
    }

    function itemCount(item) {
        if (item === null || item === undefined) return ""
        if (item.count === undefined || item.count === null) return ""
        var count = Number(item.count)
        return count > 0 ? qsTr("%1 条").arg(count) : ""
    }

    // 当前会话高亮：优先本地选中的 id；启动时后端当前会话通常是最近更新的一条
    function itemSelected(item, index) {
        if (item === null || item === undefined) return false
        if (list.currentConversationId !== "")
            return String(item.id) === String(list.currentConversationId)
        return index === 0
    }

    Item {
        id: headerRow
        objectName: "AIHistoryHeader"
        width: parent.width
        height: 30

        Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: list.title
            color: AppTheme.textPrimary
            font.pixelSize: AppTheme.fs(13)
            font.weight: Font.DemiBold
            font.family: AppTheme.fontFamily
            font.letterSpacing: 0.5
        }

        Item {
            id: newButton
            objectName: "AIHistoryNewButton"
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: newButtonLabel.implicitWidth + 22
            height: 24

            Rectangle {
                anchors.fill: parent
                radius: 12
                color: newArea.containsMouse ? AppTheme.accentSoft : AppTheme.accent
            }

            Row {
                anchors.centerIn: parent
                spacing: 3

                Glyph {
                    anchors.verticalCenter: parent.verticalCenter
                    kind: "plus"
                    size: 9
                    color: "#FFFFFF"
                }

                Text {
                    id: newButtonLabel
                    anchors.verticalCenter: parent.verticalCenter
                    text: list.newText
                    color: "#FFFFFF"
                    font.pixelSize: AppTheme.fs(10)
                    font.weight: Font.DemiBold
                    font.family: AppTheme.fontFamily
                }
            }

            MouseArea {
                id: newArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: list.newRequested()
            }
        }
    }

    Rectangle {
        id: divider
        anchors.top: headerRow.bottom
        anchors.topMargin: 8
        width: parent.width
        height: 1
        color: AppTheme.divider
    }

    ListView {
        id: conversationList
        objectName: "AIHistoryListView"
        anchors.top: divider.bottom
        anchors.topMargin: 6
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        clip: true
        spacing: 3
        boundsBehavior: Flickable.StopAtBounds
        model: list.conversations

        delegate: Item {
            id: conversationRow
            width: conversationList.width
            height: list.rowHeight

            readonly property bool selected: list.itemSelected(modelData, index)

            Rectangle {
                anchors.fill: parent
                radius: 10
                color: conversationRow.selected
                       ? (AppTheme.glass ? "#26FFFFFF" : AppTheme.cardBgAlt)
                       : (rowArea.containsMouse ? (AppTheme.glass ? "#12FFFFFF" : AppTheme.cardBgAlt)
                                                : "transparent")
                Behavior on color { ColorAnimation { duration: 120 } }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.leftMargin: 2
                anchors.verticalCenter: parent.verticalCenter
                width: 3
                height: Math.min(20, parent.height - 12)
                radius: 1.5
                color: AppTheme.accent
                visible: conversationRow.selected
            }

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 12
                anchors.right: deleteButton.left
                anchors.rightMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                spacing: 1

                Text {
                    width: parent.width
                    text: list.itemTitle(modelData)
                    color: conversationRow.selected ? AppTheme.textPrimary : AppTheme.textSecondary
                    font.pixelSize: AppTheme.fs(11)
                    font.weight: conversationRow.selected ? Font.DemiBold : Font.Normal
                    font.family: AppTheme.fontFamily
                    elide: Text.ElideRight
                    maximumLineCount: 1
                }

                Text {
                    visible: text !== ""
                    width: parent.width
                    text: list.itemCount(modelData)
                    color: AppTheme.textTertiary
                    font.pixelSize: AppTheme.fs(9)
                    font.family: AppTheme.fontFamily
                    elide: Text.ElideRight
                }
            }

            Item {
                id: deleteButton
                objectName: "AIHistoryDeleteButton"
                anchors.right: parent.right
                anchors.rightMargin: 4
                anchors.verticalCenter: parent.verticalCenter
                width: 20
                height: 20
                visible: rowArea.containsMouse || conversationRow.selected

                Rectangle {
                    anchors.fill: parent
                    radius: 10
                    color: deleteArea.containsMouse
                           ? (AppTheme.glass ? "#33FFFFFF" : AppTheme.cardBgAlt) : "transparent"
                }

                Glyph {
                    anchors.centerIn: parent
                    kind: "close"
                    size: 8
                    color: deleteArea.containsMouse ? AppTheme.danger : AppTheme.textTertiary
                }

                MouseArea {
                    id: deleteArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: list.deleteRequested(String(modelData.id))
                }
            }

            MouseArea {
                id: rowArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: list.selected(String(modelData.id))
            }
        }

        // 空态
        Text {
            anchors.top: parent.top
            anchors.topMargin: 10
            anchors.left: parent.left
            anchors.right: parent.right
            visible: conversationList.count === 0
            text: qsTr("还没有会话，点「新建」开始记录")
            color: AppTheme.textTertiary
            font.pixelSize: AppTheme.fs(10)
            font.family: AppTheme.fontFamily
            wrapMode: Text.WordWrap
            lineHeight: 1.3
        }
    }
}
