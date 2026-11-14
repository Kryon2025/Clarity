import QtQuick
import QtQuick.Effects
import "../theme"

// 页面底：渐变 + 样式特效（v0.21：样式 style 与配色 scheme 正交）
// - solid / custom:<id>：只有 scheme 决定的渐变（custom 用 palette 的 bgTop/bgMid/bgBottom）
// - glass：渐变 + 光斑 + 暗角 + 噪点（浅色配色用浅色暗角与更淡的噪点）
// - ocean：渐变 + 静态分层浪花（浅色配色用浅色浪花，深色配色用深海）
Item {
    id: root
    property real blobStrength: 1.0
    property real noiseOpacity: AppTheme.glassNoiseOpacity
    // 海洋样式的波浪强度（静态；其他样式不显示波浪）
    property real waveIntensity: 0.85

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: AppTheme.bgStart }
            GradientStop { position: 0.55; color: AppTheme.bgCenter }
            GradientStop { position: 1.0; color: AppTheme.bgBottom }
        }
    }

    // ---------- 全幅海洋波浪（仅样式 = 海洋 显示，且完全静态） ----------
    WaveBackdrop {
        anchors.fill: parent
        visible: AppTheme.ocean
        tone: AppTheme.light ? "light" : "deep"
        intensity: root.waveIntensity
    }

    // ---------- 以下仅液态玻璃样式 ----------
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
            color: AppTheme.glassBlobA
            opacity: 0.85
        }
        MultiEffect {
            source: blobBlue
            anchors.fill: blobBlue
            blurEnabled: true
            blur: 1.0
            blurMax: 96
            opacity: 0.34 * root.blobStrength * AppTheme.glassBlobScale
        }

        Rectangle {
            id: blobCyan
            visible: false
            width: Math.max(320, root.width * 0.46)
            height: width
            radius: width / 2
            x: root.width * 0.62
            y: root.height * 0.44
            color: AppTheme.glassBlobB
            opacity: 0.85
        }
        MultiEffect {
            source: blobCyan
            anchors.fill: blobCyan
            blurEnabled: true
            blur: 1.0
            blurMax: 96
            opacity: 0.22 * root.blobStrength * AppTheme.glassBlobScale
        }

        Rectangle {
            id: blobViolet
            visible: false
            width: Math.max(320, root.width * 0.42)
            height: width
            radius: width / 2
            x: root.width * -0.04
            y: root.height * 0.66
            color: AppTheme.glassBlobC
            opacity: 0.75
        }
        MultiEffect {
            source: blobViolet
            anchors.fill: blobViolet
            blurEnabled: true
            blur: 1.0
            blurMax: 96
            opacity: 0.16 * root.blobStrength * AppTheme.glassBlobScale
        }

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: AppTheme.glassVignetteTop }
                GradientStop { position: 0.34; color: "#00000000" }
                GradientStop { position: 0.76; color: "#00000000" }
                GradientStop { position: 1.0; color: AppTheme.glassVignetteBottom }
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
