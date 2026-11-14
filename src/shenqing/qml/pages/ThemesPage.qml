import QtQuick
import "../theme"
import "../components"
import "../components/Constants.js" as C

// 主题页（v0.18）：商店入口 + 两列主题网格
// 左列：清空间浅色 / 深色（纯色）/ 液态玻璃
// 右列：当前样式（动态跟随 App.themeMode）/ 海洋
// 「当前样式」不是第 5 个独立主题，只是当前生效主题的预览卡（点击提示当前已用）。
// 窄窗口自动变单列。
Item {
    id: page

    property Item glassSource: null
    // 从搜索点进来时可指定要闪亮提示的主题值
    property string highlightValue: ""

    signal storeRequested(string kind)

    // 内置主题：solid / light / glass / ocean（海洋为 v0.17 新增的第 4 个内置主题）
    readonly property var themes: {
        var list = (typeof App !== "undefined" && App.themes && App.themes.length > 0)
                   ? App.themes
                   : [
                         { value: "solid", label: qsTr("深色"), desc: qsTr("纯色深色背景，无需 GPU 特效"), experimental: false },
                         { value: "light", label: qsTr("清空间浅色"), desc: qsTr("浅色底的清空间主题"), experimental: false },
                         { value: "glass", label: qsTr("液态玻璃"), desc: qsTr("折射玻璃与拖拽高光（实验性）"), experimental: true },
                         { value: "ocean", label: qsTr("海洋"), desc: qsTr("深海渐变与静态浪花"), experimental: false }
                     ]
        var out = []
        var haveLight = false
        var haveSolid = false
        var haveGlass = false
        var haveOcean = false
        for (var i = 0; i < list.length; i++) {
            var value = String(list[i].value)
            if (value === "light") haveLight = true
            else if (value === "solid") haveSolid = true
            else if (value === "glass") haveGlass = true
            else if (value === "ocean") haveOcean = true
            out.push(list[i])
        }
        // 兼容旧后端：缺哪个就本地补一张，选中仍走 App.setThemeMode(...)
        if (!haveLight) out.push({ value: "light", label: qsTr("清空间浅色"), desc: qsTr("浅色底的清空间主题"), experimental: false })
        if (!haveSolid) out.push({ value: "solid", label: qsTr("深色"), desc: qsTr("纯色深色背景，无需 GPU 特效"), experimental: false })
        if (!haveGlass) out.push({ value: "glass", label: qsTr("液态玻璃"), desc: qsTr("折射玻璃与拖拽高光（实验性）"), experimental: true })
        if (!haveOcean) out.push({ value: "ocean", label: qsTr("海洋"), desc: qsTr("深海渐变与静态浪花"), experimental: false })
        return out
    }

    readonly property string currentTheme: (typeof App !== "undefined" && App.themeMode)
                                           ? String(App.themeMode) : "solid"

    // 当前主题名称：内置主题取 App.themes；custom:<id> 取已安装主题包的名字
    readonly property string currentThemeLabel: {
        var mode = page.currentTheme
        if (mode.indexOf("custom:") === 0) {
            var themeId = mode.substring(7)
            var customList = (typeof App !== "undefined" && App.customThemes) ? App.customThemes : []
            for (var c = 0; c < customList.length; c++) {
                if (String(customList[c].id) === themeId) return String(customList[c].name)
            }
            return qsTr("自定义主题")
        }
        // 网格里 solid 显示为「深色」，当前样式名保持一致
        if (mode === "solid") return qsTr("深色")
        var list = page.themes
        for (var i = 0; i < list.length; i++) {
            if (String(list[i].value) === mode) return String(list[i].label)
        }
        return mode
    }

    function themeEntry(value) {
        var list = page.themes
        for (var i = 0; i < list.length; i++) {
            if (String(list[i].value) === value) return list[i]
        }
        return ({ value: value, label: value, desc: "", experimental: false })
    }

    function cardFor(value, labelOverride, descOverride) {
        var item = page.themeEntry(value)
        return ({
            value: value,
            label: (labelOverride !== undefined) ? labelOverride : String(item.label),
            desc: (descOverride !== undefined) ? descOverride : String(item.desc !== undefined ? item.desc : ""),
            experimental: item.experimental === true,
            isCurrent: page.currentTheme === value,
            live: false
        })
    }

    function currentCard() {
        return ({
            value: page.currentTheme,
            label: qsTr("当前样式"),
            desc: qsTr("正在使用：%1").arg(page.currentThemeLabel),
            experimental: false,
            isCurrent: true,
            live: true
        })
    }

    // 列优先：左列 3 张，右列 2 张（当前样式 / 海洋）
    readonly property var gridCards: [
        page.cardFor("light"),
        page.cardFor("solid", qsTr("深色"), qsTr("纯色深色背景，无需 GPU 特效")),
        page.cardFor("glass"),
        page.currentCard(),
        page.cardFor("ocean")
    ]

    function selectTheme(value) {
        page.highlightValue = String(value)
        if (typeof App !== "undefined" && typeof App.setThemeMode === "function")
            App.setThemeMode(String(value))
    }

    function selectCard(card) {
        if (!card) return
        if (card.isCurrent === true) {
            page.showToast(qsTr("当前已在使用这个样式"))
            return
        }
        page.selectTheme(String(card.value))
    }

    // ================= 两列 / 单列网格尺寸 =================
    readonly property int gridColumns: pageColumn.width < 760 ? 1 : 2
    readonly property real gridGap: 12
    readonly property real gridCardHeight: 108
    readonly property real gridCardWidth: page.gridColumns === 1
                                           ? pageColumn.width
                                           : (pageColumn.width - page.gridGap) / 2
    readonly property real gridHeight: page.gridColumns === 1
                                       ? 5 * page.gridCardHeight + 4 * page.gridGap
                                       : 3 * page.gridCardHeight + 2 * page.gridGap

    function gridCardX(index) {
        if (page.gridColumns === 1) return 0
        return index < 3 ? 0 : page.gridCardWidth + page.gridGap
    }

    function gridCardY(index) {
        if (page.gridColumns === 1) return index * (page.gridCardHeight + page.gridGap)
        return (index < 3 ? index : index - 3) * (page.gridCardHeight + page.gridGap)
    }

    function gridIndexFor(value) {
        var cards = page.gridCards
        for (var i = 0; i < cards.length; i++) {
            if (cards[i].live === true) continue
            if (String(cards[i].value) === String(value)) return i
        }
        return -1
    }

    // ================= 轻提示（当前样式卡点击） =================
    property string toastText: ""
    property bool toastVisible: false

    function showToast(text) {
        if (!text) return
        page.toastText = String(text)
        page.toastVisible = true
        themeToastTimer.restart()
    }

    Timer {
        id: themeToastTimer
        interval: 2000
        repeat: false
        onTriggered: page.toastVisible = false
    }

    Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: pageColumn.height + 64
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
            id: pageColumn
            width: Math.min(flick.width - 96, 900)
            x: (flick.width - width) / 2
            y: 26
            spacing: 16

            // ---------- 页头 ----------
            Item {
                width: parent.width
                height: 76

                // v0.17 海洋波浪页头底纹（静态，避免多页同时动画）
                WaveBackdrop {
                    x: -(page.width - parent.width) / 2
                    width: page.width
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.topMargin: -10
                    anchors.bottomMargin: -78
                    tone: AppTheme.light ? "light" : "deep"
                    intensity: 0.55
                    z: -1
                }

                Column {
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    spacing: 6
                    Text {
                        text: qsTr("主题")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(30)
                        font.weight: Font.Bold
                        font.family: AppTheme.fontFamily
                        font.letterSpacing: 1
                    }
                    Text {
                        text: qsTr("外观风格会立即生效；顶栏、导航与卡片都会跟着切换")
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(13)
                        font.family: AppTheme.fontFamily
                    }
                }

                Row {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 6
                    spacing: 6

                    Rectangle {
                        width: 7
                        height: 7
                        radius: 3.5
                        anchors.verticalCenter: parent.verticalCenter
                        color: AppTheme.accent
                    }
                    Text {
                        text: qsTr("当前：%1").arg(page.currentThemeLabel)
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(12)
                        font.family: AppTheme.fontFamily
                    }
                }
            }

            // ---------- 主题商店入口 ----------
            StoreEntryBanner {
                width: parent.width
                glassSource: page.glassSource
                title: qsTr("主题商店")
                subtitle: qsTr("发现更多配色与浪花")
                iconKind: "sparkle"
                onClicked: page.storeRequested("theme")
            }

            // ---------- 主题网格（两列 / 窄窗口单列） ----------
            Item {
                id: gridHost
                width: parent.width
                height: page.gridHeight

                Repeater {
                    model: page.gridCards

                    delegate: GlassCard {
                        id: themeCard
                        x: page.gridCardX(index)
                        y: page.gridCardY(index)
                        width: page.gridCardWidth
                        height: page.gridCardHeight
                        radius: 20
                        interactive: true
                        selected: modelData.isCurrent === true
                        accentTint: AppTheme.accent
                        glassSource: page.glassSource
                        onClicked: page.selectCard(modelData)

                        Item {
                            anchors.fill: parent
                            anchors.margins: 14

                            // 左侧预览缩略：当前样式卡直接跟随 AppTheme 当前配色
                            ThemePalettePreview {
                                id: previewBox
                                width: 58
                                height: 58
                                anchors.verticalCenter: parent.verticalCenter
                                style: modelData.live === true ? "custom" : String(modelData.value)
                                live: modelData.live === true
                                corner: 12
                                borderColor: AppTheme.glass ? "#33FFFFFF" : AppTheme.cardBorder
                            }

                            // 文字
                            Column {
                                anchors.left: previewBox.right
                                anchors.leftMargin: 12
                                anchors.right: currentBadge.left
                                anchors.rightMargin: 8
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 5

                                Row {
                                    spacing: 6

                                    Text {
                                        text: String(modelData.label)
                                        color: AppTheme.textPrimary
                                        font.pixelSize: AppTheme.fs(15)
                                        font.weight: Font.DemiBold
                                        font.family: AppTheme.fontFamily
                                        elide: Text.ElideRight
                                    }

                                    Rectangle {
                                        visible: modelData.experimental === true
                                        width: experimentalText.implicitWidth + 12
                                        height: 17
                                        radius: 8.5
                                        anchors.verticalCenter: parent.verticalCenter
                                        color: AppTheme.glass ? "#26FFB86B" : "#FFF3E2"
                                        border.width: 1
                                        border.color: AppTheme.glass ? "#66FFB86B" : "#F0C48A"

                                        Text {
                                            id: experimentalText
                                            anchors.centerIn: parent
                                            text: qsTr("实验性")
                                            color: AppTheme.glass ? "#FFD9A6" : "#9A5B12"
                                            font.pixelSize: AppTheme.fs(9)
                                            font.family: AppTheme.fontFamily
                                        }
                                    }

                                    Rectangle {
                                        visible: modelData.isCurrent === true
                                        width: currentText.implicitWidth + 12
                                        height: 17
                                        radius: 8.5
                                        anchors.verticalCenter: parent.verticalCenter
                                        color: AppTheme.glass ? "#2A4FD0E0" : "#E4F4F2"
                                        border.width: 1
                                        border.color: AppTheme.accent

                                        Text {
                                            id: currentText
                                            anchors.centerIn: parent
                                            text: qsTr("使用中")
                                            color: AppTheme.accent
                                            font.pixelSize: AppTheme.fs(9)
                                            font.family: AppTheme.fontFamily
                                        }
                                    }
                                }

                                Text {
                                    width: parent.width
                                    height: 26
                                    text: String(modelData.desc)
                                    color: AppTheme.textSecondary
                                    font.pixelSize: AppTheme.fs(11)
                                    font.family: AppTheme.fontFamily
                                    wrapMode: Text.WordWrap
                                    maximumLineCount: 2
                                    elide: Text.ElideRight
                                    lineHeight: 1.15
                                }
                            }

                            // 右侧选中标记
                            Item {
                                id: currentBadge
                                width: 30
                                height: 30
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter

                                Rectangle {
                                    anchors.fill: parent
                                    radius: 15
                                    visible: modelData.isCurrent === true
                                    color: AppTheme.accent
                                }

                                Rectangle {
                                    anchors.fill: parent
                                    radius: 15
                                    visible: modelData.isCurrent !== true
                                    color: "transparent"
                                    border.width: 1
                                    border.color: AppTheme.glass ? "#2EFFFFFF" : AppTheme.cardBorderStrong
                                }

                                Glyph {
                                    anchors.centerIn: parent
                                    kind: modelData.isCurrent === true ? "check" : "chevron"
                                    size: 14
                                    color: modelData.isCurrent === true ? AppTheme.onAccent : AppTheme.textTertiary
                                }
                            }
                        }
                    }
                }
            }

            Item { width: parent.width; height: 2 }
        }
    }

    // 从搜索点进来时，闪一下被点名的主题（纯视觉提示，不改设置）
    Rectangle {
        id: flashRing
        visible: page.highlightValue !== "" && page.gridIndexFor(page.highlightValue) >= 0
        width: page.gridCardWidth
        height: page.gridCardHeight
        radius: 20
        x: pageColumn.x + page.gridCardX(page.gridIndexFor(page.highlightValue))
        color: "transparent"
        border.width: 2
        border.color: AppTheme.accent
        opacity: 0
        y: pageColumn.y + gridHost.y + page.gridCardY(page.gridIndexFor(page.highlightValue)) - flick.contentY

        SequentialAnimation {
            running: flashRing.visible
            loops: 1
            NumberAnimation { target: flashRing; property: "opacity"; to: 0.8; duration: 160 }
            NumberAnimation { target: flashRing; property: "opacity"; to: 0; duration: 420 }
            onFinished: page.highlightValue = ""
        }
    }

    // 轻提示
    Rectangle {
        id: themeToast
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 26
        width: themeToastLabel.implicitWidth + 34
        height: 38
        radius: 19
        color: AppTheme.glass ? "#D90A1B26"
                             : Qt.rgba(AppTheme.cardBg.r, AppTheme.cardBg.g, AppTheme.cardBg.b, 0.96)
        border.width: 1
        border.color: AppTheme.cardBorderStrong
        opacity: page.toastVisible ? 1 : 0
        visible: opacity > 0.01
        z: 50
        Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

        Text {
            id: themeToastLabel
            anchors.centerIn: parent
            text: page.toastText
            color: AppTheme.textPrimary
            font.pixelSize: AppTheme.fs(12)
            font.family: AppTheme.fontFamily
        }
    }
}
