import QtQuick
import "../theme"
import "../components"

// 主题页（v0.21）：样式（style）× 配色（scheme）两列样式卡片 + 配色 chips + 商店入口
// 样式：纯色 / 液态玻璃 / 海洋（3 张内置样式卡）+「当前样式」预览卡（第 4 张，组合文案）
// 配色：「跟随系统（系统深色）/ 浅色 / 深色」chips，点击调用 App.setThemeScheme(...)
// 样式卡点击调用 App.setThemeStyle(...)；custom:<id> 由商店安装后出现在「已安装的自定义主题」。
// 窄窗口自动变单列。
Item {
    id: page
    objectName: "ThemesPage"

    property Item glassSource: null
    // 从搜索点进来时可指定要闪亮提示的样式值 / 配色行
    property string highlightValue: ""

    signal storeRequested(string kind)

    // ---------- 样式列表（App.themeStyles，缺失时用内置兜底并保证顺序） ----------
    readonly property var styleList: {
        var raw = (typeof App !== "undefined" && App.themeStyles !== undefined && App.themeStyles !== null
                   && App.themeStyles.length > 0) ? App.themeStyles : []
        var fallback = [
            { value: "solid", name: qsTr("纯色"), desc: qsTr("平面纯色，无需 GPU 特效"), experimental: false },
            { value: "glass", name: qsTr("液态玻璃"), desc: qsTr("折射玻璃与拖拽高光（实验性）"), experimental: true },
            { value: "ocean", name: qsTr("海洋"), desc: qsTr("深海渐变与静态浪花"), experimental: false }
        ]
        var out = []
        var order = ["solid", "glass", "ocean"]
        for (var k = 0; k < order.length; k++) {
            var found = null
            for (var i = 0; i < raw.length; i++) {
                var item = raw[i]
                if (String(item.value) !== order[k]) continue
                found = {
                    value: String(item.value),
                    name: String(item.name !== undefined && item.name !== null ? item.name : item.value),
                    desc: String(item.desc !== undefined && item.desc !== null ? item.desc : ""),
                    experimental: item.experimental === true
                }
                break
            }
            out.push(found !== null ? found : fallback[k])
        }
        return out
    }

    // ---------- 配色列表（App.themeSchemes：auto / light / dark） ----------
    readonly property var schemeList: {
        var raw = (typeof App !== "undefined" && App.themeSchemes !== undefined && App.themeSchemes !== null
                   && App.themeSchemes.length > 0) ? App.themeSchemes : []
        var fallback = [
            { value: "auto", name: qsTr("跟随系统") },
            { value: "light", name: qsTr("浅色") },
            { value: "dark", name: qsTr("深色") }
        ]
        if (raw.length < 3) return fallback
        var out = []
        for (var i = 0; i < raw.length; i++) {
            var item = raw[i]
            out.push({
                value: String(item.value),
                name: String(item.name !== undefined && item.name !== null ? item.name : item.value)
            })
        }
        return out
    }

    // ---------- 当前状态（样式 / 配置配色 / 实际配色 / 系统配色） ----------
    readonly property string currentStyle: (typeof App !== "undefined" && App.themeStyle)
                                           ? String(App.themeStyle) : "solid"
    readonly property string currentScheme: (typeof App !== "undefined" && App.themeScheme)
                                            ? String(App.themeScheme) : "auto"
    readonly property string effectiveScheme: (typeof App !== "undefined" && App.effectiveScheme)
                                              ? String(App.effectiveScheme) : "dark"
    readonly property string systemScheme: (typeof App !== "undefined" && App.systemScheme)
                                           ? String(App.systemScheme) : page.effectiveScheme

    readonly property var customThemes: (typeof App !== "undefined" && App.customThemes !== undefined
                                         && App.customThemes !== null) ? App.customThemes : []

    // ---------- 文案 ----------
    function styleLabel(value) {
        var v = String(value === undefined || value === null ? "" : value)
        if (v.indexOf("custom:") === 0) {
            var themeId = v.substring(7)
            var list = page.customThemes
            for (var c = 0; c < list.length; c++) {
                if (String(list[c].id) === themeId) return String(list[c].name)
            }
            return qsTr("自定义主题")
        }
        var styles = page.styleList
        for (var i = 0; i < styles.length; i++) {
            if (String(styles[i].value) === v) return String(styles[i].name)
        }
        return v
    }

    function schemeLabel(value) {
        var v = String(value === undefined || value === null ? "" : value)
        var schemes = page.schemeList
        for (var i = 0; i < schemes.length; i++) {
            if (String(schemes[i].value) === v) return String(schemes[i].name)
        }
        if (v === "light") return qsTr("浅色")
        if (v === "dark") return qsTr("深色")
        return qsTr("跟随系统")
    }

    // 配色 chips 文案：「跟随系统（系统深色）」把当前系统深浅提示出来
    function schemeChipLabel(value) {
        var v = String(value)
        var name = page.schemeLabel(v)
        if (v === "auto") return qsTr("%1（系统%2）").arg(name).arg(page.schemeLabel(page.systemScheme))
        return name
    }

    readonly property string currentStyleLabel: page.styleLabel(page.currentStyle)
    // 组合文案：「纯色 · 跟随系统(深色)」/「液态玻璃 · 浅色」
    readonly property string combinedLabel: {
        var base = page.currentStyleLabel
        if (page.currentScheme === "auto")
            return qsTr("%1 · 跟随系统(%2)").arg(base).arg(page.schemeLabel(page.effectiveScheme))
        return qsTr("%1 · %2").arg(base).arg(page.schemeLabel(page.currentScheme))
    }

    // ---------- 卡片数据（两列：纯色 / 液态玻璃 / 海洋 + 当前样式） ----------
    function styleCard(value) {
        var styles = page.styleList
        var item = null
        for (var i = 0; i < styles.length; i++) {
            if (String(styles[i].value) === String(value)) item = styles[i]
        }
        if (item === null) item = { value: value, name: value, desc: "", experimental: false }
        return {
            kind: "style",
            value: String(item.value),
            label: String(item.name),
            desc: String(item.desc),
            experimental: item.experimental === true,
            isCurrent: page.currentStyle === String(item.value)
        }
    }

    function currentCard() {
        return {
            kind: "current",
            value: page.currentStyle,
            label: qsTr("当前样式"),
            desc: page.combinedLabel,
            experimental: false,
            isCurrent: true
        }
    }

    readonly property var gridCards: [
        page.styleCard("solid"),
        page.styleCard("glass"),
        page.styleCard("ocean"),
        page.currentCard()
    ]

    // ---------- 选择动作 ----------
    function selectStyle(value) {
        var v = String(value)
        if (v === page.currentStyle) {
            page.showToast(qsTr("当前已是 %1").arg(page.combinedLabel))
            return
        }
        if (typeof App !== "undefined" && typeof App.setThemeStyle === "function")
            App.setThemeStyle(v)
        else if (typeof App !== "undefined" && typeof App.setThemeMode === "function")
            App.setThemeMode(v)
        page.highlightValue = v
        page.showToast(qsTr("已切换到 %1").arg(page.styleLabel(v)))
    }

    function selectScheme(value) {
        var v = String(value)
        if (v === page.currentScheme) {
            page.showToast(qsTr("当前配色已是 %1").arg(page.schemeLabel(v)))
            return
        }
        if (typeof App !== "undefined" && typeof App.setThemeScheme === "function")
            App.setThemeScheme(v)
        else if (typeof App !== "undefined" && typeof App.setThemeMode === "function")
            App.setThemeMode(v)
        page.flashSchemeRow()
        if (v === "auto")
            page.showToast(qsTr("配色：跟随系统（%1）").arg(page.schemeLabel(page.systemScheme)))
        else
            page.showToast(qsTr("配色已切换为 %1").arg(page.schemeLabel(v)))
    }

    function selectCard(card) {
        if (!card) return
        if (card.kind === "current") {
            page.showToast(qsTr("当前已是 %1").arg(page.combinedLabel))
            return
        }
        page.selectStyle(String(card.value))
    }

    function selectCustomTheme(themeId) {
        var v = "custom:" + String(themeId)
        if (v === page.currentStyle) {
            page.showToast(qsTr("当前已是 %1").arg(page.combinedLabel))
            return
        }
        if (typeof App !== "undefined" && typeof App.setThemeStyle === "function")
            App.setThemeStyle(v)
        else if (typeof App !== "undefined" && typeof App.setThemeMode === "function")
            App.setThemeMode(v)
        page.showToast(qsTr("已切换到 %1").arg(page.styleLabel(v)))
    }

    // ================= 两列 / 单列网格尺寸 =================
    readonly property int gridColumns: pageColumn.width < 760 ? 1 : 2
    readonly property real gridGap: 12
    readonly property real gridCardHeight: 108
    readonly property real gridCardWidth: page.gridColumns === 1
                                           ? pageColumn.width
                                           : (pageColumn.width - page.gridGap) / 2
    readonly property real gridHeight: page.gridColumns === 1
                                        ? 4 * page.gridCardHeight + 3 * page.gridGap
                                        : 2 * page.gridCardHeight + page.gridGap

    function gridCardX(index) {
        if (page.gridColumns === 1) return 0
        return (index % 2) * (page.gridCardWidth + page.gridGap)
    }

    function gridCardY(index) {
        if (page.gridColumns === 1) return index * (page.gridCardHeight + page.gridGap)
        return Math.floor(index / 2) * (page.gridCardHeight + page.gridGap)
    }

    function gridIndexFor(value) {
        var cards = page.gridCards
        for (var i = 0; i < cards.length; i++) {
            if (cards[i].kind === "current") continue
            if (String(cards[i].value) === String(value)) return i
        }
        return -1
    }

    // ================= 轻提示（当前样式卡 / chips 点击） =================
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

    // 搜索结果里的「主题配色」：闪一下配色 chips 行
    function flashSchemeRow() {
        schemeFlashAnim.restart()
    }

    Flickable {
        id: flick
        objectName: "ThemesFlick"
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

                // 海洋样式的波浪页头底纹（静态；其它样式自动隐藏）
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
                        text: qsTr("样式决定质感与强调色，配色决定明暗；两者独立生效")
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
                        text: qsTr("当前：%1").arg(page.combinedLabel)
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(12)
                        font.family: AppTheme.fontFamily
                    }
                }
            }

            // ---------- 配色 chips ----------
            GlassCard {
                width: parent.width
                implicitHeight: schemeColumn.implicitHeight + 32
                height: implicitHeight
                radius: 20
                interactive: false
                glassSource: page.glassSource

                Column {
                    id: schemeColumn
                    x: 18
                    y: 16
                    width: parent.width - 36
                    spacing: 10

                    Item {
                        width: parent.width
                        height: 22

                        Text {
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("配色")
                            color: AppTheme.textPrimary
                            font.pixelSize: AppTheme.fs(14)
                            font.weight: Font.DemiBold
                            font.family: AppTheme.fontFamily
                        }
                        Text {
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("当前生效：%1").arg(page.schemeLabel(page.effectiveScheme))
                            color: AppTheme.textTertiary
                            font.pixelSize: AppTheme.fs(11)
                            font.family: AppTheme.fontFamily
                        }
                    }

                    // chips 行 +「配色行高亮」放在同一个 Item 里：
                    // Column 内的子项不能再用 fill/verticalCenter 锚点，所以高亮框改相对 Row 定位。
                    Item {
                        id: schemeRowHost
                        width: parent.width
                        height: schemeChips.height

                        Row {
                            id: schemeChips
                            spacing: 8

                            Repeater {
                                model: page.schemeList

                                delegate: Rectangle {
                                    id: schemeChip
                                    objectName: "SchemeChip_" + String(modelData.value)
                                    readonly property bool selectedChip: page.currentScheme === String(modelData.value)
                                    width: schemeChipLabelText.implicitWidth + 30
                                    height: 34
                                    radius: 17
                                    color: schemeChip.selectedChip
                                           ? Qt.rgba(AppTheme.accent.r, AppTheme.accent.g, AppTheme.accent.b, 0.16)
                                           : (schemeChipArea.containsMouse ? AppTheme.cardBgAlt : AppTheme.chipBg)
                                    border.width: 1
                                    border.color: schemeChip.selectedChip ? AppTheme.accent : AppTheme.cardBorder
                                    Behavior on color { ColorAnimation { duration: 140 } }

                                    Row {
                                        anchors.centerIn: parent
                                        spacing: 6

                                        Rectangle {
                                            visible: schemeChip.selectedChip
                                            width: 6
                                            height: 6
                                            radius: 3
                                            anchors.verticalCenter: parent.verticalCenter
                                            color: AppTheme.accent
                                        }
                                        Text {
                                            id: schemeChipLabelText
                                            text: page.schemeChipLabel(String(modelData.value))
                                            color: schemeChip.selectedChip ? AppTheme.accent : AppTheme.textSecondary
                                            font.pixelSize: AppTheme.fs(12)
                                            font.family: AppTheme.fontFamily
                                        }
                                    }

                                    MouseArea {
                                        id: schemeChipArea
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: page.selectScheme(String(modelData.value))
                                    }
                                }
                            }
                        }

                        // 配色行高亮（搜索结果「主题配色」进来时闪一下）
                        Rectangle {
                            id: schemeFlash
                            x: -5
                            y: -5
                            width: schemeChips.width + 10
                            height: schemeChips.height + 10
                            radius: 22
                            color: "transparent"
                            border.width: 2
                            border.color: AppTheme.accent
                            opacity: 0
                            visible: opacity > 0.01

                            SequentialAnimation {
                                id: schemeFlashAnim
                                NumberAnimation { target: schemeFlash; property: "opacity"; to: 0.85; duration: 140 }
                                NumberAnimation { target: schemeFlash; property: "opacity"; to: 0; duration: 420 }
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        text: qsTr("「跟随系统」会随 Windows 的浅色/深色自动切换；换样式不会改变明暗。")
                        color: AppTheme.textTertiary
                        font.pixelSize: AppTheme.fs(10)
                        font.family: AppTheme.fontFamily
                        wrapMode: Text.WordWrap
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

            // ---------- 样式网格（两列 / 窄窗口单列） ----------
            Item {
                id: gridHost
                width: parent.width
                height: page.gridHeight

                Repeater {
                    model: page.gridCards

                    delegate: GlassCard {
                        id: themeCard
                        objectName: "StyleCard_" + String(modelData.kind === "current"
                                                          ? "current" : modelData.value)
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
                                style: modelData.kind === "current" ? String(AppTheme.style) : String(modelData.value)
                                live: modelData.kind === "current"
                                scheme: page.effectiveScheme
                                corner: 12
                                borderColor: AppTheme.glass ? AppTheme.hairlineStrong : AppTheme.cardBorder
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
                                    border.color: AppTheme.glass ? AppTheme.hairlineStrong : AppTheme.cardBorderStrong
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

            // ---------- 已安装的自定义主题（来自商店） ----------
            Item {
                width: parent.width
                height: page.customThemes.length > 0 ? customTitle.height + 10 + customGrid.height : 0
                visible: page.customThemes.length > 0

                Text {
                    id: customTitle
                    text: qsTr("已安装的自定义主题")
                    color: AppTheme.textPrimary
                    font.pixelSize: AppTheme.fs(14)
                    font.weight: Font.DemiBold
                    font.family: AppTheme.fontFamily
                }

                Flow {
                    id: customGrid
                    anchors.top: customTitle.bottom
                    anchors.topMargin: 10
                    width: parent.width
                    spacing: 12

                    Repeater {
                        model: page.customThemes

                        delegate: GlassCard {
                            readonly property string themeId: String(modelData.id)
                            width: page.gridCardWidth
                            height: 76
                            radius: 18
                            interactive: true
                            selected: page.currentStyle === "custom:" + themeId
                            accentTint: AppTheme.accent
                            glassSource: page.glassSource
                            onClicked: page.selectCustomTheme(themeId)

                            Row {
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 12

                                ThemePalettePreview {
                                    width: 44
                                    height: 44
                                    anchors.verticalCenter: parent.verticalCenter
                                    style: "custom"
                                    themePalette: modelData.palette !== undefined ? modelData.palette : ({})
                                    corner: 10
                                    borderColor: AppTheme.glass ? AppTheme.hairlineStrong : AppTheme.cardBorder
                                }

                                Column {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width - 44 - 12
                                    spacing: 4

                                    Text {
                                        width: parent.width
                                        text: String(modelData.name)
                                        color: AppTheme.textPrimary
                                        font.pixelSize: AppTheme.fs(13)
                                        font.weight: Font.DemiBold
                                        font.family: AppTheme.fontFamily
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        width: parent.width
                                        text: String(modelData.description !== undefined ? modelData.description : "")
                                        color: AppTheme.textTertiary
                                        font.pixelSize: AppTheme.fs(10)
                                        font.family: AppTheme.fontFamily
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // ---------- 页脚提示 ----------
            Text {
                width: parent.width
                text: qsTr("样式与配色互相独立：纯色看平面、液态玻璃看折射、海洋看浪花；深浅交给配色。")
                color: AppTheme.textTertiary
                font.pixelSize: AppTheme.fs(10)
                font.family: AppTheme.fontFamily
                wrapMode: Text.WordWrap
            }

            Item { width: parent.width; height: 2 }
        }
    }

    // 从搜索点进来时，闪一下被点名的样式（纯视觉提示，不改设置）
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
        color: AppTheme.glass ? AppTheme.cardOverlayHover
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
