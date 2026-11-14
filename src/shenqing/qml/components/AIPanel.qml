import QtQuick
import QtQuick.Window
import "../theme"
import "../glass"
import "../components"
import "../components/Constants.js" as C

// v0.9 全局 AI 助手浮层。
// 数据接口：App.aiConfigured / aiEnabled / aiState(idle|loading|ok|error) / aiAnswer / aiError / aiAsk(query)
Window {
    id: panel
    objectName: "AIPanel"
    title: qsTr("深清 · AI 助手")
    property bool animationsEnabled: true
    width: Screen.width
    height: Screen.height
    property bool showing: false
    property bool closing: false
    property string query: ""
    property string localError: ""
    property bool localMissingApi: false

    signal settingsRequested()

    readonly property bool configured: (typeof App !== "undefined")
                                       && (App.aiConfigured !== undefined
                                           ? App.aiConfigured === true
                                           : App.aiEnabled === true)
    readonly property string aiState: (typeof App !== "undefined" && App.aiState !== undefined)
                                      ? String(App.aiState) : (panel.localMissingApi ? "error" : "idle")
    readonly property string aiAnswer: (typeof App !== "undefined" && App.aiAnswer !== undefined)
                                       ? String(App.aiAnswer) : ""
    readonly property string aiError: {
        if (panel.localMissingApi) return panel.localError
        return (typeof App !== "undefined" && App.aiError !== undefined) ? String(App.aiError) : ""
    }

    visibility: (panel.showing || panel.closing) ? Window.FullScreen : Window.Hidden
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: "transparent"

    function showPanel() {
        panel.showing = true
        panel.closing = false
        sceneRoot.opacity = panel.animationsEnabled ? 0 : 1
        panel.show()
        panel.raise()
        panel.requestActivate()
        if (panel.animationsEnabled) enterAnim.restart()
        if (panel.configured) inputField.forceActiveFocus()
    }
    function hide() {
        if (!panel.showing) return
        if (!panel.animationsEnabled) { panel.showing = false; return }
        panel.closing = true
        closeAnim.restart()
    }
    function send() {
        var text = String(panel.query).trim()
        if (text.length === 0) return
        panel.localMissingApi = false
        panel.localError = ""
        if (typeof App !== "undefined" && typeof App.aiAsk === "function") {
            App.aiAsk(text)
        } else {
            panel.localMissingApi = true
            panel.localError = qsTr("缺少 AI 对话接口（App.aiAsk）")
        }
    }
    function copyAnswer() {
        answerHelper.text = panel.aiAnswer
        answerHelper.selectAll()
        answerHelper.copy()
        copiedHint.visible = true
        copyTimer.restart()
    }

    // ---------- v0.21 聊天记录抽屉 ----------
    property bool drawerOpen: false
    property string currentConversationId: ""
    // 截图 / 演示用：非 null 时替代 App.aiConversations
    property var demoConversations: null
    readonly property var conversations: panel.demoConversations !== null ? panel.demoConversations
                                          : ((typeof App !== "undefined" && App.aiConversations !== undefined)
                                             ? App.aiConversations : [])

    function toggleDrawer() {
        panel.drawerOpen = !panel.drawerOpen
    }
    function newConversation() {
        panel.currentConversationId = ""
        if (typeof App !== "undefined" && typeof App.newAIConversation === "function")
            App.newAIConversation()
    }
    function selectConversation(id) {
        panel.currentConversationId = String(id)
        if (typeof App !== "undefined" && typeof App.selectAIConversation === "function")
            App.selectAIConversation(String(id))
    }
    function deleteConversation(id) {
        if (panel.currentConversationId === String(id)) panel.currentConversationId = ""
        if (typeof App !== "undefined" && typeof App.deleteAIConversation === "function")
            App.deleteAIConversation(String(id))
    }

    // ---------- v0.21 AI 动作确认 ----------
    // 后端契约：aiActionPending 为 dict（空闲 {}），aiActionPendingActive 为 bool
    readonly property var aiActionPending: {
        if (typeof App === "undefined") return null
        var pending = App.aiActionPending
        if (pending === undefined || pending === null || pending === false) return null
        if (typeof pending === "object") {
            if (App.aiActionPendingActive !== undefined && App.aiActionPendingActive !== true)
                return null
            for (var key in pending) return pending
            return null
        }
        return pending
    }
    function pendingActionText() {
        var pending = panel.aiActionPending
        if (pending === null) return ""
        if (pending.summary !== undefined && String(pending.summary) !== "") return String(pending.summary)
        if (pending.text !== undefined && String(pending.text) !== "") return String(pending.text)
        var kind = (pending.type !== undefined) ? String(pending.type)
                   : ((pending.kind !== undefined) ? String(pending.kind) : "")
        var target = (pending.target !== undefined) ? String(pending.target)
                     : (pending.spaceName !== undefined ? String(pending.spaceName)
                        : (pending.name !== undefined ? String(pending.name) : ""))
        if (kind === "space" || kind === "openSpace") return qsTr("打开空间「%1」").arg(target)
        if (kind === "setting" || kind === "changeSetting") {
            if (pending.value !== undefined) return qsTr("修改设置：%1 %2").arg(target).arg(String(pending.value))
            return qsTr("修改设置：%1").arg(target)
        }
        return (pending.title !== undefined && String(pending.title) !== "") ? String(pending.title)
                                                                             : qsTr("执行一个动作")
    }
    function pendingActionConfirmLabel() {
        var pending = panel.aiActionPending
        if (pending !== null && pending.confirmLabel !== undefined
                && String(pending.confirmLabel) !== "")
            return String(pending.confirmLabel)
        return qsTr("确认执行")
    }
    function pendingActionDetail() {
        var pending = panel.aiActionPending
        if (pending === null) return ""
        var title = (pending.title !== undefined) ? String(pending.title) : ""
        var text = panel.pendingActionText()
        if (title !== "" && title !== text) return title
        if (pending.detail !== undefined && String(pending.detail) !== "") return String(pending.detail)
        return ""
    }
    function confirmAIAction() {
        var pending = panel.aiActionPending
        if (pending === null) return
        if (typeof App !== "undefined" && typeof App.aiConfirmAction === "function") {
            try {
                App.aiConfirmAction()
            } catch (err) {
                // 接口异常时静默：后端会以自己的方式回报
            }
        }
    }
    function cancelAIAction() {
        var pending = panel.aiActionPending
        if (pending === null) return
        if (typeof App !== "undefined" && typeof App.aiCancelAction === "function") {
            try {
                App.aiCancelAction()
            } catch (err) {
                // 取消不改变任何状态
            }
        }
    }

    Shortcut { sequence: "Escape"; onActivated: panel.hide() }

    Timer {
        id: copyTimer
        interval: 1600
        onTriggered: copiedHint.visible = false
    }
    ParallelAnimation {
        id: enterAnim
        NumberAnimation { target: sceneRoot; property: "opacity"; from: 0; to: 1; duration: 180; easing.type: Easing.OutCubic }
    }
    ParallelAnimation {
        id: closeAnim
        NumberAnimation { target: sceneRoot; property: "opacity"; to: 0; duration: 180; easing.type: Easing.OutCubic }
        onFinished: { panel.closing = false; panel.showing = false }
    }

    Item {
        id: sceneRoot
        anchors.fill: parent

        Rectangle { anchors.fill: parent; color: AppTheme.scrimMedium }
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onClicked: panel.hide()
        }

        Rectangle {
            id: dialog
            width: Math.min(760, panel.width * 0.56)
            height: Math.min(600, panel.height * 0.76)
            anchors.centerIn: parent
            radius: 24
            color: AppTheme.glass ? AppTheme.dialogBg : AppTheme.cardBg
            border.width: 1
            border.color: AppTheme.glass ? "#4DFFFFFF" : AppTheme.cardBorderStrong
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: {} }

            // 标题
            Row {
                id: titleRow
                x: 24
                y: 20
                width: parent.width - 48
                spacing: 10
                Rectangle {
                    width: 30; height: 30; radius: 15
                    anchors.verticalCenter: parent.verticalCenter
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: AppTheme.gradA }
                        GradientStop { position: 1.0; color: AppTheme.gradC }
                    }
                    Glyph { anchors.centerIn: parent; kind: "sparkle"; size: 16; color: AppTheme.onAccent }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: qsTr("AI 助手")
                    color: AppTheme.textPrimary
                    font.pixelSize: AppTheme.fs(17)
                    font.weight: Font.DemiBold
                    font.family: AppTheme.fontFamily
                }
            }

            // v0.21：「聊天记录」抽屉开关
            Item {
                id: drawerToggle
                objectName: "AIHistoryToggle"
                anchors.right: closeButton.left
                anchors.rightMargin: 8
                anchors.top: parent.top
                anchors.topMargin: 20
                width: drawerToggleLabel.implicitWidth + 32
                height: 26

                Rectangle {
                    anchors.fill: parent
                    radius: 13
                    color: drawerToggleArea.containsMouse
                           ? (AppTheme.glass ? "#26FFFFFF" : AppTheme.cardBgAlt)
                           : (AppTheme.glass ? "#14FFFFFF" : AppTheme.buttonBg)
                    border.width: 1
                    border.color: panel.drawerOpen ? AppTheme.accent : AppTheme.cardBorder
                }

                Row {
                    anchors.centerIn: parent
                    spacing: 4

                    Glyph {
                        anchors.verticalCenter: parent.verticalCenter
                        kind: panel.drawerOpen ? "chevronLeft" : "chevron"
                        size: 8
                        color: panel.drawerOpen ? AppTheme.accent : AppTheme.textSecondary
                    }

                    Text {
                        id: drawerToggleLabel
                        anchors.verticalCenter: parent.verticalCenter
                        text: qsTr("聊天记录")
                        color: panel.drawerOpen ? AppTheme.accent : AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(10)
                        font.family: AppTheme.fontFamily
                    }
                }

                MouseArea {
                    id: drawerToggleArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: panel.toggleDrawer()
                }
            }

            Item {
                id: closeButton
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.rightMargin: 16
                anchors.topMargin: 16
                width: 30; height: 30
                Rectangle {
                    anchors.fill: parent
                    radius: 15
                    color: closeArea.containsMouse ? "#33FFFFFF" : "transparent"
                }
                Glyph { anchors.centerIn: parent; kind: "close"; size: 12; color: AppTheme.textTertiary }
                MouseArea {
                    id: closeArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: panel.hide()
                }
            }

            Rectangle { x: 24; y: 58; width: parent.width - 48; height: 1; color: AppTheme.divider }

            // 未配置
            Column {
                visible: !panel.configured
                anchors.centerIn: parent
                width: parent.width - 80
                spacing: 16
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr("还没有配置 AI 助手")
                    color: AppTheme.textPrimary
                    font.pixelSize: AppTheme.fs(20)
                    font.weight: Font.DemiBold
                    font.family: AppTheme.fontFamily
                }
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr("请在设置 → AI 助手中配置服务商与 API Key。")
                    color: AppTheme.textSecondary
                    font.pixelSize: AppTheme.fs(13)
                    font.family: AppTheme.fontFamily
                    wrapMode: Text.WordWrap
                }
                GlassButton {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: qsTr("打开 AI 设置")
                    tone: "light"
                    fontSize: 13
                    padH: 22
                    minHeight: 38
                    onClicked: { panel.hide(); panel.settingsRequested() }
                }
            }

            // 会话区
            Item {
                visible: panel.configured
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                anchors.topMargin: 74
                anchors.bottom: inputRow.top
                anchors.bottomMargin: 14

                Flickable {
                    id: answerFlick
                    anchors.fill: parent
                    contentWidth: width
                    contentHeight: answerColumn.height
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds

                    Column {
                        id: answerColumn
                        width: answerFlick.width
                        spacing: 12

                        Text {
                            visible: panel.aiState === "idle"
                            width: parent.width
                            text: qsTr("把问题交给深清：可以问专注方法、帮你整理思路，或随便聊聊。")
                            color: AppTheme.textSecondary
                            font.pixelSize: AppTheme.fs(13)
                            font.family: AppTheme.fontFamily
                            wrapMode: Text.WordWrap
                        }

                        Row {
                            visible: panel.aiState === "loading"
                            spacing: 10
                            Item {
                                width: 18; height: 18
                                anchors.verticalCenter: parent.verticalCenter
                                Rectangle {
                                    width: 18; height: 18; radius: 9
                                    color: "transparent"
                                    border.width: 2
                                    border.color: AppTheme.accent
                                    opacity: 0.35
                                }
                                Rectangle {
                                    width: 18; height: 18; radius: 9
                                    color: "transparent"
                                    border.width: 2
                                    border.color: AppTheme.accent
                                    rotation: 45
                                    Behavior on rotation { NumberAnimation { duration: 1 } }
                                }
                                RotationAnimation on rotation {
                                    running: panel.aiState === "loading"
                                    from: 0; to: 360; duration: 900; loops: Animation.Infinite
                                }
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: qsTr("思考中…")
                                color: AppTheme.textSecondary
                                font.pixelSize: AppTheme.fs(13)
                                font.family: AppTheme.fontFamily
                            }
                        }

                        TextEdit {
                            id: answerText
                            visible: panel.aiState === "ok"
                            width: parent.width
                            text: panel.aiAnswer
                            readOnly: true
                            textFormat: TextEdit.PlainText
                            wrapMode: TextEdit.Wrap
                            color: AppTheme.textPrimary
                            selectionColor: AppTheme.accentSoft
                            selectedTextColor: "#FFFFFF"
                            font.pixelSize: AppTheme.fs(14)
                            font.family: AppTheme.fontFamily
                            selectByMouse: true
                        }

                        Text {
                            visible: panel.aiState === "error"
                            width: parent.width
                            text: panel.aiError !== "" ? panel.aiError : qsTr("AI 请求失败")
                            color: AppTheme.danger
                            font.pixelSize: AppTheme.fs(13)
                            font.family: AppTheme.fontFamily
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }

            // v0.21 聊天记录抽屉（从左侧滑出；标题「聊天记录」+ 新建 + 列表可滚动 + 当前项高亮 + 可删除）
            Item {
                id: historyDrawer
                objectName: "AIHistoryDrawer"
                width: Math.min(236, dialog.width - 120)
                anchors.top: parent.top
                anchors.topMargin: 66
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 82
                x: panel.drawerOpen ? 12 : -(width + 18)
                visible: panel.drawerOpen || x > -(width + 2)
                z: 20

                Behavior on x {
                    enabled: panel.animationsEnabled
                    NumberAnimation { duration: 200; easing.type: Easing.OutCubic }
                }

                Rectangle {
                    anchors.fill: parent
                    radius: 16
                    color: AppTheme.glass ? AppTheme.dialogBg : AppTheme.cardBg
                    border.width: 1
                    border.color: AppTheme.glass ? "#4DFFFFFF" : AppTheme.cardBorderStrong
                }

                // 吃掉抽屉内点击，避免关掉浮窗
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.AllButtons
                    onClicked: {}
                }

                Item {
                    anchors.fill: parent
                    anchors.margins: 12

                    AIHistoryList {
                        id: historyList
                        objectName: "AIHistoryList"
                        anchors.fill: parent
                        animationsEnabled: panel.animationsEnabled
                        conversations: panel.conversations
                        currentConversationId: panel.currentConversationId
                        title: qsTr("聊天记录")
                        newText: qsTr("新建")
                        onNewRequested: panel.newConversation()
                        onSelected: (conversationId) => panel.selectConversation(conversationId)
                        onDeleteRequested: (conversationId) => panel.deleteConversation(conversationId)
                    }
                }
            }

            // 输入区
            Item {
                id: inputRow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                anchors.bottomMargin: 20
                height: 46
                visible: panel.configured

                Rectangle {
                    anchors.fill: parent
                    radius: 14
                    color: AppTheme.glass ? "#1AFFFFFF" : AppTheme.cardBgAlt
                    border.width: 1
                    border.color: inputField.activeFocus ? AppTheme.accent : AppTheme.cardBorder
                }

                TextInput {
                    id: inputField
                    anchors.left: parent.left
                    anchors.right: sendButton.left
                    anchors.leftMargin: 16
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    height: parent.height
                    verticalAlignment: TextInput.AlignVCenter
                    color: AppTheme.textPrimary
                    selectionColor: AppTheme.accentSoft
                    selectedTextColor: "#FFFFFF"
                    font.pixelSize: AppTheme.fs(13)
                    font.family: AppTheme.fontFamily
                    text: panel.query
                    onTextChanged: panel.query = text
                    enabled: panel.aiState !== "loading"
                    onAccepted: panel.send()
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        visible: inputField.text.length === 0
                        text: qsTr("问点什么…（Enter 发送）")
                        color: AppTheme.textTertiary
                        font.pixelSize: AppTheme.fs(13)
                        font.family: AppTheme.fontFamily
                    }
                }

                Item {
                    id: sendButton
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    width: 76; height: 32
                    Rectangle {
                        anchors.fill: parent
                        radius: 16
                        color: sendArea.containsMouse ? AppTheme.accentSoft : AppTheme.accent
                    }
                    Text {
                        anchors.centerIn: parent
                        text: qsTr("发送")
                        color: "#FFFFFF"
                        font.pixelSize: AppTheme.fs(12)
                        font.weight: Font.DemiBold
                        font.family: AppTheme.fontFamily
                    }
                    MouseArea {
                        id: sendArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        enabled: panel.aiState !== "loading"
                        onClicked: panel.send()
                    }
                }
            }

            // 复制全文（有答案时）
            Item {
                visible: panel.configured && panel.aiState === "ok"
                anchors.right: parent.right
                anchors.rightMargin: 24
                anchors.bottom: inputRow.top
                anchors.bottomMargin: 4
                width: 88; height: 26
                Text {
                    anchors.centerIn: parent
                    text: copiedHint.visible ? qsTr("已复制") : qsTr("复制全文")
                    color: copyArea.containsMouse ? AppTheme.accent : AppTheme.textTertiary
                    font.pixelSize: AppTheme.fs(11)
                    font.family: AppTheme.fontFamily
                }
                MouseArea {
                    id: copyArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: panel.copyAnswer()
                }
            }
        }

        // ---------- v0.21 AI 动作确认卡（后端 App.aiActionPending 存在时弹出） ----------
        AIActionConfirmCard {
            id: aiActionCard
            objectName: "AIPanelActionConfirm"
            anchors.fill: parent
            animationsEnabled: panel.animationsEnabled
            opened: panel.aiActionPending !== null
            actionText: panel.pendingActionText()
            detail: panel.pendingActionDetail()
            confirmText: panel.pendingActionConfirmLabel()
            onConfirmed: panel.confirmAIAction()
            onCancelled: panel.cancelAIAction()
        }
    }

    TextEdit {
        id: answerHelper
        visible: false
        width: 1
        height: 1
    }
    Text {
        id: copiedHint
        visible: false
        text: ""
    }
}
