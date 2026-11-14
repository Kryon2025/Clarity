import QtQuick
import "../../theme"

// v24 内置组件目录：6 种 type 的元数据 + type → 组件映射 + 布局归一化。
// 使用方式：在任意 Item 里放一个 WidgetCatalog { id: catalog }（不可见、零尺寸），
// 然后 catalog.componentFor(type) 拿 Loader.sourceComponent，catalog.types 拿组件库列表。
// 说明：组件元数据（标题/描述/图标）放在 QML 里以便 qsTr 翻译；
//       默认尺寸与后端 App.widgetCatalog 保持一致，仅在后端缺失时作为兜底。
Item {
    id: catalog
    visible: false
    implicitWidth: 0
    implicitHeight: 0

    readonly property int maxWidgets: 12
    readonly property real minSize: 0.12
    readonly property real snapStep: 0.02

    // 组件库（左侧列表 + 添加下拉共用）
    readonly property var types: [
        {
            type: "clock",
            icon: "clock",
            title: qsTr("时钟"),
            desc: qsTr("大号时间与日期，一眼看清当下"),
            defaultW: 0.88,
            defaultH: 0.20
        },
        {
            type: "countdown",
            icon: "timer",
            title: qsTr("专注倒计时"),
            desc: qsTr("剩余时间大数字 + 进度环"),
            defaultW: 0.88,
            defaultH: 0.22
        },
        {
            type: "today",
            icon: "waveBars",
            title: qsTr("今日专注"),
            desc: qsTr("今日时长、次数与连续打卡"),
            defaultW: 0.88,
            defaultH: 0.22
        },
        {
            type: "streak",
            icon: "flame",
            title: qsTr("连续打卡"),
            desc: qsTr("连续专注天数与小火焰"),
            defaultW: 0.44,
            defaultH: 0.18
        },
        {
            type: "quote",
            icon: "quote",
            title: qsTr("每日一言"),
            desc: qsTr("每天一句话，可手动刷新"),
            defaultW: 0.88,
            defaultH: 0.16
        },
        {
            type: "weather",
            icon: "cloud",
            title: qsTr("天气"),
            desc: qsTr("城市、温度与更新时间"),
            defaultW: 0.88,
            defaultH: 0.18
        }
    ]

    // ---------- 六个组件的 Component（type → 组件） ----------
    Component { id: clockComponent; ClockWidget { } }
    Component { id: countdownComponent; CountdownWidget { } }
    Component { id: todayComponent; TodayWidget { } }
    Component { id: streakComponent; StreakWidget { } }
    Component { id: quoteComponent; QuoteWidget { } }
    Component { id: weatherComponent; WeatherWidget { } }

    function componentFor(type) {
        if (type === "clock") return clockComponent
        if (type === "countdown") return countdownComponent
        if (type === "today") return todayComponent
        if (type === "streak") return streakComponent
        if (type === "quote") return quoteComponent
        if (type === "weather") return weatherComponent
        return null
    }

    function metaOf(type) {
        var list = catalog.types
        for (var i = 0; i < list.length; i++) {
            if (list[i].type === String(type)) return list[i]
        }
        return null
    }

    function isKnownType(type) { return catalog.metaOf(type) !== null }

    function titleOf(type) {
        var meta = catalog.metaOf(type)
        return meta !== null ? String(meta.title) : String(type)
    }

    function descOf(type) {
        var meta = catalog.metaOf(type)
        return meta !== null ? String(meta.desc) : ""
    }

    function iconOf(type) {
        var meta = catalog.metaOf(type)
        return meta !== null ? String(meta.icon) : "grid"
    }

    function defaultWidth(type) {
        var meta = catalog.metaOf(type)
        return meta !== null ? Number(meta.defaultW) : 0.88
    }

    function defaultHeight(type) {
        var meta = catalog.metaOf(type)
        return meta !== null ? Number(meta.defaultH) : 0.20
    }

    function clamp(value, low, high) {
        return Math.max(low, Math.min(high, value))
    }

    // 网格吸附（0.02）并保留两位小数，避免浮点噪声写回后端
    function snap(value) {
        var step = catalog.snapStep
        return Math.round(Math.round(Number(value) / step) * step * 100) / 100
    }

    function round2(value) {
        return Math.round(Number(value) * 100) / 100
    }

    // 防御性归一化：与后端同一套规则（最多 12 个、w/h 0.12~1、x/y 0~1 且不越界、id 去重、非法丢弃）。
    // 后端已校验时是幂等的；后端缺失时保证界面仍能安全渲染。
    function normalizeLayout(raw) {
        var out = []
        if (raw === undefined || raw === null) return out
        var list = raw
        if (typeof list === "string") {
            try { list = JSON.parse(list) } catch (error) { return out }
        }
        if (list === null || list === undefined || typeof list.length !== "number") return out
        var seen = {}
        for (var i = 0; i < list.length && out.length < catalog.maxWidgets; i++) {
            var entry = list[i]
            if (!entry || typeof entry !== "object") continue
            var type = String(entry.type !== undefined ? entry.type : "")
            if (!catalog.isKnownType(type)) continue
            var id = String(entry.id !== undefined ? entry.id : "")
            if (id === "") id = type + "-" + (i + 1)
            if (seen[id] === true) continue
            seen[id] = true
            var minSize = catalog.minSize
            var w = catalog.clamp(Number(entry.w), minSize, 1.0)
            var h = catalog.clamp(Number(entry.h), minSize, 1.0)
            if (!isFinite(w)) w = catalog.defaultWidth(type)
            if (!isFinite(h)) h = catalog.defaultHeight(type)
            w = catalog.round2(catalog.clamp(w, minSize, 1.0))
            h = catalog.round2(catalog.clamp(h, minSize, 1.0))
            var x = Number(entry.x)
            var y = Number(entry.y)
            x = isFinite(x) ? catalog.clamp(catalog.round2(x), 0, 1) : 0
            y = isFinite(y) ? catalog.clamp(catalog.round2(y), 0, 1) : 0
            if (x + w > 1) x = catalog.round2(Math.max(0, 1 - w))
            if (y + h > 1) y = catalog.round2(Math.max(0, 1 - h))
            var props = (entry.props !== undefined && entry.props !== null
                         && typeof entry.props === "object") ? entry.props : ({})
            out.push({
                id: id,
                type: type,
                x: x,
                y: y,
                w: w,
                h: h,
                visible: entry.visible !== false,
                props: props
            })
        }
        return out
    }

    // 后端接口缺失时的本地演示布局（仅用于预览页，不进入锁屏渲染）
    function demoLayout() {
        return [
            { id: "clock-1", type: "clock", x: 0.06, y: 0.04, w: 0.88, h: 0.20, visible: true, props: ({}) },
            { id: "today-1", type: "today", x: 0.06, y: 0.28, w: 0.88, h: 0.22, visible: true, props: ({}) },
            { id: "quote-1", type: "quote", x: 0.06, y: 0.54, w: 0.88, h: 0.16, visible: true, props: ({}) }
        ]
    }
}
