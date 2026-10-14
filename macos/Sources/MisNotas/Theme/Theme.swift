import AppKit
import SwiftUI

/// Colores y tipografías del diseño.
enum Theme {
    static let window = Color.black
    static let sidebar = Color(hex: 0x111111)
    static let border = Color(hex: 0x222222)
    static let divider = Color(hex: 0x1A1A1A)
    static let field = Color(hex: 0x1A1A1A)
    static let fieldBorder = Color(hex: 0x2A2A2A)
    static let hover = Color(hex: 0x1F1F1F)
    static let popover = Color(hex: 0x161616)
    static let text = Color(hex: 0xE6E6E6)
    static let textMuted = Color(hex: 0x888888)
    static let textSoft = Color(hex: 0xA0A0A0)
    static let icon = Color(hex: 0xCCCCCC)
    static let orange = Color(hex: 0xFF5500)
    static let yellow = Color(hex: 0xFFB800)
    static let green = Color(hex: 0x1F6B45)

    static let gradient = LinearGradient(
        stops: [.init(color: Color(hex: 0xD4006C), location: 0),
                .init(color: Color(hex: 0xFF5500), location: 0.5),
                .init(color: Color(hex: 0xFFB800), location: 1)],
        startPoint: .topLeading, endPoint: .bottomTrailing)

    // MARK: Tipografías

    static func display(_ size: CGFloat, weight: Font.Weight = .heavy) -> Font {
        .custom("Barlow Condensed", size: size).weight(weight)
    }

    static func body(_ size: CGFloat = 14, weight: Font.Weight = .regular) -> Font {
        .custom("DM Sans", size: size).weight(weight)
    }

    static let mono = Font.system(size: 13, design: .monospaced)

    static func nsBody(_ size: CGFloat, bold: Bool = false, italic: Bool = false) -> NSFont {
        nsFont(family: "DM Sans", size: size, weight: bold ? .bold : .regular, italic: italic)
    }

    static func nsDisplay(_ size: CGFloat, weight: NSFont.Weight, italic: Bool = false) -> NSFont {
        nsFont(family: "Barlow Condensed", size: size, weight: weight, italic: italic)
    }

    static let nsMono = NSFont.monospacedSystemFont(ofSize: 13, weight: .regular)

    private static var fontCache: [String: NSFont] = [:]

    static func nsFont(family: String, size: CGFloat, weight: NSFont.Weight, italic: Bool) -> NSFont {
        let key = "\(family)|\(size)|\(weight.rawValue)|\(italic)"
        if let f = fontCache[key] { return f }
        var traits: [NSFontDescriptor.TraitKey: Any] = [.weight: weight.rawValue]
        if italic { traits[.symbolic] = NSFontDescriptor.SymbolicTraits.italic.rawValue }
        let desc = NSFontDescriptor(fontAttributes: [.family: family, .traits: traits])
        var font = NSFont(descriptor: desc, size: size) ?? .systemFont(ofSize: size, weight: weight)
        if italic, !font.fontDescriptor.symbolicTraits.contains(.italic) {
            font = NSFontManager.shared.convert(font, toHaveTrait: .italicFontMask)
        }
        fontCache[key] = font
        return font
    }

    /// Registra las fuentes incluidas (Barlow Condensed y DM Sans, licencia OFL).
    static func registerFonts() {
        let candidates = [
            Bundle.main.resourceURL?.appendingPathComponent("Fonts"),
            // `swift run`: las fuentes siguen en el árbol de fuentes.
            URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
                .appendingPathComponent("Resources/Fonts"),
        ].compactMap { $0 }
        guard let dir = candidates.first(where: { FileManager.default.fileExists(atPath: $0.path) }),
              let files = try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)
        else { return }
        for url in files where url.pathExtension == "ttf" {
            CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
        }
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(.sRGB, red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255)
    }
}

extension NSColor {
    convenience init(hex: UInt32) {
        self.init(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255,
                  blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
    }
}

/// Botón de icono de 30×28 con fondo al pasar el ratón, como los de la barra de herramientas del diseño.
struct IconButton: View {
    let systemName: String
    var help: String = ""
    var size: CGFloat = 14
    var width: CGFloat = 30
    var color: Color = Theme.icon
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: size, weight: .regular))
                .foregroundStyle(hover ? .white : color)
                .frame(width: width, height: 28)
                .background(RoundedRectangle(cornerRadius: 5).fill(hover ? Theme.hover : .clear))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(help)
        .onHover { hover = $0 }
    }
}

/// Zona que permite arrastrar la ventana (la barra de título está oculta).
struct WindowDragArea: NSViewRepresentable {
    final class DragView: NSView {
        override var mouseDownCanMoveWindow: Bool { true }
        override func mouseDown(with event: NSEvent) {
            if event.clickCount == 2 { window?.performZoom(nil) } else { window?.performDrag(with: event) }
        }
    }
    func makeNSView(context: Context) -> NSView { DragView() }
    func updateNSView(_ nsView: NSView, context: Context) {}
}

/// Casilla de verificación con el degradado del diseño.
struct GradientCheckbox: View {
    let checked: Bool
    var size: CGFloat = 17
    var body: some View {
        RoundedRectangle(cornerRadius: 4)
            .fill(checked ? AnyShapeStyle(Theme.gradient) : AnyShapeStyle(Color.clear))
            .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(checked ? .clear : Color(hex: 0x666666), lineWidth: 1.5))
            .overlay(checked ? Image(systemName: "checkmark").font(.system(size: size * 0.6, weight: .bold)).foregroundStyle(.black) : nil)
            .frame(width: size, height: size)
    }
}
