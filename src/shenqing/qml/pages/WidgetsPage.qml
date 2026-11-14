import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window
import "../theme"
import "../components"
import "../components/widgets"
import "../components/Constants.js" as C

// v24「组件与布局」页：左侧组件库 + 已添加列表，右侧「右半屏预览」画布。
// - 预览画布按锁屏右半屏比例（屏宽 50% × 屏高）等比缩放，组件按 App.overlayWidgets 的
//   x/y/w/h（右半屏自身 0~1 归一化）渲染；拖动改 x/y、右下角拖拽改 w/h，吸附 0.02 网格。
// - 后端接口（全部 typeof 兜底，缺失时用本地演示布局，页面仍可操作）：
//   App.overlayWidgets / overlayWidgetsEnabled / widgetDataChanged、
//   App.updateOverlayWidget(id, patch) / addOverlayWidget(type) / removeOverlayWidget(id) /
//   resetOverlayWidgets() / refreshWidgetData()。
Item {
    id: page

    property Item glassSource: null

    // 返回上一页（设置页）——由宿主连接
    signal backRequested()

    objectName: "WidgetsPage"

    // ================= 后端接口探测（防御式） =================
    readonly property bool backendReady: (typeof App !== "undefined"
                                          && App.overlayWidgets !== undefined)
    // patch 槽：优先 updateOverlayWidgetJson(str, jsonStr)；旧版回退 updateOverlayWidget。
    // 注意 QML 侧只能传 JSON 字符串 —— PySide 的 @Slot(str, object) 在 QML 里不可调用。
    readonly property bool hasUpdateApi: (typeof App !== "undefined"
                                          && (typeof App.updateOverlayWidgetJson === "function"
                                              || typeof App.updateOverlayWidget === "function"))
    readonly property bool hasAddApi: (typeof App !== "undefined"
                                       && typeof App.addOverlayWidget === "function")
    readonly property bool hasRemoveApi: (typeof App !== "undefined"
                                          && typeof App.removeOverlayWidget === "function")
    readonly property bool hasResetApi: (typeof App !== "undefined"
                                         && typeof App.resetOverlayWidgets === "function")
    readonly property bool hasRefreshApi: (typeof App !== "undefined"
                                           && typeof App.refreshWidgetData === "function")

    // 本地兜底布局（后端缺失 / 保存失败时仍能演示与编辑）
    property var localItems: catalog.demoLayout()
    property bool localEnabled: true

    readonly property var sourceLayout: page.backendReady
                                        ? catalog.normalizeLayout(App.overlayWidgets)
                                        : catalog.normalizeLayout(page.localItems)
    // 拖动过程中的临时覆盖（松手提交后清空）
    property var pendingPatch: ({})
    readonly property var items: page.applyPatch(page.sourceLayout, page.pendingPatch)

    readonly property bool enabledValue: page.backendReady
                                         ? (App.overlayWidgetsEnabled === true)
                                         : page.localEnabled
    readonly property int widgetCount: page.items.length
    readonly property int maxWidgets: catalog.maxWidgets
    readonly property bool full: page.widgetCount >= page.maxWidgets

    // ================= 页面状态 =================
    property string selectedId: ""
    property bool addMenuOpen: false
    property string statusText: ""
    property bool statusIsError: false

    function flashStatus(text, isError) {
        page.statusText = String(text)
        page.statusIsError = isError === true
        statusTimer.restart()
    }

    Timer {
        id: statusTimer
        interval: 3200
        repeat: false
        onTriggered: page.statusText = ""
    }

    // 整页背景：与主界面同款渐变底，避免透出下层设置页内容
    Backdrop {
        anchors.fill: parent
        z: -10
    }

    WidgetCatalog { id: catalog }

    // ================= 布局数据工具 =================
    function applyPatch(base, patch) {
        var out = []
        for (var i = 0; i < base.length; i++) {
            var entry = base[i]
            var patchEntry = (patch !== null && patch !== undefined) ? patch[entry.id] : undefined
            if (patchEntry === undefined) {
                out.push(entry)
            } else {
                out.push({
                    id: entry.id,
                    type: entry.type,
                    x: patchEntry.x !== undefined ? patchEntry.x : entry.x,
                    y: patchEntry.y !== undefined ? patchEntry.y : entry.y,
                    w: patchEntry.w !== undefined ? patchEntry.w : entry.w,
                    h: patchEntry.h !== undefined ? patchEntry.h : entry.h,
                    visible: entry.visible,
                    props: entry.props
                })
            }
        }
        return out
    }

    function entryById(id) {
        for (var i = 0; i < page.items.length; i++) {
            if (page.items[i].id === String(id)) return page.items[i]
        }
        return null
    }

    function clampedGeometry(id, x, y, w, h) {
        var minimum = catalog.minSize
        var width = catalog.clamp(catalog.snap(w), minimum, 1.0)
        var height = catalog.clamp(catalog.snap(h), minimum, 1.0)
        var left = catalog.clamp(catalog.snap(x), 0, 1)
        var top = catalog.clamp(catalog.snap(y), 0, 1)
        if (left + width > 1) left = catalog.round2(Math.max(0, 1 - width))
        if (top + height > 1) top = catalog.round2(Math.max(0, 1 - height))
        return { id: String(id), x: left, y: top, w: width, h: height }
    }

    // 写布局补丁：QML 侧统一传 JSON 字符串（PySide 的 @Slot(str, object) 无法从 QML 调用）
    function pushPatch(id, data) {
        var json = JSON.stringify(data)
        if (typeof App.updateOverlayWidgetJson === "function")
            return App.updateOverlayWidgetJson(String(id), json) !== false
        if (typeof App.updateOverlayWidget === "function")
            return App.updateOverlayWidget(String(id), json) !== false
        return false
    }

    // 松手提交：优先写后端；后端缺失时写本地演示布局
    function commitGeometry(id, x, y, w, h) {
        var geo = page.clampedGeometry(id, x, y, w, h)
        if (page.hasUpdateApi) {
            var ok = page.pushPatch(id, { x: geo.x, y: geo.y, w: geo.w, h: geo.h })
            page.pendingPatch = ({})
            if (!ok) {
                page.flashStatus(qsTr("保存失败：布局未更新"), true)
            }
            return
        }
        if (!page.backendReady) {
            var list = []
            for (var i = 0; i < page.localItems.length; i++) {
                var entry = page.localItems[i]
                if (String(entry.id) === String(id)) {
                    list.push({
                        id: entry.id,
                        type: entry.type,
                        x: geo.x,
                        y: geo.y,
                        w: geo.w,
                        h: geo.h,
                        visible: entry.visible !== false,
                        props: entry.props !== undefined ? entry.props : ({})
                    })
                } else {
                    list.push(entry)
                }
            }
            page.localItems = list
            page.pendingPatch = ({})
            return
        }
        page.pendingPatch = ({})
        page.flashStatus(qsTr("缺少接口：App.updateOverlayWidget"), true)
    }

    function selectWidget(id) {
        page.selectedId = String(id)
    }

    function toggleVisible(id) {
        var entry = page.entryById(id)
        if (entry === null) return
        var next = !(entry.visible !== false)
        if (page.hasUpdateApi) {
            page.pushPatch(id, { visible: next })
            return
        }
        var list = []
        for (var i = 0; i < page.localItems.length; i++) {
            var item = page.localItems[i]
            var copy = {
                id: item.id, type: item.type, x: item.x, y: item.y, w: item.w, h: item.h,
                visible: item.visible !== false,
                props: item.props !== undefined ? item.props : ({})
            }
            if (String(item.id) === String(id)) copy.visible = next
            list.push(copy)
        }
        page.localItems = list
    }

    function removeWidget(id) {
        if (page.hasRemoveApi) {
            App.removeOverlayWidget(String(id))
            if (page.selectedId === String(id)) page.selectedId = ""
            return
        }
        var list = []
        for (var i = 0; i < page.localItems.length; i++) {
            if (String(page.localItems[i].id) !== String(id)) list.push(page.localItems[i])
        }
        page.localItems = list
        if (page.selectedId === String(id)) page.selectedId = ""
    }

    function resetWidget(id) {
        var entry = page.entryById(id)
        if (entry === null) return
        var width = catalog.defaultWidth(entry.type)
        var height = catalog.defaultHeight(entry.type)
        page.commitGeometry(id, entry.x, entry.y, width, height)
        page.flashStatus(qsTr("已重置组件大小"))
    }

    function resetAll() {
        if (page.hasResetApi) {
            App.resetOverlayWidgets()
            page.selectedId = ""
            page.flashStatus(qsTr("已恢复默认布局"))
            return
        }
        page.localItems = catalog.demoLayout()
        page.selectedId = ""
        page.flashStatus(qsTr("已恢复默认布局（本地演示）"))
    }

    function refreshData() {
        if (page.hasRefreshApi) {
            App.refreshWidgetData()
            page.flashStatus(qsTr("正在刷新天气与一言…"))
        } else {
            page.flashStatus(qsTr("缺少接口：App.refreshWidgetData"), true)
        }
    }

    function setEnabled(value) {
        if (typeof App !== "undefined" && typeof App.setOverlayWidgetsEnabled === "function") {
            App.setOverlayWidgetsEnabled(value === true)
            return
        }
        if (page.backendReady && App.overlayWidgetsEnabled !== undefined
                && typeof App.setOverlayWidgetsEnabled !== "function") {
            page.flashStatus(qsTr("缺少接口：App.setOverlayWidgetsEnabled"), true)
            return
        }
        page.localEnabled = value === true
    }

    function addWidget(type) {
        page.addMenuOpen = false
        if (page.full) {
            page.flashStatus(qsTr("最多只能放 %1 个组件").arg(page.maxWidgets), true)
            return
        }
        if (page.hasAddApi) {
            var newId = App.addOverlayWidget(String(type))
            if (newId === undefined || newId === null || String(newId) === "") {
                page.flashStatus(qsTr("添加失败：组件已满或类型不支持"), true)
            } else {
                page.selectedId = String(newId)
                page.flashStatus(qsTr("已添加：%1").arg(catalog.titleOf(type)))
            }
            return
        }
        // 本地兜底：排到现有组件下方
        var list = []
        var bottom = 0
        for (var i = 0; i < page.localItems.length; i++) {
            list.push(page.localItems[i])
            var y = Number(page.localItems[i].y) + Number(page.localItems[i].h)
            if (isFinite(y) && y > bottom) bottom = y
        }
        var typeName = String(type)
        var id = typeName + "-" + (list.length + 1)
        var used = {}
        for (var j = 0; j < list.length; j++) used[String(list[j].id)] = true
        var suffix = list.length + 1
        while (used[id] === true) { suffix += 1; id = typeName + "-" + suffix }
        var width = catalog.defaultWidth(typeName)
        var height = catalog.defaultHeight(typeName)
        var top = catalog.clamp(catalog.snap(bottom + 0.04), 0, 1 - height)
        list.push({
            id: id,
            type: typeName,
            x: 0.06,
            y: top,
            w: width,
            h: height,
            visible: true,
            props: ({})
        })
        page.localItems = list
        page.selectedId = id
        page.flashStatus(qsTr("已添加：%1（本地演示）").arg(catalog.titleOf(typeName)))
    }

    function layoutJson() {
        var out = []
        for (var i = 0; i < page.items.length; i++) {
            var entry = page.items[i]
            out.push({
                id: entry.id,
                type: entry.type,
                x: entry.x,
                y: entry.y,
                w: entry.w,
                h: entry.h,
                visible: entry.visible !== false
            })
        }
        try {
            return JSON.stringify(out)
        } catch (error) {
            return ""
        }
    }

    // ================= 预览画布尺寸（右半屏 = 屏宽 50% × 屏高） =================
    readonly property real screenWidthValue: {
        var win = page.Window.window
        if (win && Number(win.width) > 0) return Number(win.width)
        return Screen.width > 0 ? Screen.width : 1280
    }
    readonly property real screenHeightValue: {
        var win = page.Window.window
        if (win && Number(win.height) > 0) return Number(win.height)
        return Screen.height > 0 ? Screen.height : 820
    }
    readonly property real halfAspect: (page.screenWidthValue * 0.5)
                                       / Math.max(1, page.screenHeightValue)

    // ================= 界面 =================
    Column {
        anchors.fill: parent
        anchors.leftMargin: 34
        anchors.rightMargin: 34
        anchors.topMargin: 24
        anchors.bottomMargin: 20
        spacing: 14

        // ---------- 页头 ----------
        Row {
            id: headerRow
            width: parent.width
            spacing: 14

            Item {
                id: backButton
                objectName: "WidgetsBackButton"
                width: 40
                height: 40
                anchors.verticalCenter: parent.verticalCenter

                Rectangle {
                    anchors.fill: parent
                    radius: 20
                    color: backArea.containsMouse ? AppTheme.cardBgAlt : AppTheme.cardBg
                    border.width: 1
                    border.color: AppTheme.cardBorder
                }
                Glyph {
                    anchors.centerIn: parent
                    kind: "back"
                    size: 17
                    color: backArea.containsMouse ? AppTheme.accent : AppTheme.textPrimary
                }
                MouseArea {
                    id: backArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: page.backRequested()
                }
            }

            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 3
                Text {
                    text: qsTr("组件与布局")
                    color: AppTheme.textPrimary
                    font.pixelSize: AppTheme.fs(24)
                    font.weight: Font.Bold
                    font.family: AppTheme.fontFamily
                    font.letterSpacing: 1
                }
                Text {
                    text: qsTr("自定义锁屏右半屏的组件：拖动摆放，右下角拖拽改大小，松手自动对齐 0.02 网格")
                    color: AppTheme.textSecondary
                    font.pixelSize: AppTheme.fs(12)
                    font.family: AppTheme.fontFamily
                }
            }

            Item { width: 12; height: 1 }

            // 状态提示
            Item {
                anchors.verticalCenter: parent.verticalCenter
                visible: page.statusText !== ""
                width: statusLabel.implicitWidth + 22
                height: 26
                Rectangle {
                    anchors.fill: parent
                    radius: 13
                    color: page.statusIsError ? "#33E2555F" : "#262ED3C6"
                    border.width: 1
                    border.color: page.statusIsError ? AppTheme.danger : AppTheme.accent
                }
                Text {
                    id: statusLabel
                    anchors.centerIn: parent
                    text: page.statusText
                    color: page.statusIsError ? AppTheme.danger : AppTheme.accent
                    font.pixelSize: AppTheme.fs(11)
                    font.family: AppTheme.fontFamily
                }
            }
        }

        // ---------- 工具栏：总开关 / 添加 / 重置 / 刷新 ----------
        GlassCard {
            id: toolbar
            width: parent.width
            height: 62
            radius: 18
            interactive: false
            glassSource: page.glassSource

            Row {
                anchors.left: parent.left
                anchors.leftMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                spacing: 12

                GlassSwitch {
                    id: enabledSwitch
                    objectName: "WidgetsEnabledSwitch"
                    anchors.verticalCenter: parent.verticalCenter
                    checked: page.enabledValue
                    onClicked: page.setEnabled(!page.enabledValue)
                }

                Column {
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 2
                    Text {
                        text: page.enabledValue ? qsTr("锁屏组件已开启") : qsTr("锁屏组件已关闭")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(13)
                        font.weight: Font.DemiBold
                        font.family: AppTheme.fontFamily
                    }
                    Text {
                        text: qsTr("已添加 %1 / %2 个").arg(page.widgetCount).arg(page.maxWidgets)
                        color: AppTheme.textTertiary
                        font.pixelSize: AppTheme.fs(11)
                        font.family: AppTheme.fontFamily
                    }
                }
            }

            Row {
                anchors.right: parent.right
                anchors.rightMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10

                GlassButton {
                    id: addButton
                    objectName: "WidgetsAddButton"
                    text: qsTr("＋ 添加组件")
                    tone: "accent"
                    fontSize: 12
                    padH: 16
                    minHeight: 34
                    onClicked: page.addMenuOpen = !page.addMenuOpen
                }

                GlassButton {
                    objectName: "WidgetsResetButton"
                    text: qsTr("全部重置")
                    tone: "ghost"
                    fontSize: 12
                    padH: 14
                    minHeight: 34
                    onClicked: page.resetAll()
                }

                GlassButton {
                    objectName: "WidgetsRefreshButton"
                    text: qsTr("刷新数据")
                    tone: "ghost"
                    fontSize: 12
                    padH: 14
                    minHeight: 34
                    onClicked: page.refreshData()
                }
            }
        }

        // ---------- 主体：左组件库 / 右预览 ----------
        Row {
            width: parent.width
            height: Math.max(0, parent.height - headerRow.height - toolbar.height
                             - parent.spacing * 2)
            spacing: 16

            // 左列：组件库 + 已添加
            Flickable {
                id: libraryFlick
                width: Math.min(336, Math.round(page.width * 0.32))
                height: parent.height
                contentWidth: width
                contentHeight: libraryColumn.height + 8
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                ScrollBar.vertical: ScrollBar {
                    id: libraryScroll
                    policy: ScrollBar.AsNeeded
                    interactive: true
                    width: 5
                    contentItem: Rectangle {
                        implicitWidth: 5
                        radius: 2.5
                        color: AppTheme.textTertiary
                        opacity: libraryScroll.pressed ? 0.9 : 0.35
                    }
                    background: Item {}
                }

                Column {
                    id: libraryColumn
                    width: libraryFlick.width - 8
                    spacing: 12

                    // 组件库
                    GlassCard {
                        width: parent.width
                        height: libraryTitle.height + libraryList.height + 26
                        radius: 18
                        interactive: false
                        glassSource: page.glassSource

                        Column {
                            id: libraryBody
                            x: 14
                            y: 13
                            width: parent.width - 28
                            spacing: 2

                            Row {
                                id: libraryTitle
                                width: parent.width
                                spacing: 8

                                Text {
                                    text: qsTr("组件库")
                                    color: AppTheme.textPrimary
                                    font.pixelSize: AppTheme.fs(13)
                                    font.weight: Font.DemiBold
                                    font.family: AppTheme.fontFamily
                                }
                                Item { width: parent.width - 150; height: 1 }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: qsTr("点击「添加」")
                                    color: AppTheme.textTertiary
                                    font.pixelSize: AppTheme.fs(10)
                                    font.family: AppTheme.fontFamily
                                }
                            }

                            Column {
                                id: libraryList
                                width: parent.width
                                spacing: 0

                                Repeater {
                                    model: catalog.types

                                    delegate: Item {
                                        id: libraryRow
                                        width: libraryList.width
                                        height: 56

                                        Row {
                                            anchors.fill: parent
                                            anchors.leftMargin: 2
                                            anchors.rightMargin: 2
                                            spacing: 10

                                            // 图标底
                                            Item {
                                                width: 30
                                                height: 30
                                                anchors.verticalCenter: parent.verticalCenter
                                                Rectangle {
                                                    anchors.fill: parent
                                                    radius: 10
                                                    gradient: Gradient {
                                                        GradientStop { position: 0.0; color: AppTheme.gradA }
                                                        GradientStop { position: 1.0; color: AppTheme.gradDeep }
                                                    }
                                                }
                                                Glyph {
                                                    anchors.centerIn: parent
                                                    kind: String(modelData.icon)
                                                    size: 15
                                                    color: AppTheme.onAccent
                                                }
                                            }

                                            Column {
                                                width: Math.max(0, parent.width - 30 - 10
                                                                   - addTypeButton.width - 10)
                                                anchors.verticalCenter: parent.verticalCenter
                                                spacing: 1
                                                Text {
                                                    width: parent.width
                                                    text: String(modelData.title)
                                                    color: AppTheme.textPrimary
                                                    font.pixelSize: AppTheme.fs(12)
                                                    font.weight: Font.DemiBold
                                                    font.family: AppTheme.fontFamily
                                                    elide: Text.ElideRight
                                                }
                                                Text {
                                                    width: parent.width
                                                    text: String(modelData.desc)
                                                    color: AppTheme.textTertiary
                                                    font.pixelSize: AppTheme.fs(10)
                                                    font.family: AppTheme.fontFamily
                                                    elide: Text.ElideRight
                                                }
                                            }

                                            GlassButton {
                                                id: addTypeButton
                                                objectName: "WidgetsAdd_" + String(modelData.type)
                                                anchors.verticalCenter: parent.verticalCenter
                                                text: qsTr("添加")
                                                tone: "tinted"
                                                fontSize: 10
                                                padH: 10
                                                minHeight: 26
                                                enabled: !page.full
                                                opacity: page.full ? 0.5 : 1.0
                                                onClicked: page.addWidget(String(modelData.type))
                                            }
                                        }

                                        Rectangle {
                                            anchors.left: parent.left
                                            anchors.right: parent.right
                                            anchors.bottom: parent.bottom
                                            height: 1
                                            color: AppTheme.divider
                                            visible: index < catalog.types.length - 1
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // 已添加
                    GlassCard {
                        width: parent.width
                        height: addedTitle.height + addedList.height + 26
                        radius: 18
                        interactive: false
                        glassSource: page.glassSource

                        Column {
                            x: 14
                            y: 13
                            width: parent.width - 28
                            spacing: 2

                            Row {
                                id: addedTitle
                                width: parent.width
                                Text {
                                    text: qsTr("已添加")
                                    color: AppTheme.textPrimary
                                    font.pixelSize: AppTheme.fs(13)
                                    font.weight: Font.DemiBold
                                    font.family: AppTheme.fontFamily
                                }
                                Item { width: parent.width - 190; height: 1 }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: qsTr("隐藏 / 重置 / 删除")
                                    color: AppTheme.textTertiary
                                    font.pixelSize: AppTheme.fs(10)
                                    font.family: AppTheme.fontFamily
                                }
                            }

                            Column {
                                id: addedList
                                width: parent.width
                                spacing: 0

                                Repeater {
                                    model: page.items

                                    delegate: Item {
                                        id: addedRow
                                        readonly property var entry: modelData
                                        readonly property bool isSelected: page.selectedId === String(entry.id)
                                        width: addedList.width
                                        height: 42

                                        Rectangle {
                                            anchors.fill: parent
                                            radius: 10
                                            color: addedRow.isSelected ? AppTheme.cardOverlaySelected
                                                                       : "transparent"
                                            Behavior on color { ColorAnimation { duration: 120 } }
                                        }

                                        MouseArea {
                                            anchors.fill: parent
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: page.selectWidget(addedRow.entry.id)
                                        }

                                        Row {
                                            anchors.fill: parent
                                            anchors.leftMargin: 4
                                            anchors.rightMargin: 2
                                            spacing: 6

                                            Glyph {
                                                anchors.verticalCenter: parent.verticalCenter
                                                kind: catalog.iconOf(String(addedRow.entry.type))
                                                size: 13
                                                color: addedRow.isSelected ? AppTheme.accent : AppTheme.textSecondary
                                            }

                                            Column {
                                                width: Math.max(0, parent.width - 20
                                                                   - hideButton.width - resetButton.width
                                                                   - deleteButton.width - 24)
                                                anchors.verticalCenter: parent.verticalCenter
                                                spacing: 0
                                                Text {
                                                    width: parent.width
                                                    text: catalog.titleOf(String(addedRow.entry.type))
                                                    color: AppTheme.textPrimary
                                                    font.pixelSize: AppTheme.fs(11)
                                                    font.family: AppTheme.fontFamily
                                                    elide: Text.ElideRight
                                                }
                                                Text {
                                                    width: parent.width
                                                    text: addedRow.entry.visible !== false
                                                          ? qsTr("%1 · %2 × %3")
                                                            .arg(String(addedRow.entry.id))
                                                            .arg(Number(addedRow.entry.w).toFixed(2))
                                                            .arg(Number(addedRow.entry.h).toFixed(2))
                                                          : qsTr("已隐藏 · %1").arg(String(addedRow.entry.id))
                                                    color: AppTheme.textTertiary
                                                    font.pixelSize: AppTheme.fs(9)
                                                    font.family: C.monoFont
                                                    elide: Text.ElideRight
                                                }
                                            }

                                            GlassButton {
                                                id: hideButton
                                                anchors.verticalCenter: parent.verticalCenter
                                                text: addedRow.entry.visible !== false
                                                      ? qsTr("隐藏") : qsTr("显示")
                                                tone: "ghost"
                                                fontSize: 9
                                                padH: 8
                                                minHeight: 22
                                                onClicked: page.toggleVisible(addedRow.entry.id)
                                            }

                                            GlassButton {
                                                id: resetButton
                                                anchors.verticalCenter: parent.verticalCenter
                                                text: qsTr("重置")
                                                tone: "ghost"
                                                fontSize: 9
                                                padH: 8
                                                minHeight: 22
                                                onClicked: page.resetWidget(addedRow.entry.id)
                                            }

                                            Item {
                                                id: deleteButton
                                                anchors.verticalCenter: parent.verticalCenter
                                                width: 22
                                                height: 22

                                                Rectangle {
                                                    anchors.fill: parent
                                                    radius: 11
                                                    color: deleteArea.containsMouse ? "#33E2555F"
                                                                                    : AppTheme.cardOverlay
                                                }
                                                Glyph {
                                                    anchors.centerIn: parent
                                                    kind: "close"
                                                    size: 9
                                                    color: deleteArea.containsMouse ? AppTheme.danger
                                                                                    : AppTheme.textTertiary
                                                }
                                                MouseArea {
                                                    id: deleteArea
                                                    anchors.fill: parent
                                                    hoverEnabled: true
                                                    cursorShape: Qt.PointingHandCursor
                                                    onClicked: page.removeWidget(addedRow.entry.id)
                                                }
                                            }
                                        }
                                    }
                                }

                                Text {
                                    width: parent.width
                                    visible: page.items.length === 0
                                    text: qsTr("还没有组件，从上面的组件库添加一个")
                                    color: AppTheme.textTertiary
                                    font.pixelSize: AppTheme.fs(11)
                                    font.family: AppTheme.fontFamily
                                    wrapMode: Text.WordWrap
                                }
                            }
                        }
                    }

                    // 接口状态
                    Item {
                        width: parent.width
                        height: 22
                        Row {
                            anchors.left: parent.left
                            spacing: 6
                            Rectangle {
                                width: 7
                                height: 7
                                radius: 3.5
                                anchors.verticalCenter: parent.verticalCenter
                                color: page.backendReady ? AppTheme.success : AppTheme.danger
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: page.backendReady
                                      ? qsTr("后端接口就绪：布局保存到设置")
                                      : qsTr("后端接口未就绪：当前为本地演示布局")
                                color: AppTheme.textTertiary
                                font.pixelSize: AppTheme.fs(10)
                                font.family: AppTheme.fontFamily
                            }
                        }
                    }
                }
            }

            // 右列：右半屏预览
            Item {
                id: previewHost
                width: Math.max(0, parent.width - libraryFlick.width - parent.spacing)
                height: parent.height

                Item {
                    id: canvasFrame
                    width: Math.round(Math.min(previewHost.width - 4,
                                               Math.max(120, (previewHost.height - 44) * page.halfAspect)))
                    height: Math.round(width / Math.max(0.2, page.halfAspect))
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.top: parent.top
                    anchors.topMargin: 2

                    // 画布底：深色 + 圆角 + 描边
                    Rectangle {
                        id: canvasBg
                        anchors.fill: parent
                        radius: 20
                        color: "#08151E"
                        border.width: 1
                        border.color: AppTheme.cardBorderStrong
                    }

                    // 网格
                    Canvas {
                        id: gridCanvas
                        anchors.fill: parent
                        antialiasing: true
                        onPaint: {
                            var ctx = getContext("2d")
                            ctx.reset()
                            var stepX = gridCanvas.width * 0.1
                            var stepY = gridCanvas.height * 0.1
                            ctx.lineWidth = 1
                            ctx.strokeStyle = "rgba(255,255,255,0.055)"
                            var x = stepX
                            while (x < gridCanvas.width - 0.5) {
                                ctx.beginPath()
                                ctx.moveTo(x, 0)
                                ctx.lineTo(x, gridCanvas.height)
                                ctx.stroke()
                                x += stepX
                            }
                            var y = stepY
                            while (y < gridCanvas.height - 0.5) {
                                ctx.beginPath()
                                ctx.moveTo(0, y)
                                ctx.lineTo(gridCanvas.width, y)
                                ctx.stroke()
                                y += stepY
                            }
                            // 中缝（屏幕中线）：右半屏的左边界
                            ctx.strokeStyle = "rgba(46,211,198,0.45)"
                            ctx.setLineDash([6, 6])
                            ctx.beginPath()
                            ctx.moveTo(0.5, 0)
                            ctx.lineTo(0.5, gridCanvas.height)
                            ctx.stroke()
                            ctx.setLineDash([])
                        }
                        onWidthChanged: requestPaint()
                        onHeightChanged: requestPaint()
                    }

                    // 组件层
                    Item {
                        id: widgetLayer
                        anchors.fill: parent
                        anchors.margins: 1
                        clip: true

                        Repeater {
                            model: page.items

                            delegate: Item {
                                id: slot
                                readonly property var entry: modelData
                                readonly property bool entryVisible: entry.visible !== false
                                readonly property bool isSelected: page.selectedId === String(entry.id)
                                readonly property string titleText: catalog.titleOf(String(entry.type))

                                x: Math.round(Number(entry.x) * widgetLayer.width)
                                y: Math.round(Number(entry.y) * widgetLayer.height)
                                width: Math.max(8, Math.round(Number(entry.w) * widgetLayer.width))
                                height: Math.max(8, Math.round(Number(entry.h) * widgetLayer.height))

                                objectName: "WidgetPreviewSlot_" + String(entry.id)

                                Loader {
                                    id: widgetLoader
                                    anchors.fill: parent
                                    sourceComponent: catalog.componentFor(String(slot.entry.type))

                                    onLoaded: {
                                        if (widgetLoader.item) {
                                            widgetLoader.item.props = slot.entry.props !== undefined
                                                                     ? slot.entry.props : ({})
                                            widgetLoader.item.compact = slot.width < 230 || slot.height < 96
                                            widgetLoader.item.app = (typeof App !== "undefined") ? App : null
                                        }
                                    }
                                }

                                // 已隐藏：压暗 + 角标
                                Rectangle {
                                    anchors.fill: parent
                                    visible: !slot.entryVisible
                                    radius: 18
                                    color: "#B308151E"
                                }
                                Text {
                                    anchors.centerIn: parent
                                    visible: !slot.entryVisible
                                    text: qsTr("已隐藏")
                                    color: AppTheme.textTertiary
                                    font.pixelSize: AppTheme.fs(11)
                                    font.family: AppTheme.fontFamily
                                }

                                // 选中描边
                                Rectangle {
                                    anchors.fill: parent
                                    visible: slot.isSelected
                                    radius: 18
                                    color: "transparent"
                                    border.width: 2
                                    border.color: AppTheme.accent
                                }

                                // 四角手柄（右下角可拖拽）
                                Repeater {
                                    model: slot.isSelected ? 4 : 0
                                    delegate: Rectangle {
                                        width: 7
                                        height: 7
                                        radius: 2
                                        color: "#FFFFFF"
                                        border.width: 1
                                        border.color: AppTheme.accent
                                        x: (index === 0 || index === 2) ? -3 : slot.width - 4
                                        y: (index === 0 || index === 1) ? -3 : slot.height - 4
                                    }
                                }

                                // 尺寸角标
                                Rectangle {
                                    visible: slot.isSelected
                                    x: 0
                                    y: -20
                                    width: sizeLabel.implicitWidth + 10
                                    height: 16
                                    radius: 8
                                    color: AppTheme.accent
                                    Text {
                                        id: sizeLabel
                                        anchors.centerIn: parent
                                        text: Number(slot.entry.w).toFixed(2) + " × "
                                              + Number(slot.entry.h).toFixed(2)
                                        color: AppTheme.onAccent
                                        font.pixelSize: 9
                                        font.family: C.monoFont
                                    }
                                }

                                // 拖动（整块）——选中 + 改 x/y
                                MouseArea {
                                    id: dragArea
                                    anchors.fill: parent
                                    enabled: page.enabledValue
                                    cursorShape: Qt.SizeAllCursor
                                    drag.target: slot
                                    drag.axis: Drag.XAndYAxis
                                    drag.minimumX: 0
                                    drag.maximumX: widgetLayer.width - slot.width
                                    drag.minimumY: 0
                                    drag.maximumY: widgetLayer.height - slot.height
                                    onPressed: page.selectWidget(slot.entry.id)
                                    onPositionChanged: {
                                        if (!dragArea.drag.active) return
                                        var stepX = widgetLayer.width * catalog.snapStep
                                        var stepY = widgetLayer.height * catalog.snapStep
                                        if (stepX > 0) slot.x = Math.round(slot.x / stepX) * stepX
                                        if (stepY > 0) slot.y = Math.round(slot.y / stepY) * stepY
                                    }
                                    onReleased: {
                                        page.commitGeometry(slot.entry.id,
                                                            slot.x / Math.max(1, widgetLayer.width),
                                                            slot.y / Math.max(1, widgetLayer.height),
                                                            slot.entry.w,
                                                            slot.entry.h)
                                    }
                                }

                                // 右下角缩放
                                Item {
                                    id: resizeHandle
                                    visible: slot.isSelected
                                    width: 18
                                    height: 18
                                    anchors.right: parent.right
                                    anchors.bottom: parent.bottom

                                    Rectangle {
                                        anchors.fill: parent
                                        anchors.margins: 2
                                        radius: 4
                                        color: AppTheme.accent
                                        opacity: resizeArea.containsMouse || resizeArea.pressed ? 1.0 : 0.82
                                    }

                                    MouseArea {
                                        id: resizeArea
                                        anchors.fill: parent
                                        cursorShape: Qt.SizeFDiagCursor
                                        property real pressCanvasX: 0
                                        property real pressCanvasY: 0
                                        property real startWidth: 0
                                        property real startHeight: 0
                                        onPressed: (mouse) => {
                                            page.selectWidget(slot.entry.id)
                                            var point = resizeArea.mapToItem(widgetLayer, mouse.x, mouse.y)
                                            resizeArea.pressCanvasX = point.x
                                            resizeArea.pressCanvasY = point.y
                                            resizeArea.startWidth = slot.width
                                            resizeArea.startHeight = slot.height
                                        }
                                        onPositionChanged: (mouse) => {
                                            if (!resizeArea.pressed) return
                                            var point = resizeArea.mapToItem(widgetLayer, mouse.x, mouse.y)
                                            var stepX = Math.max(1, widgetLayer.width * catalog.snapStep)
                                            var stepY = Math.max(1, widgetLayer.height * catalog.snapStep)
                                            var deltaX = point.x - resizeArea.pressCanvasX
                                            var deltaY = point.y - resizeArea.pressCanvasY
                                            var newWidth = resizeArea.startWidth + deltaX
                                            var newHeight = resizeArea.startHeight + deltaY
                                            newWidth = Math.round(newWidth / stepX) * stepX
                                            newHeight = Math.round(newHeight / stepY) * stepY
                                            newWidth = Math.max(widgetLayer.width * catalog.minSize,
                                                                Math.min(newWidth, widgetLayer.width - slot.x))
                                            newHeight = Math.max(widgetLayer.height * catalog.minSize,
                                                                 Math.min(newHeight, widgetLayer.height - slot.y))
                                            slot.width = Math.round(newWidth)
                                            slot.height = Math.round(newHeight)
                                        }
                                        onReleased: {
                                            page.commitGeometry(slot.entry.id,
                                                                slot.x / Math.max(1, widgetLayer.width),
                                                                slot.y / Math.max(1, widgetLayer.height),
                                                                slot.width / Math.max(1, widgetLayer.width),
                                                                slot.height / Math.max(1, widgetLayer.height))
                                        }
                                    }
                                }
                            }
                        }
                    }

                    // 关闭态遮罩
                    Rectangle {
                        anchors.fill: parent
                        visible: !page.enabledValue
                        radius: 20
                        color: "#B3040E15"
                        Text {
                            anchors.centerIn: parent
                            width: parent.width - 40
                            horizontalAlignment: Text.AlignHCenter
                            text: qsTr("锁屏组件已关闭，打开上方开关后才会在锁屏显示")
                            color: AppTheme.textSecondary
                            font.pixelSize: AppTheme.fs(13)
                            font.family: AppTheme.fontFamily
                            wrapMode: Text.WordWrap
                        }
                    }

                    // 画布角标
                    Text {
                        anchors.left: parent.left
                        anchors.bottom: parent.bottom
                        anchors.leftMargin: 10
                        anchors.bottomMargin: 8
                        text: qsTr("右半屏预览 · 归一化 0~1 · 网格 0.02")
                        color: "#8FA9B6"
                        font.pixelSize: AppTheme.fs(10)
                        font.family: AppTheme.fontFamily
                    }
                }

                // 布局 JSON（调试用，一行）
                Text {
                    anchors.top: canvasFrame.bottom
                    anchors.topMargin: 8
                    anchors.left: canvasFrame.left
                    anchors.right: canvasFrame.right
                    text: qsTr("布局 JSON：") + page.layoutJson()
                    color: AppTheme.textTertiary
                    font.pixelSize: AppTheme.fs(9)
                    font.family: C.monoFont
                    elide: Text.ElideRight
                    maximumLineCount: 1
                }
            }
        }
    }

    // ---------- 添加组件下拉 ----------
    Item {
        id: addMenu
        objectName: "WidgetsAddMenu"
        visible: page.addMenuOpen
        z: 60
        width: 236
        height: addMenuColumn.height + 20
        // 位置：工具栏右下方（页面坐标，避免跨父对象 mapToItem 的坐标陷阱）
        x: Math.max(12, page.width - 34 - 18 - width)
        y: 24 + headerRow.height + 14 + toolbar.height + 8

        Rectangle {
            anchors.fill: parent
            radius: 16
            color: AppTheme.dialogBg
            border.width: 1
            border.color: AppTheme.cardBorderStrong
        }

        Column {
            id: addMenuColumn
            x: 14
            y: 12
            width: parent.width - 28
            spacing: 2

            Text {
                text: qsTr("添加组件")
                color: AppTheme.textTertiary
                font.pixelSize: AppTheme.fs(10)
                font.family: AppTheme.fontFamily
                font.letterSpacing: 1
            }

            Repeater {
                model: catalog.types

                delegate: Item {
                    id: addMenuItem
                    width: addMenuColumn.width
                    height: 34

                    Rectangle {
                        anchors.fill: parent
                        radius: 9
                        color: addMenuArea.containsMouse ? AppTheme.cardOverlayHover : "transparent"
                    }

                    Row {
                        anchors.left: parent.left
                        anchors.leftMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 8

                        Glyph {
                            anchors.verticalCenter: parent.verticalCenter
                            kind: String(modelData.icon)
                            size: 13
                            color: AppTheme.textSecondary
                        }

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: String(modelData.title)
                            color: AppTheme.textPrimary
                            font.pixelSize: AppTheme.fs(12)
                            font.family: AppTheme.fontFamily
                        }
                    }

                    MouseArea {
                        id: addMenuArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.addWidget(String(modelData.type))
                    }
                }
            }
        }
    }

    // 点击空白关闭下拉
    MouseArea {
        anchors.fill: parent
        visible: page.addMenuOpen
        z: 55
        onClicked: page.addMenuOpen = false
    }
}
