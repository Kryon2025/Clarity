import QtQuick
import "../theme"
import "../components"
import "../glass"
import "../components/Constants.js" as C

// v0.10 独立更新页：当前版本 / 检查更新 / 新版本说明 / 下载安装 / 自动检查 / 最近更新日志
Item {
    id: page

    property Item glassSource: null
    property bool animationsEnabled: true

    readonly property string updateState: (typeof App !== "undefined" && App.updateState !== undefined)
                                         ? String(App.updateState) : "idle"
    readonly property bool updateAvailable: (typeof App !== "undefined" && App.updateAvailable === true)
    readonly property string latestVersion: (typeof App !== "undefined" && App.updateLatestVersion !== undefined)
                                            ? String(App.updateLatestVersion) : ""
    readonly property string updateNotes: (typeof App !== "undefined" && App.updateNotes !== undefined)
                                          ? String(App.updateNotes) : ""
    readonly property int updateProgress: (typeof App !== "undefined" && App.updateProgress !== undefined)
                                          ? Math.max(0, Math.min(100, Number(App.updateProgress))) : 0
    readonly property string updateError: (typeof App !== "undefined" && App.updateError !== undefined)
                                          ? String(App.updateError) : ""
    readonly property bool autoUpdateEnabled: (typeof App !== "undefined" && App.autoUpdate === true)

    readonly property string statusText: {
        if (page.updateState === "checking") return qsTr("正在检查更新…")
        if (page.updateState === "available") return qsTr("发现新版本 v%1").arg(page.latestVersion)
        if (page.updateState === "downloading") return qsTr("正在下载更新 %1%").arg(Math.round(page.updateProgress))
        if (page.updateState === "ready") return qsTr("更新已就绪，安装并重启即可")
        if (page.updateState === "error") return page.updateError !== "" ? page.updateError : qsTr("检查更新失败")
        return qsTr("已是最新版本")
    }

    function checkUpdate() {
        if (typeof App !== "undefined" && typeof App.checkUpdate === "function")
            App.checkUpdate()
    }
    function downloadUpdate() {
        if (typeof App !== "undefined" && typeof App.downloadUpdate === "function")
            App.downloadUpdate()
    }
    function cancelDownload() {
        if (typeof App !== "undefined" && typeof App.cancelUpdateDownload === "function")
            App.cancelUpdateDownload()
    }
    function installUpdate() {
        if (typeof App !== "undefined" && typeof App.installUpdate === "function")
            App.installUpdate()
    }
    function openReleasePage() {
        if (typeof App !== "undefined" && typeof App.openReleasePage === "function")
            App.openReleasePage()
        else
            Qt.openUrlExternally("https://github.com/Kryon2025/Clarity/releases")
    }
    function setAutoUpdate(enabled) {
        if (typeof App !== "undefined" && typeof App.setAutoUpdate === "function")
            App.setAutoUpdate(!!enabled)
    }

    // ---------- v0.16 更新下载源（GitHub / GitLink / Gitee / 自定义） ----------
    readonly property bool hasBackendSources: (typeof App !== "undefined" && App.updateSources !== undefined
                                               && App.updateSources !== null && App.updateSources.length > 0)
    property string localSourceId: "github"
    property var localCustomSources: []
    property string localSourceError: ""
    property bool addSourceOpen: false
    property string addSourceName: ""
    property string addSourceUrl: ""
    property string addSourceError: ""

    readonly property var fallbackSources: [
        { id: "github", name: "GitHub", kind: "github", custom: false, url: "https://github.com/Kryon2025/Clarity/releases" },
        { id: "gitlink", name: "GitLink", kind: "gitlink", custom: false, url: "https://gitlink.org.cn/Kryon/Clarity" },
        { id: "gitee", name: "Gitee", kind: "gitee", custom: false, url: "https://gitee.com/kryonF/Clarity" }
    ]
    readonly property var sourceItems: {
        var out = []
        var list = page.hasBackendSources ? App.updateSources : page.fallbackSources
        for (var i = 0; i < list.length; i++) {
            var item = list[i]
            if (item === null || item === undefined) continue
            var sourceId = String(item.id !== undefined ? item.id : "")
            if (sourceId === "") continue
            out.push({
                id: sourceId,
                name: item.name !== undefined ? String(item.name)
                      : (item.label !== undefined ? String(item.label) : sourceId),
                kind: item.kind !== undefined ? String(item.kind) : "",
                custom: item.custom === true || sourceId.indexOf("custom:") === 0
            })
        }
        if (!page.hasBackendSources) {
            for (var j = 0; j < page.localCustomSources.length; j++)
                out.push(page.localCustomSources[j])
        }
        return out
    }
    readonly property var customSourceList: {
        var out = []
        for (var i = 0; i < page.sourceItems.length; i++)
            if (page.sourceItems[i].custom === true) out.push(page.sourceItems[i])
        return out
    }
    readonly property string currentSourceId: {
        if (page.hasBackendSources)
            return String(App.updateSource !== undefined && App.updateSource !== null ? App.updateSource : "")
        return page.localSourceId
    }
    readonly property string currentSourceName: {
        var list = page.sourceItems
        for (var i = 0; i < list.length; i++)
            if (String(list[i].id) === page.currentSourceId) return String(list[i].name)
        return page.currentSourceId !== "" ? page.currentSourceId : "GitHub"
    }
    readonly property var customSourceDetails: (typeof App !== "undefined" && App.customUpdateSources !== undefined
                                                && App.customUpdateSources !== null)
                                               ? App.customUpdateSources : page.localCustomSources
    function sourceUrlOf(id) {
        var list = page.customSourceDetails
        for (var i = 0; i < list.length; i++)
            if (String(list[i].id) === String(id)) return String(list[i].url !== undefined ? list[i].url : "")
        return ""
    }
    readonly property string currentSourceUrl: page.sourceUrlOf(page.currentSourceId)
    readonly property string sourceErrorText: {
        if (typeof App !== "undefined" && App.updateSourceError !== undefined
                && String(App.updateSourceError) !== "")
            return String(App.updateSourceError)
        return page.localSourceError
    }

    function chooseSource(id) {
        page.localSourceError = ""
        if (page.hasBackendSources && typeof App.setUpdateSource === "function")
            App.setUpdateSource(String(id))
        else
            page.localSourceId = String(id)
    }
    function openAddSource() {
        page.addSourceName = ""
        page.addSourceUrl = ""
        page.addSourceError = ""
        page.addSourceOpen = true
    }
    function closeAddSource() {
        page.addSourceOpen = false
    }
    function submitAddSource() {
        var name = String(page.addSourceName).trim()
        var url = String(page.addSourceUrl).trim()
        if (url === "") {
            page.addSourceError = qsTr("请填写更新源地址")
            return
        }
        if (!/^https?:\/\//i.test(url)) {
            page.addSourceError = qsTr("地址需要以 http:// 或 https:// 开头")
            return
        }
        if (typeof App !== "undefined" && typeof App.addCustomUpdateSource === "function") {
            var created = App.addCustomUpdateSource(name !== "" ? name : qsTr("自定义源"), url, "")
            if (created !== undefined && created !== null && String(created) !== "") {
                page.addSourceOpen = false
                return
            }
            var error = (typeof App !== "undefined" && App.updateSourceError !== undefined)
                        ? String(App.updateSourceError) : ""
            page.addSourceError = error !== "" ? error : qsTr("添加失败")
            return
        }
        // 后端缺失时的本地兜底：只在本页生效（本轮运行内）
        var list = page.localCustomSources.slice()
        list.push({ id: "custom:" + Date.now(), name: name !== "" ? name : qsTr("自定义源"),
                    kind: "custom", custom: true, url: url })
        page.localCustomSources = list
        page.localSourceId = String(list[list.length - 1].id)
        page.addSourceOpen = false
    }
    function removeCustomSource(id) {
        if (typeof App !== "undefined" && typeof App.removeCustomUpdateSource === "function") {
            App.removeCustomUpdateSource(String(id))
            return
        }
        var list = []
        for (var i = 0; i < page.localCustomSources.length; i++)
            if (String(page.localCustomSources[i].id) !== String(id))
                list.push(page.localCustomSources[i])
        page.localCustomSources = list
        if (String(page.localSourceId) === String(id)) page.localSourceId = "github"
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
            width: Math.min(flick.width - 96, 860)
            x: (flick.width - width) / 2
            y: 24
            spacing: 16

            Item {
                width: parent.width
                height: 78
                Column {
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    spacing: 6
                    Text {
                        text: qsTr("更新")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(30)
                        font.weight: Font.Bold
                        font.family: AppTheme.fontFamily
                        font.letterSpacing: 1
                    }
                    Text {
                        text: qsTr("深清当前版本 v%1 · 数据保存在本机").arg(String(App.version))
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(13)
                        font.family: AppTheme.fontFamily
                    }
                }

                // v0.16 页头：下载源选择 + 添加自定义源
                Row {
                    objectName: "UpdateSourceHeader"
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 2
                    spacing: 8

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: qsTr("下载源")
                        color: AppTheme.textTertiary
                        font.pixelSize: AppTheme.fs(11)
                        font.family: AppTheme.fontFamily
                    }

                    Item {
                        id: sourceField
                        objectName: "UpdateSourceField"
                        width: Math.max(132, sourceFieldLabel.implicitWidth + 44)
                        height: 30
                        Rectangle {
                            anchors.fill: parent
                            radius: 9
                            color: sourceFieldArea.containsMouse ? AppTheme.cardBgAlt : AppTheme.cardBg
                            border.width: 1
                            border.color: sourceCombo.opened ? AppTheme.accent : AppTheme.cardBorder
                        }
                        Text {
                            id: sourceFieldLabel
                            anchors.left: parent.left
                            anchors.leftMargin: 11
                            anchors.verticalCenter: parent.verticalCenter
                            text: page.currentSourceName
                            color: AppTheme.textPrimary
                            font.pixelSize: AppTheme.fs(11)
                            font.family: AppTheme.fontFamily
                        }
                        Text {
                            anchors.right: parent.right
                            anchors.rightMargin: 9
                            anchors.verticalCenter: parent.verticalCenter
                            text: "▾"
                            color: AppTheme.textTertiary
                            font.pixelSize: AppTheme.fs(11)
                        }
                        MouseArea {
                            id: sourceFieldArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: sourceCombo.open()
                        }
                    }

                    GlassButton {
                        objectName: "AddUpdateSourceButton"
                        text: qsTr("＋ 自定义源")
                        tone: "ghost"
                        fontSize: 11
                        padH: 13
                        minHeight: 30
                        onClicked: page.openAddSource()
                    }
                }
            }

            GlassCard {
                width: parent.width
                implicitHeight: updateColumn.implicitHeight + 36
                height: implicitHeight
                radius: 22
                interactive: false
                glassSource: page.glassSource

                Column {
                    id: updateColumn
                    x: 22
                    y: 18
                    width: parent.width - 44
                    spacing: 14

                    Item {
                        width: parent.width
                        height: 52

                        Rectangle {
                            width: 42
                            height: 42
                            radius: 13
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            gradient: Gradient {
                                GradientStop { position: 0.0; color: "#BEEFF6" }
                                GradientStop { position: 1.0; color: "#2E9FBF" }
                            }
                            Glyph { anchors.centerIn: parent; kind: "download"; size: 20; color: "#0B2B3A" }
                        }

                        Column {
                            anchors.left: parent.left
                            anchors.leftMargin: 54
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 300
                            spacing: 3
                            Text {
                                text: qsTr("当前版本 v%1").arg(String(App.version))
                                color: AppTheme.textPrimary
                                font.pixelSize: AppTheme.fs(16)
                                font.weight: Font.DemiBold
                                font.family: AppTheme.fontFamily
                            }
                            Text {
                                width: parent.width
                                text: page.statusText
                                color: page.updateState === "error" ? AppTheme.danger
                                      : (page.updateState === "available" ? AppTheme.accent : AppTheme.textSecondary)
                                font.pixelSize: AppTheme.fs(12)
                                font.family: AppTheme.fontFamily
                                wrapMode: Text.WordWrap
                            }
                        }

                        Row {
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 10
                            GlassButton {
                                text: page.updateState === "checking" ? qsTr("检查中…") : qsTr("检查更新")
                                tone: "tinted"
                                fontSize: 13
                                padH: 18
                                minHeight: 36
                                enabled: page.updateState !== "checking" && page.updateState !== "downloading"
                                onClicked: page.checkUpdate()
                            }
                            GlassButton {
                                visible: page.updateState === "available" || page.updateState === "ready"
                                text: qsTr("前往发布页")
                                tone: "ghost"
                                fontSize: 12
                                padH: 14
                                minHeight: 34
                                onClicked: page.openReleasePage()
                            }
                        }
                    }

                    Rectangle { width: parent.width; height: 1; color: AppTheme.divider }

                    // 新版本说明
                    Column {
                        width: parent.width
                        spacing: 8
                        visible: page.updateState === "available" || page.updateState === "downloading"
                                 || page.updateState === "ready"

                        Text {
                            text: page.latestVersion !== ""
                                  ? qsTr("新版本 v%1").arg(page.latestVersion) : qsTr("新版本")
                            color: AppTheme.textPrimary
                            font.pixelSize: AppTheme.fs(14)
                            font.weight: Font.DemiBold
                            font.family: AppTheme.fontFamily
                        }
                        Text {
                            width: parent.width
                            text: page.updateNotes !== "" ? page.updateNotes : qsTr("暂无更新说明")
                            color: AppTheme.textSecondary
                            font.pixelSize: AppTheme.fs(12)
                            font.family: AppTheme.fontFamily
                            wrapMode: Text.WordWrap
                            lineHeight: 1.45
                        }
                    }

                    // 下载进度
                    Column {
                        width: parent.width
                        spacing: 8
                        visible: page.updateState === "downloading"

                        Item {
                            width: parent.width
                            height: 10
                            Rectangle {
                                anchors.fill: parent
                                radius: 5
                                color: AppTheme.glass ? "#1AFFFFFF" : AppTheme.divider
                            }
                            Rectangle {
                                width: parent.width * page.updateProgress / 100
                                height: parent.height
                                radius: 5
                                gradient: Gradient {
                                    orientation: Gradient.Horizontal
                                    GradientStop { position: 0.0; color: "#2E9FBF" }
                                    GradientStop { position: 1.0; color: "#4FD0E0" }
                                }
                                Behavior on width { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
                            }
                        }
                        Row {
                            width: parent.width
                            Text {
                                text: qsTr("已下载 %1%").arg(Math.round(page.updateProgress))
                                color: AppTheme.textSecondary
                                font.pixelSize: AppTheme.fs(12)
                                font.family: AppTheme.fontFamily
                            }
                            Item { width: parent.width - 200; height: 1 }
                            GlassButton {
                                text: qsTr("取消下载")
                                tone: "ghost"
                                fontSize: 12
                                padH: 14
                                minHeight: 32
                                onClicked: page.cancelDownload()
                            }
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: 10
                        visible: page.updateState === "available" || page.updateState === "ready"
                        GlassButton {
                            visible: page.updateState === "available"
                            text: qsTr("下载更新")
                            tone: "light"
                            fontSize: 13
                            padH: 20
                            minHeight: 38
                            onClicked: page.downloadUpdate()
                        }
                        GlassButton {
                            visible: page.updateState === "ready"
                            text: qsTr("安装并重启")
                            tone: "light"
                            fontSize: 13
                            padH: 20
                            minHeight: 38
                            onClicked: page.installUpdate()
                        }
                    }

                    Text {
                        visible: page.updateState === "error" && page.updateError !== ""
                        width: parent.width
                        text: page.updateError
                        color: AppTheme.danger
                        font.pixelSize: AppTheme.fs(12)
                        font.family: AppTheme.fontFamily
                        wrapMode: Text.WordWrap
                    }

                    Rectangle { width: parent.width; height: 1; color: AppTheme.divider }

                    Row {
                        width: parent.width
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("启动时自动检查更新")
                            color: AppTheme.textPrimary
                            font.pixelSize: AppTheme.fs(13)
                            font.family: AppTheme.fontFamily
                        }
                        Item { width: parent.width - 220; height: 1 }
                        GlassSwitch {
                            anchors.verticalCenter: parent.verticalCenter
                            checked: page.autoUpdateEnabled
                            onClicked: page.setAutoUpdate(!page.autoUpdateEnabled)
                        }
                    }
                }
            }

            // ---------- v0.16 下载源详情 / 自定义源管理 ----------
            GlassCard {
                objectName: "UpdateSourceCard"
                width: parent.width
                implicitHeight: sourceColumn.implicitHeight + 36
                height: implicitHeight
                radius: 22
                interactive: false
                glassSource: page.glassSource

                Column {
                    id: sourceColumn
                    x: 22
                    y: 18
                    width: parent.width - 44
                    spacing: 12

                    Row {
                        width: parent.width
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("下载源")
                            color: AppTheme.textPrimary
                            font.pixelSize: AppTheme.fs(15)
                            font.weight: Font.DemiBold
                            font.family: AppTheme.fontFamily
                        }
                        Item { width: parent.width - 210; height: 1 }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("当前：%1").arg(page.currentSourceName)
                            color: AppTheme.accent
                            font.pixelSize: AppTheme.fs(11)
                            font.family: AppTheme.fontFamily
                        }
                    }

                    Text {
                        width: parent.width
                        text: qsTr("检查更新时从所选源读取 Release。GitHub 访问慢或失败时，可切到 GitLink / Gitee，或添加自己的镜像地址。")
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(12)
                        font.family: AppTheme.fontFamily
                        wrapMode: Text.WordWrap
                        lineHeight: 1.4
                    }

                    Row {
                        width: parent.width
                        spacing: 10
                        Text {
                            width: 64
                            text: qsTr("源地址")
                            color: AppTheme.textTertiary
                            font.pixelSize: AppTheme.fs(11)
                            font.family: AppTheme.fontFamily
                        }
                        Text {
                            width: parent.width - 74
                            text: page.currentSourceUrl !== "" ? page.currentSourceUrl
                                                              : qsTr("内置源（详情见对应发布页）")
                            color: AppTheme.textSecondary
                            font.pixelSize: AppTheme.fs(11)
                            font.family: C.monoFont
                            elide: Text.ElideMiddle
                        }
                    }

                    Text {
                        width: parent.width
                        visible: page.sourceErrorText !== ""
                        text: qsTr("下载源错误：%1").arg(page.sourceErrorText)
                        color: AppTheme.danger
                        font.pixelSize: AppTheme.fs(11)
                        font.family: AppTheme.fontFamily
                        wrapMode: Text.WordWrap
                    }

                    // 自定义源列表
                    Column {
                        width: parent.width
                        spacing: 6
                        visible: page.customSourceList.length > 0

                        Text {
                            text: qsTr("自定义源")
                            color: AppTheme.textTertiary
                            font.pixelSize: AppTheme.fs(11)
                            font.family: AppTheme.fontFamily
                            font.letterSpacing: 1
                        }

                        Repeater {
                            model: page.customSourceList
                            delegate: Item {
                                width: sourceColumn.width
                                height: 34
                                readonly property string itemId: String(modelData.id)
                                readonly property string itemUrl: page.sourceUrlOf(modelData.id)

                                Rectangle {
                                    anchors.fill: parent
                                    radius: 10
                                    color: AppTheme.cardBgAlt
                                    border.width: 1
                                    border.color: String(modelData.id) === page.currentSourceId
                                                  ? AppTheme.accent : AppTheme.cardBorder
                                }

                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 12
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 130
                                    text: String(modelData.name)
                                    color: AppTheme.textPrimary
                                    font.pixelSize: AppTheme.fs(11)
                                    font.family: AppTheme.fontFamily
                                    elide: Text.ElideRight
                                }
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 150
                                    anchors.right: removeSourceButton.left
                                    anchors.rightMargin: 8
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: itemUrl
                                    color: AppTheme.textTertiary
                                    font.pixelSize: AppTheme.fs(10)
                                    font.family: C.monoFont
                                    elide: Text.ElideMiddle
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    anchors.rightMargin: 40
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: page.chooseSource(itemId)
                                }

                                Item {
                                    id: removeSourceButton
                                    objectName: "RemoveUpdateSourceButton"
                                    width: 30
                                    height: 30
                                    anchors.right: parent.right
                                    anchors.rightMargin: 2
                                    anchors.verticalCenter: parent.verticalCenter
                                    Rectangle {
                                        anchors.fill: parent
                                        radius: 15
                                        color: removeSourceArea.containsMouse ? AppTheme.cardBg : "transparent"
                                    }
                                    Glyph {
                                        anchors.centerIn: parent
                                        kind: "close"
                                        size: 11
                                        color: removeSourceArea.containsMouse ? AppTheme.danger : AppTheme.textTertiary
                                    }
                                    MouseArea {
                                        id: removeSourceArea
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: page.removeCustomSource(itemId)
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // 最近更新日志
            GlassCard {
                width: parent.width
                implicitHeight: changelogColumn.implicitHeight + 36
                height: implicitHeight
                radius: 22
                interactive: false
                glassSource: page.glassSource

                Column {
                    id: changelogColumn
                    x: 22
                    y: 18
                    width: parent.width - 44
                    spacing: 10

                    Row {
                        width: parent.width
                        Text {
                            text: qsTr("最近更新日志")
                            color: AppTheme.textPrimary
                            font.pixelSize: AppTheme.fs(15)
                            font.weight: Font.DemiBold
                            font.family: AppTheme.fontFamily
                        }
                        Item { width: parent.width - 200; height: 1 }
                        Text {
                            text: qsTr("共 %1 个版本").arg((typeof App !== "undefined" && App.changelog !== undefined)
                                                          ? App.changelog.length : 0)
                            color: AppTheme.textTertiary
                            font.pixelSize: AppTheme.fs(11)
                            font.family: AppTheme.fontFamily
                        }
                    }

                    Repeater {
                        model: (typeof App !== "undefined" && App.changelog !== undefined) ? App.changelog : []
                        delegate: Item {
                            width: parent.width
                            height: 42
                            visible: index < 4
                            Row {
                                anchors.fill: parent
                                spacing: 10
                                Rectangle {
                                    width: 42
                                    height: 22
                                    radius: 11
                                    anchors.verticalCenter: parent.verticalCenter
                                    color: index === 0 ? AppTheme.accentSoft : AppTheme.cardBgAlt
                                    Text {
                                        anchors.centerIn: parent
                                        text: "v" + String(modelData.version)
                                        color: index === 0 ? AppTheme.accent : AppTheme.textSecondary
                                        font.pixelSize: AppTheme.fs(11)
                                        font.family: C.monoFont
                                    }
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width - 180
                                    text: (modelData.items !== undefined && modelData.items.length > 0)
                                          ? String(modelData.items[0]) : qsTr("更新内容")
                                    color: AppTheme.textSecondary
                                    font.pixelSize: AppTheme.fs(11)
                                    font.family: AppTheme.fontFamily
                                    elide: Text.ElideRight
                                }
                                Item { width: parent.width - 470; height: 1 }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: (modelData.date !== undefined) ? String(modelData.date) : ""
                                    color: AppTheme.textTertiary
                                    font.pixelSize: AppTheme.fs(10)
                                    font.family: AppTheme.fontFamily
                                }
                            }
                        }
                    }
                }
            }

            Text {
                width: parent.width
                text: qsTr("更新会从所选下载源获取安装包（默认 GitHub），下载完成后可一键安装并重启。")
                color: AppTheme.textTertiary
                font.pixelSize: AppTheme.fs(11)
                font.family: AppTheme.fontFamily
                wrapMode: Text.WordWrap
            }
        }
    }

    Rectangle {
        visible: flick.contentHeight > flick.height + 4
        width: 4
        radius: 2
        color: AppTheme.glass ? "#26FFFFFF" : AppTheme.divider
        x: flick.width - 14
        height: Math.max(48, flick.height * flick.height / Math.max(1, flick.contentHeight))
        y: 18 + Math.max(0, Math.min(1, flick.contentY / Math.max(1, flick.contentHeight - flick.height)))
           * Math.max(1, flick.height - 36 - height)
    }

    // v0.16 下载源下拉（复用 ScrollablePopup）：自动翻转 / 滚轮隔离 / 右侧滚动条
    ScrollablePopup {
        id: sourceCombo
        objectName: "UpdateSourcePopup"
        anchors.fill: parent
        model: page.sourceItems
        valueKey: "id"
        labelKey: "name"
        currentValue: page.currentSourceId
        anchorItem: sourceField
        outerFlick: flick
        rowHeight: 32
        maxPopupHeight: 200
        minPopupWidth: 180
        badgeText: qsTr("自定义")
        badgeWhen: function (item) { return item !== null && item !== undefined && item.custom === true }
        onSelected: (value) => page.chooseSource(value)
    }

    // v0.16 添加自定义下载源弹窗
    Item {
        id: addSourceLayer
        objectName: "AddUpdateSourceDialog"
        anchors.fill: parent
        z: 90
        visible: page.addSourceOpen

        Rectangle { anchors.fill: parent; color: "#B3051620" }

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onClicked: page.closeAddSource()
        }

        Rectangle {
            anchors.centerIn: parent
            width: Math.min(460, page.width * 0.6)
            height: addSourceColumn.implicitHeight + 44
            radius: 22
            color: AppTheme.glass ? "#F2082430" : AppTheme.cardBg
            border.width: 1
            border.color: AppTheme.cardBorderStrong

            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: {} }

            Column {
                id: addSourceColumn
                x: 24
                y: 22
                width: parent.width - 48
                spacing: 12

                Row {
                    width: parent.width
                    spacing: 9
                    Glyph { anchors.verticalCenter: parent.verticalCenter; kind: "download"; size: 17
                            color: AppTheme.accent }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: qsTr("添加自定义更新源")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(16)
                        font.weight: Font.DemiBold
                        font.family: AppTheme.fontFamily
                    }
                }

                Text {
                    width: parent.width
                    text: qsTr("地址需要是返回 Release JSON 的 http/https API（与 GitHub Releases API 结构一致即可）。")
                    color: AppTheme.textSecondary
                    font.pixelSize: AppTheme.fs(11)
                    font.family: AppTheme.fontFamily
                    wrapMode: Text.WordWrap
                }

                Item {
                    width: parent.width
                    height: 34
                    Text {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: 56
                        text: qsTr("名称")
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(12)
                        font.family: AppTheme.fontFamily
                    }
                    TextInput {
                        id: addSourceNameInput
                        anchors.left: parent.left
                        anchors.leftMargin: 56
                        anchors.right: parent.right
                        height: 34
                        verticalAlignment: TextInput.AlignVCenter
                        color: AppTheme.textPrimary
                        selectionColor: AppTheme.accentSoft
                        selectedTextColor: "#FFFFFF"
                        font.pixelSize: AppTheme.fs(12)
                        font.family: AppTheme.fontFamily
                        text: page.addSourceName
                        onTextChanged: page.addSourceName = text
                        Rectangle {
                            anchors.fill: parent
                            z: -1
                            radius: 9
                            color: AppTheme.cardBgAlt
                            border.width: 1
                            border.color: addSourceNameInput.activeFocus ? AppTheme.accent : AppTheme.cardBorder
                        }
                    }
                }

                Item {
                    width: parent.width
                    height: 34
                    Text {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: 56
                        text: qsTr("地址")
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(12)
                        font.family: AppTheme.fontFamily
                    }
                    TextInput {
                        id: addSourceUrlInput
                        anchors.left: parent.left
                        anchors.leftMargin: 56
                        anchors.right: parent.right
                        height: 34
                        verticalAlignment: TextInput.AlignVCenter
                        color: AppTheme.textPrimary
                        selectionColor: AppTheme.accentSoft
                        selectedTextColor: "#FFFFFF"
                        font.pixelSize: AppTheme.fs(12)
                        font.family: C.monoFont
                        text: page.addSourceUrl
                        onTextChanged: page.addSourceUrl = text
                        onAccepted: page.submitAddSource()
                        Rectangle {
                            anchors.fill: parent
                            z: -1
                            radius: 9
                            color: AppTheme.cardBgAlt
                            border.width: 1
                            border.color: addSourceUrlInput.activeFocus ? AppTheme.accent : AppTheme.cardBorder
                        }
                    }
                }

                Text {
                    width: parent.width
                    visible: page.addSourceError !== ""
                    text: page.addSourceError
                    color: AppTheme.danger
                    font.pixelSize: AppTheme.fs(11)
                    font.family: AppTheme.fontFamily
                    wrapMode: Text.WordWrap
                }

                Row {
                    width: parent.width
                    spacing: 10
                    Item { width: parent.width - 200; height: 1 }
                    GlassButton {
                        text: qsTr("取消")
                        tone: "ghost"
                        fontSize: 12
                        padH: 18
                        minHeight: 34
                        onClicked: page.closeAddSource()
                    }
                    GlassButton {
                        objectName: "ConfirmAddUpdateSource"
                        text: qsTr("添加")
                        tone: "light"
                        fontSize: 12
                        padH: 22
                        minHeight: 34
                        onClicked: page.submitAddSource()
                    }
                }
            }
        }
    }
}
