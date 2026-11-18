import QtQuick
import QtQuick.Effects
import "../theme"
import "../glass"
import "Constants.js" as C

// 灵动岛（多活动版）：
// 收起 = 胶囊（主活动标题 + 活动数）；点击展开成多张活动卡（音乐 / 专注 / 清番），避免只有一张卡。
// 音乐卡参考网易云风格：模糊封面底光 + 封面/标题/艺术家 + 进度 + 喜欢/上一首/播放/下一首/音量。
// 无媒体时只显示专注与清番卡；深清不显示（由 LockOverlay 控制）。
Item {
    id: island
    objectName: "MediaIsland"

    property Item glassSource: null

    // 音乐活动
    property bool hasMedia: false
    property string mediaTitle: ""
    property string mediaArtist: ""
    property string mediaAlbum: ""
    property string mediaApp: ""
    property string mediaArtUrl: ""
    property bool mediaPlaying: false
    property real mediaPosition: 0
    property real mediaDuration: 0

    // 专注活动
    property bool focusActive: false
    property string focusTitle: ""
    property string focusSub: ""
    property real focusProgress: 0

    // 清番活动
    property bool pomodoroActive: false
    property string pomodoroTitle: ""
    property string pomodoroSub: ""
    property real pomodoroProgress: 0

    signal togglePlay()
    signal nextTrack()
    signal prevTrack()

    property bool favorite: false
    property bool cardsOpen: false
    property bool peekOpen: false
    readonly property bool expanded: cardsOpen || peekOpen
    readonly property bool hovered: islandHover.hovered

    readonly property bool hasArt: mediaArtUrl !== ""
    readonly property int activityCount: (hasMedia ? 1 : 0) + (focusActive ? 1 : 0)
                                           + (pomodoroActive ? 1 : 0)
    readonly property int expandedHeight: {
        var h = 0
        if (hasMedia) h += 226
        if (focusActive) h += (h > 0 ? 8 : 0) + 92
        if (pomodoroActive) h += (h > 0 ? 8 : 0) + 92
        return Math.max(92, h)
    }

    implicitWidth: expanded ? 496 : 330
    implicitHeight: expanded ? expandedHeight : 62
    width: implicitWidth
    height: implicitHeight

    Behavior on width { NumberAnimation { duration: 320; easing.type: Easing.OutQuint } }
    Behavior on height { NumberAnimation { duration: 320; easing.type: Easing.OutQuint } }

    function clamp01(v) { return Math.max(0, Math.min(1, v)) }
    function timeText(seconds) {
        var total = Math.max(0, Math.round(Number(seconds) || 0))
        var m = Math.floor(total / 60)
        var s = total % 60
        return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s
    }
    function triggerPeek(durationMs) {
        if (island.activityCount > 1 || island.hasMedia || island.focusActive) {
            island.peekOpen = true
            peekTimer.restart()
        }
    }
    function toggleCards() {
        island.peekOpen = false
        peekTimer.stop()
        island.cardsOpen = !island.cardsOpen
    }
    readonly property real mediaProgress: mediaDuration > 0
                                        ? island.clamp01(mediaPosition / mediaDuration) : 0

    // 展开面板（卡片列）
    Column {
        id: cardStack
        visible: island.expanded
        opacity: island.expanded ? 1 : 0
        anchors.left: parent.left
        anchors.top: parent.top
        width: 496
        spacing: 8
        Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

        // ---------- 音乐卡 ----------
        Item {
            id: musicCard
            width: 496
            height: 226
            visible: island.hasMedia
            clip: true

            // 点空白处收起卡片列
            MouseArea {
                anchors.fill: parent
                onClicked: island.cardsOpen = false
            }

            Rectangle {
                anchors.fill: parent
                radius: 40
                color: "#F00A0C12"
            }
            Image {
                id: artBg
                anchors.fill: parent
                anchors.margins: 16
                source: island.hasArt ? island.mediaArtUrl : ""
                visible: false
                fillMode: Image.PreserveAspectCrop
                cache: false
                sourceSize.width: 320
                sourceSize.height: 240
            }
            MultiEffect {
                anchors.fill: parent
                source: artBg
                visible: island.hasArt
                blurEnabled: true
                blur: 1.0
                blurMax: 96
                saturation: 0.7
                brightness: 0.02
                opacity: 1.0
            }
            Image {
                anchors.fill: parent
                anchors.margins: 22
                source: island.hasArt ? island.mediaArtUrl : ""
                visible: island.hasArt
                fillMode: Image.PreserveAspectCrop
                cache: false
                sourceSize.width: 160
                sourceSize.height: 120
                scale: 1.25
                opacity: 0.4
            }
            Rectangle {
                anchors.fill: parent
                visible: !island.hasArt
                radius: 40
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: Qt.rgba(AppTheme.gradA.r, AppTheme.gradA.g, AppTheme.gradA.b, 0.55) }
                    GradientStop { position: 1.0; color: Qt.rgba(AppTheme.gradDeep.r, AppTheme.gradDeep.g, AppTheme.gradDeep.b, 0.85) }
                }
            }
            Rectangle {
                anchors.fill: parent
                radius: 40
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "#22000000" }
                    GradientStop { position: 0.5; color: "#4D000000" }
                    GradientStop { position: 1.0; color: "#8C000000" }
                }
            }
            Rectangle {
                anchors.fill: parent
                radius: 40
                color: "transparent"
                border.width: 1
                border.color: "#26FFFFFF"
            }

            // 封面
            Rectangle {
                x: 30; y: 26; width: 64; height: 64; radius: 15
                color: "#1AFFFFFF"
                Rectangle {
                    anchors.fill: parent; radius: parent.radius
                    visible: !island.hasArt
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: AppTheme.gradA }
                        GradientStop { position: 1.0; color: AppTheme.gradDeep }
                    }
                }
                Image {
                    anchors.fill: parent
                    source: island.hasArt ? island.mediaArtUrl : ""
                    visible: island.hasArt
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    cache: false
                }
                Rectangle { anchors.fill: parent; radius: parent.radius; color: "transparent"; border.width: 1; border.color: "#40FFFFFF" }
                Glyph {
                    anchors.centerIn: parent
                    visible: !island.hasArt
                    kind: "wave"; size: 24; color: "#FFFFFF"
                }
            }

            // 标题 / 艺术家
            Column {
                x: 108; y: 30
                width: musicCard.width - x - 76
                spacing: 6
                Text {
                    width: parent.width
                    text: island.mediaTitle
                    color: "#FFFFFF"
                    font.pixelSize: AppTheme.fs(19)
                    font.weight: Font.DemiBold
                    font.family: AppTheme.fontFamily
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    text: island.mediaArtist !== "" ? island.mediaArtist : island.mediaAlbum
                    visible: text !== ""
                    color: "#A6FFFFFF"
                    font.pixelSize: AppTheme.fs(13)
                    font.family: AppTheme.fontFamily
                    elide: Text.ElideRight
                }
            }

            // 应用角标
            Rectangle {
                width: 38; height: 38; radius: 19
                anchors.right: parent.right; anchors.rightMargin: 26
                y: 27
                color: "#E8443F"
                border.width: 2; border.color: "#40FFFFFF"
                Text {
                    anchors.centerIn: parent
                    text: island.mediaApp !== "" ? island.mediaApp.substring(0, 1) : "♪"
                    color: "#FFFFFF"
                    font.pixelSize: AppTheme.fs(16)
                    font.weight: Font.DemiBold
                    font.family: AppTheme.fontFamily
                }
            }

            // 进度
            Row {
                x: 30; y: 116
                width: musicCard.width - 60
                spacing: 10
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: island.timeText(island.mediaPosition)
                    color: "#B3FFFFFF"; font.pixelSize: AppTheme.fs(10.5); font.family: C.monoFont
                }
                Item {
                    width: parent.width - 96
                    height: 16
                    anchors.verticalCenter: parent.verticalCenter
                    Rectangle { anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 4; radius: 2; color: "#33FFFFFF" }
                    Rectangle { anchors.verticalCenter: parent.verticalCenter; width: Math.max(parent.height, parent.width * island.mediaProgress); height: 4; radius: 2; color: "#F2FFFFFF" }
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        x: Math.max(0, Math.min(parent.width - width, parent.width * island.mediaProgress - width / 2))
                        width: 14; height: 14; radius: 7
                        color: "#FFFFFF"; border.width: 2; border.color: "#66FFFFFF"
                    }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: island.timeText(island.mediaDuration)
                    color: "#B3FFFFFF"; font.pixelSize: AppTheme.fs(10.5); font.family: C.monoFont
                }
            }

            // 控制
            Item {
                x: 0; y: 150; width: musicCard.width; height: 56

                Item {
                    width: 40; height: 40
                    anchors.left: parent.left; anchors.leftMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    scale: heartArea.pressed ? 0.86 : (heartArea.containsMouse ? 1.08 : 1)
                    Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                    Glyph {
                        anchors.centerIn: parent
                        kind: island.favorite ? "heartFilled" : "heart"
                        size: 25
                        color: island.favorite ? "#FF5C7A" : "#F2FFFFFF"
                    }
                    MouseArea {
                        id: heartArea; anchors.fill: parent; hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: island.favorite = !island.favorite
                    }
                }
                Item {
                    width: 42; height: 42
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.horizontalCenterOffset: -96
                    anchors.verticalCenter: parent.verticalCenter
                    Glyph { anchors.centerIn: parent; kind: "skipBack"; size: 24; color: "#F2FFFFFF" }
                    MouseArea {
                        anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: island.prevTrack()
                    }
                }
                Rectangle {
                    width: 58; height: 58; radius: 29
                    anchors.centerIn: parent
                    color: playArea.pressed ? "#4DFFFFFF" : (playArea.containsMouse ? "#3DFFFFFF" : "#2BFFFFFF")
                    border.width: 1; border.color: "#59FFFFFF"
                    scale: playArea.pressed ? 0.93 : (playArea.containsMouse ? 1.06 : 1)
                    Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                    Glyph {
                        anchors.centerIn: parent
                        kind: island.mediaPlaying ? "pause" : "play"
                        size: 25; color: "#FFFFFF"
                    }
                    MouseArea {
                        id: playArea; anchors.fill: parent; hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: island.togglePlay()
                    }
                }
                Item {
                    width: 42; height: 42
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.horizontalCenterOffset: 96
                    anchors.verticalCenter: parent.verticalCenter
                    Glyph { anchors.centerIn: parent; kind: "skip"; size: 24; color: "#F2FFFFFF" }
                    MouseArea {
                        anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: island.nextTrack()
                    }
                }
                Item {
                    width: 40; height: 40
                    anchors.right: parent.right; anchors.rightMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    Glyph { anchors.centerIn: parent; kind: "volume"; size: 23; color: "#D9FFFFFF" }
                }
            }
        }

        // ---------- 专注卡 ----------
        Item {
            id: focusCard
            width: 496
            height: 92
            visible: island.focusActive
            clip: true
            MouseArea { anchors.fill: parent; onClicked: island.cardsOpen = false }
            Rectangle { anchors.fill: parent; radius: 28; color: "#F00B0E16"; border.width: 1; border.color: "#26FFFFFF" }
            Rectangle {
                anchors.fill: parent; radius: 28
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: Qt.rgba(AppTheme.accent.r, AppTheme.accent.g, AppTheme.accent.b, 0.18) }
                    GradientStop { position: 0.7; color: "#00000000" }
                }
            }
            Rectangle {
                width: 44; height: 44; radius: 22
                x: 22; y: 24
                gradient: Gradient {
                    GradientStop { position: 0.0; color: AppTheme.gradA }
                    GradientStop { position: 1.0; color: AppTheme.gradDeep }
                }
                Glyph { anchors.centerIn: parent; kind: "ripple"; size: 21; color: AppTheme.onAccent }
            }
            Column {
                x: 84; y: 22
                width: focusCard.width - x - 28
                spacing: 5
                Text {
                    width: parent.width
                    text: island.focusTitle !== "" ? island.focusTitle : qsTr("专注中")
                    color: "#FFFFFF"
                    font.pixelSize: AppTheme.fs(16)
                    font.weight: Font.DemiBold
                    font.family: AppTheme.fontFamily
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    text: island.focusSub
                    visible: text !== ""
                    color: "#B3FFFFFF"
                    font.pixelSize: AppTheme.fs(12)
                    font.family: AppTheme.fontFamily
                    elide: Text.ElideRight
                }
            }
            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right
                anchors.leftMargin: 84; anchors.rightMargin: 28
                anchors.bottom: parent.bottom; anchors.bottomMargin: 16
                height: 4; radius: 2
                color: "#26FFFFFF"
                Rectangle {
                    width: parent.width * island.clamp01(island.focusProgress)
                    height: parent.height; radius: 2
                    color: AppTheme.accent
                }
            }
        }

        // ---------- 清番卡 ----------
        Item {
            id: pomodoroCard
            width: 496
            height: 92
            visible: island.pomodoroActive
            clip: true
            MouseArea { anchors.fill: parent; onClicked: island.cardsOpen = false }
            Rectangle { anchors.fill: parent; radius: 28; color: "#F00B0E16"; border.width: 1; border.color: "#26FFFFFF" }
            Rectangle {
                width: 44; height: 44; radius: 22
                x: 22; y: 24
                color: "#26FFFFFF"; border.width: 1; border.color: "#40FFFFFF"
                Glyph { anchors.centerIn: parent; kind: "timer"; size: 21; color: "#FFFFFF" }
            }
            Column {
                x: 84; y: 22
                width: pomodoroCard.width - x - 28
                spacing: 5
                Text {
                    width: parent.width
                    text: island.pomodoroTitle !== "" ? island.pomodoroTitle : qsTr("清番")
                    color: "#FFFFFF"
                    font.pixelSize: AppTheme.fs(16)
                    font.weight: Font.DemiBold
                    font.family: AppTheme.fontFamily
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    text: island.pomodoroSub
                    visible: text !== ""
                    color: "#B3FFFFFF"
                    font.pixelSize: AppTheme.fs(12)
                    font.family: AppTheme.fontFamily
                    elide: Text.ElideRight
                }
            }
            Rectangle {
                anchors.left: parent.left; anchors.right: parent.right
                anchors.leftMargin: 84; anchors.rightMargin: 28
                anchors.bottom: parent.bottom; anchors.bottomMargin: 16
                height: 4; radius: 2
                color: "#26FFFFFF"
                Rectangle {
                    width: parent.width * island.clamp01(island.pomodoroProgress)
                    height: parent.height; radius: 2
                    color: "#F2FFFFFF"
                }
            }
        }
    }

    // ---------- 收起态：胶囊按钮（点击展开卡片列） ----------
    Item {
        id: mini
        anchors.fill: parent
        opacity: island.expanded ? 0 : 1
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }

        Rectangle {
            anchors.fill: parent
            radius: 31
            color: "#F00A0C12"
            border.width: 1
            border.color: island.hovered ? "#4DFFFFFF" : "#26FFFFFF"
        }

        Item {
            id: miniCover
            width: 40; height: 40
            anchors.left: parent.left; anchors.leftMargin: 11
            anchors.verticalCenter: parent.verticalCenter
            Rectangle {
                anchors.fill: parent; radius: 12
                visible: !island.hasArt
                gradient: Gradient {
                    GradientStop { position: 0.0; color: AppTheme.gradA }
                    GradientStop { position: 1.0; color: AppTheme.gradDeep }
                }
            }
            Image {
                anchors.fill: parent
                source: island.hasArt ? island.mediaArtUrl : ""
                visible: island.hasArt
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                cache: false
            }
            Rectangle { anchors.fill: parent; radius: 12; color: "transparent"; border.width: 1; border.color: "#33FFFFFF"; visible: island.hasArt }
            Glyph {
                anchors.centerIn: parent
                visible: !island.hasArt
                kind: island.hasMedia ? "wave" : (island.pomodoroActive ? "timer" : "ripple")
                size: 18
                color: island.hasMedia ? "#FFFFFF" : AppTheme.onAccent
            }
        }

        Column {
            anchors.left: parent.left
            anchors.leftMargin: 61
            anchors.right: badge.left
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            Text {
                width: parent.width
                text: island.hasMedia
                      ? island.mediaTitle
                      : (island.focusTitle !== "" ? island.focusTitle : qsTr("专注中"))
                color: "#F5FFFFFF"
                font.pixelSize: AppTheme.fs(13)
                font.weight: Font.DemiBold
                font.family: AppTheme.fontFamily
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                text: island.hasMedia
                      ? (island.mediaArtist !== "" ? island.mediaArtist : island.mediaApp)
                      : island.focusSub
                visible: text !== ""
                color: "#A6FFFFFF"
                font.pixelSize: AppTheme.fs(10.5)
                font.family: AppTheme.fontFamily
                elide: Text.ElideRight
            }
        }

        // 活动数角标
        Rectangle {
            id: badge
            anchors.right: chevron.left
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(20, badgeText.implicitWidth + 10)
            height: 20
            radius: 10
            color: "#2EFFFFFF"
            Text {
                id: badgeText
                anchors.centerIn: parent
                text: String(Math.max(1, island.activityCount))
                color: "#FFFFFF"
                font.pixelSize: AppTheme.fs(10)
                font.family: AppTheme.fontFamily
            }
        }
        Text {
            id: chevron
            anchors.right: parent.right
            anchors.rightMargin: 13
            anchors.verticalCenter: parent.verticalCenter
            text: "⌄"
            color: "#B3FFFFFF"
            font.pixelSize: AppTheme.fs(14)
        }

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: island.toggleCards()
        }
    }

    HoverHandler { id: islandHover }

    Timer {
        id: peekTimer
        interval: 4600
        repeat: false
        onTriggered: island.peekOpen = false
    }

    onMediaTitleChanged: {
        if (hasMedia && mediaTitle !== "") triggerPeek(4600)
    }
    onHasMediaChanged: {
        if (hasMedia) triggerPeek(4600)
    }
}
