import QtQuick
import "../theme"
import "../components"
import "../components/Constants.js" as C

// 主题 / 插件商店（v0.18）：App Store 风格。
// 从主题页 / 插件页顶部的商店入口进入（不占左侧 navIndex），返回按钮回到来源页。
// 列表页：大标题 + 搜索 + 分类 chips + 刷新 + 自适应应用卡片网格；
// 详情页：大预览 / 作者版本评分下载量 / 介绍 / 配色 / 截图 / 安装 / 评分分布 + 评论 + 写评论。
Item {
    id: page
    objectName: "StorePage"

    property Item glassSource: null
    property bool active: false
    property string kind: "theme"            // theme / plugin

    // ---------- 目录 ----------
    property bool loading: false
    property bool catalogLoaded: false
    property var catalog: []
    property string catalogStatus: "builtin"  // online / builtin / error:<原因>
    property string catalogError: ""
    property int storeRevision: 0
    property string searchText: ""
    property string activeTag: qsTr("全部")

    // ---------- 列表 / 详情 ----------
    property string view: "list"              // list / detail
    property string detailId: ""
    property var detailItem: ({})
    property var detailComments: []
    property int detailPending: 0
    property int commentRating: 5
    property string commentDraft: ""

    // ---------- 安装 ----------
    property string installingId: ""
    property real installProgress: 0
    property string pendingInstallId: ""
    property var localInstalled: ({})         // 后端缺失安装接口时的本地兜底

    // ---------- 轻提示 ----------
    property string toastText: ""
    property bool toastVisible: false

    signal backRequested()

    // ================= 基础文案 =================
    readonly property bool themeKind: page.kind === "theme"
    readonly property string kindLabel: page.themeKind ? qsTr("主题") : qsTr("插件")
    readonly property string pageTitle: page.themeKind ? qsTr("主题商店") : qsTr("插件商店")
    readonly property string pageSubtitle: page.themeKind ? qsTr("发现更多配色与浪花") : qsTr("发现更多效率工具与玩法")

    readonly property string statusText: {
        var status = String(page.catalogStatus)
        if (status === "online") return qsTr("在线目录")
        if (status.indexOf("error:") === 0) return qsTr("加载失败，使用内置目录")
        return qsTr("内置示例目录")
    }

    // ================= 目录加载 =================
    function open(storeKind) {
        page.kind = (String(storeKind) === "plugin") ? "plugin" : "theme"
        page.view = "list"
        page.searchText = ""
        page.activeTag = qsTr("全部")
        page.detailId = ""
        page.detailItem = ({})
        page.detailComments = []
        page.detailPending = 0
        page.installProgress = 0
        page.ensureCatalog(false)
    }

    function ensureCatalog(force) {
        if (page.catalogLoaded && !force) return
        page.loading = true
        page.pendingForce = (force === true)
        // 先让「加载中」状态渲染一帧，再进后端（目录首次拉取可能同步等待网络 6 秒）
        storeLoadTimer.restart()
    }

    property bool pendingForce: false

    Timer {
        id: storeLoadTimer
        interval: 40
        repeat: false
        onTriggered: page.loadCatalog(page.pendingForce)
    }

    function loadCatalog(force) {
        var items = []
        var status = ""
        var error = ""
        if (typeof App !== "undefined" && typeof App.storeItems === "function") {
            if (force && typeof App.refreshStore === "function") {
                try { status = String(App.refreshStore() || "") } catch (e) { status = "" }
            }
            try { items = App.storeItems("") || [] } catch (e) { items = [] }
            if (typeof App.storeCatalogStatus !== "undefined" && App.storeCatalogStatus !== undefined)
                status = String(App.storeCatalogStatus)
            if (typeof App.storeCatalogError !== "undefined" && App.storeCatalogError !== undefined)
                error = String(App.storeCatalogError)
        }
        if (!items || items.length === 0) {
            items = page.sampleCatalog()
            if (status === "" || status === "online") status = "builtin"
        }
        page.catalog = items
        page.catalogStatus = (status !== "") ? status : "builtin"
        page.catalogError = error
        page.catalogLoaded = true
        page.loading = false
        page.pendingForce = false
    }

    function syncStatus() {
        if (typeof App === "undefined") return
        if (typeof App.storeCatalogStatus !== "undefined" && App.storeCatalogStatus !== undefined)
            page.catalogStatus = String(App.storeCatalogStatus)
        if (typeof App.storeCatalogError !== "undefined" && App.storeCatalogError !== undefined)
            page.catalogError = String(App.storeCatalogError)
    }

    function refreshCatalog() {
        if (page.loading) return
        page.ensureCatalog(true)
        page.showToast(qsTr("正在刷新商店目录…"))
    }

    // ================= 目录筛选 =================
    readonly property var kindItems: {
        var revision = page.storeRevision
        var source = page.catalog || []
        var result = []
        for (var i = 0; i < source.length; i++) {
            if (String(source[i].kind) === page.kind) result.push(source[i])
        }
        return result
    }

    readonly property var tagList: {
        var items = page.kindItems
        var tags = []
        for (var i = 0; i < items.length; i++) {
            var itemTags = items[i].tags || []
            for (var j = 0; j < itemTags.length; j++) {
                var text = String(itemTags[j])
                if (text !== "" && tags.indexOf(text) < 0) tags.push(text)
            }
        }
        return [qsTr("全部")].concat(tags)
    }

    function matchesSearch(item) {
        var text = page.searchText.trim().toLowerCase()
        if (text.length === 0) return true
        var haystack = (String(item.name || "") + " " + String(item.author || "") + " "
                        + String(item.summary || "") + " " + String(item.description || "") + " "
                        + (item.tags || []).join(" ")).toLowerCase()
        return haystack.indexOf(text) >= 0
    }

    function matchesTag(item) {
        if (page.activeTag === qsTr("全部")) return true
        var tags = item.tags || []
        for (var i = 0; i < tags.length; i++) {
            if (String(tags[i]) === page.activeTag) return true
        }
        return false
    }

    readonly property var filteredItems: {
        var items = page.kindItems
        var result = []
        for (var i = 0; i < items.length; i++) {
            if (page.matchesSearch(items[i]) && page.matchesTag(items[i])) result.push(items[i])
        }
        return result
    }

    // ================= 网格尺寸 =================
    readonly property int gridColumns: listColumn.width >= 980 ? 3 : (listColumn.width >= 640 ? 2 : 1)
    readonly property real gridGap: 14
    readonly property real cardWidth: (listColumn.width - page.gridGap * (page.gridColumns - 1)) / page.gridColumns
    readonly property real cardHeight: 226

    function cardX(index) { return (index % page.gridColumns) * (page.cardWidth + page.gridGap) }
    function cardY(index) { return Math.floor(index / page.gridColumns) * (page.cardHeight + page.gridGap) }
    readonly property real gridHeight: {
        var rows = Math.ceil(page.filteredItems.length / page.gridColumns)
        if (rows <= 0) return 0
        return rows * page.cardHeight + (rows - 1) * page.gridGap
    }

    // ================= 评分 / 下载量 =================
    function formatCount(value) {
        var number = Number(value)
        if (!isFinite(number) || number <= 0) return "0"
        if (number >= 10000) {
            var unit = number / 10000
            return (unit >= 10 ? unit.toFixed(0) : unit.toFixed(1)) + qsTr("万")
        }
        return String(Math.round(number))
    }

    function downloadsText(item) {
        return qsTr("%1 次下载").arg(page.formatCount(item.downloads))
    }

    function ratingText(item) {
        var value = Number(item.rating)
        if (!isFinite(value) || value <= 0) return "—"
        return value.toFixed(1)
    }

    function filledStars(rating) {
        var count = Math.max(0, Math.min(5, Math.round(Number(rating))))
        if (!isFinite(count)) count = 0
        var text = ""
        for (var i = 0; i < count; i++) text += "★"
        return text
    }

    function emptyStars(rating) {
        var count = Math.max(0, Math.min(5, Math.round(Number(rating))))
        if (!isFinite(count)) count = 0
        var text = ""
        for (var i = count; i < 5; i++) text += "☆"
        return text
    }

    function pluginInitial(item) {
        var name = String(item.name !== undefined ? item.name : "?")
        return name.length > 0 ? name.substring(0, 1) : "?"
    }

    function formatTime(value) {
        var text = String(value === undefined || value === null ? "" : value)
        if (text.length >= 16) return text.substring(0, 16).replace("T", " ")
        return text
    }

    function avatarInitial(name) {
        var text = String(name === undefined || name === null ? "" : name)
        return text.length > 0 ? text.substring(0, 1) : qsTr("匿")
    }

    function avatarColor(name) {
        var text = String(name === undefined || name === null ? "" : name)
        var code = 0
        for (var i = 0; i < text.length; i++) code = (code * 31 + text.charCodeAt(i)) % 360
        return Qt.hsla(code / 360, 0.45, 0.45, 1)
    }

    // ================= 已安装 / 更新 =================
    function isThemeInstalled(itemId) {
        var wanted = String(itemId)
        var list = (typeof App !== "undefined" && App.customThemes) ? App.customThemes : []
        for (var i = 0; i < list.length; i++) {
            if (String(list[i].id) === wanted) return true
        }
        return page.localInstalled[wanted] === true
    }

    function isThemeCurrent(itemId) {
        if (typeof App === "undefined" || App.themeMode === undefined) return false
        return String(App.themeMode) === ("custom:" + String(itemId))
    }

    function installedPluginVersion(itemId) {
        var wanted = String(itemId)
        var list = (typeof App !== "undefined" && App.plugins) ? App.plugins : []
        for (var i = 0; i < list.length; i++) {
            if (String(list[i].id) === wanted) return String(list[i].version !== undefined ? list[i].version : "")
        }
        return ""
    }

    function pluginInstalled(item) {
        var version = page.installedPluginVersion(item.id)
        if (version !== "") return true
        return page.localInstalled[String(item.id)] === true
    }

    function isInstalled(item) {
        if (!item || item.id === undefined) return false
        return page.themeKind
                ? page.isThemeInstalled(item.id)
                : page.pluginInstalled(item)
    }

    function needsUpdate(item) {
        if (!item || item.kind !== "plugin") return false
        var installedVersion = page.installedPluginVersion(item.id)
        if (installedVersion === "") return false
        return String(item.version !== undefined ? item.version : "") !== installedVersion
    }

    // install / installing / installed / update / current / apply
    function installState(item) {
        if (!item || item.id === undefined) return "install"
        if (page.installingId === String(item.id)) return "installing"
        if (item.kind === "theme") {
            if (page.isThemeCurrent(item.id)) return "current"
            if (page.isThemeInstalled(item.id)) return "apply"
        } else if (page.pluginInstalled(item)) {
            return page.needsUpdate(item) ? "update" : "installed"
        }
        return "install"
    }

    function installLabel(item) {
        var state = page.installState(item)
        if (state === "installing") return qsTr("安装中…")
        if (state === "installed") return qsTr("已安装")
        if (state === "update") return qsTr("更新")
        if (state === "current") return qsTr("使用中")
        if (state === "apply") return qsTr("应用")
        return qsTr("安装")
    }

    function handleInstall(item) {
        if (!item || item.id === undefined) return
        var state = page.installState(item)
        if (state === "installing") return
        if (state === "current") {
            page.showToast(qsTr("当前已在使用这个主题"))
            return
        }
        if (state === "installed") {
            page.showToast(qsTr("已经安装过了"))
            return
        }
        if (state === "apply") {
            page.applyTheme(item)
            return
        }
        if (item.kind === "theme") page.installTheme(item)
        else page.installPlugin(item)
    }

    function applyTheme(item) {
        if (typeof App === "undefined" || typeof App.setThemeMode !== "function") {
            page.showToast(qsTr("缺少主题切换接口（App.setThemeMode）"))
            return
        }
        var ok = false
        try { ok = App.setThemeMode("custom:" + String(item.id)) === true } catch (e) { ok = false }
        if (ok) page.showToast(qsTr("已应用主题：%1").arg(String(item.name)))
        else page.showToast(qsTr("应用主题失败"))
    }

    function installTheme(item) {
        page.installingId = String(item.id)
        page.installProgress = 0.12
        if (typeof App === "undefined" || typeof App.installCustomTheme !== "function") {
            page.finishInstall(false, qsTr("缺少安装接口（App.installCustomTheme）"), item)
            return
        }
        var ok = false
        try {
            ok = App.installCustomTheme(String(item.id), String(item.name),
                                        String(item.description !== undefined && item.description !== ""
                                               ? item.description : item.summary),
                                        item.palette) === true
        } catch (e) {
            ok = false
        }
        if (ok) page.finishInstall(true, qsTr("已安装并应用"), item)
        else page.finishInstall(false, qsTr("安装主题失败"), item)
    }

    property var pendingInstallItem: ({})

    function installPlugin(item) {
        page.installingId = String(item.id)
        page.installProgress = 0.12
        page.pendingInstallItem = item
        // 先渲染「安装中」，再进后端下载（后端是同步调用，会阻塞到下载完成）
        installStartTimer.restart()
    }

    function runPluginInstall() {
        var item = page.pendingInstallItem
        page.pendingInstallItem = ({})
        if (!item || item.id === undefined) {
            page.finishInstall(false, qsTr("安装失败"), ({}))
            return
        }
        if (typeof App === "undefined" || typeof App.installStorePlugin !== "function") {
            page.finishInstall(false, qsTr("缺少插件安装接口（App.installStorePlugin）"), ({}))
            return
        }
        var result = ({})
        try { result = App.installStorePlugin(String(item.id)) || ({}) } catch (e) { result = ({}) }
        if (result.ok === true) {
            page.finishInstall(true, String(result.message !== undefined && result.message !== ""
                                           ? result.message : qsTr("插件已安装：%1").arg(String(item.name))), item)
        } else {
            page.finishInstall(false, String(result.message !== undefined && result.message !== ""
                                             ? result.message : qsTr("插件安装失败")), item)
        }
    }

    function markInstalled(itemId) {
        var wanted = String(itemId)
        var next = ({})
        var keys = Object.keys(page.localInstalled)
        for (var i = 0; i < keys.length; i++) next[keys[i]] = page.localInstalled[keys[i]]
        next[wanted] = true
        page.localInstalled = next
    }

    function finishInstall(ok, message, item) {
        page.installingId = ""
        page.installProgress = 0
        if (ok && item && item.id !== undefined) page.markInstalled(item.id)
        page.showToast(message)
        if (ok) page.loadComments()
    }

    // ================= 详情 / 评论 =================
    function openDetail(itemId) {
        page.detailId = String(itemId)
        page.view = "detail"
        page.commentRating = 5
        page.commentDraft = ""
        page.installProgress = 0
        page.detailItem = page.findItem(page.detailId)
        page.loadComments()
        flick.contentY = 0
        // 后端有更完整的条目时再刷新一次
        if (typeof App !== "undefined" && typeof App.storeItem === "function") {
            try {
                var remote = App.storeItem(page.detailId)
                if (remote && remote.id !== undefined) page.detailItem = remote
            } catch (e) { /* 保留目录里的副本 */ }
        }
    }

    function findItem(itemId) {
        var wanted = String(itemId)
        var items = page.catalog || []
        for (var i = 0; i < items.length; i++) {
            if (String(items[i].id) === wanted) return items[i]
        }
        return ({})
    }

    function loadComments() {
        var comments = []
        var pending = 0
        if (page.detailId !== "" && typeof App !== "undefined" && typeof App.storeComments === "function") {
            var payload = ({})
            try { payload = App.storeComments(page.detailId) || ({}) } catch (e) { payload = ({}) }
            if (payload.comments !== undefined && payload.comments !== null) comments = payload.comments
            if (payload.pendingCount !== undefined) pending = Number(payload.pendingCount) || 0
        }
        page.detailComments = comments
        page.detailPending = pending
    }

    readonly property var ratingDistribution: {
        var counts = [0, 0, 0, 0, 0]   // index 0 = 5★
        var comments = page.detailComments || []
        for (var i = 0; i < comments.length; i++) {
            var rating = Math.round(Number(comments[i].rating))
            if (rating >= 1 && rating <= 5) counts[5 - rating] += 1
        }
        return counts
    }

    readonly property int distributionMax: {
        var counts = page.ratingDistribution
        var max = 1
        for (var i = 0; i < counts.length; i++) if (counts[i] > max) max = counts[i]
        return max
    }

    function submitComment() {
        var text = page.commentDraft.trim()
        if (page.commentRating < 1) {
            page.showToast(qsTr("请先选择星级"))
            return
        }
        if (text.length === 0) {
            page.showToast(qsTr("评论内容不能为空"))
            return
        }
        if (typeof App === "undefined" || typeof App.addStoreComment !== "function") {
            page.showToast(qsTr("缺少评论接口（App.addStoreComment）"))
            return
        }
        var result = ({})
        try { result = App.addStoreComment(page.detailId, page.commentRating, text) || ({}) } catch (e) { result = ({}) }
        if (result.ok === false) {
            page.showToast(String(result.message !== undefined ? result.message : qsTr("评论提交失败")))
            return
        }
        page.commentDraft = ""
        page.commentRating = 5
        page.showToast(qsTr("已提交，审核通过后展示"))
        page.loadComments()
    }

    function back() {
        if (page.view === "detail") {
            page.view = "list"
            if (flick) flick.contentY = 0
            return
        }
        page.backRequested()
    }

    // ================= 轻提示 =================
    function showToast(text) {
        if (!text) return
        page.toastText = String(text)
        page.toastVisible = true
        toastTimer.restart()
    }

    Timer {
        id: toastTimer
        interval: 2400
        repeat: false
        onTriggered: page.toastVisible = false
    }

    Timer {
        id: installStartTimer
        interval: 90
        repeat: false
        onTriggered: page.runPluginInstall()
    }

    NumberAnimation {
        id: installProgressAnim
        target: page
        property: "installProgress"
        from: 0.12
        to: 0.9
        duration: 9000
        easing.type: Easing.InOutQuad
        running: page.installingId !== ""
    }

    // ================= 面板 =================
    Flickable {
        id: flick
        objectName: "StoreFlick"
        anchors.fill: parent
        contentWidth: width
        contentHeight: page.view === "list" ? listColumn.height + 64 : detailColumn.height + 64
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        // ---------- 列表页 ----------
        Column {
            id: listColumn
            visible: page.view === "list"
            width: Math.min(flick.width - 96, 1020)
            x: (flick.width - width) / 2
            y: 26
            spacing: 16

            // 页头：返回 + 标题 + 目录状态
            Item {
                width: parent.width
                height: 68

                Item {
                    id: listBackButton
                    width: 36
                    height: 36
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 8

                    Rectangle {
                        anchors.fill: parent
                        radius: 18
                        color: listBackArea.containsMouse ? AppTheme.cardBgAlt : AppTheme.cardBg
                        border.width: 1
                        border.color: AppTheme.cardBorder
                    }
                    Glyph {
                        anchors.centerIn: parent
                        kind: "chevronLeft"
                        size: 16
                        color: AppTheme.textSecondary
                    }
                    MouseArea {
                        id: listBackArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.back()
                    }
                }

                Column {
                    anchors.left: listBackButton.right
                    anchors.leftMargin: 14
                    anchors.bottom: parent.bottom
                    spacing: 5

                    Text {
                        text: page.pageTitle
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(28)
                        font.weight: Font.Bold
                        font.family: AppTheme.fontFamily
                        font.letterSpacing: 1
                    }
                    Text {
                        text: page.pageSubtitle
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(12)
                        font.family: AppTheme.fontFamily
                    }
                }

                // 目录状态胶囊
                Rectangle {
                    id: statusPill
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 10
                    width: statusRow.width + 22
                    height: 26
                    radius: 13
                    color: page.catalogStatus.indexOf("error:") === 0
                           ? (AppTheme.glass ? "#26FF8898" : "#3AE2555F")
                           : (AppTheme.glass ? "#22FFFFFF" : AppTheme.chipBg)
                    border.width: 1
                    border.color: AppTheme.glass ? "#33FFFFFF" : AppTheme.cardBorder

                    Row {
                        id: statusRow
                        anchors.centerIn: parent
                        spacing: 6
                        Rectangle {
                            width: 6
                            height: 6
                            radius: 3
                            anchors.verticalCenter: parent.verticalCenter
                            color: page.catalogStatus === "online" ? AppTheme.accent
                                   : (page.catalogStatus.indexOf("error:") === 0 ? AppTheme.danger : AppTheme.textTertiary)
                        }
                        Text {
                            text: page.loading ? qsTr("正在加载…") : page.statusText
                            color: page.catalogStatus.indexOf("error:") === 0 ? AppTheme.danger : AppTheme.textSecondary
                            font.pixelSize: AppTheme.fs(11)
                            font.family: AppTheme.fontFamily
                        }
                    }
                }
            }

            // 搜索 + 刷新
            Row {
                width: parent.width
                spacing: 10

                Item {
                    width: parent.width - refreshButton.width - 10
                    height: 40

                    Rectangle {
                        anchors.fill: parent
                        radius: 12
                        color: AppTheme.cardBgAlt
                        border.width: 1
                        border.color: storeSearchInput.activeFocus ? AppTheme.accent : AppTheme.cardBorder
                    }
                    Glyph {
                        id: searchGlyph
                        anchors.left: parent.left
                        anchors.leftMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        kind: "search"
                        size: 15
                        color: AppTheme.textTertiary
                    }
                    TextInput {
                        id: storeSearchInput
                        anchors.left: searchGlyph.right
                        anchors.leftMargin: 8
                        anchors.right: parent.right
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        color: AppTheme.textPrimary
                        selectionColor: AppTheme.accentSoft
                        selectedTextColor: "#FFFFFF"
                        font.pixelSize: AppTheme.fs(12)
                        font.family: AppTheme.fontFamily
                        text: page.searchText
                        onTextChanged: page.searchText = text
                        onAccepted: page.searchText = text
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: storeSearchInput.text.length === 0
                            text: page.themeKind ? qsTr("搜索主题、作者或标签…") : qsTr("搜索插件、作者或标签…")
                            color: AppTheme.textTertiary
                            font.pixelSize: AppTheme.fs(12)
                            font.family: AppTheme.fontFamily
                        }
                    }
                }

                GlassButton {
                    id: refreshButton
                    text: page.loading ? qsTr("刷新中…") : qsTr("刷新")
                    tone: "tinted"
                    fontSize: 12
                    padH: 16
                    minHeight: 40
                    enabled: !page.loading
                    onClicked: page.refreshCatalog()
                }
            }

            // 分类 chips（按 item.tags 过滤）
            Flickable {
                width: parent.width
                height: 30
                contentWidth: chipsRow.width
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                flickableDirection: Flickable.HorizontalFlick

                Row {
                    id: chipsRow
                    spacing: 8
                    Repeater {
                        model: page.tagList
                        delegate: Rectangle {
                            width: chipLabel.implicitWidth + 24
                            height: 28
                            radius: 14
                            color: page.activeTag === String(modelData)
                                   ? AppTheme.accent
                                   : (AppTheme.glass ? "#14FFFFFF" : AppTheme.chipBg)
                            border.width: 1
                            border.color: page.activeTag === String(modelData)
                                          ? AppTheme.accent : AppTheme.cardBorder
                            Behavior on color { ColorAnimation { duration: 120 } }

                            Text {
                                id: chipLabel
                                anchors.centerIn: parent
                                text: String(modelData)
                                color: page.activeTag === String(modelData)
                                       ? AppTheme.onAccent : AppTheme.textSecondary
                                font.pixelSize: AppTheme.fs(11)
                                font.family: AppTheme.fontFamily
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: page.activeTag = String(modelData)
                            }
                        }
                    }
                }
            }

            // 应用卡片网格
            Item {
                id: gridHost
                width: parent.width
                height: Math.max(page.cardHeight, page.gridHeight)
                visible: page.filteredItems.length > 0

                Repeater {
                    model: page.filteredItems
                    delegate: GlassCard {
                        id: storeCard
                        x: page.cardX(index)
                        y: page.cardY(index)
                        width: page.cardWidth
                        height: page.cardHeight
                        radius: 20
                        interactive: true
                        glassSource: page.glassSource
                        onClicked: page.openDetail(String(modelData.id))

                        Item {
                            anchors.fill: parent
                            anchors.margins: 14

                            // 预览：主题用配色块，插件用图标 / 首字母
                            Item {
                                id: cardPreview
                                width: parent.width
                                height: 92

                                ThemePalettePreview {
                                    anchors.fill: parent
                                    visible: page.themeKind
                                    style: "custom"
                                    themePalette: modelData.palette !== undefined ? modelData.palette : ({})
                                    corner: 12
                                    borderColor: AppTheme.glass ? "#33FFFFFF" : AppTheme.cardBorder
                                }

                                Rectangle {
                                    anchors.fill: parent
                                    visible: !page.themeKind
                                    radius: 12
                                    gradient: Gradient {
                                        GradientStop {
                                            position: 0.0
                                            color: Qt.rgba(AppTheme.accent.r, AppTheme.accent.g, AppTheme.accent.b, 0.22)
                                        }
                                        GradientStop { position: 1.0; color: AppTheme.cardBgAlt }
                                    }
                                    border.width: 1
                                    border.color: AppTheme.cardBorder

                                    Rectangle {
                                        width: 46
                                        height: 46
                                        radius: 14
                                        anchors.centerIn: parent
                                        color: Qt.rgba(AppTheme.accent.r, AppTheme.accent.g, AppTheme.accent.b, 0.16)
                                        border.width: 1
                                        border.color: Qt.rgba(AppTheme.accent.r, AppTheme.accent.g, AppTheme.accent.b, 0.5)

                                        Text {
                                            anchors.centerIn: parent
                                            text: page.pluginInitial(modelData)
                                            color: AppTheme.accent
                                            font.pixelSize: AppTheme.fs(20)
                                            font.weight: Font.Bold
                                            font.family: AppTheme.fontFamily
                                        }
                                    }
                                }
                            }

                            Text {
                                id: cardName
                                anchors.top: cardPreview.bottom
                                anchors.topMargin: 10
                                width: parent.width - 54
                                text: String(modelData.name)
                                color: AppTheme.textPrimary
                                font.pixelSize: AppTheme.fs(14)
                                font.weight: Font.DemiBold
                                font.family: AppTheme.fontFamily
                                elide: Text.ElideRight
                            }

                            Text {
                                anchors.top: cardName.bottom
                                anchors.topMargin: 3
                                width: parent.width
                                text: String(modelData.author !== undefined && String(modelData.author) !== ""
                                             ? modelData.author : qsTr("深清社区"))
                                color: AppTheme.textTertiary
                                font.pixelSize: AppTheme.fs(10)
                                font.family: AppTheme.fontFamily
                                elide: Text.ElideRight
                            }

                            Row {
                                anchors.top: cardName.bottom
                                anchors.topMargin: 2
                                anchors.right: parent.right
                                spacing: 3
                                Text {
                                    text: "★"
                                    color: AppTheme.accent
                                    font.pixelSize: AppTheme.fs(11)
                                    font.family: AppTheme.fontFamily
                                }
                                Text {
                                    text: page.ratingText(modelData) + " · " + page.downloadsText(modelData)
                                    color: AppTheme.textTertiary
                                    font.pixelSize: AppTheme.fs(10)
                                    font.family: AppTheme.fontFamily
                                }
                            }

                            // 底部：简介 + 安装按钮
                            Text {
                                id: cardSummary
                                anchors.left: parent.left
                                anchors.right: installButton.left
                                anchors.rightMargin: 8
                                anchors.bottom: parent.bottom
                                height: 30
                                text: String(modelData.summary !== undefined && modelData.summary !== ""
                                             ? modelData.summary : modelData.description)
                                color: AppTheme.textSecondary
                                font.pixelSize: AppTheme.fs(10)
                                font.family: AppTheme.fontFamily
                                wrapMode: Text.WordWrap
                                maximumLineCount: 2
                                elide: Text.ElideRight
                                lineHeight: 1.2
                            }

                            GlassButton {
                                id: installButton
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                text: page.installLabel(modelData)
                                tone: page.installState(modelData) === "install"
                                      || page.installState(modelData) === "update" ? "accent" : "tinted"
                                fontSize: 11
                                padH: 14
                                minHeight: 30
                                enabled: page.installState(modelData) !== "installing"
                                onClicked: page.handleInstall(modelData)
                            }
                        }
                    }
                }
            }

            // 空结果
            Text {
                width: parent.width
                visible: page.filteredItems.length === 0 && !page.loading
                text: page.searchText.trim() !== "" || page.activeTag !== qsTr("全部")
                      ? qsTr("没有符合条件的%1，换个关键词试试").arg(page.kindLabel)
                      : qsTr("商店暂时没有可用的%1").arg(page.kindLabel)
                color: AppTheme.textTertiary
                font.pixelSize: AppTheme.fs(12)
                font.family: AppTheme.fontFamily
                horizontalAlignment: Text.AlignHCenter
                topPadding: 20
                bottomPadding: 20
            }

            Text {
                width: parent.width
                visible: page.loading
                text: qsTr("正在加载商店目录…")
                color: AppTheme.textTertiary
                font.pixelSize: AppTheme.fs(12)
                font.family: AppTheme.fontFamily
                horizontalAlignment: Text.AlignHCenter
            }

            Item { width: parent.width; height: 2 }
        }

        // ---------- 详情页 ----------
        Column {
            id: detailColumn
            visible: page.view === "detail"
            width: Math.min(flick.width - 96, 860)
            x: (flick.width - width) / 2
            y: 26
            spacing: 14

            // 顶部：返回商店
            Row {
                spacing: 10
                Item {
                    id: detailBackButton
                    width: 32
                    height: 32
                    Rectangle {
                        anchors.fill: parent
                        radius: 16
                        color: detailBackArea.containsMouse ? AppTheme.cardBgAlt : AppTheme.cardBg
                        border.width: 1
                        border.color: AppTheme.cardBorder
                    }
                    Glyph {
                        anchors.centerIn: parent
                        kind: "chevronLeft"
                        size: 15
                        color: AppTheme.textSecondary
                    }
                    MouseArea {
                        id: detailBackArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.back()
                    }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: page.pageTitle
                    color: AppTheme.textSecondary
                    font.pixelSize: AppTheme.fs(12)
                    font.family: AppTheme.fontFamily
                }
            }

            // 大预览：主题 = palette 渐变底 + 居中的迷你界面，插件 = 图标面
            Item {
                id: detailHero
                width: parent.width
                height: 196

                Rectangle {
                    anchors.fill: parent
                    visible: page.themeKind
                    radius: 20
                    gradient: Gradient {
                        GradientStop {
                            position: 0.0
                            color: page.themeKind ? page.paletteValue(page.detailItem, "bgTop", "#123243") : "#123243"
                        }
                        GradientStop {
                            position: 0.6
                            color: page.themeKind ? page.paletteValue(page.detailItem, "bgMid", "#071F2A") : "#071F2A"
                        }
                        GradientStop {
                            position: 1.0
                            color: page.themeKind ? page.paletteValue(page.detailItem, "bgBottom", "#04121C") : "#04121C"
                        }
                    }
                    border.width: 1
                    border.color: AppTheme.glass ? "#33FFFFFF" : AppTheme.cardBorderStrong
                }

                ThemePalettePreview {
                    visible: page.themeKind
                    anchors.centerIn: parent
                    width: Math.min(520, detailHero.width * 0.66)
                    height: Math.min(148, detailHero.height * 0.76)
                    style: "custom"
                    themePalette: page.detailItem.palette !== undefined ? page.detailItem.palette : ({})
                    corner: 14
                    borderColor: "#40FFFFFF"
                }

                Rectangle {
                    anchors.fill: parent
                    visible: !page.themeKind
                    radius: 20
                    gradient: Gradient {
                        GradientStop {
                            position: 0.0
                            color: Qt.rgba(AppTheme.accent.r, AppTheme.accent.g, AppTheme.accent.b, 0.3)
                        }
                        GradientStop { position: 0.55; color: AppTheme.cardBgAlt }
                        GradientStop { position: 1.0; color: AppTheme.cardBg }
                    }
                    border.width: 1
                    border.color: AppTheme.cardBorder

                    Rectangle {
                        width: 82
                        height: 82
                        radius: 24
                        anchors.centerIn: parent
                        color: Qt.rgba(AppTheme.accent.r, AppTheme.accent.g, AppTheme.accent.b, 0.16)
                        border.width: 1
                        border.color: Qt.rgba(AppTheme.accent.r, AppTheme.accent.g, AppTheme.accent.b, 0.5)
                        Text {
                            anchors.centerIn: parent
                            text: page.pluginInitial(page.detailItem)
                            color: AppTheme.accent
                            font.pixelSize: AppTheme.fs(34)
                            font.weight: Font.Bold
                            font.family: AppTheme.fontFamily
                        }
                    }
                }
            }

            // 标题 / 作者 / 版本 / 评分 / 下载量 / 安装按钮
            Item {
                width: parent.width
                height: detailTitleColumn.height + 6

                Column {
                    id: detailTitleColumn
                    anchors.left: parent.left
                    anchors.right: detailInstallButton.left
                    anchors.rightMargin: 16
                    spacing: 6

                    Row {
                        spacing: 8
                        Text {
                            text: String(page.detailItem.name !== undefined ? page.detailItem.name : qsTr("商店条目"))
                            color: AppTheme.textPrimary
                            font.pixelSize: AppTheme.fs(24)
                            font.weight: Font.Bold
                            font.family: AppTheme.fontFamily
                        }
                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            width: versionLabel.implicitWidth + 14
                            height: 20
                            radius: 10
                            color: AppTheme.chipBg
                            border.width: 1
                            border.color: AppTheme.cardBorder
                            Text {
                                id: versionLabel
                                anchors.centerIn: parent
                                text: "v" + String(page.detailItem.version !== undefined ? page.detailItem.version : "1.0.0")
                                color: AppTheme.textTertiary
                                font.pixelSize: AppTheme.fs(10)
                                font.family: AppTheme.fontFamily
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        text: qsTr("作者：%1").arg(String(page.detailItem.author !== undefined && String(page.detailItem.author) !== ""
                                                     ? page.detailItem.author : qsTr("深清社区")))
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(12)
                        font.family: AppTheme.fontFamily
                        elide: Text.ElideRight
                    }

                    Row {
                        spacing: 6
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: page.filledStars(page.detailItem.rating)
                            color: AppTheme.accent
                            font.pixelSize: AppTheme.fs(14)
                            font.family: AppTheme.fontFamily
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: page.emptyStars(page.detailItem.rating)
                            color: AppTheme.textTertiary
                            font.pixelSize: AppTheme.fs(14)
                            font.family: AppTheme.fontFamily
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: page.ratingText(page.detailItem) + " · " + page.downloadsText(page.detailItem)
                            color: AppTheme.textSecondary
                            font.pixelSize: AppTheme.fs(12)
                            font.family: AppTheme.fontFamily
                        }
                    }

                    // 标签
                    Row {
                        spacing: 6
                        Repeater {
                            model: page.detailItem.tags !== undefined ? page.detailItem.tags : []
                            delegate: Rectangle {
                                width: tagLabel.implicitWidth + 16
                                height: 20
                                radius: 10
                                color: AppTheme.chipBg
                                Text {
                                    id: tagLabel
                                    anchors.centerIn: parent
                                    text: String(modelData)
                                    color: AppTheme.textTertiary
                                    font.pixelSize: AppTheme.fs(10)
                                    font.family: AppTheme.fontFamily
                                }
                            }
                        }
                    }
                }

                GlassButton {
                    id: detailInstallButton
                    anchors.right: parent.right
                    anchors.top: parent.top
                    width: 120
                    minHeight: 40
                    fontSize: 13
                    text: page.installLabel(page.detailItem)
                    tone: page.installState(page.detailItem) === "install"
                          || page.installState(page.detailItem) === "update" ? "accent" : "tinted"
                    enabled: page.installState(page.detailItem) !== "installing"
                    onClicked: page.handleInstall(page.detailItem)
                }
            }

            // 安装进度
            Item {
                width: parent.width
                height: 8
                visible: page.installingId !== "" && page.installingId === page.detailId
                Rectangle {
                    anchors.fill: parent
                    radius: 4
                    color: AppTheme.divider
                }
                Rectangle {
                    width: Math.max(6, parent.width * page.installProgress)
                    height: parent.height
                    radius: 4
                    color: AppTheme.accent
                    Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
                }
            }

            // 介绍
            GlassCard {
                width: parent.width
                implicitHeight: introColumn.implicitHeight + 32
                height: implicitHeight
                radius: 20
                interactive: false
                glassSource: page.glassSource

                Column {
                    id: introColumn
                    x: 16
                    y: 16
                    width: parent.width - 32
                    spacing: 8
                    Text {
                        text: qsTr("介绍")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(14)
                        font.weight: Font.DemiBold
                        font.family: AppTheme.fontFamily
                    }
                    Text {
                        width: parent.width
                        text: {
                            var text = String(page.detailItem.description !== undefined ? page.detailItem.description : "")
                            if (text.length === 0) text = String(page.detailItem.summary !== undefined ? page.detailItem.summary : "")
                            return text.length > 0 ? text : qsTr("暂无介绍")
                        }
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(12)
                        font.family: AppTheme.fontFamily
                        wrapMode: Text.WordWrap
                        lineHeight: 1.5
                    }
                }
            }

            // 主题配色 swatch
            GlassCard {
                width: parent.width
                visible: page.themeKind
                implicitHeight: paletteColumn.implicitHeight + 32
                height: implicitHeight
                radius: 20
                interactive: false
                glassSource: page.glassSource

                Column {
                    id: paletteColumn
                    x: 16
                    y: 16
                    width: parent.width - 32
                    spacing: 10
                    Text {
                        text: qsTr("配色")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(14)
                        font.weight: Font.DemiBold
                        font.family: AppTheme.fontFamily
                    }
                    Row {
                        spacing: 10
                        Repeater {
                            model: page.paletteSwatches(page.detailItem)
                            delegate: Column {
                                spacing: 5
                                Rectangle {
                                    width: 54
                                    height: 34
                                    radius: 9
                                    color: String(modelData)
                                    border.width: 1
                                    border.color: AppTheme.cardBorder
                                }
                                Text {
                                    width: 54
                                    text: String(modelData)
                                    color: AppTheme.textTertiary
                                    font.pixelSize: AppTheme.fs(8)
                                    font.family: C.monoFont
                                }
                            }
                        }
                    }
                }
            }

            // 截图（可空）
            GlassCard {
                width: parent.width
                visible: page.detailScreenshots(page.detailItem).length > 0
                implicitHeight: shotsColumn.implicitHeight + 32
                height: implicitHeight
                radius: 20
                interactive: false
                glassSource: page.glassSource

                Column {
                    id: shotsColumn
                    x: 16
                    y: 16
                    width: parent.width - 32
                    spacing: 10
                    Text {
                        text: qsTr("截图")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(14)
                        font.weight: Font.DemiBold
                        font.family: AppTheme.fontFamily
                    }
                    Flickable {
                        width: parent.width
                        height: 140
                        contentWidth: shotsRow.width
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        flickableDirection: Flickable.HorizontalFlick
                        Row {
                            id: shotsRow
                            spacing: 10
                            Repeater {
                                model: page.detailScreenshots(page.detailItem)
                                delegate: Rectangle {
                                    width: 220
                                    height: 132
                                    radius: 12
                                    color: AppTheme.cardBgAlt
                                    border.width: 1
                                    border.color: AppTheme.cardBorder
                                    Image {
                                        anchors.fill: parent
                                        anchors.margins: 2
                                        source: String(modelData)
                                        fillMode: Image.PreserveAspectCrop
                                        asynchronous: true
                                        visible: status === Image.Ready
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // 评分分布
            GlassCard {
                width: parent.width
                implicitHeight: ratingColumn.implicitHeight + 32
                height: implicitHeight
                radius: 20
                interactive: false
                glassSource: page.glassSource

                Column {
                    id: ratingColumn
                    x: 16
                    y: 16
                    width: parent.width - 32
                    spacing: 12
                    Text {
                        text: qsTr("评分与评论")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(14)
                        font.weight: Font.DemiBold
                        font.family: AppTheme.fontFamily
                    }

                    Row {
                        width: parent.width
                        spacing: 24

                        Column {
                            width: 150
                            spacing: 4
                            Text {
                                text: page.ratingText(page.detailItem)
                                color: AppTheme.textPrimary
                                font.pixelSize: AppTheme.fs(34)
                                font.weight: Font.Bold
                                font.family: AppTheme.fontFamily
                            }
                            Row {
                                spacing: 2
                                Text {
                                    text: page.filledStars(page.detailItem.rating)
                                    color: AppTheme.accent
                                    font.pixelSize: AppTheme.fs(13)
                                    font.family: AppTheme.fontFamily
                                }
                                Text {
                                    text: page.emptyStars(page.detailItem.rating)
                                    color: AppTheme.textTertiary
                                    font.pixelSize: AppTheme.fs(13)
                                    font.family: AppTheme.fontFamily
                                }
                            }
                            Text {
                                text: qsTr("共 %1 条评分").arg(page.detailComments.length)
                                color: AppTheme.textTertiary
                                font.pixelSize: AppTheme.fs(10)
                                font.family: AppTheme.fontFamily
                            }
                        }

                        Column {
                            width: parent.width - 174
                            spacing: 5
                            Repeater {
                                model: 5
                                delegate: Row {
                                    width: parent.width
                                    spacing: 8
                                    Text {
                                        width: 24
                                        text: (5 - index) + "★"
                                        color: AppTheme.textTertiary
                                        font.pixelSize: AppTheme.fs(10)
                                        font.family: AppTheme.fontFamily
                                    }
                                    Rectangle {
                                        id: ratingTrack
                                        width: parent.width - 24 - 8 - 34 - 8
                                        height: 6
                                        radius: 3
                                        anchors.verticalCenter: parent.verticalCenter
                                        color: AppTheme.divider
                                        Rectangle {
                                            width: Math.max(0, ratingTrack.width
                                                            * page.ratingDistribution[index] / page.distributionMax)
                                            height: parent.height
                                            radius: 3
                                            color: AppTheme.accent
                                            Behavior on width { NumberAnimation { duration: 180 } }
                                        }
                                    }
                                    Text {
                                        width: 34
                                        text: String(page.ratingDistribution[index])
                                        color: AppTheme.textTertiary
                                        font.pixelSize: AppTheme.fs(10)
                                        font.family: AppTheme.fontFamily
                                    }
                                }
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 1
                        color: AppTheme.divider
                    }

                    Text {
                        visible: page.detailPending > 0
                        text: qsTr("审核中 %1 条").arg(page.detailPending)
                        color: AppTheme.accent
                        font.pixelSize: AppTheme.fs(11)
                        font.family: AppTheme.fontFamily
                    }

                    // 评论列表
                    Repeater {
                        model: page.detailComments
                        delegate: Row {
                            width: parent.width
                            spacing: 10

                            Rectangle {
                                width: 32
                                height: 32
                                radius: 16
                                color: page.avatarColor(modelData.author)
                                Text {
                                    anchors.centerIn: parent
                                    text: page.avatarInitial(modelData.author)
                                    color: "#FFFFFF"
                                    font.pixelSize: AppTheme.fs(13)
                                    font.weight: Font.DemiBold
                                    font.family: AppTheme.fontFamily
                                }
                            }

                            Column {
                                width: parent.width - 42
                                spacing: 3
                                Row {
                                    spacing: 8
                                    Text {
                                        text: String(modelData.author !== undefined ? modelData.author : qsTr("匿名"))
                                        color: AppTheme.textPrimary
                                        font.pixelSize: AppTheme.fs(12)
                                        font.weight: Font.DemiBold
                                        font.family: AppTheme.fontFamily
                                    }
                                    Text {
                                        text: page.filledStars(modelData.rating)
                                        color: AppTheme.accent
                                        font.pixelSize: AppTheme.fs(10)
                                        font.family: AppTheme.fontFamily
                                    }
                                    Text {
                                        text: page.formatTime(modelData.created_at)
                                        color: AppTheme.textTertiary
                                        font.pixelSize: AppTheme.fs(9)
                                        font.family: AppTheme.fontFamily
                                    }
                                }
                                Text {
                                    width: parent.width
                                    text: String(modelData.text !== undefined ? modelData.text : "")
                                    color: AppTheme.textSecondary
                                    font.pixelSize: AppTheme.fs(11)
                                    font.family: AppTheme.fontFamily
                                    wrapMode: Text.WordWrap
                                    lineHeight: 1.4
                                }
                            }
                        }
                    }

                    Text {
                        visible: page.detailComments.length === 0
                        width: parent.width
                        text: qsTr("还没有评论，来第一条吧")
                        color: AppTheme.textTertiary
                        font.pixelSize: AppTheme.fs(12)
                        font.family: AppTheme.fontFamily
                        horizontalAlignment: Text.AlignHCenter
                        topPadding: 10
                        bottomPadding: 10
                    }

                    Rectangle {
                        width: parent.width
                        height: 1
                        color: AppTheme.divider
                    }

                    // 写评论
                    Text {
                        text: qsTr("写评论")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(13)
                        font.weight: Font.DemiBold
                        font.family: AppTheme.fontFamily
                    }

                    Row {
                        spacing: 4
                        Repeater {
                            model: 5
                            delegate: Text {
                                text: index < page.commentRating ? "★" : "☆"
                                color: index < page.commentRating ? AppTheme.accent : AppTheme.textTertiary
                                font.pixelSize: AppTheme.fs(20)
                                font.family: AppTheme.fontFamily

                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: page.commentRating = index + 1
                                }
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 96
                        radius: 12
                        color: AppTheme.cardBgAlt
                        border.width: 1
                        border.color: commentInput.activeFocus ? AppTheme.accent : AppTheme.cardBorder

                        TextEdit {
                            id: commentInput
                            anchors.fill: parent
                            anchors.margins: 10
                            color: AppTheme.textPrimary
                            selectionColor: AppTheme.accentSoft
                            selectedTextColor: "#FFFFFF"
                            font.pixelSize: AppTheme.fs(12)
                            font.family: AppTheme.fontFamily
                            textFormat: TextEdit.PlainText
                            wrapMode: TextEdit.Wrap
                            clip: true
                            text: page.commentDraft
                            onTextChanged: page.commentDraft = text
                        }

                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 12
                            anchors.top: parent.top
                            anchors.topMargin: 10
                            visible: commentInput.text.length === 0
                            text: qsTr("写下你的使用感受…")
                            color: AppTheme.textTertiary
                            font.pixelSize: AppTheme.fs(12)
                            font.family: AppTheme.fontFamily
                        }
                    }

                    Row {
                        width: parent.width
                        height: 34
                        spacing: 8
                        Text {
                            id: submitHint
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("提交后进入审核，通过后才会展示")
                            color: AppTheme.textTertiary
                            font.pixelSize: AppTheme.fs(10)
                            font.family: AppTheme.fontFamily
                        }
                        Item {
                            width: Math.max(1, parent.width - submitHint.width - submitButton.width - 16)
                            height: 1
                        }
                        GlassButton {
                            id: submitButton
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("提交评论")
                            tone: "accent"
                            fontSize: 12
                            padH: 16
                            minHeight: 34
                            enabled: page.commentDraft.trim().length > 0
                            onClicked: page.submitComment()
                        }
                    }
                }
            }

            Item { width: parent.width; height: 2 }
        }
    }

    // 滚动条
    Rectangle {
        visible: flick.contentHeight > flick.height + 4
        width: 4
        radius: 2
        color: "#26FFFFFF"
        x: flick.width - 14
        height: Math.max(48, flick.height * flick.height / Math.max(1, flick.contentHeight))
        y: 18 + Math.max(0, Math.min(1, flick.contentY / Math.max(1, flick.contentHeight - flick.height)))
           * Math.max(1, flick.height - 36 - height)
    }

    // 轻提示
    Rectangle {
        id: toast
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 26
        width: toastLabel.implicitWidth + 34
        height: 38
        radius: 19
        color: AppTheme.glass ? "#D90A1B26" : Qt.rgba(AppTheme.cardBg.r, AppTheme.cardBg.g, AppTheme.cardBg.b, 0.96)
        border.width: 1
        border.color: AppTheme.cardBorderStrong
        opacity: page.toastVisible ? 1 : 0
        visible: opacity > 0.01
        z: 50
        Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

        Text {
            id: toastLabel
            anchors.centerIn: parent
            text: page.toastText
            color: AppTheme.textPrimary
            font.pixelSize: AppTheme.fs(12)
            font.family: AppTheme.fontFamily
        }
    }

    // ================= 辅助数据 =================
    function paletteValue(item, key, fallback) {
        if (!item || item.palette === undefined || item.palette === null) return fallback
        var value = item.palette[key]
        if (value === undefined || value === null) return fallback
        return String(value)
    }

    function paletteSwatches(item) {
        var palette = item && item.palette ? item.palette : ({})
        var keys = ["bgTop", "bgMid", "bgBottom", "accent", "cardBg", "textPrimary"]
        var result = []
        for (var i = 0; i < keys.length; i++) {
            if (palette[keys[i]] !== undefined) result.push(String(palette[keys[i]]))
        }
        return result
    }

    function detailScreenshots(item) {
        if (!item || item.screenshots === undefined || item.screenshots === null) return []
        return item.screenshots
    }

    // 后端缺失商店接口时的内置示例目录（与 backend builtin_catalog 一致的 6 主题 + 4 插件）
    function sampleCatalog() {
        // 仅在后端缺少商店接口时使用的内置示例目录（与 backend builtin_catalog 一致），
        // 属于演示数据、不是界面文案，因此不包 qsTr。
        return [
            { id: "theme-aurora", kind: "theme", name: "极光", author: "Clarity Studio",
              summary: "青绿极光掠过深夜海面",
              description: "以深海为底、极光青绿为强调色的深色主题包，适合夜间长时间专注。",
              version: "1.0.0", rating: 4.8, downloads: 12840, tags: ["深色", "青绿", "夜间"],
              screenshots: [],
              palette: { bgTop: "#0A1F2E", bgMid: "#06202C", bgBottom: "#04121A", accent: "#35E0C8", cardBg: "#0D2634", textPrimary: "#EAF8FC" } },
            { id: "theme-sakura", kind: "theme", name: "樱雾", author: "Aki",
              summary: "淡粉雾气里的安静书桌",
              description: "低饱和樱粉浅色主题，配深莓强调色，白天的清空间会更柔和。",
              version: "1.0.0", rating: 4.6, downloads: 9360, tags: ["浅色", "樱粉", "温柔"],
              screenshots: [],
              palette: { bgTop: "#F6EEF1", bgMid: "#F1E3E9", bgBottom: "#E9D6DE", accent: "#D46A8C", cardBg: "#FFFFFF", textPrimary: "#3A2230" } },
            { id: "theme-forest", kind: "theme", name: "苔原", author: "青苔",
              summary: "安静生长的深林绿",
              description: "以苔绿与松针色构成的深色主题，长时间盯屏幕也不刺眼。",
              version: "1.0.0", rating: 4.5, downloads: 7710, tags: ["深色", "自然", "护眼"],
              screenshots: [],
              palette: { bgTop: "#0C1F16", bgMid: "#0A291C", bgBottom: "#07170F", accent: "#6FD8A0", cardBg: "#103024", textPrimary: "#E9F7EF" } },
            { id: "theme-mono", kind: "theme", name: "墨白", author: "Norr",
              summary: "只有黑白灰的极简空间",
              description: "去掉一切彩色干扰的墨白浅色主题，强调色仍是近黑，适合写作与阅读。",
              version: "1.0.0", rating: 4.3, downloads: 5620, tags: ["浅色", "极简", "写作"],
              screenshots: [],
              palette: { bgTop: "#F7F7F5", bgMid: "#EFEFEB", bgBottom: "#E6E6E0", accent: "#2B2B2B", cardBg: "#FFFFFF", textPrimary: "#1B1B1B" } },
            { id: "theme-sunset", kind: "theme", name: "暮橘", author: "Haru",
              summary: "黄昏落在桌面的一角",
              description: "暮色酒红与暖橘强调色，给夜晚的专注一点温度。",
              version: "1.0.0", rating: 4.7, downloads: 11050, tags: ["深色", "暖色", "黄昏"],
              screenshots: [],
              palette: { bgTop: "#2C1420", bgMid: "#3A1A1E", bgBottom: "#1A0B12", accent: "#FF9E64", cardBg: "#3A1C24", textPrimary: "#FFE9DC" } },
            { id: "theme-cyber", kind: "theme", name: "霓虹夜", author: "Nova",
              summary: "霓虹紫在电路板上呼吸",
              description: "高对比霓虹紫主题包，配合深紫卡片，适合喜欢赛博感的用户。",
              version: "1.0.0", rating: 4.4, downloads: 6890, tags: ["深色", "赛博", "紫色"],
              screenshots: [],
              palette: { bgTop: "#0B0B1A", bgMid: "#14102B", bgBottom: "#07060F", accent: "#B45CFF", cardBg: "#171330", textPrimary: "#EDE6FF" } },
            { id: "pomodoro-plus", kind: "plugin", name: "清番增强", author: "社区",
              summary: "更细的番茄钟节奏与统计",
              description: "在清番基础上增加长休息提示、今日完成轮次与周统计，数据保存在插件目录。",
              version: "1.0.0", rating: 4.6, downloads: 8450, tags: ["专注", "统计", "番茄钟"], screenshots: [], palette: {} },
            { id: "muyu", kind: "plugin", name: "木鱼", author: "社区",
              summary: "敲一下，功德加一",
              description: "遮罩右下角的小木鱼，点击有敲击动画与功德计数，专注时也能小小放松。",
              version: "1.0.0", rating: 4.9, downloads: 15230, tags: ["趣味", "遮罩组件", "解压"], screenshots: [], palette: {} },
            { id: "water-reminder", kind: "plugin", name: "喝水提醒", author: "社区",
              summary: "按时提醒你补充水分",
              description: "专注期间每隔一段时间弹出轻提示，最多每小时一次，不会打断锁定流程。",
              version: "1.0.0", rating: 4.2, downloads: 4980, tags: ["健康", "提醒"], screenshots: [], palette: {} },
            { id: "media-island", kind: "plugin", name: "媒体岛增强", author: "社区",
              summary: "把正在播放的歌放得更显眼",
              description: "在遮罩顶部增加媒体信息与音量快捷入口，支持常见播放器的 SMTC 信息。",
              version: "1.0.0", rating: 4.5, downloads: 7030, tags: ["媒体", "遮罩组件"], screenshots: [], palette: {} }
        ]
    }

    // ================= 后端信号 =================
    Connections {
        target: (typeof App !== "undefined") ? App : null

        function onStoreChanged() {
            page.storeRevision += 1
            page.syncStatus()
        }
        function onCustomThemesChanged() { page.storeRevision += 1 }
        function onPluginsChanged() { page.storeRevision += 1 }
        function onStoreCommentsChanged(itemId) {
            if (String(itemId) === page.detailId) page.loadComments()
        }
    }

    onActiveChanged: {
        if (page.active && !page.catalogLoaded) page.ensureCatalog(false)
    }
}
