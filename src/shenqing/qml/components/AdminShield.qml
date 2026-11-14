import QtQuick

// 蓝黄四格盾牌（「重启为管理员」图标）
// 参考 Windows UAC 盾牌：蓝 #2B86FF / 黄 #FFC72C 四象限，尺寸与关闭图标一致。
// 纯 Canvas 绘制，不依赖外部图片；可随主题/缩放自由缩放。
Canvas {
    id: shield
    property real size: 18
    property color blue: "#2B86FF"
    property color yellow: "#FFC72C"
    property color outline: "#33FFFFFF"

    width: size
    height: size
    antialiasing: true

    onSizeChanged: requestPaint()
    onBlueChanged: requestPaint()
    onYellowChanged: requestPaint()

    function shieldPath(ctx, s) {
        ctx.beginPath()
        ctx.moveTo(12 * s, 3.2 * s)
        ctx.lineTo(19.2 * s, 6.1 * s)
        ctx.lineTo(19.2 * s, 11.4 * s)
        ctx.bezierCurveTo(19.2 * s, 16.5 * s, 16.0 * s, 19.2 * s, 12 * s, 20.6 * s)
        ctx.bezierCurveTo(8.0 * s, 19.2 * s, 4.8 * s, 16.5 * s, 4.8 * s, 11.4 * s)
        ctx.lineTo(4.8 * s, 6.1 * s)
        ctx.closePath()
    }

    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        var s = width / 24
        ctx.scale(s, s)

        // 四象限底色（左上蓝 / 右上黄 / 左下黄 / 右下蓝）
        ctx.save()
        shield.shieldPath(ctx, 1)
        ctx.clip()
        ctx.fillStyle = shield.blue
        ctx.fillRect(0, 0, 12, 12)
        ctx.fillStyle = shield.yellow
        ctx.fillRect(12, 0, 12, 12)
        ctx.fillStyle = shield.yellow
        ctx.fillRect(0, 12, 12, 12)
        ctx.fillStyle = shield.blue
        ctx.fillRect(12, 12, 12, 12)
        ctx.restore()

        // 描边 + 中间白色对勾，保证小尺寸也能认出是盾牌
        ctx.lineWidth = Math.max(1.0, 1.3 / s)
        ctx.strokeStyle = shield.outline
        shield.shieldPath(ctx, 1)
        ctx.stroke()

        ctx.strokeStyle = "#FFFFFF"
        ctx.lineWidth = 2.0
        ctx.lineCap = "round"
        ctx.lineJoin = "round"
        ctx.beginPath()
        ctx.moveTo(8.6, 11.9)
        ctx.lineTo(11.2, 14.4)
        ctx.lineTo(15.6, 9.3)
        ctx.stroke()
    }
}
