// Dibuja el logo del diseño (diseño-mis-notas.html) y genera un .iconset.
// Uso: swift scripts/make-icon.swift <directorio de salida>
import AppKit

let out = URL(fileURLWithPath: CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : ".")
let iconset = out.appendingPathComponent("AppIcon.iconset")
try? FileManager.default.removeItem(at: iconset)
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)

func color(_ hex: UInt32) -> CGColor {
    CGColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255, blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
}

func render(_ px: Int) -> Data {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8, samplesPerPixel: 4,
                               hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let ctx = NSGraphicsContext.current!.cgContext
    // Rejilla de iconos de macOS: el cuadrado ocupa 824 de 1024 px. En el SVG mide 96 de 100 unidades.
    let unit = CGFloat(px) * 824 / 1024 / 96
    let origin = (CGFloat(px) - 96 * unit) / 2 - 2 * unit
    ctx.translateBy(x: 0, y: CGFloat(px))
    ctx.scaleBy(x: 1, y: -1)          // coordenadas como en SVG (y hacia abajo)
    ctx.translateBy(x: origin, y: origin)
    ctx.scaleBy(x: unit, y: unit)

    ctx.setShadow(offset: CGSize(width: 0, height: -1.2), blur: 3, color: CGColor(gray: 0, alpha: 0.3))
    ctx.addPath(CGPath(roundedRect: CGRect(x: 2, y: 2, width: 96, height: 96), cornerWidth: 22, cornerHeight: 22, transform: nil))
    ctx.setFillColor(color(0x1F6B45))
    ctx.fillPath()
    ctx.setShadow(offset: .zero, blur: 0, color: nil)

    // Hoja: M29 20h31l15 15v43a2 2 0 0 1-2 2H29a2 2 0 0 1-2-2V22a2 2 0 0 1 2-2z
    let page = CGMutablePath()
    page.move(to: CGPoint(x: 29, y: 20))
    page.addLine(to: CGPoint(x: 60, y: 20))
    page.addLine(to: CGPoint(x: 75, y: 35))
    page.addLine(to: CGPoint(x: 75, y: 78))
    page.addArc(tangent1End: CGPoint(x: 75, y: 80), tangent2End: CGPoint(x: 73, y: 80), radius: 2)
    page.addLine(to: CGPoint(x: 29, y: 80))
    page.addArc(tangent1End: CGPoint(x: 27, y: 80), tangent2End: CGPoint(x: 27, y: 78), radius: 2)
    page.addLine(to: CGPoint(x: 27, y: 22))
    page.addArc(tangent1End: CGPoint(x: 27, y: 20), tangent2End: CGPoint(x: 29, y: 20), radius: 2)
    page.closeSubpath()
    ctx.addPath(page); ctx.setFillColor(color(0xFFFFFF)); ctx.fillPath()

    // Esquina doblada: M60 20v13a2 2 0 0 0 2 2h13z
    let fold = CGMutablePath()
    fold.move(to: CGPoint(x: 60, y: 20))
    fold.addLine(to: CGPoint(x: 60, y: 33))
    fold.addArc(tangent1End: CGPoint(x: 60, y: 35), tangent2End: CGPoint(x: 62, y: 35), radius: 2)
    fold.addLine(to: CGPoint(x: 75, y: 35))
    fold.closeSubpath()
    ctx.addPath(fold); ctx.setFillColor(color(0xCCCCCC)); ctx.fillPath()

    // Marcador con degradado: M35 20h11v22l-5.5-4.5L35 42z
    let mark = CGMutablePath()
    mark.move(to: CGPoint(x: 35, y: 20))
    mark.addLine(to: CGPoint(x: 46, y: 20))
    mark.addLine(to: CGPoint(x: 46, y: 42))
    mark.addLine(to: CGPoint(x: 40.5, y: 37.5))
    mark.addLine(to: CGPoint(x: 35, y: 42))
    mark.closeSubpath()
    ctx.saveGState()
    ctx.addPath(mark); ctx.clip()
    let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(),
                              colors: [color(0xD4006C), color(0xFF5500), color(0xFFB800)] as CFArray,
                              locations: [0, 0.5, 1])!
    ctx.drawLinearGradient(gradient, start: CGPoint(x: 35, y: 20), end: CGPoint(x: 46, y: 42), options: [])
    ctx.restoreGState()

    // Líneas de texto
    ctx.setFillColor(color(0x0E3B25))
    for (y, w) in [(50.0, 30.0), (59, 34), (68, 20)] {
        ctx.addPath(CGPath(roundedRect: CGRect(x: 35, y: y, width: w, height: 4), cornerWidth: 1, cornerHeight: 1, transform: nil))
        ctx.fillPath()
    }
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

for size in [16, 32, 128, 256, 512] {
    try render(size).write(to: iconset.appendingPathComponent("icon_\(size)x\(size).png"))
    try render(size * 2).write(to: iconset.appendingPathComponent("icon_\(size)x\(size)@2x.png"))
}
print(iconset.path)
