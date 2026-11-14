pragma Singleton
import QtQuick

// 应用内轻量事件总线（v0.17）
// Main.qml 与独立窗口（QuickPanel 等）不在同一对象树里，用一个 QML 单例转发「打开清番番茄钟」，
// 保证全应用只有一个 PomodoroPanel 实例，不需要改 Python 桥。
QtObject {
    signal openPomodoroRequested()

    function openPomodoro() {
        openPomodoroRequested()
    }
}
