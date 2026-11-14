import QtQuick
import "theme"
import QtQuick.Window
import QtQuick.Effects
import "components"
import "glass"
import "bus"
import "components/Constants.js" as C

// 速启面板（CW2 TrayPanel 形态）：340×336、无边框、置顶、失焦自动隐藏。
// v0.17 重做：
//  - 去掉顶部深清 logo 方块，只保留标题文字；
//  - 专注档位改为横向滑动卡列（浅清 / 覆清 / 深清 / 还清），默认露出 3 个，可拖动、滚轮或边缘箭头露出第 4 个；
//    选中态高亮，点选即 App.startMode 开始专注；
//  - 顶部右侧图标组：关闭 / 重启 / 重启为管理员（同位置、纯图标、无文字），
//    管理员的蓝黄四格盾牌图标由 AdminShield 自绘；App.isAdmin 为 true 时隐藏「重启为管理员」；
//  - 删除底部「重启 / 重启为管理员」文字按钮；空间卡与快捷入口保持不变。
// 对外：showAt(px, py) / toggleAt(px, py) / hide() / openPanel()（Python 侧接托盘与快捷键）
Window {
    id: panel
    title: qsTr("深清 · 速启")
    width: 340
    height: 318
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
    color: "transparent"
    visible: false

    // 刚 showAt 后的一个短保护期：避免「点托盘 → 面板弹出 → 立刻被判失焦」而闪退
    property double guardUntil: 0

    // Python 侧触发入口：每次右键托盘把 requestTick +1 并带上坐标，面板就重新定位并显示
    property real requestX: 0
    property real requestY: 0
    property int requestTick: 0
    onRequestTickChanged: panel.toggleAt(requestX, requestY)

    // 主题跟随 Python 设置（v0.21：样式 + 配色；typeof 兜底：单独加载面板时退回纯色 + 跟随系统）
    readonly property string resolvedThemeStyle: (typeof App !== "undefined" && App.themeStyle)
                                                 ? String(App.themeStyle) : "solid"
    readonly property string resolvedThemeScheme: (typeof App !== "undefined" && App.themeScheme)
                                                  ? String(App.themeScheme) : "auto"
    readonly property string resolvedEffectiveScheme: (typeof App !== "undefined" && App.effectiveScheme)
                                                      ? String(App.effectiveScheme) : "dark"
    readonly property string resolvedSystemScheme: (typeof App !== "undefined" && App.systemScheme)
                                                   ? String(App.systemScheme) : panel.resolvedEffectiveScheme
    readonly property string themeSignature: panel.resolvedThemeStyle + "|" + panel.resolvedThemeScheme
                                             + "|" + panel.resolvedEffectiveScheme
    onThemeSignatureChanged: panel.syncTheme()
    function syncTheme() {
        AppTheme.style = panel.resolvedThemeStyle
        AppTheme.scheme = panel.resolvedThemeScheme
        AppTheme.effectiveScheme = panel.resolvedEffectiveScheme
        AppTheme.systemScheme = panel.resolvedSystemScheme
        var palette = ({})
        if (typeof App !== "undefined" && App.customThemePalette !== undefined
                && App.customThemePalette !== null && typeof App.customThemePalette === "object")
            palette = App.customThemePalette
        AppTheme.customPalette = palette
    }

    onActiveChanged: {
        if (active) return
        if (Qt.application.active === true) return
        if (Date.now() < guardUntil) return
        hide()
    }

    // 幂等：无论面板当前开/关，都重新定位到托盘图标附近并置顶激活（不会把自己关掉）
    function showAt(px, py) {
        var margin = 8
        var screenW = Screen.width
        var screenH = Screen.height
        var targetX = px - panel.width / 2
        var targetY = py + 30
        if (targetY + panel.height > screenH - margin)
            targetY = py - panel.height - 30
        if (targetY < margin)
            targetY = margin
        if (targetX < margin)
            targetX = margin
        if (targetX + panel.width > screenW - margin)
            targetX = screenW - panel.width - margin

        panel.guardUntil = Date.now() + 280
        panel.x = Math.round(targetX)
        panel.y = Math.round(targetY)

        if (!panel.visible) {
            hideAnim.stop()
            panelRoot.opacity = 0
            panelShift.y = 10
            panel.visible = true
            if (panel.animationsEnabled) {
                showAnim.restart()
            } else {
                panelRoot.opacity = 1
                panelShift.y = 0
            }
        } else if (hideAnim.running) {
            hideAnim.stop()
            panelRoot.opacity = 1
            panelShift.y = 0
        }

        panel.raise()
        panel.requestActivate()
    }

    // 托盘右键每次都调这个：已打开时重新定位+置顶，而不是关掉
    function toggleAt(px, py) {
        showAt(px, py)
    }

    function openPanel() {
        showAt(Screen.width / 2, Screen.height / 2)
    }

    function hide() {
        if (!panel.visible) return
        if (!panel.animationsEnabled) {
            hideAnim.stop()
            showAnim.stop()
            panelRoot.opacity = 0
            panelShift.y = 10
            panel.visible = false
            return
        }
        if (hideAnim.running) return
        showAnim.stop()
        hideAnim.restart()
    }

    function closePanel() {
        hide()
    }

    Shortcut {
        sequence: "Escape"
        onActivated: panel.hide()
    }

    // ---------- 显示 / 隐藏动画（v0.6） ----------
    // 独立 Window 由 Python 加载，拿不到 Main.pageTransitions，用本地开关（默认开启）
    property bool animationsEnabled: true

    ParallelAnimation {
        id: showAnim
        NumberAnimation {
            target: panelRoot
            property: "opacity"
            from: 0
            to: 1
            duration: panel.animationsEnabled ? 160 : 0
            easing.type: Easing.OutCubic
        }
        NumberAnimation {
            target: panelShift
            property: "y"
            from: 10
            to: 0
            duration: panel.animationsEnabled ? 160 : 0
            easing.type: Easing.OutCubic
        }
    }

    SequentialAnimation {
        id: hideAnim
        NumberAnimation {
            target: panelRoot
            property: "opacity"
            to: 0
            duration: panel.animationsEnabled ? 120 : 0
            easing.type: Easing.OutCubic
        }
        ScriptAction { script: panel.visible = false }
    }

    // 四档：浅清 / 覆清 / 深清 / 还清（后端 v0.15 起 modes 已含 sleep；旧后端本地补一条）
    readonly property var modes: {
        var list = (typeof App !== "undefined" && App.modes && App.modes.length > 0)
                   ? App.modes
                   : [
                         { value: "light", label: qsTr("浅清") },
                         { value: "medium", label: qsTr("覆清") },
                         { value: "heavy", label: qsTr("深清") }
                     ]
        for (var i = 0; i < list.length; i++) {
            if (String(list[i].value) === "sleep") return list
        }
        var out = []
        for (var j = 0; j < list.length; j++) out.push(list[j])
        out.push({ value: "sleep", label: qsTr("还清") })
        return out
    }

    // v0.17：横向档位条把「清番」放第一个（置顶番茄钟，不进入专注）
    readonly property var tabs: {
        var out = [{ value: "pomodoro", label: qsTr("清番") }]
        for (var i = 0; i < panel.modes.length; i++) out.push(panel.modes[i])
        return out
    }

    readonly property var spaceData: (typeof App !== "undefined" && App.space) ? App.space : ({})
    readonly property int spaceMinutes: (typeof App !== "undefined" && App.spaceMinutes !== undefined)
                                        ? Number(App.spaceMinutes) : 45
    readonly property string defaultModeValue: (typeof App !== "undefined" && App.defaultMode)
                                               ? String(App.defaultMode) : "medium"
    // 管理员身份：为 true 时不显示「重启为管理员」
    readonly property bool isAdmin: (typeof App !== "undefined" && App.isAdmin !== undefined)
                                    ? App.isAdmin === true : false

    // 选中档位（默认跟随设置的默认档位；点选后立即开始专注）
    property string selectedMode: defaultModeValue

    function modeGlyph(value) {
        if (value === "pomodoro") return "clock"
        if (value === "light") return "moon"
        if (value === "medium") return "wave"
        if (value === "heavy") return "lock"
        if (value === "sleep") return "clock"
        return "wave"
    }

    function modeLabel(value) {
        for (var i = 0; i < panel.modes.length; i++) {
            if (String(panel.modes[i].value) === String(value))
                return String(panel.modes[i].label)
        }
        return String(value)
    }

    // v0.8：空间卡 → 打开主窗口空间页并切到对应标签（不直接开始专注）
    function openSpaces(value) {
        if (typeof App !== "undefined" && typeof App.openSpacesPage === "function")
            App.openSpacesPage(String(value || ""))
        else if (typeof App.startMode === "function")
            App.startMode(String(value))
        panel.hide()
    }

    // v0.17：档位卡点选 = 选中高亮 + 开始专注
    // v0.21：开始前先弹二次确认卡；后端有 confirmationPending/confirmStart/cancelStart 时走后端挂起流程
    function startMode(value) {
        var mode = String(value)
        panel.selectedMode = mode
        // 还清 / 清番不走「开始专注」确认（还清按作息自动锁定，清番另有小窗）
        if (mode !== "light" && mode !== "medium" && mode !== "heavy") {
            if (typeof App.startMode === "function")
                App.startMode(mode)
            panel.hide()
            return
        }
        panel.pendingStartInfo = panel.spaceInfoForMode(mode)
        // 后端挂起流程：只登记待确认（不会开始倒计时），confirmStart 才真正开始
        if (panel.backendConfirm) {
            if (typeof App.requestStartMode === "function")
                App.requestStartMode(mode)
        }
    }

    // ---------- v0.21 开始前二次确认 ----------
    property var pendingStartInfo: null        // { spaceId, mode, name, minutes, allowedCount }
    readonly property bool backendConfirm: (typeof App !== "undefined"
                                           && (App.confirmationActive !== undefined
                                               || App.confirmationPending !== undefined))
    // 新契约：confirmationActive(bool) + confirmationPending(dict)；旧契约：confirmationPending(bool)
    readonly property bool backendPending: {
        if (!panel.backendConfirm) return false
        if (App.confirmationActive !== undefined) return App.confirmationActive === true
        if (App.confirmationPending === true) return true
        return false
    }
    readonly property bool confirming: panel.pendingStartInfo !== null || panel.backendPending

    // 按档位找对应空间（优先当前空间，其次该档位第一张）
    function modeSpace(value) {
        var first = null
        var list = (typeof App !== "undefined" && App.spaces) ? App.spaces : []
        for (var i = 0; i < list.length; i++) {
            if (list[i] !== null && list[i] !== undefined && String(list[i].mode) === String(value)) {
                first = list[i]
                break
            }
        }
        var current = (typeof App !== "undefined" && App.space !== undefined) ? App.space : null
        if (current !== null && current !== undefined && String(current.mode) === String(value))
            return current
        return first
    }

    function spaceInfoForMode(value) {
        var space = panel.modeSpace(value)
        var sameAsDefault = String(panel.defaultModeValue) === String(value)
        return {
            spaceId: (space !== null && space !== undefined && space.id !== undefined) ? String(space.id) : "",
            mode: String(value),
            name: (space !== null && space !== undefined && space.name !== undefined)
                  ? String(space.name) : qsTr("%1空间").arg(panel.modeLabel(value)),
            minutes: (space !== null && space !== undefined && space.minutes !== undefined)
                     ? Number(space.minutes) : (sameAsDefault ? panel.spaceMinutes : 0),
            allowedCount: (space !== null && space !== undefined && space.allowedCount !== undefined)
                          ? Number(space.allowedCount) : -1
        }
    }

    readonly property var confirmInfo: {
        var summary = null
        if (typeof App !== "undefined") {
            if (App.confirmationSummary !== undefined && App.confirmationSummary !== null
                    && typeof App.confirmationSummary === "object")
                summary = App.confirmationSummary
            else if (App.confirmationPending !== undefined && App.confirmationPending !== null
                     && typeof App.confirmationPending === "object")
                summary = App.confirmationPending
        }
        if (summary !== null) {
            var s = summary
            return {
                spaceName: s.spaceName !== undefined ? String(s.spaceName)
                                                      : (s.name !== undefined ? String(s.name) : ""),
                mode: s.mode !== undefined ? String(s.mode) : "medium",
                modeLabel: s.modeLabel !== undefined ? String(s.modeLabel) : "",
                minutes: s.minutes !== undefined ? Number(s.minutes) : 0,
                allowedCount: s.allowedCount !== undefined ? Number(s.allowedCount) : -1,
                whitelistSummary: s.whitelistSummary !== undefined ? String(s.whitelistSummary) : ""
            }
        }
        var local = panel.pendingStartInfo
        if (local === null || local === undefined)
            return ({ spaceName: "", mode: "medium", modeLabel: "", minutes: 0,
                       allowedCount: -1, whitelistSummary: "" })
        return {
            spaceName: String(local.name !== undefined ? local.name : ""),
            mode: String(local.mode !== undefined ? local.mode : "medium"),
            modeLabel: panel.modeLabel(local.mode),
            minutes: Number(local.minutes !== undefined ? local.minutes : 0),
            allowedCount: Number(local.allowedCount !== undefined ? local.allowedCount : -1),
            whitelistSummary: ""
        }
    }

    function cancelStart() {
        panel.pendingStartInfo = null
        if (panel.backendConfirm && typeof App.cancelStart === "function")
            App.cancelStart()
    }

    function confirmStart() {
        var info = panel.pendingStartInfo
        panel.pendingStartInfo = null
        var backendPending = panel.backendPending
        if (backendPending && typeof App.confirmStart === "function") {
            App.confirmStart()
            panel.hide()
            return
        }
        if (info === null || info === undefined) {
            panel.hide()
            return
        }
        if (typeof App.startMode === "function")
            App.startMode(String(info.mode))
        else if (typeof App.startSpace === "function" && String(info.spaceId) !== "")
            App.startSpace(String(info.spaceId))
        panel.hide()
    }

    // v0.16：重启 / 以管理员身份重启（接口缺失时静默，说明见发布说明）
    function restartApp() {
        if (typeof App !== "undefined" && typeof App.restartApp === "function")
            App.restartApp()
        panel.hide()
    }
    function relaunchAsAdmin() {
        if (typeof App !== "undefined" && typeof App.relaunchAsAdmin === "function")
            App.relaunchAsAdmin()
        panel.hide()
    }
    function quitApp() {
        if (typeof App !== "undefined" && typeof App.quitApp === "function")
            App.quitApp()
        else
            panel.hide()
    }

    Component.onCompleted: {
        panel.syncTheme()
        panel.selectedMode = panel.defaultModeValue
    }

    // ---------- 内容根：显示时上滑 10px + 淡入（160ms），隐藏 120ms 淡出后 visible=false ----------
    Item {
        id: panelRoot
        objectName: "PanelRoot"
        anchors.fill: parent
        opacity: 1
        // anchors.fill 锁住 x/y，位移用 Translate
        property alias shiftY: panelShift.y
        transform: Translate {
            id: panelShift
            y: 0
        }

        // ---------- 背景：主题底色 +（海洋主题静态浪花）+ 光斑 + 细噪点（光斑/噪点仅玻璃主题） ----------
        Item {
            id: bgLayer
            anchors.fill: parent

            Rectangle {
                anchors.fill: parent
                radius: 18
                gradient: Gradient {
                    GradientStop { position: 0.0; color: AppTheme.bgStart }
                    GradientStop { position: 0.55; color: AppTheme.bgCenter }
                    GradientStop { position: 1.0; color: AppTheme.bgBottom }
                }
            }

            // 海洋主题：头部静态浪花（WaveBackdrop 内部只在 AppTheme.ocean 时可见）
            WaveBackdrop {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.leftMargin: 1
                anchors.rightMargin: 1
                anchors.topMargin: 1
                height: 150
                tone: AppTheme.light ? "light" : "deep"
                intensity: 0.70
            }

            Item {
                anchors.fill: parent
                visible: AppTheme.glass

                Rectangle {
                    id: pb1
                    visible: false
                    width: 320
                    height: 320
                    radius: 160
                    x: -80
                    y: -120
                    color: C.waterBlue
                }
                MultiEffect {
                    source: pb1
                    width: pb1.width
                    height: pb1.height
                    blurEnabled: true
                    blur: 1.0
                    blurMax: 96
                    opacity: 0.22
                }

                Rectangle {
                    id: pb2
                    visible: false
                    width: 280
                    height: 280
                    radius: 140
                    x: 170
                    y: 220
                    color: C.waterTeal
                }
                MultiEffect {
                    source: pb2
                    width: pb2.width
                    height: pb2.height
                    blurEnabled: true
                    blur: 1.0
                    blurMax: 96
                    opacity: 0.16
                }

                Image {
                    anchors.fill: parent
                    source: "assets/img/noise.png"
                    fillMode: Image.Tile
                    smooth: false
                    opacity: 0.1
                }
            }
        }

        Rectangle {
            anchors.fill: parent
            radius: 18
            color: "transparent"
            border.width: 1
            border.color: AppTheme.glass ? "#4DFFFFFF" : AppTheme.cardBorderStrong
        }

        // ---------- 内容 ----------
        Item {
            id: content
            anchors.fill: parent
            anchors.margins: 14
            property Item glassSource: bgLayer

            // ============ 顶部 header：标题（无 logo 方块）+ 右侧图标组 ============
            Item {
                id: header
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 44

                Row {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 7

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: qsTr("深清")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(17)
                        font.weight: Font.DemiBold
                        font.family: AppTheme.fontFamily
                        font.letterSpacing: 1
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Clarity"
                        color: AppTheme.textTertiary
                        font.pixelSize: AppTheme.fs(10)
                        font.family: AppTheme.fontFamily
                    }
                }

                // 关闭 / 重启 / 重启为管理员：同一组、同一位置，纯图标
                Row {
                    id: headerActions
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 4

                    // 关闭（退出深清）
                    Item {
                        id: closeAction
                        objectName: "QuickCloseButton"
                        width: 30
                        height: 30
                        Rectangle {
                            anchors.fill: parent
                            radius: 10
                            color: closeArea.containsMouse
                                   ? (AppTheme.glass ? "#26FFFFFF" : AppTheme.buttonBgAlt)
                                   : "transparent"
                            border.width: 1
                            border.color: closeArea.containsMouse
                                          ? (AppTheme.glass ? "#33FFFFFF" : AppTheme.cardBorder)
                                          : "transparent"
                            Behavior on color { ColorAnimation { duration: 110 } }
                        }
                        Glyph {
                            anchors.centerIn: parent
                            kind: "close"
                            size: 16
                            color: closeArea.containsMouse ? AppTheme.danger : AppTheme.textSecondary
                        }
                        MouseArea {
                            id: closeArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: panel.quitApp()
                        }
                    }

                    // 重启（圆形箭头）
                    Item {
                        id: restartAction
                        objectName: "QuickRestartButton"
                        width: 30
                        height: 30
                        Rectangle {
                            anchors.fill: parent
                            radius: 10
                            color: restartArea.containsMouse
                                   ? (AppTheme.glass ? "#26FFFFFF" : AppTheme.buttonBgAlt)
                                   : "transparent"
                            border.width: 1
                            border.color: restartArea.containsMouse
                                          ? (AppTheme.glass ? "#33FFFFFF" : AppTheme.cardBorder)
                                          : "transparent"
                            Behavior on color { ColorAnimation { duration: 110 } }
                        }
                        Glyph {
                            anchors.centerIn: parent
                            kind: "restart"
                            size: 17
                            color: restartArea.containsMouse ? AppTheme.accent : AppTheme.textSecondary
                        }
                        MouseArea {
                            id: restartArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: panel.restartApp()
                        }
                    }

                    // 重启为管理员（蓝黄四格盾牌；管理员身份下隐藏）
                    Item {
                        id: adminRestartAction
                        objectName: "QuickRelaunchAdminButton"
                        width: 30
                        height: 30
                        visible: !panel.isAdmin
                        Rectangle {
                            anchors.fill: parent
                            radius: 10
                            color: adminArea.containsMouse
                                   ? (AppTheme.glass ? "#26FFFFFF" : AppTheme.buttonBgAlt)
                                   : "transparent"
                            border.width: 1
                            border.color: adminArea.containsMouse
                                          ? (AppTheme.glass ? "#33FFFFFF" : AppTheme.cardBorder)
                                          : "transparent"
                            Behavior on color { ColorAnimation { duration: 110 } }
                        }
                        AdminShield {
                            anchors.centerIn: parent
                            size: 17
                        }
                        MouseArea {
                            id: adminArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: panel.relaunchAsAdmin()
                        }
                    }
                }
            }

            // ============ 档位标题 ============
            Text {
                id: modeTitle
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: header.bottom
                anchors.topMargin: 6
                text: qsTr("专注档位")
                color: AppTheme.textSecondary
                font.pixelSize: AppTheme.fs(13)
                font.weight: Font.DemiBold
                font.family: AppTheme.fontFamily
                font.letterSpacing: 1
            }

            // ============ 横向滑动档位卡列（默认露出 3 个 + 第 4 个边缘） ============
            Item {
                id: modeCarousel
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: modeTitle.bottom
                anchors.topMargin: 8
                height: 94

                readonly property int gap: 10
                readonly property int peek: 22
                readonly property real cardW: Math.max(62, (width - gap * 3 - peek) / 3)
                readonly property bool canLeft: modeFlick.contentX > 0.5
                readonly property bool canRight: modeFlick.contentX < modeFlick.contentWidth - modeFlick.width - 0.5

                function scrollBy(steps) {
                    var maxX = Math.max(0, modeFlick.contentWidth - modeFlick.width)
                    var target = Math.max(0, Math.min(maxX, modeFlick.contentX + steps * (modeCarousel.cardW + modeCarousel.gap)))
                    scrollAnim.stop()
                    scrollAnim.from = modeFlick.contentX
                    scrollAnim.to = target
                    scrollAnim.start()
                }

                NumberAnimation {
                    id: scrollAnim
                    target: modeFlick
                    property: "contentX"
                    duration: 200
                    easing.type: Easing.OutCubic
                }

                Flickable {
                    id: modeFlick
                    anchors.fill: parent
                    contentWidth: panel.tabs.length * modeCarousel.cardW
                                  + (panel.tabs.length - 1) * modeCarousel.gap
                    contentHeight: height
                    flickableDirection: Flickable.HorizontalFlick
                    boundsBehavior: Flickable.StopAtBounds
                    clip: true
                    pressDelay: 80

                    Row {
                        spacing: modeCarousel.gap

                        Repeater {
                            model: panel.tabs

                            delegate: Item {
                                id: modeCell
                                width: modeCarousel.cardW
                                height: modeCarousel.height
                                property point pressPoint: Qt.point(0.5, 0.5)
                                readonly property bool selected: panel.selectedMode === String(modelData.value)
                                readonly property bool isDefault: String(modelData.value) === panel.defaultModeValue

                                function trackPointer(mx, my) {
                                    modeCell.pressPoint = Qt.point(
                                        Math.max(0, Math.min(1, mx / Math.max(1, modeCell.width))),
                                        Math.max(0, Math.min(1, my / Math.max(1, 66))))
                                }

                                // 档位卡
                                Item {
                                    id: modeTile
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    height: 66
                                    scale: !AppTheme.glass && modeArea.pressed ? 0.97 : 1.0
                                    Behavior on scale { NumberAnimation { duration: 90; easing.type: Easing.OutCubic } }

                                    LiquidGlass {
                                        anchors.fill: parent
                                        visible: AppTheme.glass
                                        sourceItem: bgLayer
                                        radius: 16
                                        depth: 1.2
                                        frost: 0.02
                                        aberration: 0.58
                                        highlight: 1.45
                                        whiten: 0.05
                                        tintAlpha: modeCell.selected ? 0.30 : (modeCell.isDefault ? 0.22 : 0.14)
                                        tint: modeCell.selected ? AppTheme.accentSoft
                                              : (modeCell.isDefault ? AppTheme.accentSoft : AppTheme.glassTint)
                                        sheen: 0.5
                                        pointer: modeCell.pressPoint
                                        pull: modeArea.pressed ? 1 : 0
                                        Behavior on pull {
                                            NumberAnimation {
                                                duration: modeArea.pressed ? 90 : 440
                                                easing.type: modeArea.pressed ? Easing.OutCubic : Easing.OutElastic
                                                easing.amplitude: 0.9
                                                easing.period: 0.5
                                            }
                                        }
                                    }

                                    Rectangle {
                                        anchors.fill: parent
                                        visible: !AppTheme.glass
                                        radius: 16
                                        color: modeCell.selected
                                               ? Qt.rgba(AppTheme.accent.r, AppTheme.accent.g, AppTheme.accent.b, 0.18)
                                               : (modeArea.containsMouse ? AppTheme.buttonBgAlt : AppTheme.buttonBg)
                                        border.width: 1
                                        border.color: modeCell.selected ? AppTheme.accent : AppTheme.cardBorder
                                        Behavior on color { ColorAnimation { duration: 130 } }
                                        Behavior on border.color { ColorAnimation { duration: 130 } }
                                    }

                                    Rectangle {
                                        anchors.fill: parent
                                        visible: AppTheme.glass
                                        radius: 16
                                        color: "transparent"
                                        border.width: 1
                                        border.color: modeCell.selected ? AppTheme.accent : "#45FFFFFF"
                                    }

                                    Glyph {
                                        anchors.centerIn: parent
                                        kind: panel.modeGlyph(String(modelData.value))
                                        size: 23
                                        color: modeCell.selected ? AppTheme.accent : AppTheme.textPrimary
                                    }
                                }

                                Text {
                                    anchors.top: modeTile.bottom
                                    anchors.topMargin: 7
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: String(modelData.label)
                                    color: modeCell.selected ? AppTheme.accent : AppTheme.textSecondary
                                    font.pixelSize: AppTheme.fs(12)
                                    font.weight: modeCell.selected ? Font.DemiBold : Font.Normal
                                    font.family: AppTheme.fontFamily
                                }

                                MouseArea {
                                    id: modeArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onPressed: (mouse) => modeCell.trackPointer(mouse.x, mouse.y)
                                    onPositionChanged: (mouse) => {
                                        if (pressed) modeCell.trackPointer(mouse.x, mouse.y)
                                    }
                                    onClicked: {
                                        if (String(modelData.value) === "pomodoro") {
                                            AppBus.openPomodoro()
                                            panel.hide()
                                        } else {
                                            panel.startMode(String(modelData.value))
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // 滚轮：横向滚动档位卡（不穿透到页面）
                    WheelHandler {
                        onWheel: (wheel) => {
                            var delta = wheel.angleDelta.y !== 0 ? wheel.angleDelta.y : wheel.angleDelta.x
                            var maxX = Math.max(0, modeFlick.contentWidth - modeFlick.width)
                            modeFlick.contentX = Math.max(0, Math.min(maxX, modeFlick.contentX - delta * 0.5))
                            wheel.accepted = true
                        }
                    }
                }

                // 左右边缘箭头（有隐藏档位时出现）
                Rectangle {
                    visible: modeCarousel.canLeft
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.verticalCenterOffset: -12
                    width: 20
                    height: 20
                    radius: 10
                    color: AppTheme.glass ? "#33000000" : AppTheme.cardBg
                    opacity: leftArea.containsMouse ? 1.0 : 0.86
                    border.width: 1
                    border.color: AppTheme.cardBorder
                    Glyph {
                        anchors.centerIn: parent
                        kind: "chevronLeft"
                        size: 10
                        color: AppTheme.textSecondary
                    }
                    MouseArea {
                        id: leftArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: modeCarousel.scrollBy(-1)
                    }
                }

                Rectangle {
                    visible: modeCarousel.canRight
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.verticalCenterOffset: -12
                    width: 20
                    height: 20
                    radius: 10
                    color: AppTheme.glass ? "#33000000" : AppTheme.cardBg
                    opacity: rightArea.containsMouse ? 1.0 : 0.86
                    border.width: 1
                    border.color: AppTheme.cardBorder
                    Glyph {
                        anchors.centerIn: parent
                        kind: "chevron"
                        size: 10
                        color: AppTheme.textSecondary
                    }
                    MouseArea {
                        id: rightArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: modeCarousel.scrollBy(1)
                    }
                }
            }

            // ============ 空间卡（保持） ============
            Text {
                id: spaceTitle
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: modeCarousel.bottom
                anchors.topMargin: 10
                text: qsTr("空间")
                color: AppTheme.textSecondary
                font.pixelSize: AppTheme.fs(13)
                font.weight: Font.DemiBold
                font.family: AppTheme.fontFamily
                font.letterSpacing: 1
            }

            Item {
                id: spaceCard
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: spaceTitle.bottom
                anchors.topMargin: 8
                height: 74
                scale: !AppTheme.glass && spaceArea.pressed ? 0.985 : 1.0
                Behavior on scale { NumberAnimation { duration: 90; easing.type: Easing.OutCubic } }

                LiquidGlass {
                    anchors.fill: parent
                    visible: AppTheme.glass
                    sourceItem: bgLayer
                    radius: 16
                    depth: 0.95
                    frost: 0.02
                    aberration: 0.45
                    highlight: 1.05
                    whiten: 0.04
                    tintAlpha: 0.16
                    tint: AppTheme.glassTint
                    sheen: 0.45
                }

                Rectangle {
                    anchors.fill: parent
                    visible: !AppTheme.glass
                    radius: 16
                    color: spaceArea.containsMouse ? AppTheme.buttonBgAlt : AppTheme.buttonBg
                    border.width: 1
                    border.color: AppTheme.cardBorder
                    Behavior on color { ColorAnimation { duration: 120 } }
                }

                Rectangle {
                    anchors.fill: parent
                    visible: AppTheme.glass
                    radius: 16
                    color: "transparent"
                    border.width: 1
                    border.color: "#3DFFFFFF"
                }

                Column {
                    anchors.left: parent.left
                    anchors.leftMargin: 14
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 4

                    Row {
                        spacing: 8

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: panel.spaceData.name !== undefined ? String(panel.spaceData.name) : qsTr("清空间")
                            color: AppTheme.textPrimary
                            font.pixelSize: AppTheme.fs(14)
                            font.weight: Font.DemiBold
                            font.family: AppTheme.fontFamily
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("%1 分钟").arg(panel.spaceMinutes)
                            color: AppTheme.textTertiary
                            font.pixelSize: AppTheme.fs(11)
                            font.family: AppTheme.fontFamily
                        }
                    }

                    Text {
                        width: spaceCard.width - 80
                        text: qsTr("点击以「%1」开始专注").arg(panel.modeLabel(panel.defaultModeValue))
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(11)
                        font.family: AppTheme.fontFamily
                        elide: Text.ElideRight
                    }
                }

                Rectangle {
                    width: 30
                    height: 30
                    radius: 15
                    anchors.right: parent.right
                    anchors.rightMargin: 14
                    anchors.verticalCenter: parent.verticalCenter
                    color: AppTheme.glass ? "#26FFFFFF" : AppTheme.accent

                    Glyph {
                        anchors.centerIn: parent
                        kind: "play"
                        size: 13
                        color: AppTheme.glass ? AppTheme.textPrimary : "#FFFFFF"
                    }
                }

                MouseArea {
                    id: spaceArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: panel.openSpaces(panel.defaultModeValue)
                }
            }
        }

        // ---------- v0.21 开始专注二次确认卡（340 宽容器自动紧凑排版） ----------
        StartConfirmSheet {
            id: startConfirmSheet
            objectName: "QuickPanelStartConfirmSheet"
            anchors.fill: parent
            z: 90
            animationsEnabled: panel.animationsEnabled
            opened: panel.confirming
            spaceName: panel.confirmInfo.spaceName !== undefined ? String(panel.confirmInfo.spaceName) : ""
            mode: panel.confirmInfo.mode !== undefined ? String(panel.confirmInfo.mode) : "medium"
            modeLabel: panel.confirmInfo.modeLabel !== undefined ? String(panel.confirmInfo.modeLabel) : ""
            minutes: panel.confirmInfo.minutes !== undefined ? Number(panel.confirmInfo.minutes) : 0
            whitelistCount: panel.confirmInfo.allowedCount !== undefined ? Number(panel.confirmInfo.allowedCount) : -1
            whitelistSummary: panel.confirmInfo.whitelistSummary !== undefined
                              ? String(panel.confirmInfo.whitelistSummary) : ""
            onConfirmed: panel.confirmStart()
            onCancelled: panel.cancelStart()
        }
    }
}
