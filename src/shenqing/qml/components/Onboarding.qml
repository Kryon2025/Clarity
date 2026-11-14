import QtQuick
import QtQuick.Window
import "../theme"
import "Constants.js" as C

// v0.16 首次使用引导：全屏引导替代主界面
// - App.needsOnboarding 为 true 时自动全屏显示（主窗口由 Main.qml / Python 隐藏）
// - 完成时优先 App.finishOnboarding()，旧接口回退 App.setOnboardingDone(true)
// - 页面：欢迎 → 外观（可直接改主题/字号/导航/语言）→ 三档空间 → 还清与清番 → 插件 → 完成
// - 底部：跳过 / 圆点 / 上一步 / 下一步；设置页「新手引导」可随时重新打开
Window {
    id: overlay
    objectName: "Onboarding"
    title: qsTr("深清 · 新手引导")
    property bool animationsEnabled: true
    width: Screen.width > 0 ? Screen.width : 1280
    height: Screen.height > 0 ? Screen.height : 800
    property bool showing: false
    property int pageIndex: 0
    readonly property int pageCount: 6

    // 后端缺失 onboardingDone 时的本地兜底（不持久化，仅本次运行）
    property bool localDone: false

    readonly property bool hasNeedsOnboarding: (typeof App !== "undefined" && App.needsOnboarding !== undefined)
    readonly property bool needsOnboardingValue: overlay.hasNeedsOnboarding ? App.needsOnboarding === true : false
    readonly property bool hasBackendDone: (typeof App !== "undefined" && App.onboardingDone !== undefined)
    readonly property bool backendDone: overlay.hasBackendDone ? App.onboardingDone === true : false
    onNeedsOnboardingValueChanged: if (overlay.needsOnboardingValue && !overlay.showing) overlay.showPages()

    visibility: overlay.showing ? Window.FullScreen : Window.Hidden
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: "transparent"

    function showPages() {
        overlay.pageIndex = 0
        overlay.showing = true
        sceneRoot.opacity = overlay.animationsEnabled ? 0 : 1
        overlay.show()
        overlay.raise()
        overlay.requestActivate()
        if (overlay.animationsEnabled) enterAnim.restart()
    }
    function nextPage() {
        if (overlay.pageIndex < overlay.pageCount - 1) {
            overlay.pageIndex++
            pageAnim.restart()
        } else {
            overlay.finishGuide()
        }
    }
    function prevPage() {
        if (overlay.pageIndex > 0) {
            overlay.pageIndex--
            pageAnim.restart()
        }
    }
    function goToPage(index) {
        var value = Number(index)
        if (!isFinite(value)) return
        overlay.pageIndex = Math.max(0, Math.min(overlay.pageCount - 1, Math.round(value)))
        pageAnim.restart()
    }
    function finishGuide() {
        if (typeof App !== "undefined" && typeof App.finishOnboarding === "function")
            App.finishOnboarding()
        else if (typeof App !== "undefined" && typeof App.setOnboardingDone === "function")
            App.setOnboardingDone(true)
        overlay.localDone = true
        if (overlay.animationsEnabled) closeAnim.restart()
        else overlay.showing = false
    }

    Component.onCompleted: {
        if (overlay.hasNeedsOnboarding) {
            if (overlay.needsOnboardingValue) overlay.showPages()
        } else if (overlay.hasBackendDone) {
            if (!overlay.backendDone) overlay.showPages()
        } else if (!overlay.localDone) {
            overlay.showPages()
        }
    }

    Shortcut {
        sequence: "Escape"
        onActivated: overlay.finishGuide()
    }

    ParallelAnimation {
        id: enterAnim
        NumberAnimation {
            target: sceneRoot
            property: "opacity"
            from: 0
            to: 1
            duration: overlay.animationsEnabled ? 260 : 0
            easing.type: Easing.OutCubic
        }
    }
    // 换页：只做透明度脉冲，避免和 anchors 抢 y（anchored 元素不能直接动画 y）
    SequentialAnimation {
        id: pageAnim
        NumberAnimation {
            target: pageArea
            property: "opacity"
            from: 0.25
            to: 1
            duration: overlay.animationsEnabled ? 200 : 0
            easing.type: Easing.OutCubic
        }
    }
    ParallelAnimation {
        id: closeAnim
        NumberAnimation {
            target: sceneRoot
            property: "opacity"
            from: 1
            to: 0
            duration: overlay.animationsEnabled ? 200 : 0
            easing.type: Easing.OutCubic
        }
        onFinished: overlay.showing = false
    }

    // ---------- 外观页：可选项数据（都从后端读，缺失时用内置） ----------
    readonly property var themeOptions: (typeof App !== "undefined" && App.themes && App.themes.length > 0)
                                        ? App.themes
                                        : [
                                              { value: "solid", label: qsTr("纯色") },
                                              { value: "light", label: qsTr("清空间浅色") },
                                              { value: "glass", label: qsTr("液态玻璃") }
                                          ]
    readonly property var fontScaleOptions: (typeof App !== "undefined" && App.uiFontScaleOptions !== undefined
                                             && App.uiFontScaleOptions !== null && App.uiFontScaleOptions.length > 0)
                                            ? App.uiFontScaleOptions : [0.85, 1.0, 1.15, 1.3]
    readonly property var navModeOptions: [
        { value: "auto", label: qsTr("自动") },
        { value: "expanded", label: qsTr("始终展开") },
        { value: "icons", label: qsTr("仅图标") }
    ]
    readonly property var languageOptions: (typeof App !== "undefined" && App.languages
                                            && App.languages !== null && App.languages.length > 1)
                                           ? App.languages
                                           : [
                                                 { code: "auto", label: qsTr("跟随系统") },
                                                 { code: "zh_CN", label: qsTr("简体中文") },
                                                 { code: "en_US", label: "English" }
                                             ]
    readonly property string currentTheme: (typeof App !== "undefined" && App.themeMode)
                                           ? String(App.themeMode) : "solid"
    readonly property real currentFontScale: (typeof App !== "undefined" && App.uiFontScale !== undefined)
                                             ? Number(App.uiFontScale) : (AppTheme.fontScale || 1)
    readonly property string currentNavMode: (typeof App !== "undefined" && App.navMode !== undefined)
                                             ? String(App.navMode) : String(AppTheme.navMode || "auto")
    readonly property string currentLanguage: (typeof App !== "undefined" && App.language !== undefined)
                                              ? String(App.language) : "auto"

    function chooseTheme(value) {
        if (typeof App !== "undefined" && typeof App.setThemeMode === "function")
            App.setThemeMode(String(value))
        AppTheme.mode = String(value)
    }
    function chooseFontScale(value) {
        if (typeof App !== "undefined" && typeof App.setUIFontScale === "function")
            App.setUIFontScale(Number(value))
        AppTheme.fontScale = Number(value)
    }
    function chooseNavMode(value) {
        if (typeof App !== "undefined" && typeof App.setNavMode === "function")
            App.setNavMode(String(value))
        if (String(value) !== "auto") AppTheme.navMode = String(value)
    }
    function chooseLanguage(code) {
        if (typeof App !== "undefined" && typeof App.setLanguage === "function")
            App.setLanguage(String(code))
    }
    function fontScaleLabel(value) {
        return Math.round(Number(value) * 100) + "%"
    }

    Item {
        id: sceneRoot
        objectName: "OnboardingRoot"
        anchors.fill: parent
        opacity: 1

        // ---------- 全屏背景：深海渐变 + 光斑 ----------
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: AppTheme.bgTop }
                GradientStop { position: 0.55; color: AppTheme.bgMid }
                GradientStop { position: 1.0; color: AppTheme.bgBottom }
            }
        }
        Rectangle {
            anchors.fill: parent
            visible: AppTheme.glass
            color: "transparent"
            Image {
                anchors.fill: parent
                source: "../assets/img/noise.png"
                fillMode: Image.Tile
                opacity: 0.08
            }
        }
        Rectangle {
            x: -160
            y: -200
            width: 620
            height: 620
            radius: 310
            color: C.waterBlue
            opacity: 0.10
        }
        Rectangle {
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.rightMargin: -160
            anchors.bottomMargin: -220
            width: 700
            height: 700
            radius: 350
            color: C.waterTeal
            opacity: 0.08
        }

        // v0.17 海洋波浪：引导页全屏分层浪花（跟随引导动画开关，低端机静态）
        WaveBackdrop {
            anchors.fill: parent
            tone: AppTheme.light ? "light" : "deep"
            intensity: 0.80
            animated: overlay.animationsEnabled && overlay.showing
            z: 0
        }

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onClicked: {}
        }

        // ---------- 顶部品牌 ----------
        Item {
            id: brandRow
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 48
            anchors.rightMargin: 48
            anchors.topMargin: 34
            height: 40

            Row {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10
                Rectangle {
                    width: 30
                    height: 30
                    radius: 10
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: "#BEEFF6" }
                        GradientStop { position: 1.0; color: "#2E9FBF" }
                    }
                    Image {
                        anchors.fill: parent
                        source: (typeof App !== "undefined" && App.appIconUrl) ? String(App.appIconUrl) : ""
                        fillMode: Image.PreserveAspectCrop
                        visible: source !== ""
                    }
                    Glyph {
                        anchors.centerIn: parent
                        visible: !(typeof App !== "undefined" && App.appIconUrl)
                        kind: "drop"; size: 17; color: "#0B2B3A"
                    }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: qsTr("深清")
                    color: AppTheme.textPrimary
                    font.pixelSize: AppTheme.fs(17)
                    font.weight: Font.DemiBold
                    font.family: AppTheme.fontFamily
                    font.letterSpacing: 2
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Clarity · " + qsTr("新手引导")
                    color: AppTheme.textTertiary
                    font.pixelSize: AppTheme.fs(11)
                    font.family: AppTheme.fontFamily
                }
            }

            Text {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                text: qsTr("%1 / %2").arg(overlay.pageIndex + 1).arg(overlay.pageCount)
                color: AppTheme.textTertiary
                font.pixelSize: AppTheme.fs(12)
                font.family: C.monoFont
            }
        }

        // ---------- 引导主体 ----------
        Item {
            id: contentBox
            anchors.horizontalCenter: parent.horizontalCenter
            y: Math.max(96, Math.round((overlay.height - height) * 0.44))
            width: Math.min(900, overlay.width - 96)
            height: Math.min(620, overlay.height - 200)

            Item {
                id: pageArea
                objectName: "OnboardingPageArea"
                anchors.left: parent.left
                anchors.right: parent.right
                y: 0
                height: parent.height - 78

                // ========== 0 欢迎 ==========
                Column {
                    anchors.centerIn: parent
                    width: parent.width
                    spacing: 18
                    visible: overlay.pageIndex === 0

                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 104
                        height: 104
                        radius: 32
                        gradient: Gradient {
                            GradientStop { position: 0.0; color: "#BEEFF6" }
                            GradientStop { position: 0.55; color: "#4FD0E0" }
                            GradientStop { position: 1.0; color: "#144F66" }
                        }
                        border.width: 1
                        border.color: "#66FFFFFF"
                        Glyph { anchors.centerIn: parent; kind: "drop"; size: 46; color: "#0B2B3A" }
                    }
                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: qsTr("欢迎使用深清")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(36)
                        font.weight: Font.Bold
                        font.family: AppTheme.fontFamily
                        font.letterSpacing: 2
                    }
                    Text {
                        width: Math.min(parent.width, 620)
                        anchors.horizontalCenter: parent.horizontalCenter
                        horizontalAlignment: Text.AlignHCenter
                        text: qsTr("选好模式与时长，时间没到不开门。深清会帮你把注意力收回来，专注记录都保存在本机。")
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(15)
                        font.family: AppTheme.fontFamily
                        wrapMode: Text.WordWrap
                        lineHeight: 1.5
                    }
                    Row {
                        anchors.horizontalCenter: parent.horizontalCenter
                        spacing: 10
                        Repeater {
                            model: [qsTr("三档空间"), qsTr("还清作息"), qsTr("清番番茄钟")]
                            delegate: Rectangle {
                                width: chipText.implicitWidth + 26
                                height: 28
                                radius: 14
                                color: AppTheme.glass ? "#1AFFFFFF" : AppTheme.chipBg
                                border.width: 1
                                border.color: AppTheme.cardBorder
                                Text {
                                    id: chipText
                                    anchors.centerIn: parent
                                    text: String(modelData)
                                    color: AppTheme.textSecondary
                                    font.pixelSize: AppTheme.fs(11)
                                    font.family: AppTheme.fontFamily
                                }
                            }
                        }
                    }
                }

                // ========== 1 外观 ==========
                Column {
                    anchors.centerIn: parent
                    width: parent.width
                    spacing: 12
                    visible: overlay.pageIndex === 1

                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: qsTr("先调成你喜欢的样子")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(30)
                        font.weight: Font.Bold
                        font.family: AppTheme.fontFamily
                        font.letterSpacing: 1
                    }
                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: qsTr("下面每一项都会立即生效，之后也可以在「设置」里继续调整。")
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(13)
                        font.family: AppTheme.fontFamily
                    }

                    Item { width: 1; height: 4 }

                    // 主题
                    Row {
                        width: parent.width
                        spacing: 12
                        Text {
                            width: 78
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("主题")
                            color: AppTheme.textSecondary
                            font.pixelSize: AppTheme.fs(13)
                            font.family: AppTheme.fontFamily
                        }
                        Repeater {
                            model: overlay.themeOptions
                            delegate: GlassButton {
                                text: String(modelData.label)
                                tone: overlay.currentTheme === String(modelData.value) ? "light" : "ghost"
                                selected: overlay.currentTheme === String(modelData.value)
                                fontSize: 12
                                padH: 16
                                minHeight: 34
                                onClicked: overlay.chooseTheme(String(modelData.value))
                            }
                        }
                    }
                    // 字号
                    Row {
                        width: parent.width
                        spacing: 12
                        Text {
                            width: 78
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("字号")
                            color: AppTheme.textSecondary
                            font.pixelSize: AppTheme.fs(13)
                            font.family: AppTheme.fontFamily
                        }
                        Repeater {
                            model: overlay.fontScaleOptions
                            delegate: GlassButton {
                                text: overlay.fontScaleLabel(modelData)
                                tone: Math.abs(Number(modelData) - overlay.currentFontScale) < 0.001 ? "light" : "ghost"
                                selected: Math.abs(Number(modelData) - overlay.currentFontScale) < 0.001
                                fontSize: 12
                                padH: 14
                                minHeight: 34
                                onClicked: overlay.chooseFontScale(Number(modelData))
                            }
                        }
                    }
                    // 导航
                    Row {
                        width: parent.width
                        spacing: 12
                        Text {
                            width: 78
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("导航")
                            color: AppTheme.textSecondary
                            font.pixelSize: AppTheme.fs(13)
                            font.family: AppTheme.fontFamily
                        }
                        Repeater {
                            model: overlay.navModeOptions
                            delegate: GlassButton {
                                text: String(modelData.label)
                                tone: overlay.currentNavMode === String(modelData.value) ? "light" : "ghost"
                                selected: overlay.currentNavMode === String(modelData.value)
                                fontSize: 12
                                padH: 14
                                minHeight: 34
                                onClicked: overlay.chooseNavMode(String(modelData.value))
                            }
                        }
                    }
                    // 语言
                    Row {
                        width: parent.width
                        spacing: 12
                        Text {
                            width: 78
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("语言")
                            color: AppTheme.textSecondary
                            font.pixelSize: AppTheme.fs(13)
                            font.family: AppTheme.fontFamily
                        }
                        Repeater {
                            model: overlay.languageOptions
                            delegate: GlassButton {
                                text: String(modelData.label)
                                tone: overlay.currentLanguage === String(modelData.code) ? "light" : "ghost"
                                selected: overlay.currentLanguage === String(modelData.code)
                                fontSize: 12
                                padH: 14
                                minHeight: 34
                                onClicked: overlay.chooseLanguage(String(modelData.code))
                            }
                        }
                    }
                }

                // ========== 2 三档空间 ==========
                Column {
                    anchors.centerIn: parent
                    width: parent.width
                    spacing: 16
                    visible: overlay.pageIndex === 2

                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: qsTr("三档空间，各有边界")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(30)
                        font.weight: Font.Bold
                        font.family: AppTheme.fontFamily
                    }
                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: qsTr("每个档位可以建多个空间，各自保存时长与白名单。")
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(13)
                        font.family: AppTheme.fontFamily
                    }

                    Row {
                        width: parent.width
                        spacing: 14
                        Repeater {
                            model: [
                                { icon: "moon", title: qsTr("浅清"), desc: qsTr("只屏蔽黑名单应用的窗口与声音。可以暂停，适合轻量专注。") },
                                { icon: "wave", title: qsTr("覆清"), desc: qsTr("屏蔽干扰，同时显示白名单 dock。不可暂停，也不可提前结束。") },
                                { icon: "lock", title: qsTr("深清"), desc: qsTr("白名单之外全部屏蔽，只保留倒计时。连点时间 10 次才能确认退出。") }
                            ]
                            delegate: Rectangle {
                                width: (parent.width - 28) / 3
                                height: 218
                                radius: 22
                                color: AppTheme.cardBg
                                border.width: 1
                                border.color: AppTheme.cardBorder

                                Column {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 20
                                    spacing: 10

                                    Rectangle {
                                        width: 44
                                        height: 44
                                        radius: 15
                                        color: AppTheme.chipBg
                                        Glyph { anchors.centerIn: parent; kind: String(modelData.icon); size: 21
                                                color: AppTheme.accent }
                                    }
                                    Text {
                                        text: String(modelData.title)
                                        color: AppTheme.textPrimary
                                        font.pixelSize: AppTheme.fs(19)
                                        font.weight: Font.Bold
                                        font.family: AppTheme.fontFamily
                                    }
                                    Text {
                                        width: parent.width
                                        text: String(modelData.desc)
                                        color: AppTheme.textSecondary
                                        font.pixelSize: AppTheme.fs(12)
                                        font.family: AppTheme.fontFamily
                                        wrapMode: Text.WordWrap
                                        lineHeight: 1.4
                                    }
                                }
                            }
                        }
                    }
                }

                // ========== 3 还清与清番 ==========
                Column {
                    anchors.centerIn: parent
                    width: parent.width
                    spacing: 16
                    visible: overlay.pageIndex === 3

                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: qsTr("还清到点，清番计时")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(30)
                        font.weight: Font.Bold
                        font.family: AppTheme.fontFamily
                    }
                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: qsTr("除了三档专注，深清还有两种更轻的节奏。")
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(13)
                        font.family: AppTheme.fontFamily
                    }

                    Row {
                        width: parent.width
                        spacing: 14
                        Repeater {
                            model: [
                                { icon: "moon", title: qsTr("还清（睡眠模式）"),
                                  desc: qsTr("按作息时间自动进入深清锁定，到点替你合上今天。可设置作息时间与每月解锁次数。"),
                                  hint: qsTr("在「空间 → 还清」里设置作息") },
                                { icon: "clock", title: qsTr("清番（置顶番茄钟）"),
                                  desc: qsTr("25 分钟专注 + 5 分钟休息，每 4 轮长休息。无边框置顶小窗，可随时暂停或关闭。"),
                                  hint: qsTr("在「空间」页右上角打开清番") }
                            ]
                            delegate: Rectangle {
                                width: (parent.width - 14) / 2
                                height: 244
                                radius: 22
                                color: AppTheme.cardBg
                                border.width: 1
                                border.color: AppTheme.cardBorder

                                Column {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.margins: 22
                                    spacing: 10

                                    Rectangle {
                                        width: 46
                                        height: 46
                                        radius: 15
                                        gradient: Gradient {
                                            GradientStop { position: 0.0; color: "#BEEFF6" }
                                            GradientStop { position: 1.0; color: "#2E9FBF" }
                                        }
                                        Glyph { anchors.centerIn: parent; kind: String(modelData.icon); size: 22
                                                color: "#0B2B3A" }
                                    }
                                    Text {
                                        text: String(modelData.title)
                                        color: AppTheme.textPrimary
                                        font.pixelSize: AppTheme.fs(19)
                                        font.weight: Font.Bold
                                        font.family: AppTheme.fontFamily
                                    }
                                    Text {
                                        width: parent.width
                                        text: String(modelData.desc)
                                        color: AppTheme.textSecondary
                                        font.pixelSize: AppTheme.fs(12)
                                        font.family: AppTheme.fontFamily
                                        wrapMode: Text.WordWrap
                                        lineHeight: 1.45
                                    }
                                    Text {
                                        width: parent.width
                                        text: String(modelData.hint)
                                        color: AppTheme.accent
                                        font.pixelSize: AppTheme.fs(11)
                                        font.family: AppTheme.fontFamily
                                    }
                                }
                            }
                        }
                    }
                }

                // ========== 4 插件 ==========
                Column {
                    anchors.centerIn: parent
                    width: parent.width
                    spacing: 14
                    visible: overlay.pageIndex === 4

                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: qsTr("插件扩展深清")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(30)
                        font.weight: Font.Bold
                        font.family: AppTheme.fontFamily
                    }
                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: qsTr("内置插件开箱可用；第三方插件可以给遮罩加组件或接入自己的统计。")
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(13)
                        font.family: AppTheme.fontFamily
                    }

                    Grid {
                        anchors.horizontalCenter: parent.horizontalCenter
                        columns: 2
                        spacing: 12
                        Repeater {
                            model: [
                                { icon: "drop", title: qsTr("卡皮巴拉敲木鱼"), desc: qsTr("专注遮罩右下角的小木鱼，敲一敲攒功德。") },
                                { icon: "clock", title: qsTr("番茄同步"), desc: qsTr("把清番的专注次数同步到今日统计。") },
                                { icon: "waveBars", title: qsTr("专注统计"), desc: qsTr("汇总累计专注次数与时长。") },
                                { icon: "grid", title: qsTr("第三方插件"), desc: qsTr("可在「插件」页启用、停用与查看插件设置。") }
                            ]
                            delegate: Rectangle {
                                width: 400
                                height: 86
                                radius: 18
                                color: AppTheme.cardBg
                                border.width: 1
                                border.color: AppTheme.cardBorder

                                Row {
                                    anchors.fill: parent
                                    anchors.margins: 16
                                    spacing: 12
                                    Rectangle {
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 40
                                        height: 40
                                        radius: 13
                                        color: AppTheme.chipBg
                                        Glyph { anchors.centerIn: parent; kind: String(modelData.icon); size: 19
                                                color: AppTheme.accent }
                                    }
                                    Column {
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: parent.width - 56
                                        spacing: 3
                                        Text {
                                            text: String(modelData.title)
                                            color: AppTheme.textPrimary
                                            font.pixelSize: AppTheme.fs(13)
                                            font.weight: Font.DemiBold
                                            font.family: AppTheme.fontFamily
                                        }
                                        Text {
                                            width: parent.width
                                            text: String(modelData.desc)
                                            color: AppTheme.textTertiary
                                            font.pixelSize: AppTheme.fs(11)
                                            font.family: AppTheme.fontFamily
                                            elide: Text.ElideRight
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // ========== 5 完成 ==========
                Column {
                    anchors.centerIn: parent
                    width: parent.width
                    spacing: 18
                    visible: overlay.pageIndex === 5

                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 96
                        height: 96
                        radius: 32
                        gradient: Gradient {
                            GradientStop { position: 0.0; color: "#BEEFF6" }
                            GradientStop { position: 1.0; color: "#2E9FBF" }
                        }
                        Glyph { anchors.centerIn: parent; kind: "check"; size: 44; color: "#0B2B3A" }
                    }
                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: qsTr("准备好了")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(34)
                        font.weight: Font.Bold
                        font.family: AppTheme.fontFamily
                    }
                    Text {
                        width: Math.min(parent.width, 620)
                        anchors.horizontalCenter: parent.horizontalCenter
                        horizontalAlignment: Text.AlignHCenter
                        text: qsTr("开始第一轮专注吧。引导可以随时在「设置 → 新手引导」里重新打开。")
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(15)
                        font.family: AppTheme.fontFamily
                        wrapMode: Text.WordWrap
                        lineHeight: 1.45
                    }
                    GlassButton {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: qsTr("进入深清")
                        tone: "light"
                        fontSize: 14
                        padH: 30
                        minHeight: 42
                        onClicked: overlay.finishGuide()
                    }
                }
            }

            // ---------- 底部：跳过 / 圆点 / 上一步 / 下一步 ----------
            Item {
                id: footer
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 54

                GlassButton {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    text: qsTr("跳过")
                    tone: "ghost"
                    fontSize: 12
                    padH: 16
                    minHeight: 34
                    onClicked: overlay.finishGuide()
                }

                Row {
                    anchors.centerIn: parent
                    spacing: 9
                    Repeater {
                        model: overlay.pageCount
                        delegate: Item {
                            width: 20
                            height: 20
                            Rectangle {
                                anchors.centerIn: parent
                                width: index === overlay.pageIndex ? 20 : 8
                                height: 8
                                radius: 4
                                color: index === overlay.pageIndex ? AppTheme.accent
                                                                   : (AppTheme.glass ? "#55FFFFFF" : AppTheme.cardBorderStrong)
                                Behavior on width { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: overlay.goToPage(index)
                            }
                        }
                    }
                }

                Row {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 10

                    GlassButton {
                        visible: overlay.pageIndex > 0
                        text: qsTr("上一步")
                        tone: "ghost"
                        fontSize: 13
                        padH: 18
                        minHeight: 38
                        onClicked: overlay.prevPage()
                    }
                    GlassButton {
                        objectName: "OnboardingNext"
                        text: overlay.pageIndex === overlay.pageCount - 1 ? qsTr("进入深清") : qsTr("下一步")
                        tone: "light"
                        fontSize: 13
                        padH: 24
                        minHeight: 38
                        onClicked: overlay.nextPage()
                    }
                }
            }
        }
    }
}
