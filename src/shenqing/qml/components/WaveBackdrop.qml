import QtQuick
import "../theme"

// ================= 海洋波浪背景（v0.17） =================
// 全幅分层波浪：4 层半透明浪花，底部密 / 顶部疏；每层用 Canvas 一次性绘制成纹理，
// 之后只做整层水平平移 + 透明度呼吸 —— 不逐帧重绘，避免整页卡顿。
//
// 参数：
//   intensity 0~1   波浪强度（0 直接隐藏；页面头部装饰建议 0.4~0.6）
//   tone  deep/light 深海模式（浅蓝浪花） / 浅色模式（白色浪花）；默认跟随 AppTheme
//   animated bool   是否漂移 + 呼吸（低端机 / 截图 / 页面头部装饰建议 false）
//
// 复用：Main 根背景、页面头部、Onboarding、LockOverlay、EnterCountdown、QuickPanel、
//       FocusSummary 都实例化本组件，禁止每个页面各自复制波浪绘制代码。
Item {
    id: root
    clip: true

    property real intensity: 1.0
    property string tone: AppTheme.light ? "light" : "deep"
    property bool animated: true

    readonly property bool lightTone: tone === "light"
    readonly property real strength: Math.max(0, Math.min(1, Number(intensity)))
    // 3~4 层：base=波峰在高度上的位置，amp=振幅比例，periodRatio=波长相对宽度，
    //         drift/breathe=漂移与呼吸周期(ms)，alpha=该层浪花不透明度基数
    readonly property var layerSpecs: [
        { base: 0.50, amp: 0.050, periodRatio: 0.78, drift: 46000, breathe: 10800, phase: 0.6, alpha: 0.30 },
        { base: 0.66, amp: 0.062, periodRatio: 0.62, drift: 39000, breathe: 9400,  phase: 2.3, alpha: 0.42 },
        { base: 0.81, amp: 0.070, periodRatio: 0.54, drift: 32000, breathe: 8200,  phase: 4.1, alpha: 0.58 },
        { base: 0.96, amp: 0.048, periodRatio: 0.46, drift: 27000, breathe: 7200,  phase: 5.5, alpha: 0.78 }
    ]

    visible: root.strength > 0.01
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
            property real breath: 1.0

            // 只画「浪尖 → 自身底部」这条带，纹理高度远小于整屏，省内存也省填充
            y: Math.round(root.height * spec.base - root.height * spec.amp * 1.8)
            width: root.width + period
            height: Math.max(2, root.height - y)
            antialiasing: true
            opacity: 0.82 + 0.18 * breath

            // 水平漂移：宽度 = 屏宽 + 一个波长，平移一个波长即可无缝循环
            NumberAnimation on x {
                running: root.animated && root.visible
                from: 0
                to: -wave.period
                duration: wave.spec.drift
                loops: Animation.Infinite
                easing.type: Easing.Linear
            }

            // 呼吸：只改透明度，不触发重绘
            SequentialAnimation on breath {
                running: root.animated && root.visible
                loops: Animation.Infinite
                NumberAnimation {
                    from: 0.84; to: 1.0
                    duration: wave.spec.breathe
                    easing.type: Easing.InOutSine
                }
                NumberAnimation {
                    from: 1.0; to: 0.84
                    duration: wave.spec.breathe
                    easing.type: Easing.InOutSine
                }
            }

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
