import QtQuick
import "../theme"
import "../components"
import "../glass"
import "../components/Constants.js" as C

Item {
    id: page
    property Item glassSource: null
    property bool animationsEnabled: true
    // v0.21：AI 设置默认收起，把横向空间让给「聊天记录」左栏
    property bool configOpen: false
    // v0.21：左侧「聊天记录」分栏；窄窗口自动收起，可用顶部「聊天记录」按钮切换
    property bool sidebarOpen: true
    // 打开 AI 设置时让出横向空间（设置是临时面板，关掉后恢复左栏）
    property bool sidebarBeforeConfig: true
    readonly property bool sidebarVisible: page.sidebarOpen && !page.configOpen
    readonly property bool narrowLayout: page.width < 900
    onNarrowLayoutChanged: page.sidebarOpen = !page.narrowLayout
    // v0.21：AI 动作结果系统小字（[{ conversationId, text, kind }]；演示数据见 demoActionNotes）
    property var actionNotes: []
    property var demoActionNotes: null
    property int providerIndex: 0
    property string modelDraft: ""
    property string baseDraft: ""
    property string keyDraft: ""
    property string testText: ""
    property string testKind: "idle"
    property string localModelsError: ""
    property bool localReasoning: false
    property bool localWebSearch: false
    property string query: ""
    property bool copied: false
    property string expandedReasoningKey: ""
    property string currentConversationId: ""
    property var demoConversations: null
    property var demoMessages: null
    property var demoLastUsage: null
    property int demoTodayTokens: -1
    property real demoTodayCost: -1
    property string demoCurrency: ""

    readonly property var providerList: {
        var source = (typeof App !== "undefined" && App.aiProviders !== undefined && App.aiProviders !== null
                      && App.aiProviders.length > 0) ? App.aiProviders : [
            { id: "deepseek", label: "DeepSeek", base: "https://api.deepseek.com/v1",
              models: ["deepseek-flash", "deepseek-v4-pro"], capabilities: ["reasoning"] },
            { id: "mimo", label: qsTr("小米 MiMo"), base: "https://api.xiaomimimo.com/v1",
              models: ["mimo-v2.6-flash", "mimo-v2.6-pro"] },
            { id: "openai", label: "ChatGPT", base: "https://api.openai.com/v1",
              models: ["gpt-4o-mini", "gpt-4o"], capabilities: ["webSearch"] },
            { id: "groq", label: "Groq", base: "https://api.groq.com/openai/v1",
              models: ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"] },
            { id: "glm", label: qsTr("智谱 GLM"), base: "https://open.bigmodel.cn/api/paas/v4",
              models: ["glm-4.7-flash", "glm-4-flash"], capabilities: ["reasoning", "webSearch"] },
            { id: "siliconflow", label: qsTr("硅基流动"), base: "https://api.siliconflow.cn/v1",
              models: ["Qwen/Qwen2.5-7B-Instruct", "deepseek-ai/DeepSeek-V3"] },
            { id: "custom", label: qsTr("自定义"), base: "", models: [] }
        ]
        var hasFree = false
        for (var i = 0; i < source.length; i++) {
            var item = source[i]
            if (String(item.id) === "free" || item.free === true || item.noConfig === true
                    || String(item.label).indexOf(qsTr("免配置")) >= 0) {
                hasFree = true
                break
            }
        }
        if (hasFree) return source
        var out = [{ id: "free", label: qsTr("免费直连（免配置）"), base: "", free: true,
                     models: ["deepseek-chat", "glm-4-flash"], capabilities: ["reasoning"] }]
        for (var j = 0; j < source.length; j++) out.push(source[j])
        return out
    }
    readonly property var currentProvider: {
        var list = page.providerList
        return (page.providerIndex >= 0 && page.providerIndex < list.length) ? list[page.providerIndex] : list[0]
    }
    readonly property string providerLabel: (page.currentProvider.label !== undefined) ? String(page.currentProvider.label) : ""
    readonly property bool freeProvider: page.currentProvider.needs_key === false
                                          || String(page.currentProvider.id) === "free"
                                          || String(page.currentProvider.id) === "pollinations"
                                          || page.currentProvider.free === true
                                          || page.currentProvider.noConfig === true
                                          || page.currentProvider.mode === "free"
                                          || String(page.currentProvider.label).indexOf(qsTr("免配置")) >= 0
    readonly property bool reasoningSupported: (typeof App !== "undefined" && App.aiSupportsReasoning !== undefined)
                                               ? App.aiSupportsReasoning === true
                                               : page.providerFlag("reasoning")
    readonly property bool webSupported: (typeof App !== "undefined" && App.aiSupportsWebSearch !== undefined)
                                         ? App.aiSupportsWebSearch === true
                                         : page.providerFlag("webSearch")
    readonly property bool reasoningEnabled: (typeof App !== "undefined" && App.aiReasoningEnabled !== undefined)
                                             ? App.aiReasoningEnabled === true : page.localReasoning
    readonly property bool webEnabled: (typeof App !== "undefined" && App.aiWebSearchEnabled !== undefined)
                                       ? App.aiWebSearchEnabled === true : page.localWebSearch

    function providerFlag(name) {
        var p = page.currentProvider
        if (!p) return false
        var caps = p.capabilities
        if (caps !== undefined && caps !== null) {
            if (typeof caps === "object" && caps[name] !== undefined) return caps[name] === true
            if (caps.length !== undefined)
                for (var i = 0; i < caps.length; i++)
                    if (String(caps[i]) === name) return true
        }
        if (name === "reasoning") {
            if (p.supports_reasoning !== undefined) return p.supports_reasoning === true
            if (p.supportsReasoning !== undefined) return p.supportsReasoning === true
            return ["pollinations", "free", "deepseek", "glm", "siliconflow"].indexOf(String(p.id)) >= 0
        }
        if (p.supports_web_search !== undefined) return p.supports_web_search === true
        if (p.supportsWebSearch !== undefined) return p.supportsWebSearch === true
        return ["pollinations", "free", "openai", "glm"].indexOf(String(p.id)) >= 0
    }

    readonly property var modelCandidates: {
        if (typeof App !== "undefined" && App.aiModels !== undefined && App.aiModels !== null
                && App.aiModels.length > 0)
            return App.aiModels
        return (page.currentProvider.models !== undefined) ? page.currentProvider.models : []
    }
    readonly property string modelsState: (typeof App !== "undefined" && App.aiModelsState !== undefined)
                                         ? String(App.aiModelsState) : ""
    readonly property string modelsError: page.localModelsError !== "" ? page.localModelsError
                                         : ((typeof App !== "undefined" && App.aiModelsError !== undefined)
                                            ? String(App.aiModelsError) : "")
    readonly property string modelsHint: page.modelsState === "loading" ? qsTr("正在获取模型列表…")
                                         : (page.modelsState === "error" && page.modelsError !== "" ? page.modelsError
                                            : (page.modelCandidates.length > 0
                                               ? qsTr("共 %1 个模型").arg(page.modelCandidates.length)
                                               : qsTr("暂无模型列表，可手动输入")))

    readonly property var conversations: page.demoConversations !== null ? page.demoConversations
                                        : ((typeof App !== "undefined" && App.aiConversations !== undefined)
                                           ? App.aiConversations : [])
    readonly property var messages: page.demoMessages !== null ? page.demoMessages
                                   : ((typeof App !== "undefined" && App.aiMessages !== undefined) ? App.aiMessages : [])
    readonly property int messageCount: page.messages !== null ? page.messages.length : 0
    readonly property var lastUsage: page.demoLastUsage !== null ? page.demoLastUsage
                                     : ((typeof App !== "undefined" && App.aiLastUsage !== undefined) ? App.aiLastUsage : ({}))
    readonly property int todayTokens: page.demoTodayTokens >= 0 ? page.demoTodayTokens
                                       : ((typeof App !== "undefined" && App.aiTodayTokens !== undefined) ? Number(App.aiTodayTokens) : 0)
    readonly property real todayCost: page.demoTodayCost >= 0 ? page.demoTodayCost
                                      : ((typeof App !== "undefined" && App.aiTodayCost !== undefined) ? Number(App.aiTodayCost) : 0)
    readonly property string currency: page.demoCurrency !== "" ? page.demoCurrency
                                       : ((typeof App !== "undefined" && App.aiCurrency !== undefined
                                           && String(App.aiCurrency) !== "") ? String(App.aiCurrency) : "CNY")
    readonly property string costSymbol: page.currency === "CNY" ? "¥" : page.currency + " "
    readonly property bool configured: page.freeProvider
                                       || ((typeof App !== "undefined") && App.aiConfigured === true)
    readonly property string chatState: (typeof App !== "undefined" && App.aiState !== undefined) ? String(App.aiState) : "idle"
    readonly property string chatAnswer: (typeof App !== "undefined" && App.aiAnswer !== undefined) ? String(App.aiAnswer) : ""
    readonly property string chatError: (typeof App !== "undefined" && App.aiError !== undefined) ? String(App.aiError) : ""

    function messageRole(m) { return (m !== null && m.role !== undefined) ? String(m.role) : "assistant" }
    function messageContent(m) { return (m !== null && m.content !== undefined) ? String(m.content) : "" }
    function messageReasoning(m) { return (m !== null && m.reasoning !== undefined) ? String(m.reasoning) : "" }
    function messageKey(i) { return page.currentConversationId + "#" + i }
    function toggleReasoningMessage(i) {
        var key = page.messageKey(i)
        page.expandedReasoningKey = page.expandedReasoningKey === key ? "" : key
    }
    function usageText() {
        var tokens = Number(page.lastUsage.tokens !== undefined ? page.lastUsage.tokens
                        : (page.lastUsage.totalTokens !== undefined ? page.lastUsage.totalTokens
                           : (Number(page.lastUsage.prompt_tokens || 0) + Number(page.lastUsage.completion_tokens || 0))))
        var cost = Number(page.lastUsage.cost !== undefined ? page.lastUsage.cost : 0)
        var currency = (page.lastUsage.currency !== undefined && String(page.lastUsage.currency) !== "")
                       ? String(page.lastUsage.currency) : page.currency
        var symbol = currency === "CNY" ? "¥" : (currency === "USD" ? "$" : currency + " ")
        return (tokens <= 0 && cost <= 0) ? ""
               : qsTr("上次回复 %1 tokens · %2%3（估算）").arg(tokens).arg(symbol).arg(cost.toFixed(4))
    }
    // v0.16：服务商 / 模型下拉改用可复用 ScrollablePopup（自动翻转、滚轮隔离、右侧滚动条）
    readonly property string currentProviderId: (typeof App !== "undefined" && App.aiProvider !== undefined
                                                && String(App.aiProvider) !== "")
                                               ? String(App.aiProvider) : String(page.currentProvider.id)
    function openProviderMenu(anchor) {
        providerCombo.anchorItem = (anchor !== undefined && anchor !== null)
                                   ? anchor : (page.configOpen ? configProviderField : providerButton)
        providerCombo.currentValue = page.currentProviderId
        providerCombo.open()
    }
    function openModelMenu(anchor) {
        modelCombo.anchorItem = (anchor !== undefined && anchor !== null) ? anchor : modelInput
        modelCombo.currentValue = page.modelDraft
        modelCombo.open()
    }
    function selectProviderValue(id) {
        for (var i = 0; i < page.providerList.length; i++) {
            if (String(page.providerList[i].id) === String(id)) {
                page.selectProvider(i)
                return
            }
        }
    }
    function init() {
        if (typeof App !== "undefined" && App.aiProvider !== undefined) {
            for (var i = 0; i < page.providerList.length; i++)
                if (String(page.providerList[i].id) === String(App.aiProvider)) { page.providerIndex = i; break }
        }
        var p = page.currentProvider
        page.baseDraft = (typeof App !== "undefined" && App.aiBase !== undefined && String(App.aiBase) !== "")
                         ? String(App.aiBase) : String(p.base || "")
        page.modelDraft = (typeof App !== "undefined" && App.aiModel !== undefined && String(App.aiModel) !== "")
                          ? String(App.aiModel) : (p.models && p.models.length > 0 ? String(p.models[0]) : "")
    }
    function toggleEnabled() {
        if (typeof App !== "undefined" && typeof App.setAIEnabled === "function")
            App.setAIEnabled(!(typeof App !== "undefined" && App.aiEnabled === true))
    }
    function selectProvider(i) {
        page.providerIndex = i
        var p = page.providerList[i]
        page.baseDraft = (p.base !== undefined) ? String(p.base) : ""
        page.localModelsError = ""
        page.modelDraft = (p.models && p.models.length > 0) ? String(p.models[0]) : ""
        if (typeof App !== "undefined" && typeof App.setAIProvider === "function") App.setAIProvider(String(p.id))
        if (typeof App !== "undefined" && typeof App.setAIBase === "function" && !page.freeProvider) App.setAIBase(page.baseDraft)
        if (typeof App !== "undefined" && typeof App.setAIModel === "function" && page.modelDraft !== "") App.setAIModel(page.modelDraft)
        if (typeof App !== "undefined" && typeof App.fetchAIModels === "function"
                && (page.freeProvider || App.aiConfigured === true)) App.fetchAIModels()
    }
    function selectModel(name) {
        page.modelDraft = String(name)
        if (typeof App !== "undefined" && typeof App.setAIModel === "function") App.setAIModel(page.modelDraft)
    }
    function saveModel() { if (typeof App !== "undefined" && typeof App.setAIModel === "function") App.setAIModel(page.modelDraft) }
    function saveBase() { if (typeof App !== "undefined" && typeof App.setAIBase === "function") App.setAIBase(page.baseDraft) }
    function saveKey() { if (typeof App !== "undefined" && typeof App.setAIKey === "function" && page.keyDraft !== "") App.setAIKey(page.keyDraft) }
    function refreshModels() {
        page.localModelsError = ""
        if (typeof App !== "undefined" && typeof App.fetchAIModels === "function") App.fetchAIModels()
        else page.localModelsError = qsTr("缺少模型获取接口（App.fetchAIModels）")
    }
    function testConnection() {
        page.testKind = "testing"
        page.testText = ""
        if (typeof App !== "undefined" && typeof App.testAIConnection === "function") App.testAIConnection()
        else { page.testKind = "error"; page.testText = qsTr("缺少测试接口（App.testAIConnection）") }
    }
    function toggleReasoning() {
        if (typeof App !== "undefined" && typeof App.setAIReasoningEnabled === "function")
            App.setAIReasoningEnabled(!page.reasoningEnabled)
        else page.localReasoning = !page.localReasoning
    }
    function toggleWebSearch() {
        if (typeof App !== "undefined" && typeof App.setAIWebSearchEnabled === "function")
            App.setAIWebSearchEnabled(!page.webEnabled)
        else page.localWebSearch = !page.localWebSearch
    }
    function newConversation() {
        page.currentConversationId = ""
        if (typeof App !== "undefined" && typeof App.newAIConversation === "function") App.newAIConversation()
    }
    function selectConversation(id) {
        page.currentConversationId = String(id)
        page.expandedReasoningKey = ""
        if (typeof App !== "undefined" && typeof App.selectAIConversation === "function") App.selectAIConversation(String(id))
    }
    function deleteConversation(id) {
        if (page.currentConversationId === String(id)) page.currentConversationId = ""
        if (typeof App !== "undefined" && typeof App.deleteAIConversation === "function") App.deleteAIConversation(String(id))
    }
    function send() {
        var text = String(page.query).trim()
        if (text.length === 0 || !page.configured) return
        if (typeof App !== "undefined" && typeof App.aiAsk === "function") App.aiAsk(text)
        page.query = ""
    }
    function resetUsage() {
        if (typeof App !== "undefined" && typeof App.resetAIUsage === "function") App.resetAIUsage()
    }
    // 左栏开关：从收起状态点开时顺带收起设置面板，保证聊天区宽度
    function toggleSidebar() {
        if (!page.sidebarOpen) {
            page.sidebarOpen = true
            page.configOpen = false
        } else {
            page.sidebarOpen = false
        }
    }
    // 设置面板开关：打开设置时暂时收起左栏，关闭后恢复
    function toggleConfig() {
        if (!page.configOpen) {
            page.sidebarBeforeConfig = page.sidebarOpen
            page.configOpen = true
            page.sidebarOpen = false
        } else {
            page.configOpen = false
            page.sidebarOpen = page.sidebarBeforeConfig
        }
    }

    // ---------- v0.21 AI 动作：结果系统提示 + 待确认卡 ----------
    // 后端契约：App.aiActionPending 为 dict（空闲时 {}），App.aiActionPendingActive 为 bool；
    // App.aiActionResult / App.aiActionLog 提供执行结果（text 由后端生成，QML 直接展示）。
    // 确认 / 取消分别调 App.aiConfirmAction / App.aiCancelAction。
    readonly property var aiActionPending: {
        if (typeof App === "undefined") return null
        var pending = App.aiActionPending
        if (pending === undefined || pending === null || pending === false) return null
        if (typeof pending === "object") {
            if (App.aiActionPendingActive !== undefined && App.aiActionPendingActive !== true)
                return null
            for (var key in pending) return pending   // 非空 dict 才算有 pending
            return null                                 // {} = 空闲
        }
        return pending
    }
    // 后端动作结果日志（最新在末尾；text 已是中文文案）
    readonly property var aiActionLog: (typeof App !== "undefined" && App.aiActionLog !== undefined
                                        && App.aiActionLog !== null && App.aiActionLog.length !== undefined)
                                       ? App.aiActionLog : []

    // 聊天里要显示的动系统小字：没有 conversationId 的条目跟随所有会话
    readonly property var visibleActionNotes: {
        var out = []
        // 1) 后端执行过的动作结果（App.aiActionLog，text 由后端生成）
        var log = page.aiActionLog
        if (log !== undefined && log !== null && log.length !== undefined) {
            for (var i = 0; i < log.length; i++) {
                var entry = log[i]
                if (entry === null || entry === undefined) continue
                var text = (entry.text !== undefined) ? String(entry.text) : ""
                if (text !== "") out.push({ text: text, kind: String(entry.type !== undefined ? entry.type : ""),
                                             ok: entry.ok !== false })
            }
        }
        // 2) 本地记录 / 演示数据（没有后端日志时也能展示）
        var source = page.demoActionNotes !== null ? page.demoActionNotes : page.actionNotes
        if (source !== undefined && source !== null && source.length !== undefined) {
            for (var j = 0; j < source.length; j++) {
                var item = source[j]
                if (item === null || item === undefined) continue
                var key = (item.conversationId !== undefined) ? String(item.conversationId) : ""
                if (key !== "" && key !== page.currentConversationId) continue
                out.push(item)
            }
        }
        return out
    }

    function actionNoteText(item) {
        if (item === null || item === undefined) return ""
        if (item.text !== undefined && String(item.text) !== "") return String(item.text)
        var kind = (item.kind !== undefined) ? String(item.kind) : ""
        if (kind === "space" || kind === "openSpace")
            return qsTr("已为你打开 %1").arg(String(item.target !== undefined ? item.target : item.name))
        if (kind === "setting" || kind === "changeSetting") {
            if (item.value !== undefined)
                return qsTr("已修改设置：%1 %2").arg(String(item.name)).arg(String(item.value))
            return qsTr("已修改设置：%1").arg(String(item.name))
        }
        return qsTr("已完成 AI 动作")
    }

    function postActionNote(item) {
        var entry = (typeof item === "string") ? ({ text: String(item) })
                                               : ({ text: page.actionNoteText(item),
                                                    kind: (item.kind !== undefined ? String(item.kind) : "") })
        entry.conversationId = page.currentConversationId
        var next = page.actionNotes.slice()
        next.push(entry)
        page.actionNotes = next
    }

    // 待确认动作的标题 / 说明（后端字段名不完全统一时逐级兜底）
    function pendingActionText() {
        var pending = page.aiActionPending
        if (pending === null) return ""
        // 后端字段优先级：summary（完整中文文案）→ text → 本地兜底拼接
        if (pending.summary !== undefined && String(pending.summary) !== "") return String(pending.summary)
        if (pending.text !== undefined && String(pending.text) !== "") return String(pending.text)
        var kind = (pending.type !== undefined) ? String(pending.type)
                   : ((pending.kind !== undefined) ? String(pending.kind) : "")
        var target = (pending.target !== undefined) ? String(pending.target)
                     : (pending.spaceName !== undefined ? String(pending.spaceName)
                        : (pending.name !== undefined ? String(pending.name) : ""))
        if (kind === "space" || kind === "openSpace")
            return qsTr("打开空间「%1」").arg(target)
        if (kind === "setting" || kind === "changeSetting") {
            if (pending.value !== undefined)
                return qsTr("修改设置：%1 %2").arg(target).arg(String(pending.value))
            return qsTr("修改设置：%1").arg(target)
        }
        return (pending.title !== undefined && String(pending.title) !== "") ? String(pending.title)
                                                                             : qsTr("执行一个动作")
    }

    // 待确认动作的确认按钮文案（后端按动作类型给："确认开始" / "确认执行"）
    function pendingActionConfirmLabel() {
        var pending = page.aiActionPending
        if (pending !== null && pending.confirmLabel !== undefined
                && String(pending.confirmLabel) !== "")
            return String(pending.confirmLabel)
        return qsTr("确认执行")
    }

    function pendingActionDetail() {
        var pending = page.aiActionPending
        if (pending === null) return ""
        var title = (pending.title !== undefined) ? String(pending.title) : ""
        var text = page.pendingActionText()
        if (title !== "" && title !== text) return title
        if (pending.detail !== undefined && String(pending.detail) !== "") return String(pending.detail)
        return ""
    }

    function confirmAIAction() {
        var pending = page.aiActionPending
        if (pending === null) return
        var note = page.pendingActionText()
        if (typeof App !== "undefined" && typeof App.aiConfirmAction === "function") {
            try {
                App.aiConfirmAction()
            } catch (err) {
                // 接口异常时仍记一条本地结果，保证用户知道动作已发出
            }
        }
        // 后端有 aiActionLog 时结果文案由后端回传，避免重复记录
        if (typeof App === "undefined" || App.aiActionLog === undefined)
            page.postActionNote(note)
    }

    function cancelAIAction() {
        var pending = page.aiActionPending
        if (pending === null) return
        if (typeof App !== "undefined" && typeof App.aiCancelAction === "function") {
            try {
                App.aiCancelAction()
            } catch (err) {
                // 取消不改变任何状态
            }
        }
    }

    Component.onCompleted: init()
    onMessageCountChanged: scrollTimer.restart()
    Timer { id: scrollTimer; interval: 60; onTriggered: messageFlick.contentY = Math.max(0, messageFlick.contentHeight - messageFlick.height) }

    Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: pageColumn.height + 36
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
            id: pageColumn
            width: Math.min(flick.width - 72, 940)
            x: (flick.width - width) / 2
            y: 18
            spacing: 12

            Item {
                width: parent.width
                height: 62
                // v0.17 海洋波浪页头底纹（静态，避免多页同时动画）
                WaveBackdrop {
                    x: -(page.width - parent.width) / 2
                    width: page.width
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.topMargin: -10
                    anchors.bottomMargin: -78
                    tone: AppTheme.light ? "light" : "deep"
                    intensity: 0.50
                    z: -1
                }

                Column {
                    anchors.left: parent.left
                    anchors.bottom: parent.bottom
                    spacing: 4
                    Text { text: qsTr("AI"); color: AppTheme.textPrimary; font.pixelSize: AppTheme.fs(28); font.weight: Font.Bold; font.family: AppTheme.fontFamily }
                    Text { text: qsTr("对话、历史与用量都在这里"); color: AppTheme.textSecondary; font.pixelSize: AppTheme.fs(12); font.family: AppTheme.fontFamily }
                }
                // v0.21：「聊天记录」分栏开关（窄窗口下用来收起 / 展开左栏）
                Item {
                    id: historyToggle
                    objectName: "AIHistoryToggle"
                    anchors.right: usageBadge.left
                    anchors.rightMargin: 10
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 4
                    width: historyToggleLabel.implicitWidth + historyToggleGlyph.width + 26
                    height: 30

                    Rectangle {
                        anchors.fill: parent
                        radius: 15
                        color: historyToggleArea.containsMouse
                               ? (AppTheme.glass ? AppTheme.glassSurfaceStrong : AppTheme.cardBgAlt)
                               : (AppTheme.glass ? "#1AFFFFFF" : AppTheme.cardBgAlt)
                        border.width: 1
                        border.color: page.sidebarOpen ? AppTheme.accent : AppTheme.cardBorder
                    }

                    Row {
                        anchors.centerIn: parent
                        spacing: 5

                        Glyph {
                            id: historyToggleGlyph
                            anchors.verticalCenter: parent.verticalCenter
                            kind: page.sidebarOpen ? "chevronLeft" : "chevron"
                            size: 9
                            color: page.sidebarOpen ? AppTheme.accent : AppTheme.textSecondary
                        }

                        Text {
                            id: historyToggleLabel
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("聊天记录")
                            color: page.sidebarOpen ? AppTheme.accent : AppTheme.textSecondary
                            font.pixelSize: AppTheme.fs(11)
                            font.family: AppTheme.fontFamily
                        }
                    }

                    MouseArea {
                        id: historyToggleArea
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.toggleSidebar()
                    }
                }

                Rectangle {
                    id: usageBadge
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 4
                    width: usageHeader.implicitWidth + 24
                    height: 30
                    radius: 15
                    color: AppTheme.glass ? "#1AFFFFFF" : AppTheme.cardBgAlt
                    border.width: 1
                    border.color: AppTheme.cardBorder
                    Text {
                        id: usageHeader
                        anchors.centerIn: parent
                        text: qsTr("今日 %1 tokens · %2%3（估算）").arg(page.todayTokens).arg(page.costSymbol).arg(Number(page.todayCost).toFixed(2))
                        color: AppTheme.textSecondary
                        font.pixelSize: AppTheme.fs(11)
                        font.family: AppTheme.fontFamily
                    }
                }
            }

            // 主区：左侧「聊天记录」分栏 + 中间聊天 + 右侧 AI 设置
            Row {
                id: mainRow
                width: parent.width
                height: 470
                spacing: 14

                // ---------- 左栏：聊天记录（v0.21 分栏；窄窗口可收起） ----------
                GlassCard {
                    id: historyCard
                    objectName: "AIHistoryCard"
                    visible: page.sidebarVisible
                    width: 208
                    height: 470
                    radius: 22
                    interactive: false
                    glassSource: page.glassSource

                    Item {
                        anchors.fill: parent
                        anchors.margins: 14

                        AIHistoryList {
                            id: historyList
                            objectName: "AIHistoryList"
                            anchors.fill: parent
                            animationsEnabled: page.animationsEnabled
                            conversations: page.conversations
                            currentConversationId: page.currentConversationId
                            title: qsTr("聊天记录")
                            newText: qsTr("新建")
                            onNewRequested: page.newConversation()
                            onSelected: (conversationId) => page.selectConversation(conversationId)
                            onDeleteRequested: (conversationId) => page.deleteConversation(conversationId)
                        }
                    }
                }

                // ---------- 中间：聊天 ----------
                GlassCard {
                    id: chatCard
                    objectName: "AIChatCard"
                    width: Math.max(320, pageColumn.width - (page.sidebarVisible ? 222 : 0)
                                    - (page.configOpen ? 314 : 0))
                    height: 470
                    radius: 22
                    interactive: false
                    glassSource: page.glassSource

                    Item {
                        anchors.fill: parent
                        anchors.margins: 16
                        Column {
                            width: parent.width
                            spacing: 10
                            Row {
                                width: parent.width
                                spacing: 8
                                Item {
                                    id: providerButton
                                    width: Math.min(240, providerButtonText.implicitWidth + (page.freeProvider ? 92 : 56))
                                    height: 32
                                    Rectangle {
                                        anchors.fill: parent
                                        radius: 9
                                        color: providerButtonArea.containsMouse ? AppTheme.cardBgAlt : AppTheme.cardBg
                                        border.width: 1
                                        border.color: providerCombo.opened ? AppTheme.accent : AppTheme.cardBorder
                                    }
                                    Row {
                                        anchors.left: parent.left
                                        anchors.leftMargin: 10
                                        anchors.verticalCenter: parent.verticalCenter
                                        spacing: 6
                                        Text { id: providerButtonText; text: page.providerLabel; color: AppTheme.textPrimary; font.pixelSize: AppTheme.fs(12); font.family: AppTheme.fontFamily }
                                        Rectangle {
                                            visible: page.freeProvider
                                            width: 40
                                            height: 16
                                            radius: 8
                                            color: "#1FA36B"
                                            Text { anchors.centerIn: parent; text: qsTr("免配置"); color: "#FFFFFF"; font.pixelSize: AppTheme.fs(9); font.family: AppTheme.fontFamily }
                                        }
                                    }
                                    Text { anchors.right: parent.right; anchors.rightMargin: 9; anchors.verticalCenter: parent.verticalCenter; text: "▾"; color: AppTheme.textTertiary; font.pixelSize: AppTheme.fs(11) }
                                    MouseArea { id: providerButtonArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: page.openProviderMenu(providerButton) }
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: (page.reasoningSupported ? qsTr("思考") : "") + (page.reasoningSupported && page.webSupported ? " · " : "") + (page.webSupported ? qsTr("联网") : "")
                                    color: AppTheme.textTertiary
                                    font.pixelSize: AppTheme.fs(10)
                                    font.family: AppTheme.fontFamily
                                }
                                Item { width: parent.width - 520; height: 1 }
                                Row {
                                    visible: page.reasoningSupported
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 5
                                    Text { anchors.verticalCenter: parent.verticalCenter; text: qsTr("思考"); color: page.reasoningEnabled ? AppTheme.accent : AppTheme.textTertiary; font.pixelSize: AppTheme.fs(11); font.family: AppTheme.fontFamily }
                                    GlassSwitch { anchors.verticalCenter: parent.verticalCenter; checked: page.reasoningEnabled; onClicked: page.toggleReasoning() }
                                }
                                Row {
                                    visible: page.webSupported
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 5
                                    Text { anchors.verticalCenter: parent.verticalCenter; text: qsTr("联网"); color: page.webEnabled ? AppTheme.accent : AppTheme.textTertiary; font.pixelSize: AppTheme.fs(11); font.family: AppTheme.fontFamily }
                                    GlassSwitch { anchors.verticalCenter: parent.verticalCenter; checked: page.webEnabled; onClicked: page.toggleWebSearch() }
                                }
                                Item {
                                    width: 30
                                    height: 30
                                    anchors.verticalCenter: parent.verticalCenter
                                    Rectangle {
                                        anchors.fill: parent
                                        radius: 15
                                        color: configArea.containsMouse ? AppTheme.cardBgAlt : "transparent"
                                        border.width: 1
                                        border.color: page.configOpen ? AppTheme.accent : AppTheme.cardBorder
                                    }
                                    Glyph { anchors.centerIn: parent; kind: "gear"; size: 13; color: page.configOpen ? AppTheme.accent : AppTheme.textSecondary }
                                    MouseArea { id: configArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: page.toggleConfig() }
                                }
                            }

                            Rectangle { width: parent.width; height: 1; color: AppTheme.divider }

                            Item {
                                width: parent.width
                                height: 300
                                Flickable {
                                    id: messageFlick
                                    anchors.fill: parent
                                    contentWidth: width
                                    contentHeight: messageColumn.height
                                    clip: true
                                    boundsBehavior: Flickable.StopAtBounds
                                    Column {
                                        id: messageColumn
                                        width: messageFlick.width
                                        spacing: 10
                                        Repeater {
                                            model: page.messages
                                            delegate: Item {
                                                width: messageColumn.width
                                                height: bubbleItem.height
                                                readonly property bool isUser: page.messageRole(modelData) === "user"
                                                readonly property string reasoningText: page.messageReasoning(modelData)
                                                readonly property bool reasoningOpen: page.expandedReasoningKey === page.messageKey(index)
                                                readonly property string reasoningKey: page.messageKey(index)
                                                Item {
                                                    id: bubbleItem
                                                    width: Math.min(parent.width * 0.8, contentText.implicitWidth + 28)
                                                    height: bubbleColumn.height + 20
                                                    x: isUser ? parent.width - width : 0
                                                    Rectangle {
                                                        anchors.fill: parent
                                                        radius: 14
                                                        color: isUser ? AppTheme.accentSoft : (AppTheme.glass ? "#1AFFFFFF" : AppTheme.cardBgAlt)
                                                        border.width: 1
                                                        border.color: isUser ? AppTheme.accent : AppTheme.cardBorder
                                                    }
                                                    Column {
                                                        id: bubbleColumn
                                                        x: 12
                                                        y: 8
                                                        width: parent.width - 24
                                                        spacing: 4
                                                        Item {
                                                            visible: !isUser && reasoningText !== ""
                                                            width: parent.width
                                                            height: 20
                                                            Text {
                                                                anchors.verticalCenter: parent.verticalCenter
                                                                text: (page.expandedReasoningKey === reasoningKey ? "▾ " : "▸ ") + qsTr("思考过程")
                                                                color: AppTheme.textTertiary
                                                                font.pixelSize: AppTheme.fs(10)
                                                                font.family: AppTheme.fontFamily
                                                            }
                                                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: page.toggleReasoningMessage(index) }
                                                        }
                                                        Rectangle {
                                                            visible: !isUser && reasoningText !== "" && page.expandedReasoningKey === reasoningKey
                                                            width: parent.width
                                                            height: reasoningTextLabel.implicitHeight + 14
                                                            radius: 8
                                                            color: AppTheme.glass ? "#12FFFFFF" : AppTheme.divider
                                                            Text {
                                                                id: reasoningTextLabel
                                                                x: 8
                                                                y: 7
                                                                width: parent.width - 16
                                                                text: reasoningText
                                                                color: AppTheme.textTertiary
                                                                font.pixelSize: AppTheme.fs(10)
                                                                font.family: C.monoFont
                                                                wrapMode: Text.WordWrap
                                                            }
                                                        }
                                                        Text {
                                                            id: contentText
                                                            width: parent.width
                                                            text: page.messageContent(modelData)
                                                            color: AppTheme.textPrimary
                                                            font.pixelSize: AppTheme.fs(12)
                                                            font.family: AppTheme.fontFamily
                                                            wrapMode: Text.WordWrap
                                                            lineHeight: 1.5
                                                        }
                                                        Text {
                                                            visible: modelData.tokens !== undefined && Number(modelData.tokens) > 0
                                                            text: qsTr("%1 tokens").arg(modelData.tokens !== undefined ? modelData.tokens : 0)
                                                            color: AppTheme.textTertiary
                                                            font.pixelSize: AppTheme.fs(9)
                                                            font.family: AppTheme.fontFamily
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        // v0.21：AI 动作执行后的系统小字（「已为你打开 xx / 已修改设置：字号 120%」）
                                        Repeater {
                                            model: page.visibleActionNotes

                                            delegate: Item {
                                                objectName: "AIActionNote"
                                                width: messageColumn.width
                                                height: actionNoteChip.height + 2

                                                Rectangle {
                                                    id: actionNoteChip
                                                    anchors.horizontalCenter: parent.horizontalCenter
                                                    width: Math.min(parent.width, actionNoteRow.implicitWidth + 26)
                                                    height: 24
                                                    radius: 12
                                                    color: AppTheme.glass ? "#14FFFFFF" : AppTheme.cardBgAlt
                                                    border.width: 1
                                                    border.color: AppTheme.glass ? "#26FFFFFF" : AppTheme.cardBorder

                                                    Row {
                                                        id: actionNoteRow
                                                        anchors.centerIn: parent
                                                        spacing: 6

                                                        Glyph {
                                                            anchors.verticalCenter: parent.verticalCenter
                                                            kind: "check"
                                                            size: 9
                                                            color: AppTheme.success
                                                        }

                                                        Text {
                                                            anchors.verticalCenter: parent.verticalCenter
                                                            text: page.actionNoteText(modelData)
                                                            color: AppTheme.textTertiary
                                                            font.pixelSize: AppTheme.fs(10)
                                                            font.family: AppTheme.fontFamily
                                                            elide: Text.ElideRight
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                        Text { visible: page.messageCount === 0 && page.configured && page.chatState === "loading"; text: qsTr("思考中…"); color: AppTheme.textSecondary; font.pixelSize: AppTheme.fs(12); font.family: AppTheme.fontFamily }
                                        TextEdit {
                                            visible: page.messageCount === 0 && page.configured && page.chatState === "ok"
                                            width: parent.width
                                            text: page.chatAnswer
                                            readOnly: true
                                            textFormat: TextEdit.PlainText
                                            wrapMode: TextEdit.Wrap
                                            color: AppTheme.textPrimary
                                            selectionColor: AppTheme.accentSoft
                                            selectedTextColor: "#FFFFFF"
                                            font.pixelSize: AppTheme.fs(12)
                                            font.family: AppTheme.fontFamily
                                            selectByMouse: true
                                        }
                                        Text {
                                            visible: page.messageCount === 0 && page.configured && page.chatState === "error"
                                            width: parent.width
                                            text: page.chatError !== "" ? page.chatError : qsTr("AI 请求失败")
                                            color: AppTheme.danger
                                            font.pixelSize: AppTheme.fs(11)
                                            font.family: AppTheme.fontFamily
                                            wrapMode: Text.WordWrap
                                        }
                                        Text {
                                            visible: page.messageCount === 0 && (!page.configured || page.chatState === "idle")
                                            width: parent.width
                                            text: page.configured ? qsTr("空会话：问问专注方法，或让它帮你整理今天的任务。")
                                                                  : qsTr("还没有配置 AI。点右上角齿轮填写服务商与 Key，或选择「免费直连（免配置）」。")
                                            color: AppTheme.textTertiary
                                            font.pixelSize: AppTheme.fs(11)
                                            font.family: AppTheme.fontFamily
                                            wrapMode: Text.WordWrap
                                        }
                                    }
                                }
                            }

                            Row {
                                width: parent.width
                                spacing: 8
                                Item {
                                    width: parent.width - 90
                                    height: 38
                                    Rectangle {
                                        anchors.fill: parent
                                        radius: 12
                                        color: AppTheme.cardBgAlt
                                        border.width: 1
                                        border.color: chatInput.activeFocus ? AppTheme.accent : AppTheme.cardBorder
                                    }
                                    TextInput {
                                        id: chatInput
                                        anchors.fill: parent
                                        anchors.leftMargin: 12
                                        anchors.rightMargin: 10
                                        verticalAlignment: TextInput.AlignVCenter
                                        color: AppTheme.textPrimary
                                        selectionColor: AppTheme.accentSoft
                                        selectedTextColor: "#FFFFFF"
                                        font.pixelSize: AppTheme.fs(12)
                                        font.family: AppTheme.fontFamily
                                        enabled: page.configured
                                        text: page.query
                                        onTextChanged: page.query = text
                                        onAccepted: page.send()
                                        Text {
                                            anchors.verticalCenter: parent.verticalCenter
                                            visible: chatInput.text.length === 0
                                            text: page.configured ? qsTr("问点什么…（Enter 发送）") : qsTr("请先配置 AI")
                                            color: AppTheme.textTertiary
                                            font.pixelSize: AppTheme.fs(12)
                                            font.family: AppTheme.fontFamily
                                        }
                                    }
                                }
                                Item {
                                    width: 82
                                    height: 38
                                    Rectangle { anchors.fill: parent; radius: 19; color: sendArea.containsMouse ? AppTheme.accentSoft : AppTheme.accent; opacity: page.configured ? 1 : 0.4 }
                                    Text { anchors.centerIn: parent; text: qsTr("发送"); color: "#FFFFFF"; font.pixelSize: AppTheme.fs(12); font.weight: Font.DemiBold; font.family: AppTheme.fontFamily }
                                    MouseArea { id: sendArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; enabled: page.configured; onClicked: page.send() }
                                }
                            }

                            Text { width: parent.width; visible: page.usageText() !== ""; text: page.usageText(); color: AppTheme.textTertiary; font.pixelSize: AppTheme.fs(10); font.family: AppTheme.fontFamily }
                        }
                    }
                }

                GlassCard {
                    id: configCard
                    objectName: "AIConfigCard"
                    visible: page.configOpen
                    width: 300
                    height: 470
                    radius: 22
                    interactive: false
                    glassSource: page.glassSource
                    Flickable {
                        id: configFlick
                        anchors.fill: parent
                        anchors.margins: 16
                        contentWidth: width
                        contentHeight: configColumn.height
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        Column {
                            id: configColumn
                            width: parent.width
                            spacing: 8
                            Row {
                                width: parent.width
                                Text { text: qsTr("AI 设置"); color: AppTheme.textPrimary; font.pixelSize: AppTheme.fs(14); font.weight: Font.DemiBold; font.family: AppTheme.fontFamily }
                                Item { width: parent.width - 130; height: 1 }
                                GlassSwitch {
                                    checked: (typeof App !== "undefined" && App.aiEnabled !== undefined) ? App.aiEnabled === true : false
                                    onClicked: page.toggleEnabled()
                                }
                            }
                            Text {
                                width: parent.width
                                text: page.freeProvider ? qsTr("免配置服务商：无需 API Key，选好模型即可直接对话。")
                                                        : qsTr("Key 只保存在本机；模型列表可自动获取。")
                                color: AppTheme.textTertiary
                                font.pixelSize: AppTheme.fs(10)
                                font.family: AppTheme.fontFamily
                                wrapMode: Text.WordWrap
                            }
                            Item {
                                width: parent.width
                                height: 30
                                Text { anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; text: qsTr("服务商"); color: AppTheme.textSecondary; font.pixelSize: AppTheme.fs(11); font.family: AppTheme.fontFamily; width: 52 }
                                Item {
                                    id: configProviderField
                                    anchors.left: parent.left
                                    anchors.leftMargin: 52
                                    anchors.right: parent.right
                                    height: 28
                                    anchors.verticalCenter: parent.verticalCenter
                                    Rectangle { anchors.fill: parent; radius: 8; color: AppTheme.cardBgAlt; border.width: 1; border.color: configProviderArea.containsMouse ? AppTheme.accent : AppTheme.cardBorder }
                                    Text { anchors.left: parent.left; anchors.leftMargin: 9; anchors.verticalCenter: parent.verticalCenter; text: page.providerLabel; color: AppTheme.textPrimary; font.pixelSize: AppTheme.fs(11); font.family: AppTheme.fontFamily }
                                    Text { anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; text: "▾"; color: AppTheme.textTertiary; font.pixelSize: AppTheme.fs(11) }
                                    MouseArea { id: configProviderArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: page.openProviderMenu(configProviderField) }
                                }
                            }
                            Row {
                                width: parent.width
                                spacing: 6
                                Text { anchors.verticalCenter: parent.verticalCenter; text: qsTr("模型"); color: AppTheme.textSecondary; font.pixelSize: AppTheme.fs(11); font.family: AppTheme.fontFamily; width: 46 }
                                TextInput {
                                    id: modelInput
                                    width: parent.width - 46 - 24 - 52 - 18
                                    height: 28
                                    verticalAlignment: TextInput.AlignVCenter
                                    color: AppTheme.textPrimary
                                    selectionColor: AppTheme.accentSoft
                                    selectedTextColor: "#FFFFFF"
                                    font.pixelSize: AppTheme.fs(10)
                                    font.family: C.monoFont
                                    text: page.modelDraft
                                    onTextChanged: page.modelDraft = text
                                    onEditingFinished: page.saveModel()
                                    Rectangle { anchors.fill: parent; z: -1; radius: 8; color: AppTheme.cardBgAlt; border.width: 1; border.color: modelInput.activeFocus ? AppTheme.accent : AppTheme.cardBorder }
                                }
                                Item {
                                    width: 24
                                    height: 28
                                    Text { anchors.centerIn: parent; text: "▾"; color: AppTheme.textTertiary; font.pixelSize: AppTheme.fs(11) }
                                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: page.openModelMenu(modelInput) }
                                }
                                Item {
                                    width: 52
                                    height: 28
                                    Rectangle { anchors.fill: parent; radius: 8; color: refreshArea.containsMouse ? AppTheme.cardBgAlt : "transparent"; border.width: 1; border.color: AppTheme.cardBorder }
                                    Text { anchors.centerIn: parent; text: page.modelsState === "loading" ? qsTr("获取中") : qsTr("刷新"); color: refreshArea.containsMouse ? AppTheme.accent : AppTheme.textSecondary; font.pixelSize: AppTheme.fs(10); font.family: AppTheme.fontFamily }
                                    MouseArea { id: refreshArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: page.refreshModels() }
                                }
                            }
                            Text {
                                width: parent.width
                                visible: page.modelsHint !== ""
                                text: page.modelsHint
                                color: page.modelsState === "error" || page.localModelsError !== "" ? AppTheme.danger : AppTheme.textTertiary
                                font.pixelSize: AppTheme.fs(9)
                                font.family: AppTheme.fontFamily
                                wrapMode: Text.WordWrap
                            }
                            Item {
                                visible: !page.freeProvider
                                width: parent.width
                                height: 30
                                Text { anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; text: qsTr("API Base"); color: AppTheme.textSecondary; font.pixelSize: AppTheme.fs(11); font.family: AppTheme.fontFamily; width: 52 }
                                TextInput {
                                    id: baseInput
                                    anchors.left: parent.left
                                    anchors.leftMargin: 52
                                    anchors.right: parent.right
                                    height: 28
                                    anchors.verticalCenter: parent.verticalCenter
                                    verticalAlignment: TextInput.AlignVCenter
                                    color: AppTheme.textPrimary
                                    selectionColor: AppTheme.accentSoft
                                    selectedTextColor: "#FFFFFF"
                                    font.pixelSize: AppTheme.fs(9)
                                    font.family: C.monoFont
                                    text: page.baseDraft
                                    onTextChanged: page.baseDraft = text
                                    onEditingFinished: page.saveBase()
                                    Rectangle { anchors.fill: parent; z: -1; radius: 8; color: AppTheme.cardBgAlt; border.width: 1; border.color: baseInput.activeFocus ? AppTheme.accent : AppTheme.cardBorder }
                                }
                            }
                            Item {
                                visible: !page.freeProvider
                                width: parent.width
                                height: 30
                                Text { anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; text: qsTr("API Key"); color: AppTheme.textSecondary; font.pixelSize: AppTheme.fs(11); font.family: AppTheme.fontFamily; width: 52 }
                                TextInput {
                                    id: keyInput
                                    anchors.left: parent.left
                                    anchors.leftMargin: 52
                                    anchors.right: parent.right
                                    height: 28
                                    anchors.verticalCenter: parent.verticalCenter
                                    verticalAlignment: TextInput.AlignVCenter
                                    color: AppTheme.textPrimary
                                    selectionColor: AppTheme.accentSoft
                                    selectedTextColor: "#FFFFFF"
                                    font.pixelSize: AppTheme.fs(11)
                                    font.family: C.monoFont
                                    echoMode: TextInput.Password
                                    passwordCharacter: "•"
                                    text: page.keyDraft
                                    onTextChanged: page.keyDraft = text
                                    onEditingFinished: page.saveKey()
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        visible: keyInput.text.length === 0
                                        text: (typeof App !== "undefined" && App.aiHasKey === true) ? qsTr("已保存，留空不修改") : qsTr("输入 API Key")
                                        color: AppTheme.textTertiary
                                        font.pixelSize: AppTheme.fs(10)
                                        font.family: AppTheme.fontFamily
                                    }
                                    Rectangle { anchors.fill: parent; z: -1; radius: 8; color: AppTheme.cardBgAlt; border.width: 1; border.color: keyInput.activeFocus ? AppTheme.accent : AppTheme.cardBorder }
                                }
                            }
                            Row {
                                visible: !page.freeProvider
                                width: parent.width
                                spacing: 8
                                Item {
                                    width: 78
                                    height: 28
                                    Rectangle { anchors.fill: parent; radius: 8; color: testArea.containsMouse ? AppTheme.cardBgAlt : "transparent"; border.width: 1; border.color: AppTheme.cardBorder }
                                    Text { anchors.centerIn: parent; text: page.testKind === "testing" ? qsTr("测试中…") : qsTr("测试连接"); color: AppTheme.textSecondary; font.pixelSize: AppTheme.fs(10); font.family: AppTheme.fontFamily }
                                    MouseArea { id: testArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: page.testConnection() }
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width - 90
                                    text: page.testText !== "" ? page.testText : (page.testKind === "error" ? qsTr("连接失败") : "")
                                    color: page.testKind === "error" ? AppTheme.danger : AppTheme.textTertiary
                                    font.pixelSize: AppTheme.fs(9)
                                    font.family: AppTheme.fontFamily
                                    elide: Text.ElideRight
                                }
                            }
                            Rectangle { width: parent.width; height: 1; color: AppTheme.divider }
                            Row {
                                width: parent.width
                                spacing: 6
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width - 90
                                    text: qsTr("用量统计：今日 %1 tokens · %2%3（估算）").arg(page.todayTokens).arg(page.costSymbol).arg(Number(page.todayCost).toFixed(2))
                                    color: AppTheme.textTertiary
                                    font.pixelSize: AppTheme.fs(9)
                                    font.family: AppTheme.fontFamily
                                    wrapMode: Text.WordWrap
                                }
                                Item {
                                    width: 80
                                    height: 26
                                    Rectangle { anchors.fill: parent; radius: 8; color: resetArea.containsMouse ? AppTheme.cardBgAlt : "transparent"; border.width: 1; border.color: AppTheme.cardBorder }
                                    Text { anchors.centerIn: parent; text: qsTr("重置"); color: AppTheme.textSecondary; font.pixelSize: AppTheme.fs(9); font.family: AppTheme.fontFamily }
                                    MouseArea { id: resetArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: page.resetUsage() }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ---------- v0.16 服务商 / 模型下拉（复用 ScrollablePopup） ----------
    ScrollablePopup {
        id: providerCombo
        objectName: "AIProviderPopup"
        anchors.fill: parent
        model: page.providerList
        valueKey: "id"
        labelKey: "label"
        currentValue: page.currentProviderId
        rowHeight: 32
        maxPopupHeight: 240
        minPopupWidth: 200
        outerFlick: configFlick
        badgeText: qsTr("免配置")
        badgeWhen: function (item) {
            if (item === null || item === undefined) return false
            return item.needs_key === false || item.free === true || item.noConfig === true
                   || String(item.id) === "free" || String(item.id) === "pollinations"
                   || String(item.mode) === "free"
        }
        onSelected: (value) => page.selectProviderValue(value)
    }

    ScrollablePopup {
        id: modelCombo
        objectName: "AIModelPopup"
        anchors.fill: parent
        model: page.modelCandidates
        currentValue: page.modelDraft
        rowHeight: 30
        maxPopupHeight: 230
        minPopupWidth: 200
        outerFlick: configFlick
        mono: true
        emptyText: page.modelsState === "loading" ? qsTr("正在获取模型列表…") : qsTr("暂无可用模型")
        onSelected: (value) => page.selectModel(value)
    }

    // ---------- v0.21 AI 动作确认卡（后端提供 App.aiActionPending 时弹出） ----------
    AIActionConfirmCard {
        id: aiActionCard
        objectName: "AIPageActionConfirm"
        anchors.fill: parent
        animationsEnabled: page.animationsEnabled
        opened: page.aiActionPending !== null
        actionText: page.pendingActionText()
        detail: page.pendingActionDetail()
        confirmText: page.pendingActionConfirmLabel()
        onConfirmed: page.confirmAIAction()
        onCancelled: page.cancelAIAction()
    }
}
