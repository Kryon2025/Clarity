import QtQuick
import QtQuick.Controls
import "../theme"
import "../components"
import "../components/Constants.js" as C

// 设置页（v0.4）：权限与防退出 / 语言 / 默认专注时长 / 开机自启 / 关于
// 主题已移到独立的主题页（顶部菜单「主题」或全局搜索进入）
Item {
    id: page

    property Item glassSource: null

    signal onboardingRequested()
    signal aiPageRequested()

    // ---------- 还清（睡眠模式）本地状态 ----------
    property bool localSleepReminders: true
    property var localSleepTimes: ["23:30", "00:30"]
    property string newSleepTime: "23:30"
    property int clockClickCount: 0

    // ---------- v0.15 网址屏蔽 ----------
    property string siteInput: ""
    property bool siteBlockLocal: false
    property var localBlockedSites: []
    property var demoBlockedSites: null
    readonly property bool siteBlockEnabledValue: (typeof App !== "undefined" && App.siteBlockEnabled !== undefined)
                                                    ? App.siteBlockEnabled === true : page.siteBlockLocal
    readonly property var blockedSitesList: page.demoBlockedSites !== null ? page.demoBlockedSites
                                            : ((typeof App !== "undefined" && App.blockedSites !== undefined
                                                && App.blockedSites !== null) ? App.blockedSites : page.localBlockedSites)
    function toggleSiteBlock() {
        if (typeof App !== "undefined" && typeof App.setSiteBlockEnabled === "function")
            App.setSiteBlockEnabled(!page.siteBlockEnabledValue)
        else
            page.siteBlockLocal = !page.siteBlockLocal
    }
    function addBlockedSite() {
        var domain = page.siteInput.trim()
        if (domain.length === 0) return
        if (typeof App !== "undefined" && typeof App.addBlockedSite === "function") {
            App.addBlockedSite(domain)
        } else {
            var list = page.localBlockedSites.slice()
            if (list.indexOf(domain) < 0) list.push(domain)
            page.localBlockedSites = list
        }
        page.siteInput = ""
    }
    function removeBlockedSite(domain) {
        if (typeof App !== "undefined" && typeof App.removeBlockedSite === "function") {
            App.removeBlockedSite(String(domain))
        } else {
            var list = page.localBlockedSites.slice()
            var index = list.indexOf(String(domain))
            if (index >= 0) list.splice(index, 1)
            page.localBlockedSites = list
        }
    }

    // ---------- v0.14 数据与备份 ----------
    property bool backupBusyLocal: false
    property bool backupConfirmOpen: false
    property string backupPendingPath: ""
    property string backupStatus: ""
    property string backupStatusKind: "idle"
    readonly property bool backupBusy: backupBusyLocal
                                         || ((typeof App !== "undefined" && App.backupBusy !== undefined)
                                             ? App.backupBusy === true : false)
    readonly property string backupError: (typeof App !== "undefined" && App.lastBackupError !== undefined)
                                          ? String(App.lastBackupError) : ""
    function exportBackup() {
        if (page.backupBusy) return
        page.backupStatusKind = "busy"
        page.backupStatus = qsTr("正在导出备份…")
        page.backupBusyLocal = true
        if (typeof App !== "undefined" && typeof App.exportBackup === "function") {
            var path = App.exportBackup()
            page.backupBusyLocal = false
            if (typeof path === "string" && path !== "") {
                page.backupStatusKind = "ok"
                page.backupStatus = qsTr("备份已导出：%1").arg(path)
            } else if (page.backupError !== "") {
                page.backupStatusKind = "error"
                page.backupStatus = page.backupError
            } else {
                page.backupStatusKind = "idle"
                page.backupStatus = qsTr("已取消导出")
            }
        } else {
            page.backupBusyLocal = false
            page.backupStatusKind = "error"
            page.backupStatus = qsTr("缺少备份接口（App.exportBackup）")
        }
    }
    function importBackup() {
        if (page.backupBusy) return
        page.backupStatusKind = "busy"
        page.backupStatus = qsTr("请选择备份文件…")
        if (typeof App !== "undefined" && typeof App.pickBackupFile === "function") {
            var path = App.pickBackupFile()
            if (typeof path === "string" && path !== "") {
                page.askRestore(path)
            } else {
                page.backupStatusKind = "idle"
                page.backupStatus = qsTr("已取消导入")
            }
        } else {
            page.backupStatusKind = "error"
            page.backupStatus = qsTr("缺少备份选择接口（App.pickBackupFile）")
        }
    }
    function askRestore(path) {
        page.backupPendingPath = String(path)
        page.backupConfirmOpen = true
    }
    function confirmRestore() {
        if (page.backupPendingPath === "") return
        if (typeof App !== "undefined" && typeof App.restoreBackupFile === "function") {
            page.backupBusyLocal = true
            page.backupStatusKind = "busy"
            page.backupStatus = qsTr("正在导入备份，完成后将自动重启…")
            page.backupConfirmOpen = false
            App.restoreBackupFile(page.backupPendingPath)
            page.backupBusyLocal = false
        } else {
            page.backupConfirmOpen = false
            page.backupStatusKind = "error"
            page.backupStatus = qsTr("缺少备份恢复接口（App.restoreBackupFile）")
        }
    }

    // ---------- v0.12 外观：字号 / 字体 / 导航展开方式 ----------
    readonly property var fontFamilyList: {
        var out = [{ value: "", label: qsTr("默认") }]
        if (typeof App !== "undefined" && App.uiFontFamilies !== undefined && App.uiFontFamilies !== null
                && App.uiFontFamilies.length > 0) {
            for (var i = 0; i < App.uiFontFamilies.length; i++) {
                var family = String(App.uiFontFamilies[i])
                if (family !== "" && family.indexOf("@") !== 0)
                    out.push({ value: family, label: family })
            }
            return out
        }
        out.push({ value: "Microsoft YaHei UI", label: qsTr("微软雅黑") })
        out.push({ value: "Segoe UI", label: "Segoe UI" })
        out.push({ value: "SimSun", label: qsTr("宋体") })
        return out
    }
    readonly property string currentFontValue: (typeof App !== "undefined" && App.uiFontFamily !== undefined)
                                                ? String(App.uiFontFamily) : ""
    readonly property string currentFontLabel: {
        var list = page.fontFamilyList
        for (var i = 0; i < list.length; i++)
            if (String(list[i].value) === page.currentFontValue) return String(list[i].label)
        if (page.currentFontValue !== "") return page.currentFontValue
        return qsTr("默认")
    }
    readonly property real currentFontScale: (typeof App !== "undefined" && App.uiFontScale !== undefined)
                                              ? Number(App.uiFontScale) : AppTheme.fontScale
    readonly property string currentNavMode: (typeof App !== "undefined" && App.navMode !== undefined)
                                              ? String(App.navMode)
                                              : (AppTheme.navMode !== undefined ? AppTheme.navMode : "auto")
    function setFontScale(value) {
        if (typeof App !== "undefined" && typeof App.setUIFontScale === "function")
            App.setUIFontScale(Number(value))
        else
            AppTheme.fontScale = Number(value)
    }
    function setFontFamily(value) {
        if (typeof App !== "undefined" && typeof App.setUIFontFamily === "function")
            App.setUIFontFamily(String(value))
        else
            AppTheme.fontFamily = String(value) !== ""
                                  ? String(value)
                                  : ((typeof App !== "undefined" && App.defaultFontFamily !== undefined)
                                     ? String(App.defaultFontFamily) : C.numFont)
    }
    function setNavMode(value) {
        if (typeof App !== "undefined" && typeof App.setNavMode === "function")
            App.setNavMode(String(value))
        else
            AppTheme.navMode = String(value)
    }

    // ---------- v0.9 AI 助手设置 ----------
    property bool aiLocalEnabled: false
    property bool aiProviderMenuOpen: false
    property int aiProviderIndex: 0
    property string aiModelDraft: ""
    property string aiBaseDraft: ""
    property string aiKeyDraft: ""
    property string aiTestText: ""
    property string aiTestKind: "idle"
    readonly property var aiProviderList: {
        if (typeof App !== "undefined" && App.aiProviders !== undefined && App.aiProviders !== null
                && App.aiProviders.length > 0)
            return App.aiProviders
        return [
            { id: "groq", label: "Groq", base: "https://api.groq.com/openai/v1",
              models: ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"] },
            { id: "zhipu", label: qsTr("智谱 GLM"), base: "https://open.bigmodel.cn/api/paas/v4",
              models: ["glm-4-flash", "glm-4-plus"] },
            { id: "siliconflow", label: qsTr("硅基流动"), base: "https://api.siliconflow.cn/v1",
              models: ["Qwen/Qwen2.5-7B-Instruct", "deepseek-ai/DeepSeek-V3"] },
            { id: "custom", label: qsTr("自定义"), base: "", models: [] }
        ]
    }
    readonly property var currentAIProvider: {
        var list = page.aiProviderList
        if (page.aiProviderIndex < 0 || page.aiProviderIndex >= list.length) return list[0]
        return list[page.aiProviderIndex]
    }
    readonly property bool aiEnabledValue: (typeof App !== "undefined" && App.aiEnabled !== undefined)
                                           ? App.aiEnabled === true : page.aiLocalEnabled
    readonly property string aiProviderLabel: (page.currentAIProvider.label !== undefined)
                                               ? String(page.currentAIProvider.label) : ""
    readonly property string aiBackendState: (typeof App !== "undefined" && App.aiState !== undefined)
                                             ? String(App.aiState) : ""
    readonly property string aiStatusText: {
        if (page.aiBackendState === "testing") return qsTr("测试中…")
        if (page.aiBackendState === "ok") return qsTr("连接成功")
        if (page.aiBackendState === "error")
            return (typeof App !== "undefined" && App.aiError !== undefined && String(App.aiError) !== "")
                   ? String(App.aiError) : qsTr("连接失败")
        if (page.aiTestText !== "") return page.aiTestText
        if (typeof App !== "undefined" && App.aiConfigured === true) return qsTr("已配置")
        return qsTr("未配置")
    }
    readonly property string aiStatusColor: {
        if (page.aiBackendState === "ok" || page.aiTestKind === "ok") return AppTheme.accent
        if (page.aiBackendState === "error" || page.aiTestKind === "error") return AppTheme.danger
        return AppTheme.textTertiary
    }

    function initAI() {
        if (typeof App !== "undefined" && App.aiProvider !== undefined) {
            var providers = page.aiProviderList
            for (var i = 0; i < providers.length; i++) {
                if (String(providers[i].id) === String(App.aiProvider)) { page.aiProviderIndex = i; break }
            }
        }
        var p = page.currentAIProvider
        page.aiBaseDraft = (typeof App !== "undefined" && App.aiBase !== undefined && String(App.aiBase) !== "")
                           ? String(App.aiBase) : String(p.base || "")
        if (typeof App !== "undefined" && App.aiModel !== undefined && String(App.aiModel) !== "")
            page.aiModelDraft = String(App.aiModel)
        else if (p.models !== undefined && p.models.length > 0)
            page.aiModelDraft = String(p.models[0])
    }
    function selectAIProvider(index) {
        page.aiProviderIndex = index
        page.aiProviderMenuOpen = false
        var p = page.aiProviderList[index]
        page.aiBaseDraft = (p.base !== undefined) ? String(p.base) : ""
        page.aiModelDraft = (p.models !== undefined && p.models.length > 0) ? String(p.models[0]) : ""
        if (typeof App !== "undefined" && typeof App.setAIProvider === "function")
            App.setAIProvider(String(p.id))
        if (typeof App !== "undefined" && typeof App.setAIBase === "function")
            App.setAIBase(page.aiBaseDraft)
        if (typeof App !== "undefined" && typeof App.setAIModel === "function")
            App.setAIModel(page.aiModelDraft)
    }
    function saveAIModel() {
        if (typeof App !== "undefined" && typeof App.setAIModel === "function")
            App.setAIModel(page.aiModelDraft)
    }
    function saveAIBase() {
        if (typeof App !== "undefined" && typeof App.setAIBase === "function")
            App.setAIBase(page.aiBaseDraft)
    }
    function saveAIKey() {
        if (typeof App !== "undefined" && typeof App.setAIKey === "function" && page.aiKeyDraft !== "")
            App.setAIKey(page.aiKeyDraft)
    }
    function toggleAI() {
        if (typeof App !== "undefined" && typeof App.setAIEnabled === "function") {
            App.setAIEnabled(!page.aiEnabledValue)
        } else {
            page.aiLocalEnabled = !page.aiLocalEnabled
        }
    }
    function testAIConnection() {
        if (typeof App !== "undefined" && typeof App.testAIConnection === "function") {
            page.aiTestKind = "testing"
            page.aiTestText = ""
            App.testAIConnection()
        } else {
            page.aiTestKind = "error"
            page.aiTestText = qsTr("缺少测试接口（App.testAIConnection）")
        }
    }
    Component.onCompleted: initAI()

    readonly property bool hasSleepBackend: (typeof App !== "undefined" && App.sleepScheduleItems !== undefined)
    readonly property var sleepItems: (typeof App !== "undefined" && App.sleepScheduleItems !== undefined)
                                      ? App.sleepScheduleItems : []
    readonly property var sleepTimes: hasSleepBackend ? sleepItems : page.localSleepTimes

    function addSleepTime(timeText) {
        var text = String(timeText).trim()
        if (text.length < 4) return
        if (typeof App !== "undefined" && typeof App.addSleepSchedule === "function") {
            App.addSleepSchedule(text)
        } else {
            var list = page.localSleepTimes.slice()
            if (list.indexOf(text) < 0) list.push(text)
            page.localSleepTimes = list
        }
    }
    function removeSleepTime(item) {
        if (typeof App !== "undefined" && typeof App.removeSleepSchedule === "function") {
            var key = (item !== null && item.id !== undefined) ? String(item.id)
                                                               : String(item)
            App.removeSleepSchedule(key)
        } else {
            var text = String(item)
            var list = page.localSleepTimes.slice()
            var idx = list.indexOf(text)
            if (idx >= 0) list.splice(idx, 1)
            page.localSleepTimes = list
        }
    }
    function toggleSleepReminders() {
        if (typeof App !== "undefined" && typeof App.setSleepReminders === "function") {
            App.setSleepReminders(!App.sleepRemindersEnabled)
        } else {
            page.localSleepReminders = !page.localSleepReminders
        }
    }
    function clickSleepClock() {
        if (typeof App !== "undefined" && typeof App.clickClockForUnlock === "function") {
            App.clickClockForUnlock()
            page.clockClickCount = (page.clockClickCount % 10) + 1
        } else {
            page.clockClickCount = (page.clockClickCount + 1) % 11
        }
        clockClickReset.restart()
    }
    Timer {
        id: clockClickReset
        interval: 5000
        repeat: false
        onTriggered: page.clockClickCount = 0
    }

    readonly property var defaultMinutesValue: {
        var value = App.defaultMinutes
        return (typeof value === "number" && isFinite(value)) ? value : 45
    }

    property int draftDefaultMinutes: defaultMinutesValue

    Flickable {
        id: flick
        objectName: "SettingsFlick"
        anchors.fill: parent
        contentWidth: width
        contentHeight: pageColumn.height + 60
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        // 细滚动条：可拖动，空闲淡出，内容不足一屏时隐藏
        ScrollBar.vertical: ScrollBar {
            id: settingsScroll
            policy: ScrollBar.AsNeeded
            interactive: true
            width: 8
            anchors.right: parent.right
            anchors.rightMargin: 6
            contentItem: Rectangle {
                implicitWidth: 6
                radius: 3
                color: settingsScroll.pressed
                       ? AppTheme.accent
                       : (settingsScroll.hovered ? AppTheme.textSecondary : AppTheme.textTertiary)
                opacity: settingsScroll.active || settingsScroll.pressed ? 0.85 : 0.35
                Behavior on opacity { NumberAnimation { duration: 140 } }
            }
            background: Item {}
        }

        Column {
            id: pageColumn
            width: Math.max(320, Math.min(flick.width - 96, 780))
            x: Math.max(24, (flick.width - width) / 2)
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
                        text: qsTr("设置")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(30)
                        font.weight: Font.Bold
                        font.family: AppTheme.fontFamily
                        font.letterSpacing: 1
                    }
                    Text {
                        text: qsTr("%1（%2）v%3").arg(App.appName).arg(App.appAlias).arg(App.version)
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(13)
                        font.family: AppTheme.fontFamily
                    }
                }
            }

            // ---------- 权限与防退出 ----------
            GlassCard {
                width: parent.width
                implicitHeight: permissionColumn.implicitHeight + 16
                height: implicitHeight
                radius: 20
                interactive: false
                glassSource: page.glassSource

                Column {
                    id: permissionColumn
                    width: parent.width
                    anchors.top: parent.top
                    anchors.topMargin: 8

                    // 防退出加固
                    Item {
                        width: parent.width
                        height: 88

                        Column {
                            anchors.left: parent.left
                            anchors.leftMargin: 16
                            anchors.right: hardeningSwitch.left
                            anchors.rightMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 3

                            Text {
                                text: qsTr("防退出加固")
                                color: AppTheme.textPrimary
                                font.pixelSize: AppTheme.fs(14)
                                font.weight: Font.DemiBold
                                font.family: AppTheme.fontFamily
                            }
                            Text {
                                width: parent.width
                                text: qsTr("锁定期间隐藏任务栏，并屏蔽 Win、Alt+Tab 等系统快捷键")
                                color: AppTheme.textTertiary
                                font.pixelSize: AppTheme.fs(11)
                                font.family: AppTheme.fontFamily
                                wrapMode: Text.WordWrap
                            }
                        }

                        GlassSwitch {
                            id: hardeningSwitch
                            anchors.right: parent.right
                            anchors.rightMargin: 16
                            anchors.verticalCenter: parent.verticalCenter
                            checked: App.hardeningEnabled === true
                            onClicked: {
                                if (typeof App.setHardeningEnabled === "function")
                                    App.setHardeningEnabled(!(App.hardeningEnabled === true))
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width - 28
                        x: 14
                        height: 1
                        color: AppTheme.divider
                    }

                    // 以管理员身份运行
                    Item {
                        width: parent.width
                        height: 88

                        Column {
                            anchors.left: parent.left
                            anchors.leftMargin: 16
                            anchors.right: adminSwitch.left
                            anchors.rightMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 3

                            Row {
                                spacing: 8

                                Text {
                                    text: qsTr("以管理员身份运行")
                                    color: AppTheme.textPrimary
                                    font.pixelSize: AppTheme.fs(14)
                                    font.weight: Font.DemiBold
                                    font.family: AppTheme.fontFamily
                                }

                                Text {
                                    visible: App.isAdmin === true
                                    text: qsTr("当前已提权")
                                    color: "#6FE3B0"
                                    font.pixelSize: AppTheme.fs(11)
                                    font.family: AppTheme.fontFamily
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }

                            Text {
                                width: parent.width
                                text: qsTr("开启后会弹一次 UAC 并以管理员身份重启")
                                color: AppTheme.textTertiary
                                font.pixelSize: AppTheme.fs(11)
                                font.family: AppTheme.fontFamily
                                wrapMode: Text.WordWrap
                            }
                        }

                        GlassSwitch {
                            id: adminSwitch
                            anchors.right: parent.right
                            anchors.rightMargin: 16
                            anchors.verticalCenter: parent.verticalCenter
                            checked: App.adminMode === true
                            onClicked: {
                                if (typeof App.setAdminMode === "function")
                                    App.setAdminMode(!(App.adminMode === true))
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width - 28
                        x: 14
                        height: 1
                        color: AppTheme.divider
                    }

                    // 最高权限开机自启
                    Item {
                        width: parent.width
                        height: 92

                        Column {
                            anchors.left: parent.left
                            anchors.leftMargin: 16
                            anchors.right: elevatedSwitch.left
                            anchors.rightMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 3

                            Text {
                                text: qsTr("最高权限开机自启")
                                color: AppTheme.textPrimary
                                font.pixelSize: AppTheme.fs(14)
                                font.weight: Font.DemiBold
                                font.family: AppTheme.fontFamily
                            }
                            Text {
                                width: parent.width
                                text: qsTr("用计划任务在登录时以最高权限启动，不再弹 UAC；需要管理员")
                                color: AppTheme.textTertiary
                                font.pixelSize: AppTheme.fs(11)
                                font.family: AppTheme.fontFamily
                                wrapMode: Text.WordWrap
                            }
                        }

                        GlassSwitch {
                            id: elevatedSwitch
                            anchors.right: parent.right
                            anchors.rightMargin: 16
                            anchors.verticalCenter: parent.verticalCenter
                            checked: App.elevatedAutostart === true
                            onClicked: {
                                if (typeof App.setElevatedAutostart === "function")
                                    App.setElevatedAutostart(!(App.elevatedAutostart === true))
                            }
                        }
                    }
                }
            }

            // ---------- 语言 ----------
            GlassCard {
                width: parent.width
                height: 152
                radius: 20
                interactive: false
                glassSource: page.glassSource

                Item {
                    anchors.fill: parent
                    anchors.margins: 20

                    Text {
                        id: languageLabel
                        anchors.left: parent.left
                        anchors.top: parent.top
                        text: qsTr("语言")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(15)
                        font.weight: Font.DemiBold
                        font.family: AppTheme.fontFamily
                    }

                    Row {
                        anchors.left: parent.left
                        anchors.top: languageLabel.bottom
                        anchors.topMargin: 10
                        spacing: 10

                        Repeater {
                            model: [
                                { code: "auto", label: qsTr("跟随系统") },
                                { code: "zh_CN", label: qsTr("简体中文") },
                                { code: "en_US", label: "English" },
                                { code: "ja_JP", label: "日本語" },
                                { code: "fr_FR", label: "Français" }
                            ]
                            delegate: GlassButton {
                                text: modelData.label
                                tone: App.language === modelData.code ? "light" : "ghost"
                                fontSize: 13
                                padH: 18
                                minHeight: 36
                                selected: App.language === modelData.code
                                onClicked: {
                                    if (typeof App.setLanguage === "function")
                                        App.setLanguage(modelData.code)
                                }
                            }
                        }
                    }

                    Text {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        text: qsTr("切换后界面会立即更新；托盘菜单在下次启动时生效。")
                        color: AppTheme.textTertiary
                        font.pixelSize: AppTheme.fs(11)
                        font.family: AppTheme.fontFamily
                        wrapMode: Text.WordWrap
                    }
                }
            }

            // ---------- v0.12 外观 ----------
            GlassCard {
                width: parent.width
                implicitHeight: appearanceColumn.implicitHeight + 36
                height: implicitHeight
                radius: 20
                interactive: false
                glassSource: page.glassSource

                Column {
                    id: appearanceColumn
                    x: 20
                    y: 18
                    width: parent.width - 40
                    spacing: 12

                    Text {
                        text: qsTr("外观")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(15)
                        font.weight: Font.DemiBold
                        font.family: AppTheme.fontFamily
                    }

                    Row {
                        width: parent.width
                        spacing: 8
                        Text {
                            anchors.top: parent.top
                            anchors.topMargin: 4
                            width: 88
                            text: qsTr("字号")
                            color: AppTheme.textSecondary
                            font.pixelSize: AppTheme.fs(12)
                            font.family: AppTheme.fontFamily
                        }
                        Item {
                            width: parent.width - 88 - 54 - 16
                            height: 48

                            GlassSlider {
                                id: fontScaleSlider
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                height: 26
                                from: 0.8
                                to: 1.4
                                step: 0.05
                                value: page.currentFontScale
                                onMoved: (value) => page.setFontScale(value)
                            }

                            // 刻度提示：小（80%）/ 标准（100%）/ 大（140%）
                            Item {
                                id: fontScaleTicks
                                anchors.left: parent.left
                                anchors.leftMargin: 1
                                anchors.right: parent.right
                                anchors.rightMargin: 1
                                anchors.top: fontScaleSlider.bottom
                                anchors.topMargin: 1
                                height: 19

                                Repeater {
                                    model: [
                                        { pos: 0.0, label: qsTr("小") },
                                        { pos: 0.3333, label: qsTr("标准") },
                                        { pos: 1.0, label: qsTr("大") }
                                    ]

                                    delegate: Item {
                                        width: 40
                                        height: fontScaleTicks.height
                                        x: Math.max(0, Math.min(fontScaleTicks.width - width,
                                                                modelData.pos * fontScaleTicks.width - width / 2))

                                        Rectangle {
                                            anchors.horizontalCenter: parent.horizontalCenter
                                            anchors.top: parent.top
                                            width: 2
                                            height: 4
                                            radius: 1
                                            color: modelData.pos === 0.3333 ? AppTheme.accent : AppTheme.textTertiary
                                            opacity: modelData.pos === 0.3333 ? 0.95 : 0.55
                                        }

                                        Text {
                                            anchors.bottom: parent.bottom
                                            anchors.horizontalCenter: parent.horizontalCenter
                                            text: modelData.label
                                            color: modelData.pos === 0.3333 ? AppTheme.accent : AppTheme.textTertiary
                                            font.pixelSize: AppTheme.fs(10)
                                            font.family: AppTheme.fontFamily
                                        }
                                    }
                                }
                            }
                        }

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            width: 54
                            horizontalAlignment: Text.AlignRight
                            text: Math.round(page.currentFontScale * 100) + "%"
                            color: AppTheme.accent
                            font.pixelSize: AppTheme.fs(12)
                            font.family: C.monoFont
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: 10
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            width: 72
                            text: qsTr("字体")
                            color: AppTheme.textSecondary
                            font.pixelSize: AppTheme.fs(12)
                            font.family: AppTheme.fontFamily
                        }
                        Item {
                            id: fontField
                            width: Math.max(120, Math.min(240, parent.width - 72 - 10 - 190))
                            height: 32
                            Rectangle {
                                anchors.fill: parent
                                radius: 9
                                color: AppTheme.cardBgAlt
                                border.width: 1
                                border.color: fontFieldArea.containsMouse ? AppTheme.accent : AppTheme.cardBorder
                            }
                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 12
                                anchors.verticalCenter: parent.verticalCenter
                                text: page.currentFontLabel
                                color: AppTheme.textPrimary
                                font.pixelSize: AppTheme.fs(12)
                                font.family: AppTheme.fontFamily
                            }
                            Glyph {
                                anchors.right: parent.right
                                anchors.rightMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                kind: "chevronDown"
                                size: 12
                                color: fontFieldArea.containsMouse ? AppTheme.accent : AppTheme.textTertiary
                            }
                            MouseArea {
                                id: fontFieldArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: fontCombo.open()
                            }
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("实时生效，无需重启")
                            color: AppTheme.textTertiary
                            font.pixelSize: AppTheme.fs(10)
                            font.family: AppTheme.fontFamily
                        }
                    }

                    Row {
                        width: parent.width
                        spacing: 10
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            width: 120
                            text: qsTr("导航展开方式")
                            color: AppTheme.textSecondary
                            font.pixelSize: AppTheme.fs(12)
                            font.family: AppTheme.fontFamily
                        }
                        Repeater {
                            model: [
                                { value: "auto", label: qsTr("自动") },
                                { value: "expanded", label: qsTr("始终展开") },
                                { value: "icons", label: qsTr("仅图标") }
                            ]
                            delegate: GlassButton {
                                text: modelData.label
                                tone: page.currentNavMode === modelData.value ? "light" : "ghost"
                                fontSize: AppTheme.fs(12)
                                padH: 14
                                minHeight: 32
                                selected: page.currentNavMode === modelData.value
                                onClicked: page.setNavMode(modelData.value)
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        text: qsTr("字号影响整个界面，实时生效；字体与导航方式同样即时生效。")
                        color: AppTheme.textTertiary
                        font.pixelSize: AppTheme.fs(10)
                        font.family: AppTheme.fontFamily
                        wrapMode: Text.WordWrap
                    }
                }

            }

            // ---------- 专注 ----------
            GlassCard {
                width: parent.width
                height: 118
                radius: 20
                interactive: false
                glassSource: page.glassSource

                Item {
                    anchors.fill: parent
                    anchors.margins: 20

                    Text {
                        id: minutesLabel
                        anchors.left: parent.left
                        anchors.top: parent.top
                        text: qsTr("默认专注时长")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(15)
                        font.weight: Font.DemiBold
                        font.family: AppTheme.fontFamily
                    }

                    Text {
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.topMargin: 2
                        text: qsTr("%1 分钟").arg(page.draftDefaultMinutes)
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(13)
                        font.family: AppTheme.fontFamily
                    }

                    GlassSlider {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        from: 15
                        to: 240
                        step: 5
                        value: page.draftDefaultMinutes
                        onMoved: (value) => {
                            page.draftDefaultMinutes = value
                            App.setDefaultMinutes(value)
                        }
                    }
                }
            }

            // ---------- 系统 ----------
            GlassCard {
                width: parent.width
                implicitHeight: systemColumn.implicitHeight + 12
                height: implicitHeight
                radius: 20
                interactive: false
                glassSource: page.glassSource

                Column {
                    id: systemColumn
                    width: parent.width
                    anchors.top: parent.top
                    anchors.topMargin: 6

                    GlassRow {
                        width: parent.width
                        title: qsTr("开机自启")
                        interactive: false
                        showChevron: false

                        GlassSwitch {
                            anchors.verticalCenter: parent.verticalCenter
                            checked: App.autostartEnabled
                            onClicked: App.setAutostart(!App.autostartEnabled)
                        }
                    }
                }
            }

            // ---------- v0.15 网址屏蔽 ----------
            GlassCard {
                width: parent.width
                implicitHeight: siteBlockColumn.implicitHeight + 36
                height: implicitHeight
                radius: 20
                interactive: false
                glassSource: page.glassSource

                Column {
                    id: siteBlockColumn
                    x: 20
                    y: 18
                    width: parent.width - 40
                    spacing: 10

                    Row {
                        width: parent.width
                        spacing: 9
                        Glyph {
                            anchors.verticalCenter: parent.verticalCenter
                            kind: "lock"
                            size: 15
                            color: AppTheme.accent
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("网址屏蔽")
                            color: AppTheme.textPrimary
                            font.pixelSize: AppTheme.fs(15)
                            font.weight: Font.DemiBold
                            font.family: AppTheme.fontFamily
                        }
                        Item { width: parent.width - 300; height: 1 }
                        GlassSwitch {
                            anchors.verticalCenter: parent.verticalCenter
                            checked: page.siteBlockEnabledValue
                            onClicked: page.toggleSiteBlock()
                        }
                    }

                    Text {
                        width: parent.width
                        text: qsTr("专注期间通过 hosts 屏蔽这些网站，需要管理员权限；开关与列表在锁定开始时生效。")
                        color: AppTheme.textTertiary
                        font.pixelSize: AppTheme.fs(10)
                        font.family: AppTheme.fontFamily
                        wrapMode: Text.WordWrap
                    }

                    Row {
                        width: parent.width
                        spacing: 8
                        TextInput {
                            id: siteInput
                            width: 300
                            height: 32
                            verticalAlignment: TextInput.AlignVCenter
                            color: AppTheme.textPrimary
                            selectionColor: AppTheme.accentSoft
                            selectedTextColor: "#FFFFFF"
                            font.pixelSize: AppTheme.fs(12)
                            font.family: AppTheme.fontFamily
                            text: page.siteInput
                            onTextChanged: page.siteInput = text
                            onAccepted: page.addBlockedSite()
                            Rectangle {
                                anchors.fill: parent
                                z: -1
                                radius: 9
                                color: AppTheme.cardBgAlt
                                border.width: 1
                                border.color: siteInput.activeFocus ? AppTheme.accent : AppTheme.cardBorder
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.left: parent.left
                                anchors.leftMargin: 10
                                visible: siteInput.text.length === 0
                                text: qsTr("例如 bilibili.com")
                                color: AppTheme.textTertiary
                                font.pixelSize: AppTheme.fs(11)
                                font.family: AppTheme.fontFamily
                            }
                        }
                        GlassButton {
                            text: qsTr("添加")
                            tone: "ghost"
                            fontSize: AppTheme.fs(12)
                            padH: 16
                            minHeight: 32
                            onClicked: page.addBlockedSite()
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("已屏蔽 %1 个域名").arg(page.blockedSitesList.length)
                            color: AppTheme.textTertiary
                            font.pixelSize: AppTheme.fs(10)
                            font.family: AppTheme.fontFamily
                        }
                    }

                    Flow {
                        width: parent.width
                        spacing: 8
                        Repeater {
                            model: page.blockedSitesList
                            delegate: Item {
                                width: blockedLabel.implicitWidth + 34
                                height: 28
                                Rectangle {
                                    anchors.fill: parent
                                    radius: 14
                                    color: AppTheme.cardBgAlt
                                    border.width: 1
                                    border.color: AppTheme.cardBorder
                                }
                                Text {
                                    id: blockedLabel
                                    anchors.left: parent.left
                                    anchors.leftMargin: 11
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: String(modelData)
                                    color: AppTheme.textSecondary
                                    font.pixelSize: AppTheme.fs(10)
                                    font.family: AppTheme.fontFamily
                                }
                                Item {
                                    anchors.right: parent.right
                                    anchors.rightMargin: 6
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 16
                                    height: 16
                                    Glyph {
                                        anchors.centerIn: parent
                                        kind: "close"
                                        size: 8
                                        color: removeSiteArea.containsMouse ? AppTheme.danger : AppTheme.textTertiary
                                    }
                                    MouseArea {
                                        id: removeSiteArea
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: page.removeBlockedSite(modelData)
                                    }
                                }
                            }
                        }
                    }

                    Text {
                        visible: page.blockedSitesList.length === 0
                        text: qsTr("还没有屏蔽网站，添加一个域名即可。")
                        color: AppTheme.textTertiary
                        font.pixelSize: AppTheme.fs(10)
                        font.family: AppTheme.fontFamily
                    }
                }
            }

            // ---------- v0.14 数据与备份 ----------
            GlassCard {
                width: parent.width
                implicitHeight: backupColumn.implicitHeight + 36
                height: implicitHeight
                radius: 20
                interactive: false
                glassSource: page.glassSource

                Column {
                    id: backupColumn
                    x: 20
                    y: 18
                    width: parent.width - 40
                    spacing: 10

                    Row {
                        width: parent.width
                        spacing: 9
                        Glyph {
                            anchors.verticalCenter: parent.verticalCenter
                            kind: "download"
                            size: 15
                            color: AppTheme.accent
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("数据与备份")
                            color: AppTheme.textPrimary
                            font.pixelSize: AppTheme.fs(15)
                            font.weight: Font.DemiBold
                            font.family: AppTheme.fontFamily
                        }
                        Item { width: parent.width - 320; height: 1 }
                        Text {
                            width: 300
                            horizontalAlignment: Text.AlignRight
                            text: page.backupStatus
                            color: page.backupStatusKind === "error" ? AppTheme.danger
                                  : (page.backupStatusKind === "ok" ? AppTheme.accent : AppTheme.textTertiary)
                            font.pixelSize: AppTheme.fs(10)
                            font.family: AppTheme.fontFamily
                            wrapMode: Text.WordWrap
                            maximumLineCount: 2
                            elide: Text.ElideMiddle
                        }
                    }

                    Text {
                        width: parent.width
                        text: qsTr("备份包含：设置、空间、白名单、专注统计、应用使用记录、AI 对话与用量、睡眠与插件数据。导入会覆盖当前数据并自动重启深清。")
                        color: AppTheme.textTertiary
                        font.pixelSize: AppTheme.fs(10)
                        font.family: AppTheme.fontFamily
                        wrapMode: Text.WordWrap
                        lineHeight: 1.35
                    }

                    Row {
                        width: parent.width
                        spacing: 10
                        GlassButton {
                            text: page.backupBusy ? qsTr("处理中…") : qsTr("导出备份")
                            tone: "tinted"
                            fontSize: AppTheme.fs(12)
                            padH: 18
                            minHeight: 34
                            enabled: !page.backupBusy
                            onClicked: page.exportBackup()
                        }
                        GlassButton {
                            text: page.backupBusy ? qsTr("处理中…") : qsTr("导入备份")
                            tone: "ghost"
                            fontSize: AppTheme.fs(12)
                            padH: 18
                            minHeight: 34
                            enabled: !page.backupBusy
                            onClicked: page.importBackup()
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 260
                            text: page.backupError !== "" ? page.backupError : qsTr("导出为 .zip/.json 备份文件；导入前会二次确认。")
                            color: page.backupError !== "" ? AppTheme.danger : AppTheme.textTertiary
                            font.pixelSize: AppTheme.fs(10)
                            font.family: AppTheme.fontFamily
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }

            // ---------- 反馈 ----------
            GlassCard {
                width: parent.width
                height: 132
                radius: 20
                interactive: false
                glassSource: page.glassSource

                Item {
                    anchors.fill: parent
                    anchors.margins: 20

                    Text {
                        id: feedbackLabel
                        anchors.left: parent.left
                        anchors.top: parent.top
                        text: qsTr("反馈")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(15)
                        font.weight: Font.DemiBold
                        font.family: AppTheme.fontFamily
                    }

                    Row {
                        anchors.left: parent.left
                        anchors.top: feedbackLabel.bottom
                        anchors.topMargin: 10
                        spacing: 10

                        GlassButton {
                            text: qsTr("功能请求")
                            fontSize: 13
                            padH: 16
                            minHeight: 36
                            onClicked: App.openFeedback("request")
                        }
                        GlassButton {
                            text: qsTr("Bug 反馈")
                            fontSize: 13
                            padH: 16
                            minHeight: 36
                            onClicked: App.openFeedback("bug")
                        }
                        GlassButton {
                            text: qsTr("参与讨论")
                            fontSize: 13
                            padH: 16
                            minHeight: 36
                            onClicked: App.openFeedback("discuss")
                        }
                    }

                    Text {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        text: qsTr("在 GitHub 仓库 Kryon2025/Clarity 提交功能请求、Bug 反馈或参与讨论。")
                        color: AppTheme.textTertiary
                        font.pixelSize: AppTheme.fs(11)
                        font.family: AppTheme.fontFamily
                        wrapMode: Text.WordWrap
                    }
                }
            }

            // ---------- v0.10 AI 助手入口（配置与对话已迁移到独立 AI 页） ----------
            GlassCard {
                width: parent.width
                height: 64
                radius: 20
                interactive: false
                glassSource: page.glassSource

                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: 20
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 9
                    Glyph {
                        anchors.verticalCenter: parent.verticalCenter
                        kind: "sparkle"
                        size: 15
                        color: AppTheme.accent
                    }
                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2
                        Text {
                            text: qsTr("AI 助手")
                            color: AppTheme.textPrimary
                            font.pixelSize: AppTheme.fs(13)
                            font.family: AppTheme.fontFamily
                        }
                        Text {
                            text: qsTr("服务商、模型与对话，已移到左侧「AI」页")
                            color: AppTheme.textTertiary
                            font.pixelSize: AppTheme.fs(11)
                            font.family: AppTheme.fontFamily
                        }
                    }
                }

                GlassButton {
                    anchors.right: parent.right
                    anchors.rightMargin: 20
                    anchors.verticalCenter: parent.verticalCenter
                    text: qsTr("前往 AI 页")
                    tone: "ghost"
                    fontSize: 12
                    padH: 16
                    minHeight: 32
                    onClicked: page.aiPageRequested()
                }
            }

            // ---------- 睡眠模式（已移至清空间） ----------
            GlassCard {
                width: parent.width
                height: 64
                radius: 20
                interactive: false
                glassSource: page.glassSource

                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: 20
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 9
                    Glyph {
                        anchors.verticalCenter: parent.verticalCenter
                        kind: "moon"
                        size: 15
                        color: AppTheme.textSecondary
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: qsTr("睡眠模式已并入清空间的「还清」档位，可在那里设置作息。")
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(12)
                        font.family: AppTheme.fontFamily
                    }
                }
            }

            // ---------- 新手引导 ----------
            GlassCard {
                width: parent.width
                height: 64
                radius: 20
                interactive: false
                glassSource: page.glassSource

                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: 20
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 9
                    Glyph {
                        anchors.verticalCenter: parent.verticalCenter
                        kind: "sparkle"
                        size: 15
                        color: AppTheme.textSecondary
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: qsTr("新手引导")
                        color: AppTheme.textPrimary
                        font.pixelSize: AppTheme.fs(13)
                        font.family: AppTheme.fontFamily
                    }
                }

                GlassButton {
                    anchors.right: parent.right
                    anchors.rightMargin: 20
                    anchors.verticalCenter: parent.verticalCenter
                    text: qsTr("重新查看引导")
                    tone: "ghost"
                    fontSize: 12
                    padH: 16
                    minHeight: 32
                    onClicked: page.onboardingRequested()
                }
            }

            // ---------- 关于 ----------
            Text {
                width: parent.width
                wrapMode: Text.WordWrap
                text: qsTr("%1（%2）v%3 · Windows 专注锁机工具\n数据保存在 %APPDATA%/ShenQing/ · 主题可在左侧导航「主题」中切换").arg(App.appName).arg(App.appAlias).arg(App.version)
                color: AppTheme.textTertiary
                font.pixelSize: AppTheme.fs(12)
                font.family: AppTheme.fontFamily
                lineHeight: 1.4
            }

            Item { width: parent.width; height: 2 }
        }
    }

    // ---------- v0.14 导入备份二次确认 ----------
    Item {
        id: backupConfirmLayer
        objectName: "BackupConfirmLayer"
        anchors.fill: parent
        z: 85
        visible: opacity > 0.01
        opacity: page.backupConfirmOpen ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }

        Rectangle { anchors.fill: parent; color: AppTheme.scrimStrong }
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onClicked: page.backupConfirmOpen = false
        }
        Rectangle {
            width: Math.min(460, page.width - 80)
            height: confirmBackupColumn.height + 44
            anchors.centerIn: parent
            radius: 20
            color: AppTheme.cardBg
            border.width: 1
            border.color: AppTheme.cardBorderStrong
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onClicked: {} }
            Column {
                id: confirmBackupColumn
                x: 22
                y: 20
                width: parent.width - 44
                spacing: 14
                Text {
                    width: parent.width
                    text: qsTr("导入备份并覆盖当前数据？")
                    color: AppTheme.textPrimary
                    font.pixelSize: AppTheme.fs(16)
                    font.weight: Font.Bold
                    font.family: AppTheme.fontFamily
                    wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width
                    text: qsTr("导入会覆盖当前设置、空间、白名单、专注统计、应用使用、AI 对话与用量、睡眠与插件数据，并自动重启深清。")
                    color: AppTheme.textSecondary
                    font.pixelSize: AppTheme.fs(11)
                    font.family: AppTheme.fontFamily
                    wrapMode: Text.WordWrap
                    lineHeight: 1.4
                }
                Text {
                    width: parent.width
                    text: page.backupPendingPath
                    color: AppTheme.textTertiary
                    font.pixelSize: AppTheme.fs(9)
                    font.family: AppTheme.fontFamily
                    elide: Text.ElideMiddle
                }
                Row {
                    width: parent.width
                    spacing: 10
                    Item { width: parent.width - 230; height: 1 }
                    GlassButton {
                        text: qsTr("取消")
                        tone: "ghost"
                        fontSize: AppTheme.fs(12)
                        padH: 18
                        minHeight: 34
                        onClicked: page.backupConfirmOpen = false
                    }
                    Rectangle {
                        width: 118
                        height: 34
                        radius: 17
                        color: confirmBackupArea.containsMouse ? "#F06870" : AppTheme.danger
                        Text {
                            anchors.centerIn: parent
                            text: qsTr("覆盖并重启")
                            color: "#FFFFFF"
                            font.pixelSize: AppTheme.fs(12)
                            font.weight: Font.DemiBold
                            font.family: AppTheme.fontFamily
                        }
                        MouseArea {
                            id: confirmBackupArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.confirmRestore()
                        }
                    }
                }
            }
        }
    }

    // v0.16 字体下拉（可滚动弹出层）
    ScrollablePopup {
        id: fontCombo
        objectName: "FontComboPopup"
        anchors.fill: parent
        model: page.fontFamilyList
        currentValue: page.currentFontValue
        anchorItem: fontField
        outerFlick: flick
        rowHeight: 32
        maxPopupHeight: 300
        minPopupHeight: 120
        previewFontFamily: true
        onSelected: (value) => page.setFontFamily(String(value))
    }

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
}