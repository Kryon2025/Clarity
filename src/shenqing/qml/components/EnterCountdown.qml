import QtQuick
import QtQuick.Window
import "../theme"
import "../components/Constants.js" as C

// v0.15 进入专注倒计时：极简加载动画（无粒子）
// - 深色渐变背景 + 中央加载圆环（进度弧 10s 0→360°，青蓝渐变、圆头、发光）
// - 环上轻旋转光点 + 呼吸光晕；数字/空间名/提示文字清晰
// - 结束：圆环快速放大 / 光波扩散全屏并淡出，然后进入专注遮罩
// - 取消：圆环 200ms 淡出后再关闭窗口
Window {
    id: overlay
    objectName: "EnterCountdown"
    title: qsTr("深清 · 即将进入")
    property bool animationsEnabled: true

    readonly property bool shouldShow: (typeof App !== "undefined" && App.prepareActive === true)
    readonly property int totalSeconds: 10
    readonly property int remaining: (typeof App !== "undefined" && App.prepareRemaining !== undefined)
                                      ? Math.max(0, Number(App.prepareRemaining)) : 10
    property real progress01: 0
    readonly property string prepareLevel: (typeof App !== "undefined" && App.prepareLevel !== undefined) ? String(App.prepareLevel) : ""
    readonly property string prepareSpaceName: (typeof App !== "undefined" && App.prepareSpaceName !== undefined) ? String(App.prepareSpaceName) : ""

    property string displaySpaceName: ""
    property string displayLevel: ""
    property bool hasShown: false
    property bool closing: false
    property bool expanding: false
    property bool finishing: false
    property bool canceling: false
    property int lastRemaining: 10
    property real wave01: 0
    property real timeSeconds: 0
    property bool progressSmoothing: true
    Behavior on progress01 {
        enabled: overlay.animationsEnabled && overlay.progressSmoothing
        NumberAnimation { duration: overlay.animationsEnabled ? 1000 : 0; easing.type: Easing.Linear }
    }

    visibility: (overlay.shouldShow || overlay.closing || overlay.expanding || overlay.canceling) ? Window.FullScreen : Window.Hidden
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: "transparent"

    function modeLabel(value) {
        if (value === "light") return qsTr("浅清")
        if (value === "medium") return qsTr("覆清")
        if (value === "heavy") return qsTr("深清")
        return qsTr("专注")
    }
    function syncDisplay() {
        if (overlay.prepareSpaceName !== "") overlay.displaySpaceName = overlay.prepareSpaceName
        if (overlay.prepareLevel !== "") overlay.displayLevel = overlay.prepareLevel
    }
    function displaySpaceLabel() {
        var name = overlay.shouldShow ? overlay.prepareSpaceName : overlay.displaySpaceName
        if (name !== "") return name
        return overlay.modeLabel(overlay.shouldShow ? overlay.prepareLevel : overlay.displayLevel)
    }
    function progressAt(secondsLeft) {
        var left = Math.max(0, Math.min(overlay.totalSeconds, Number(secondsLeft)))
        return (overlay.totalSeconds - left) / overlay.totalSeconds
    }

    function startEnter() {
        overlay.closing = false; overlay.expanding = false; overlay.finishing = false
        overlay.canceling = false; overlay.hasShown = true; overlay.wave01 = 0
        overlay.syncDisplay(); overlay.lastRemaining = overlay.remaining
        overlay.progressSmoothing = false
        overlay.progress01 = overlay.progressAt(overlay.remaining)
        overlay.progressSmoothing = true
        sceneRoot.opacity = overlay.animationsEnabled ? 0 : 1
        enterAnim.stop(); fadeAnim.stop(); cancelAnim.stop(); waveAnim.stop()
        if (overlay.animationsEnabled) enterAnim.restart()
        overlay.show(); overlay.raise(); overlay.requestActivate()
    }
    function cancel() {
        if (!overlay.hasShown || overlay.canceling || overlay.closing || overlay.expanding) return
        overlay.canceling = true
        if (typeof App !== "undefined" && typeof App.cancelPrepare === "function") App.cancelPrepare()
        if (!overlay.animationsEnabled) {
            sceneRoot.opacity = 0
            overlay.canceling = false; overlay.hasShown = false
            return
        }
        cancelAnim.restart()
    }
    function startFadeOut() {
        if (!overlay.hasShown) return
        overlay.closing = true
        enterAnim.stop(); waveAnim.stop()
        if (!overlay.animationsEnabled) {
            sceneRoot.opacity = 0; overlay.closing = false; overlay.hasShown = false; return
        }
        fadeAnim.restart()
    }
    function startExpand() {
        if (overlay.expanding) return
        overlay.expanding = true; overlay.closing = false
        enterAnim.stop(); fadeAnim.stop(); cancelAnim.stop()
        overlay.progressSmoothing = false; overlay.progress01 = 1; overlay.progressSmoothing = true
        overlay.wave01 = 0
        if (!overlay.animationsEnabled) {
            sceneRoot.opacity = 0
            overlay.expanding = false; overlay.hasShown = false; return
        }
        sceneRoot.opacity = 1
        waveAnim.restart()
    }

    onShouldShowChanged: {
        if (overlay.shouldShow) overlay.startEnter()
        else if (overlay.canceling) { }
        else if (overlay.hasShown && !overlay.expanding) {
            if (overlay.finishing) overlay.startExpand()
            else overlay.startFadeOut()
        }
    }
    onPrepareSpaceNameChanged: overlay.syncDisplay()
    onPrepareLevelChanged: overlay.syncDisplay()
    onRemainingChanged: {
        if (!overlay.shouldShow) return
        overlay.lastRemaining = overlay.remaining
        if (!overlay.finishing) {
            var target = overlay.progressAt(overlay.remaining)
            if (overlay.remaining === 1) target = 0.97
            overlay.progress01 = target
        }
        if (overlay.remaining <= 0) { overlay.finishing = true; overlay.startExpand() }
    }
    Component.onCompleted: {
        overlay.syncDisplay()
        if (overlay.shouldShow) overlay.startEnter()
    }
    Shortcut { sequence: "Escape"; onActivated: overlay.cancel() }

    Timer {
        interval: 33
        repeat: true
        running: overlay.shouldShow || overlay.canceling || overlay.expanding
        onTriggered: {
            overlay.timeSeconds += 0.033
            field.requestPaint()
        }
    }

    ParallelAnimation {
        id: enterAnim
        NumberAnimation { target: sceneRoot; property: "opacity"; from: 0; to: 1; duration: overlay.animationsEnabled ? 220 : 0; easing.type: Easing.OutCubic }
    }
    ParallelAnimation {
        id: fadeAnim
        NumberAnimation { target: sceneRoot; property: "opacity"; to: 0; duration: overlay.animationsEnabled ? 200 : 0; easing.type: Easing.OutCubic }
        onFinished: { overlay.closing = false; overlay.hasShown = false }
    }
    ParallelAnimation {
        id: cancelAnim
        NumberAnimation { target: sceneRoot; property: "opacity"; to: 0; duration: 200; easing.type: Easing.OutCubic }
        onFinished: {
            overlay.canceling = false
            overlay.closing = false
            overlay.hasShown = false
        }
    }
    NumberAnimation {
        id: waveAnim
        target: overlay; property: "wave01"; from: 0; to: 1
        duration: overlay.animationsEnabled ? 460 : 0
        easing.type: Easing.OutCubic
        onFinished: {
            overlay.expanding = false
            overlay.finishing = false
            overlay.hasShown = false
            sceneRoot.opacity = 0
        }
    }

    Item {
        id: sceneRoot
        anchors.fill: parent
        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(AppTheme.overlayTop.r, AppTheme.overlayTop.g, AppTheme.overlayTop.b, 0.97)
        }
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(AppTheme.bgMid.r, AppTheme.bgMid.g, AppTheme.bgMid.b, 0.55) }
                GradientStop { position: 1.0; color: Qt.rgba(AppTheme.overlayBottom.r, AppTheme.overlayBottom.g, AppTheme.overlayBottom.b, 0.55) }
            }
        }
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: overlay.cancel() }

        Canvas {
            id: field
            anchors.fill: parent
            renderTarget: Canvas.FramebufferObject
            antialiasing: true
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                var w = width, h = height, cx = w / 2, cy = h / 2
                var t = overlay.timeSeconds
                var progress = overlay.progress01
                var wave = overlay.wave01
                var twoPi = Math.PI * 2
                var minDim = Math.min(w, h)
                var ringR = minDim * 0.205
                var startA = -Math.PI / 2

                // 背景中央柔光
                var bgGlow = ctx.createRadialGradient(cx, cy, 0, cx, cy, minDim * 0.52)
                bgGlow.addColorStop(0.0, "rgba(46, 211, 198, 0.10)")
                bgGlow.addColorStop(0.5, "rgba(43, 134, 255, 0.04)")
                bgGlow.addColorStop(1.0, "rgba(0, 0, 0, 0)")
                ctx.fillStyle = bgGlow
                ctx.fillRect(0, 0, w, h)

                // 环的呼吸光晕
                var breath = 0.55 + 0.45 * Math.sin(t * 1.6)
                ctx.globalAlpha = 0.05 + 0.05 * breath
                ctx.beginPath(); ctx.arc(cx, cy, ringR + 14, 0, twoPi)
                ctx.strokeStyle = AppTheme.accent; ctx.lineWidth = 26; ctx.stroke()
                ctx.globalAlpha = 1

                // 轨道
                ctx.beginPath(); ctx.arc(cx, cy, ringR, 0, twoPi)
                ctx.strokeStyle = "rgba(255, 255, 255, 0.12)"
                ctx.lineWidth = 3; ctx.stroke()

                // 进度弧：细→略粗，青蓝渐变、圆头
                if (progress > 0.001) {
                    var lw = 3 + 6 * progress
                    var grad = ctx.createLinearGradient(cx - ringR, cy - ringR, cx + ringR, cy + ringR)
                    grad.addColorStop(0.0, "#2ED3C6")
                    grad.addColorStop(0.55, "#7FE7DA")
                    grad.addColorStop(1.0, "#2B86FF")
                    var endA = startA + twoPi * progress

                    // 外发光
                    ctx.globalAlpha = 0.16
                    ctx.beginPath(); ctx.arc(cx, cy, ringR, startA, endA)
                    ctx.strokeStyle = "#2ED3C6"; ctx.lineWidth = lw + 12; ctx.lineCap = "round"; ctx.stroke()

                    // 主弧
                    ctx.globalAlpha = 1
                    ctx.beginPath(); ctx.arc(cx, cy, ringR, startA, endA)
                    ctx.strokeStyle = grad; ctx.lineWidth = lw; ctx.lineCap = "round"; ctx.stroke()
                }

                // 结束：圆环放大 / 光波扩散
                if (wave > 0.0001) {
                    var maxR = Math.max(w, h) * 0.75
                    var waveR = ringR + (maxR - ringR) * wave
                    var fade = 1 - wave
                    ctx.globalCompositeOperation = "lighter"
                    ctx.globalAlpha = Math.min(1, 1.1 * fade)
                    ctx.beginPath(); ctx.arc(cx, cy, waveR, 0, twoPi)
                    ctx.strokeStyle = "#FFFFFF"; ctx.lineWidth = 2 + 16 * fade; ctx.stroke()
                    ctx.globalAlpha = 0.45 * fade
                    ctx.beginPath(); ctx.arc(cx, cy, waveR * 0.92, 0, twoPi)
                    ctx.strokeStyle = "#7FE7DA"; ctx.lineWidth = 2 + 10 * fade; ctx.stroke()
                    ctx.globalAlpha = 1
                    ctx.globalCompositeOperation = "source-over"
                }
            }
        }

        Column {
            anchors.centerIn: parent
            spacing: 10
            opacity: 1 - overlay.wave01 * 0.9
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: String(Math.max(0, Math.ceil(overlay.totalSeconds * (1 - overlay.progress01))))
                color: AppTheme.textPrimary
                font.pixelSize: AppTheme.fs(Math.max(84, Math.min(overlay.width * 0.10, overlay.height * 0.17)))
                font.weight: Font.Light
                font.family: C.monoFont
                style: Text.Outline
                styleColor: "#88020A10"
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: qsTr("即将进入 · %1").arg(overlay.displaySpaceLabel())
                color: AppTheme.textSecondary
                font.pixelSize: AppTheme.fs(15)
                font.family: AppTheme.fontFamily
                font.letterSpacing: 1
                style: Text.Outline
                styleColor: "#88020A10"
            }
        }

        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: Math.max(36, Math.round(overlay.height * 0.065))
            spacing: 10
            opacity: 1 - overlay.wave01 * 0.9
            Item {
                anchors.horizontalCenter: parent.horizontalCenter
                width: hintLabel.implicitWidth + 24
                height: 26
                Rectangle { anchors.fill: parent; radius: 13; color: "#5A040A10" }
                Text {
                    id: hintLabel
                    anchors.centerIn: parent
                    text: qsTr("点击任意位置取消 / Esc")
                    color: AppTheme.textSecondary
                    font.pixelSize: AppTheme.fs(12)
                    font.family: AppTheme.fontFamily
                }
            }
        }
    }
}
