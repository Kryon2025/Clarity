import QtQuick
import QtQuick.Effects
import "../theme"
import "Constants.js" as C

// 页面底：深海渐变 +（液态玻璃主题额外加光斑 + 噪点）
// v0.17：默认 solid 恢复 v0.16.3 之前的背景；波浪只在「海洋」主题（AppTheme.ocean）下静态显示。
Item {
    id: root
    property real blobStrength: 1.0
    property real noiseOpacity: 0.13
    // 海洋主题的波浪强度（静态；其他主题不显示波浪）
    property real waveIntensity: 0.85

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: AppTheme.bgStart }
            GradientStop { position: 0.55; color: AppTheme.bgCenter }
            GradientStop { position: 1.0; color: AppTheme.bgBottom }
        }
    }

    // ---------- 全幅海洋波浪（仅第 4 个内置主题「海洋」显示，且完全静态） ----------
    WaveBackdrop {
        anchors.fill: parent
        visible: AppTheme.ocean
        tone: AppTheme.light ? "light" : "deep"
        intensity: root.waveIntensity
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
                GradientStop { position: 0.0; color: "#33040F18" }
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
