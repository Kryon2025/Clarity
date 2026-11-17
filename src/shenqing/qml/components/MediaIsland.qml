import QtQuick
import QtQuick.Effects
import "../theme"
import "../glass"
import "Constants.js" as C

// 灵动岛（音乐岛）：收起 = 封面胶囊 + 标题 + 播放；悬停展开 = 网易云式音乐卡。
// 展开卡参考效果：模糊封面底光 + 封面 / 标题 / 艺术家 + 进度条 + 喜欢·上一首·播放·下一首·音量。
// 无媒体会话时展示专注状态（空间、剩余、完成度），不显示播放控制。
Item {
    id: island
    objectName: "MediaIsland"

    property Item glassSource: null
    property bool hasMedia: false
    property string mediaTitle: ""
    property string mediaArtist: ""
    property string mediaAlbum: ""
    property string mediaApp: ""
    property string mediaArtUrl: ""
    property bool mediaPlaying: false
    property real mediaPosition: 0
    property real mediaDuration: 0

    property string focusLine: qsTr("专注中")
    property string focusSub: ""

    property bool forceExpanded: false
    property bool favorite: false
    property bool hoverLatch: false
    // 切歌 / 刚开始播放时自动展开 3.2 秒，像系统灵动岛的即时提示
    property bool peek: false
    readonly property bool expanded: forceExpanded || islandHover.hovered || hoverLatch || peek
    readonly property bool hasArt: mediaArtUrl !== ""
    readonly property bool useGlass: AppTheme.glass && island.glassSource !== null

    signal togglePlay()
    signal nextTrack()
    signal prevTrack()

    implicitWidth: expanded ? 496 : 320
    implicitHeight: expanded ? 226 : 62
    width: implicitWidth
    height: implicitHeight

    Behavior on width { NumberAnimation { duration: 340; easing.type: Easing.OutQuint } }
    Behavior on height { NumberAnimation { duration: 340; easing.type: Easing.OutQuint } }

    function clamp01(v) { return Math.max(0, Math.min(1, v)) }
    // 外部（进入专注时）主动触发一次展开提示
    function triggerPeek(durationMs) {
        if (island.hasMedia) {
            island.peek = true
            peekTimer.restart()
        }
    }
    function timeText(seconds) {
        var total = Math.max(0, Math.round(Number(seconds) || 0))
        var m = Math.floor(total / 60)
        var s = total % 60
        return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s
    }
    readonly property real progress: island.mediaDuration > 0
                                      ? island.clamp01(island.mediaPosition / island.mediaDuration) : 0

    // ---------- 卡片底：模糊封面底光 + 深色玻璃 ----------
    Item {
        id: card
        anchors.fill: parent
        clip: true

        Rectangle {
            anchors.fill: parent
            radius: island.expanded ? 40 : 31
            color: "#F00A0C12"
            Behavior on radius { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
        }

        // 封面放大，作为整张卡的底光（无封面时退回样式渐变）
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
        // 大面积模糊：软件/离屏后端也能出效果；失败时下层放大图兜底
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
        // 兜底：不依赖模糊的放大底光（模糊生效时叠加出更柔的颜色）
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
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Qt.rgba(AppTheme.gradA.r, AppTheme.gradA.g, AppTheme.gradA.b, 0.55) }
                GradientStop { position: 1.0; color: Qt.rgba(AppTheme.gradDeep.r, AppTheme.gradDeep.g, AppTheme.gradDeep.b, 0.85) }
            }
        }

        // 压暗 + 底部加深，保证白字对比度
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#22000000" }
                GradientStop { position: 0.5; color: "#4D000000" }
                GradientStop { position: 1.0; color: "#8C000000" }
            }
        }

        Rectangle {
            anchors.fill: parent
            radius: island.expanded ? 40 : 31
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#14FFFFFF" }
                GradientStop { position: 0.45; color: "#00FFFFFF" }
            }
        }

        Rectangle {
            anchors.fill: parent
            radius: island.expanded ? 40 : 31
            color: "transparent"
            border.width: 1
            border.color: "#26FFFFFF"
            Behavior on radius { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
        }
    }

    // 悬停判定：指针落在展开态按钮上时仍算「在岛上」
    HoverHandler {
        id: islandHover
        onHoveredChanged: {
            if (hovered) {
                hoverLatch = true
                collapseTimer.stop()
            } else {
                collapseTimer.restart()
            }
        }
    }
    Timer {
        id: collapseTimer
        interval: 280
        repeat: false
        onTriggered: if (!islandHover.hovered) hoverLatch = false
    }
    Timer {
        id: peekTimer
        interval: 4200
        repeat: false
        onTriggered: island.peek = false
    }
    onMediaTitleChanged: {
        if (hasMedia && mediaTitle !== "") {
            peek = true
            peekTimer.restart()
        }
    }
    onHasMediaChanged: {
        if (hasMedia) {
            peek = true
            peekTimer.restart()
        } else {
            peek = false
        }
    }

    // ---------- 收起态：胶囊 ----------
    Item {
        anchors.fill: parent
        opacity: island.expanded ? 0 : 1
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

        Item {
            id: miniCover
            width: 42
            height: 42
            anchors.left: parent.left
            anchors.leftMargin: 11
            anchors.verticalCenter: parent.verticalCenter
            visible: island.hasMedia

            Rectangle {
                anchors.fill: parent
                radius: 12
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
            Rectangle {
                anchors.fill: parent
                radius: 12
                color: "transparent"
                border.width: 1
                border.color: "#33FFFFFF"
                visible: island.hasArt
            }
            Glyph {
                anchors.centerIn: parent
                visible: !island.hasArt
                kind: island.hasMedia ? "wave" : "ripple"
                size: 18
                color: AppTheme.onAccent
            }
        }

        // 无媒体：专注orb
        Rectangle {
            width: 30
            height: 30
            radius: 15
            anchors.left: parent.left
            anchors.leftMargin: 15
            anchors.verticalCenter: parent.verticalCenter
            visible: !island.hasMedia
            gradient: Gradient {
                GradientStop { position: 0.0; color: AppTheme.gradA }
                GradientStop { position: 1.0; color: AppTheme.gradDeep }
            }
            Glyph {
                anchors.centerIn: parent
                kind: "ripple"
                size: 15
                color: AppTheme.onAccent
            }
        }

        Column {
            anchors.left: parent.left
            anchors.leftMargin: island.hasMedia ? 63 : 55
            anchors.right: playMini.visible ? playMini.left : parent.right
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            Text {
                width: parent.width
                text: island.hasMedia ? island.mediaTitle : island.focusLine
                color: "#F5FFFFFF"
                font.pixelSize: AppTheme.fs(13.5)
                font.weight: Font.DemiBold
                font.family: AppTheme.fontFamily
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                text: island.hasMedia
                      ? (island.mediaArtist !== "" ? island.mediaArtist
                                                   : (island.mediaAlbum !== "" ? island.mediaAlbum : island.mediaApp))
                      : island.focusSub
                visible: text !== ""
                color: "#A6FFFFFF"
                font.pixelSize: AppTheme.fs(11)
                font.family: AppTheme.fontFamily
                elide: Text.ElideRight
            }
        }

        Rectangle {
            id: playMini
            width: 34
            height: 34
            radius: 17
            visible: island.hasMedia
            anchors.right: parent.right
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            color: miniPlayArea.pressed ? "#33FFFFFF" : (miniPlayArea.containsMouse ? "#26FFFFFF" : "#1AFFFFFF")
            border.width: 1
            border.color: "#26FFFFFF"
            Glyph {
                anchors.centerIn: parent
                kind: island.mediaPlaying ? "pause" : "play"
                size: 15
                color: "#FFFFFF"
            }
            MouseArea {
                id: miniPlayArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: island.togglePlay()
            }
        }

        // 底部细进度
        Rectangle {
            visible: island.hasMedia && island.mediaDuration > 0
            anchors.left: parent.left
            anchors.leftMargin: 63
            anchors.right: parent.right
            anchors.rightMargin: 12
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 6
            height: 2
            radius: 1
            color: "#1FFFFFFF"
            Rectangle {
                width: parent.width * island.progress
                height: parent.height
                radius: 1
                color: "#E6FFFFFF"
            }
        }
    }

    // ---------- 展开态：音乐卡 ----------
    Item {
        anchors.fill: parent
        opacity: island.expanded ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }

        // 封面
        Rectangle {
            id: bigCover
            x: 30
            y: 26
            width: 66
            height: 66
            radius: 15
            color: "#1AFFFFFF"
            visible: island.hasMedia

            Rectangle {
                anchors.fill: parent
                radius: parent.radius
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
            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                color: "transparent"
                border.width: 1
                border.color: "#40FFFFFF"
            }
            Glyph {
                anchors.centerIn: parent
                visible: !island.hasArt
                kind: "wave"
                size: 26
                color: "#FFFFFF"
            }
        }

        // 无媒体时的大 orb
        Rectangle {
            width: 46
            height: 46
            radius: 23
            x: 30
            y: 34
            visible: !island.hasMedia
            gradient: Gradient {
                GradientStop { position: 0.0; color: AppTheme.gradA }
                GradientStop { position: 1.0; color: AppTheme.gradDeep }
            }
            Glyph {
                anchors.centerIn: parent
                kind: "ripple"
                size: 22
                color: AppTheme.onAccent
            }
        }

        // 标题 / 艺术家
        Column {
            x: island.hasMedia ? 112 : 90
            y: island.hasMedia ? 32 : 40
            width: island.width - x - 76
            spacing: 7

            Text {
                width: parent.width
                text: island.hasMedia ? island.mediaTitle : island.focusLine
                color: "#FFFFFF"
                font.pixelSize: AppTheme.fs(island.hasMedia ? 19 : 18)
                font.weight: Font.DemiBold
                font.family: AppTheme.fontFamily
                elide: Text.ElideRight
            }
            Text {
                width: parent.width
                text: island.hasMedia
                      ? (island.mediaArtist !== "" ? island.mediaArtist
                                                   : (island.mediaAlbum !== "" ? island.mediaAlbum : ""))
                      : island.focusSub
                visible: text !== ""
                color: "#A6FFFFFF"
                font.pixelSize: AppTheme.fs(13)
                font.family: AppTheme.fontFamily
                elide: Text.ElideRight
            }
        }

        // 右上角应用角标
        Rectangle {
            width: 38
            height: 38
            radius: 19
            anchors.right: parent.right
            anchors.rightMargin: 26
            y: 27
            visible: island.hasMedia
            color: "#E8443F"
            border.width: 2
            border.color: "#40FFFFFF"
            Text {
                anchors.centerIn: parent
                text: island.mediaApp !== "" ? island.mediaApp.substring(0, 1) : "♪"
                color: "#FFFFFF"
                font.pixelSize: AppTheme.fs(16)
                font.weight: Font.DemiBold
                font.family: AppTheme.fontFamily
            }
        }

        // 进度：已播 / 轨道 / 总长
        Row {
            x: 30
            y: 116
            width: island.width - 60
            spacing: 10
            visible: island.hasMedia

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: island.timeText(island.mediaPosition)
                color: "#B3FFFFFF"
                font.pixelSize: AppTheme.fs(10.5)
                font.family: C.monoFont
            }
            Item {
                width: parent.width - 96
                height: 16
                anchors.verticalCenter: parent.verticalCenter

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width
                    height: 4
                    radius: 2
                    color: "#33FFFFFF"
                }
                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.max(parent.height, parent.width * island.progress)
                    height: 4
                    radius: 2
                    color: "#F2FFFFFF"
                }
                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    x: Math.max(0, Math.min(parent.width - width, parent.width * island.progress - width / 2))
                    width: 14
                    height: 14
                    radius: 7
                    color: "#FFFFFF"
                    border.width: 2
                    border.color: "#66FFFFFF"
                }
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: island.timeText(island.mediaDuration)
                color: "#B3FFFFFF"
                font.pixelSize: AppTheme.fs(10.5)
                font.family: C.monoFont
            }
        }

        // 控制区
        Item {
            id: controls
            x: 0
            y: 150
            width: island.width
            height: 56
            visible: island.hasMedia

            // 喜欢
            Item {
                id: heartButton
                width: 40
                height: 40
                anchors.left: parent.left
                anchors.leftMargin: 18
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
                    id: heartArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: island.favorite = !island.favorite
                }
            }

            // 上一首
            Item {
                id: prevButton
                width: 42
                height: 42
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.horizontalCenterOffset: -96
                anchors.verticalCenter: parent.verticalCenter
                scale: prevArea.pressed ? 0.88 : 1
                Glyph {
                    anchors.centerIn: parent
                    kind: "skipBack"
                    size: 24
                    color: "#F2FFFFFF"
                }
                MouseArea {
                    id: prevArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: island.prevTrack()
                }
            }

            // 播放 / 暂停（中央大按钮）
            Rectangle {
                id: playButton
                width: 58
                height: 58
                radius: 29
                anchors.centerIn: parent
                color: playArea.pressed ? "#4DFFFFFF" : (playArea.containsMouse ? "#3DFFFFFF" : "#2BFFFFFF")
                border.width: 1
                border.color: "#59FFFFFF"
                scale: playArea.pressed ? 0.93 : (playArea.containsMouse ? 1.06 : 1)
                Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                Behavior on color { ColorAnimation { duration: 140 } }

                Glyph {
                    anchors.centerIn: parent
                    kind: island.mediaPlaying ? "pause" : "play"
                    size: 25
                    color: "#FFFFFF"
                }
                MouseArea {
                    id: playArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: island.togglePlay()
                }
            }

            // 下一首
            Item {
                id: nextButton
                width: 42
                height: 42
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.horizontalCenterOffset: 96
                anchors.verticalCenter: parent.verticalCenter
                scale: nextArea.pressed ? 0.88 : 1
                Glyph {
                    anchors.centerIn: parent
                    kind: "skip"
                    size: 24
                    color: "#F2FFFFFF"
                }
                MouseArea {
                    id: nextArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: island.nextTrack()
                }
            }

            // 音量
            Item {
                width: 40
                height: 40
                anchors.right: parent.right
                anchors.rightMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                Glyph {
                    anchors.centerIn: parent
                    kind: "volume"
                    size: 23
                    color: "#D9FFFFFF"
                }
            }
        }

        // 无媒体：底部一行轻提示
        Row {
            x: 30
            y: island.height - 46
            spacing: 8
            visible: !island.hasMedia
            Rectangle {
                width: 5
                height: 5
                radius: 3
                anchors.verticalCenter: parent.verticalCenter
                color: AppTheme.accent
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: qsTr("完成本轮后自动解除专注")
                color: "#8CFFFFFF"
                font.pixelSize: AppTheme.fs(11)
                font.family: AppTheme.fontFamily
            }
        }
    }
}
