import QtQuick
import "../theme"

// ================= 海洋波浪背景（v0.17，静态） =================
// 全幅分层波浪：4 层半透明浪花，底部密 / 顶部疏；每层用 Canvas 一次性绘制成纹理。
// v0.17：海洋改为内置静态主题 —— 删除漂移/呼吸动画，只在尺寸或主题变化时重绘一次，
//        页面过渡动画仍由 Main.pageTransitions 控制，与本组件无关。
//
// 参数：
//   intensity 0~1   波浪强度（0 直接隐藏；页面头部装饰建议 0.4~0.6）
//   tone  deep/light 深海模式（浅蓝浪花） / 浅色模式（白色浪花）；默认跟随 AppTheme
//
// 复用：海洋主题根背景、页面头部、Onboarding、LockOverlay、EnterCountdown、
//       QuickPanel、FocusSummary、主题页海洋预览；禁止每个页面各自复制波浪绘制代码。
Item {
    id: root
    clip: true

    property real intensity: 1.0
    property string tone: AppTheme.light ? "light" : "deep"

    readonly property bool lightTone: tone === "light"
    readonly property real strength: Math.max(0, Math.min(1, Number(intensity)))
    // 3~4 层：base=波峰在高度上的位置，amp=振幅比例，periodRatio=波长相对宽度，
    //         phase=相位，alpha=该层浪花不透明度基数
    readonly property var layerSpecs: [
        { base: 0.50, amp: 0.050, periodRatio: 0.78, phase: 0.6, alpha: 0.30 },
        { base: 0.66, amp: 0.062, periodRatio: 0.62, phase: 2.3, alpha: 0.42 },
        { base: 0.81, amp: 0.070, periodRatio: 0.54, phase: 4.1, alpha: 0.58 },
        { base: 0.96, amp: 0.048, periodRatio: 0.46, phase: 5.5, alpha: 0.78 }
    ]

    // v0.17：波浪只属于第 4 个内置主题「海洋」；其余主题完全静态背景。
    visible: root.strength > 0.01 && AppTheme.ocean
    opacity: root.strength

    function rgba(colorValue, alphaValue) {
        var a = Math.max(0, Math.min(1, Number(alphaValue)))
        return "rgba(" + Math.round(colorValue.r * 255) + ","
                + Math.round(colorValue.g * 255) + ","
                + Math.round(colorValue.b * 255) + "," + a + ")"
    }

    Repeater {
        model: root.layerSpecs

        delegate: Canvas {
            id: wave
            property var spec: root.layerSpecs[index]
            readonly property real period: Math.max(240, root.width * spec.periodRatio)

            // 只画「浪尖 → 自身底部」这条带，纹理高度远小于整屏，省内存也省填充
            y: Math.round(root.height * spec.base - root.height * spec.amp * 1.8)
            width: root.width + period
            height: Math.max(2, root.height - y)
            antialiasing: true

            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()

            Connections {
                target: root
                function onLightToneChanged() { wave.requestPaint() }
            }

            Component.onCompleted: requestPaint()

            function surfaceY(px) {
                var t = (px / period) * Math.PI * 2 + spec.phase
                var base = root.height * spec.base - wave.y
                var amp = Math.max(4, root.height * spec.amp)
                return base - (Math.sin(t) + Math.sin(t * 2 + 1.3) * 0.32) * amp
            }

            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                if (width <= 0 || height <= 0 || root.width <= 0 || root.height <= 0) return

                var w = width
                var h = height
                var step = Math.max(6, Math.round(wave.period / 36))
                var base = root.height * spec.base - wave.y
                var amp = Math.max(4, root.height * spec.amp)

                ctx.beginPath()
                ctx.moveTo(0, h + 2)
                ctx.lineTo(0, wave.surfaceY(0))
                for (var px = step; px <= w + step; px += step)
                    ctx.lineTo(px, wave.surfaceY(px))
                ctx.lineTo(w, h + 2)
                ctx.closePath()

                var topColor = root.lightTone ? AppTheme.waveLightTop : AppTheme.waveDeepTop
                var bottomColor = root.lightTone ? AppTheme.waveLightBottom : AppTheme.waveDeepBottom
                var a0 = spec.alpha * (root.lightTone ? 0.80 : 1.0)
                var grad = ctx.createLinearGradient(0, base - amp * 2.2, 0, h)
                grad.addColorStop(0.0, root.rgba(topColor, a0))
                grad.addColorStop(0.55, root.rgba(bottomColor, a0 * 0.55))
                grad.addColorStop(1.0, root.rgba(bottomColor, spec.alpha * 0.22))
                ctx.fillStyle = grad
                ctx.fill()
            }
        }
    }
}