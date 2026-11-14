import QtQuick
import QtQuick.Window
import "../theme"
import "Constants.js" as C

// v0.16 清番：无边框置顶小窗（约 300×380）
// - 圆环倒计时 + 工作/休息阶段 + 开始/暂停/继续/停止/跳过 + 轮次
// - 可拖动（startSystemMove，失败时退回手动拖拽）、可随时关闭
// - 优先绑定后端 pomodoro 接口；接口缺失时用本地计时器兜底，界面照常可用
//   期望接口：App.pomodoroState("idle"/"work"/"break"/"paused")、App.pomodoroRemaining、
//   App.pomodoroTotal、App.pomodoroRound、App.pomodoroRounds、App.pomodoroWorkMinutes、
//   App.pomodoroBreakMinutes；App.startPomodoro() / pausePomodoro() / resumePomodoro() /
//   stopPomodoro() / skipPomodoro()；notify：pomodoroChanged
Window {
    id: panel
    objectName: "PomodoroPanel"
    title: qsTr("深清 · 清番")
    width: 300
    height: 380
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
    color: "transparent"
    visible: false

    property bool animationsEnabled: true

    // ---------- 后端可用性 / 本地兜底状态 ----------
    // 后端（services/pomodoro.py + AppBridge）命名：pomodoroPhase / pomodoroPaused /
    // pomodoroRemaining / pomodoroPresetTotal / pomodoroRound / pomodoroWorkMinutes /
    // pomodoroBreakMinutes / pomodoroLongBreakMinutes / pomodoroRoundsBeforeLong
    readonly property bool backendReady: (typeof App !== "undefined" && App.pomodoroPhase !== undefined)
    readonly property string backendPhase: panel.backendReady ? String(App.pomodoroPhase) : ""
    readonly property bool backendPaused: panel.backendReady && App.pomodoroPaused === true

    property string localPhase: "work"        // work | break
    property bool localRunning: false
    property bool localStarted: false
    property int localRemaining: 0
    property int localCompleted: 0            // 已完成的工作轮数

    readonly property int workSeconds: (typeof App !== "undefined" && App.pomodoroWorkMinutes !== undefined)
                                       ? Math.max(1, Math.round(Number(App.pomodoroWorkMinutes))) * 60 : 25 * 60
    readonly property int breakSeconds: (typeof App !== "undefined" && App.pomodoroBreakMinutes !== undefined)
                                        ? Math.max(1, Math.round(Number(App.pomodoroBreakMinutes))) * 60 : 5 * 60
    readonly property int longBreakSeconds: (typeof App !== "undefined" && App.pomodoroLongBreakMinutes !== undefined)
                                            ? Math.max(1, Math.round(Number(App.pomodoroLongBreakMinutes))) * 60 : 15 * 60
    readonly property int roundsPerCycle: (typeof App !== "undefined" && App.pomodoroRoundsBeforeLong !== undefined)
                                          ? Math.max(1, Math.round(Number(App.pomodoroRoundsBeforeLong))) : 4

    readonly property string stateValue: !panel.backendReady ? panel.localStateValue
                                         : (panel.backendPhase === "idle" ? "idle"
                                            : (panel.backendPaused ? "paused" : panel.backendPhase))
    readonly property string localStateValue: !panel.localStarted ? "idle"
                                             : (!panel.localRunning ? "paused" : panel.localPhase)
    readonly property bool running: panel.stateValue === "work" || panel.stateValue === "break"
    readonly property bool paused: panel.stateValue === "paused"
    readonly property bool idle: panel.stateValue === "idle"
    readonly property string phaseKey: panel.backendReady
                                       ? (panel.backendPhase === "idle" ? "work" : panel.backendPhase)
                                       : panel.localPhase
    readonly property bool longBreak: panel.phaseKey === "break" && panel.totalSeconds >= panel.longBreakSeconds

    readonly property int totalSeconds: {
        if (panel.backendReady) {
            var total = Number(App.pomodoroPresetTotal)
            if (isFinite(total) && total > 0) return Math.round(total)
        }
        return panel.phaseKey === "break" ? panel.breakSeconds : panel.workSeconds
    }
    readonly property int remainingSeconds: {
        if (panel.backendReady) {
            if (panel.backendPhase === "idle") return panel.workSeconds
            var remain = Number(App.pomodoroRemaining)
            if (isFinite(remain) && remain >= 0) return Math.round(remain)
        }
        if (panel.localStarted) return panel.localRemaining
        return panel.localPhase === "break" ? panel.breakSeconds : panel.workSeconds
    }
    readonly property int completedRounds: {
        if (panel.backendReady) {
            var done = Number(App.pomodoroRound)
            if (isFinite(done) && done > 0) return Math.round(done) - 1
        }
        return panel.localCompleted
    }
    readonly property int currentRound: Math.min(panel.roundsPerCycle, panel.completedRounds + 1)
    readonly property real progress: {
        var total = panel.totalSeconds
        if (total <= 0 || panel.idle) return 0
        return Math.max(0, Math.min(1, (total - panel.remainingSeconds) / total))
    }
    readonly property string timeText: {
        var value = Math.max(0, panel.remainingSeconds)
        var minutes = Math.floor(value / 60)
        var seconds = value % 60
        return (minutes < 10 ? "0" + minutes : String(minutes)) + ":" + (seconds < 10 ? "0" + seconds : String(seconds))
    }
    readonly property string phaseText: panel.phaseKey === "break"
                                        ? (panel.longBreak ? qsTr("长休息") : qsTr("休息"))
                                        : qsTr("工作")
    readonly property string primaryText: panel.running ? qsTr("暂停")
                                          : (panel.paused ? qsTr("继续") : qsTr("开始"))

    // ---------- 本地计时器（后端缺失时使用） ----------
    Timer {
        id: localTimer
        interval: 1000
        repeat: true
        running: !panel.backendReady && panel.localRunning && panel.visible
        onTriggered: panel.tickLocal()
    }

    function tickLocal() {
        if (panel.localRemaining > 1) {
            panel.localRemaining -= 1
            return
        }
        if (panel.localPhase === "work") {
            panel.localCompleted += 1
            panel.localPhase = "break"
            panel.localRemaining = panel.breakSeconds
        } else {
            panel.localPhase = "work"
            panel.localRemaining = panel.workSeconds
        }
    }

    function localReset() {
        panel.localRunning = false
        panel.localStarted = false
        panel.localPhase = "work"
        panel.localRemaining = panel.workSeconds
        panel.localCompleted = 0
        panel.lastPhase = "work"
    }

    // ---------- 操作（后端优先，本地兜底） ----------
    function startOrResume() {
        if (panel.backendReady) {
            if (panel.paused) {
                if (typeof App.resumePomodoro === "function") App.resumePomodoro()
                return
            }
            if (!panel.running && typeof App.startPomodoro === "function") App.startPomodoro()
            return
        }
        if (panel.localStarted && !panel.localRunning) {
            if (panel.localRemaining <= 0)
                panel.localRemaining = panel.localPhase === "break" ? panel.breakSeconds : panel.workSeconds
            panel.localRunning = true
            return
        }
        panel.localPhase = "work"
        panel.localRemaining = panel.workSeconds
        panel.localCompleted = 0
        panel.localStarted = true
        panel.localRunning = true
        panel.lastPhase = "work"
    }
    function pause() {
        if (panel.backendReady) {
            if (typeof App.pausePomodoro === "function") App.pausePomodoro()
            return
        }
        panel.localRunning = false
    }
    function stop() {
        if (panel.backendReady) {
            if (typeof App.stopPomodoro === "function") App.stopPomodoro()
            return
        }
        panel.localReset()
    }
    function skip() {
        if (panel.backendReady) {
            if (typeof App.skipPomodoro === "function") App.skipPomodoro()
            return
        }
        if (!panel.localStarted) return
        if (panel.localPhase === "work") {
            panel.localCompleted += 1
            panel.localPhase = "break"
            panel.localRemaining = panel.breakSeconds
        } else {
            panel.localPhase = "work"
            panel.localRemaining = panel.workSeconds
        }
        panel.lastPhase = panel.localPhase
        panel.localRunning = true
    }
    function primaryAction() { panel.running ? panel.pause() : panel.startOrResume() }

    // ---------- 显示 / 关闭 ----------
    function openPanel() {
        if (panel.visible) {
            panel.raise()
            panel.requestActivate()
            return
        }
        if (panel.x <= 0 || panel.y <= 0) {
            panel.x = Math.max(24, Math.round(Screen.width - panel.width - 56))
            panel.y = Math.max(24, Math.round((Screen.height - panel.height) / 2))
        }
        if (!panel.localStarted && !panel.backendReady) panel.localRemaining = panel.workSeconds
        panelRoot.opacity = 0
        panel.visible = true
        if (panel.animationsEnabled) openAnim.restart()
        else panelRoot.opacity = 1
        panel.raise()
        panel.requestActivate()
    }
    function closePanel() {
        if (!panel.visible) return
        if (!panel.animationsEnabled) {
            panel.visible = false
            return
        }
        closeAnim.restart()
    }

    ParallelAnimation {
        id: openAnim
        NumberAnimation { target: panelRoot; property: "opacity"; from: 0; to: 1
                          duration: panel.animationsEnabled ? 160 : 0; easing.type: Easing.OutCubic }
        NumberAnimation { target: panelRoot; property: "scale"; from: 0.97; to: 1
                          duration: panel.animationsEnabled ? 160 : 0; easing.type: Easing.OutCubic }
    }
    ParallelAnimation {
        id: closeAnim
        NumberAnimation { target: panelRoot; property: "opacity"; to: 0
                          duration: panel.animationsEnabled ? 120 : 0; easing.type: Easing.OutCubic }
        onFinished: panel.visible = false
    }

    onVisibleChanged: if (panel.visible) {
        AppTheme.mode = (typeof App !== "undefined" && App.themeMode) ? String(App.themeMode) : "solid"
    }

    Shortcut {
        sequence: "Escape"
        onActivated: panel.closePanel()
    }

    Item {
        id: panelRoot
        objectName: "PomodoroRoot"
        anchors.fill: parent
        opacity: 1

        // 背景
        Rectangle {
            anchors.fill: parent
            radius: 20
            gradient: Gradient {
                GradientStop { position: 0.0; color: AppTheme.bgMid }
                GradientStop { position: 0.55; color: AppTheme.bgTop }
                GradientStop { position: 1.0; color: AppTheme.bgBottom }
            }
        }
        Rectangle {
            anchors.fill: parent
            radius: 20
            color: "transparent"
            border.width: 1
            border.color: AppTheme.glass ? "#4DFFFFFF" : AppTheme.cardBorderStrong
        }

        // ---------- 顶部拖动条 ----------
        Item {
            id: header
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 42

            MouseArea {
                id: dragArea
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                cursorShape: Qt.SizeAllCursor
                property bool fallbackDrag: false
                property point pressPoint: Qt.point(0, 0)
                property point winPoint: Qt.point(0, 0)
                onPressed: (mouse) => {
                    dragArea.pressPoint = Qt.point(mouse.x, mouse.y)
                    dragArea.winPoint = Qt.point(panel.x, panel.y)
                    dragArea.fallbackDrag = (typeof panel.startSystemMove !== "function")
                    if (!dragArea.fallbackDrag) panel.startSystemMove()
                }
                onPositionChanged: (mouse) => {
                    if (!dragArea.pressed || !dragArea.fallbackDrag) return
                    panel.x = Math.round(dragArea.winPoint.x + mouse.x - dragArea.pressPoint.x)
                    panel.y = Math.round(dragArea.winPoint.y + mouse.y - dragArea.pressPoint.y)
                }
            }

            Row {
                anchors.left: parent.left
                anchors.leftMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                Rectangle {
                    width: 24
                    height: 24
                    radius: 8
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: AppTheme.gradA }
                        GradientStop { position: 1.0; color: AppTheme.gradC }
                    }
                    Glyph { anchors.centerIn: parent; kind: "clock"; size: 14; color: AppTheme.onAccent }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: qsTr("清番")
                    color: AppTheme.textPrimary
                    font.pixelSize: AppTheme.fs(15)
                    font.weight: Font.DemiBold
                    font.family: AppTheme.fontFamily
                    font.letterSpacing: 1
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: qsTr("置顶番茄钟")
                    color: AppTheme.textTertiary
                    font.pixelSize: AppTheme.fs(10)
                    font.family: AppTheme.fontFamily
                }
            }

            Item {
                id: closeButton
                objectName: "PomodoroClose"
                width: 28
                height: 28
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                Rectangle {
                    anchors.fill: parent
                    radius: 14
                    color: closeArea.containsMouse ? AppTheme.buttonBgAlt : "transparent"
                }
                Glyph {
                    anchors.centerIn: parent
                    kind: "close"
                    size: 13
                    color: closeArea.containsMouse ? AppTheme.textPrimary : AppTheme.textTertiary
                }
                MouseArea {
                    id: closeArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: panel.closePanel()
                }
            }
        }

        // ---------- 圆环倒计时 ----------
        Item {
            id: ringBox
            objectName: "PomodoroRing"
            anchors.horizontalCenter: parent.horizontalCenter
            y: 52
            width: 176
            height: 176

            Canvas {
                id: ringCanvas
                anchors.fill: parent
                property real progressValue: panel.progress
                property bool runningValue: panel.running
                property string phaseValue: panel.phaseKey
                onProgressValueChanged: requestPaint()
                onRunningValueChanged: requestPaint()
                onPhaseValueChanged: requestPaint()
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()
                    var size = Math.min(width, height)
                    var center = size / 2
                    var radius = center - 12
                    var lineWidth = 9
                    ctx.lineCap = "round"

                    // 底环
                    ctx.beginPath()
                    ctx.arc(center, center, radius, 0, Math.PI * 2)
                    ctx.strokeStyle = AppTheme.glass ? "#22FFFFFF" : AppTheme.divider
                    ctx.lineWidth = lineWidth
                    ctx.stroke()

                    // 进度环
                    var span = Math.max(0.0001, ringCanvas.progressValue) * Math.PI * 2
                    if (ringCanvas.progressValue > 0.0005) {
                        ctx.beginPath()
                        ctx.arc(center, center, radius, -Math.PI / 2, -Math.PI / 2 + span)
                        ctx.strokeStyle = ringCanvas.phaseValue === "break" ? C.accent : AppTheme.accent
                        ctx.lineWidth = lineWidth
                        ctx.stroke()

                        // 端点小球
                        var angle = -Math.PI / 2 + span
                        var x = center + Math.cos(angle) * radius
                        var y = center + Math.sin(angle) * radius
                        ctx.beginPath()
                        ctx.arc(x, y, lineWidth / 2 + 1.2, 0, Math.PI * 2)
                        ctx.fillStyle = "#FFFFFF"
                        ctx.fill()
                    }
                }
            }

            Column {
                anchors.centerIn: parent
                spacing: 2
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: panel.timeText
                    color: panel.running && panel.phaseKey === "break" ? C.accent : AppTheme.textPrimary
                    font.family: C.monoFont
                    font.pixelSize: AppTheme.fs(38)
                    font.weight: Font.Light
                    font.letterSpacing: 1
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: panel.idle ? qsTr("准备开始") : panel.phaseText
                    color: panel.phaseKey === "break" ? C.accent : AppTheme.textSecondary
                    font.pixelSize: AppTheme.fs(12)
                    font.family: AppTheme.fontFamily
                    font.letterSpacing: 1
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: qsTr("第 %1 / %2 轮").arg(panel.idle ? 1 : panel.currentRound).arg(panel.roundsPerCycle)
                    color: AppTheme.textTertiary
                    font.pixelSize: AppTheme.fs(10)
                    font.family: AppTheme.fontFamily
                }
            }
        }

        // ---------- 阶段说明 ----------
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            y: ringBox.y + ringBox.height + 2
            text: qsTr("工作 %1 · 休息 %2 · 长休息 %3 分钟")
                  .arg(Math.round(panel.workSeconds / 60))
                  .arg(Math.round(panel.breakSeconds / 60))
                  .arg(Math.round(panel.longBreakSeconds / 60))
            color: AppTheme.textTertiary
            font.pixelSize: AppTheme.fs(10)
            font.family: AppTheme.fontFamily
        }

        // ---------- 控制按钮 ----------
        Row {
            id: controls
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 22
            spacing: 8

            GlassButton {
                objectName: "PomodoroPrimary"
                text: panel.primaryText
                tone: "light"
                fontSize: 13
                padH: 22
                minHeight: 40
                onClicked: panel.primaryAction()
            }
            GlassButton {
                objectName: "PomodoroStop"
                text: qsTr("停止")
                tone: "ghost"
                fontSize: 12
                padH: 14
                minHeight: 40
                enabled: !panel.idle
                onClicked: panel.stop()
            }
            GlassButton {
                objectName: "PomodoroSkip"
                text: qsTr("跳过")
                tone: "ghost"
                fontSize: 12
                padH: 14
                minHeight: 40
                enabled: !panel.idle
                onClicked: panel.skip()
            }
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: controls.top
            anchors.bottomMargin: 6
            text: panel.backendReady ? qsTr("已绑定番茄钟接口") : qsTr("本地计时（后端接口未接入）")
            color: AppTheme.textTertiary
            font.pixelSize: AppTheme.fs(9)
            font.family: AppTheme.fontFamily
            opacity: 0.7
        }
    }
}
