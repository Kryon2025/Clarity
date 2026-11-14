import QtQuick
import QtQuick.Effects
import "../theme"
import "Constants.js" as C

// 页面底：深海渐变 + 分层波浪 +（液态玻璃主题额外加光斑 + 噪点）
// v0.17 海洋主题：渐变改为「上浅下深」的深海色，叠一层可复用的 WaveBackdrop。
Item {
    id: root
    property real blobStrength: 1.0
    property real noiseOpacity: 0.13
    // v0.17：波浪强度 / 是否动画（低端机或截图时传 false）
    property real waveIntensity: AppTheme.light ? 0.60 : 0.85
    property bool waveAnimated: true

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: AppTheme.bgTop }
            GradientStop { position: 0.55; color: AppTheme.bgMid }
            GradientStop { position: 1.0; color: AppTheme.bgBottom }
        }
    }

    // ---------- 全幅海洋波浪（所有页面之后 / 之上） ----------
    WaveBackdrop {
        anchors.fill: parent
        tone: AppTheme.light ? "light" : "deep"
        intensity: root.waveIntensity
        animated: root.waveAnimated
    }

    // ---------- 以下仅液态玻璃主题 ----------
    Item {
        anchors.fill: parent
        visible: AppTheme.glass

        Rectangle {
            id: blobBlue
            visible: false
            width: Math.max(320, root.width * 0.52)
            height: width
            radius: width / 2
            x: -width * 0.3
            y: -height * 0.46
            color: C.waterBlue
            opacity: 0.85
        }
        MultiEffect {
            source: blobBlue
            anchors.fill: blobBlue
            blurEnabled: true
            blur: 1.0
            blurMax: 96
            opacity: 0.34 * root.blobStrength
        }

        Rectangle {
            id: blobCyan
            visible: false
            width: Math.max(320, root.width * 0.46)
            height: width
            radius: width / 2
            x: root.width * 0.62
            y: root.height * 0.44
            color: C.waterTeal
            opacity: 0.85
        }
        MultiEffect {
            source: blobCyan
            anchors.fill: blobCyan
            blurEnabled: true
            blur: 1.0
            blurMax: 96
            opacity: 0.22 * root.blobStrength
        }

        Rectangle {
            id: blobViolet
            visible: false
            width: Math.max(320, root.width * 0.42)
            height: width
            radius: width / 2
            x: root.width * -0.04
            y: root.height * 0.66
            color: C.waterSand
            opacity: 0.75
        }
        MultiEffect {
            source: blobViolet
            anchors.fill: blobViolet
            blurEnabled: true
            blur: 1.0
            blurMax: 96
            opacity: 0.16 * root.blobStrength
        }

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#3304121A" }
                GradientStop { position: 0.34; color: "#00000000" }
                GradientStop { position: 0.76; color: "#00000000" }
                GradientStop { position: 1.0; color: "#3D041018" }
            }
        }

        Image {
            anchors.fill: parent
            source: "../assets/img/noise.png"
            fillMode: Image.Tile
            smooth: false
            opacity: root.noiseOpacity
        }
    }
}
