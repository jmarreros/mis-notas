import AppKit
import MisNotasCore
import SwiftUI

/// `NSTextView` multilínea que crece con su contenido. En modo `.rich` edita el HTML
/// limitado de los párrafos; en modo `.plain`, texto sin formato (bloques de código).
struct GrowingTextView: NSViewRepresentable {
    enum Mode: Equatable {
        case rich(heading: Bool)
        case plain
    }

    var value: String
    var mode: Mode
    var placeholder = ""
    var focus = false
    var onFocused: () -> Void = {}
    var onChange: (String) -> Void
    var onDeleteEmpty: (() -> Void)?

    static let textColor = NSColor(hex: 0xE6E6E6)
    static let linkColor = NSColor(hex: 0xFF5500)

    private var baseColor: NSColor {
        switch mode {
        case .rich(heading: true): return .white
        case .rich: return Self.textColor
        case .plain: return NSColor(hex: 0xF2F2F2)
        }
    }

    private func font(bold: Bool, italic: Bool) -> NSFont {
        switch mode {
        case .rich(heading: true): return Theme.nsDisplay(22, weight: bold ? .bold : .semibold, italic: italic)
        case .rich: return Theme.nsBody(16, bold: bold, italic: italic)
        case .plain: return Theme.nsMono
        }
    }

    private var paragraphStyle: NSParagraphStyle {
        let p = NSMutableParagraphStyle()
        switch mode {
        case .rich(heading: false): p.lineSpacing = 16 * 0.4
        case .plain: p.lineSpacing = 13 * 0.45
        default: break
        }
        return p
    }

    func makeNSView(context: Context) -> BlockTextView {
        let tv = BlockTextView()
        tv.delegate = context.coordinator
        tv.drawsBackground = false
        tv.isRichText = mode != .plain
        tv.allowsUndo = true
        tv.isAutomaticQuoteSubstitutionEnabled = false
        tv.isAutomaticDashSubstitutionEnabled = false
        tv.isAutomaticTextReplacementEnabled = mode != .plain
        tv.isContinuousSpellCheckingEnabled = mode != .plain
        tv.textContainerInset = .zero
        tv.textContainer?.lineFragmentPadding = 0
        tv.textContainer?.widthTracksTextView = true
        tv.isVerticallyResizable = false
        tv.isHorizontallyResizable = false
        tv.insertionPointColor = .white
        tv.linkTextAttributes = [.foregroundColor: Self.linkColor, .underlineStyle: NSUnderlineStyle.single.rawValue,
                                 .cursor: NSCursor.pointingHand]
        tv.selectedTextAttributes = [.backgroundColor: NSColor(hex: 0x3A2A20)]
        tv.isRich = mode != .plain
        tv.fontFor = { b, i in self.font(bold: b, italic: i) }
        load(into: tv, context: context)
        return tv
    }

    private func load(into tv: BlockTextView, context: Context) {
        let attrs: [NSAttributedString.Key: Any] = [.font: font(bold: false, italic: false), .foregroundColor: baseColor,
                                                    .paragraphStyle: paragraphStyle]
        let content: NSAttributedString
        if mode == .plain {
            content = NSAttributedString(string: value, attributes: attrs)
        } else {
            let m = NSMutableAttributedString(attributedString: InlineHTML.attributedString(
                value, font: { b, i in font(bold: b, italic: i) }, color: baseColor, linkColor: Self.linkColor))
            m.addAttribute(.paragraphStyle, value: paragraphStyle, range: NSRange(location: 0, length: m.length))
            content = m
        }
        tv.textStorage?.setAttributedString(content)
        tv.typingAttributes = attrs
        tv.placeholder = placeholder
        context.coordinator.lastValue = value
    }

    func updateNSView(_ tv: BlockTextView, context: Context) {
        context.coordinator.parent = self
        tv.onBecomeFirstResponder = onFocused
        tv.onDeleteEmpty = onDeleteEmpty
        tv.isEditable = context.environment.isEnabled
        tv.fontFor = { b, i in self.font(bold: b, italic: i) }
        tv.baseAttributes = [.font: font(bold: false, italic: false), .foregroundColor: baseColor, .paragraphStyle: paragraphStyle]
        tv.placeholder = placeholder
        // Solo se recarga si el valor cambió desde fuera (sincronización, cambio de nota) y no se está escribiendo.
        if value != context.coordinator.lastValue, tv.window?.firstResponder !== tv {
            load(into: tv, context: context)
            tv.invalidateIntrinsicContentSize()
        }
        if focus {
            DispatchQueue.main.async {
                guard let window = tv.window, window.firstResponder !== tv else { return }
                window.makeFirstResponder(tv)
                tv.setSelectedRange(NSRange(location: tv.string.utf16.count, length: 0))
            }
        }
    }

    func sizeThatFits(_ proposal: ProposedViewSize, nsView tv: BlockTextView, context: Context) -> CGSize? {
        guard let width = proposal.width, width.isFinite, width > 0,
              let content = tv.textStorage else { return nil }
        // Se mide sobre una copia: SwiftUI propone anchos de prueba y cambiar el contenedor de la
        // propia vista la dejaba con un ancho viejo (texto estrecho y alturas que se solapan).
        let storage = NSTextStorage(attributedString: content)
        let lm = NSLayoutManager()
        let container = NSTextContainer(size: NSSize(width: width, height: .greatestFiniteMagnitude))
        container.lineFragmentPadding = 0
        lm.addTextContainer(container)
        storage.addLayoutManager(lm)
        lm.ensureLayout(for: container)
        var height = lm.usedRect(for: container).height
        if tv.string.isEmpty || tv.string.hasSuffix("\n") {
            // Altura de la línea vacía (o de la última línea en blanco).
            let f = (tv.typingAttributes[.font] as? NSFont) ?? font(bold: false, italic: false)
            height = max(height, lm.defaultLineHeight(for: f))
        }
        return CGSize(width: width, height: ceil(height))
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: GrowingTextView
        var lastValue = ""
        init(_ parent: GrowingTextView) { self.parent = parent }

        func textDidChange(_ notification: Notification) {
            guard let tv = notification.object as? BlockTextView else { return }
            let value = parent.mode == .plain ? tv.string : InlineHTML.html(from: tv.attributedString())
            lastValue = value
            tv.invalidateIntrinsicContentSize()
            parent.onChange(value)
        }

        func textView(_ textView: NSTextView, clickedOnLink link: Any, at charIndex: Int) -> Bool {
            if let url = link as? URL { NSWorkspace.shared.open(url); return true }
            return false
        }
    }
}

/// NSTextView con formato propio (negrita/cursiva/subrayado vía atributos de InlineHTML),
/// pegado sin formato y borrado del bloque con Retroceso cuando está vacío.
final class BlockTextView: NSTextView {
    var isRich = true
    var placeholder = "" { didSet { if placeholder != oldValue { needsDisplay = true } } }
    var fontFor: (Bool, Bool) -> NSFont = { _, _ in .systemFont(ofSize: 14) }
    var baseAttributes: [NSAttributedString.Key: Any] = [:]
    var onBecomeFirstResponder: (() -> Void)?
    var onDeleteEmpty: (() -> Void)?

    override func becomeFirstResponder() -> Bool {
        let ok = super.becomeFirstResponder()
        if ok { onBecomeFirstResponder?(); needsDisplay = true }
        return ok
    }

    override func resignFirstResponder() -> Bool {
        needsDisplay = true
        return super.resignFirstResponder()
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        if string.isEmpty, !placeholder.isEmpty, window?.firstResponder === self {
            let font = (typingAttributes[.font] as? NSFont) ?? fontFor(false, false)
            (placeholder as NSString).draw(at: .zero, withAttributes: [.font: font, .foregroundColor: NSColor(hex: 0x555555)])
        }
    }

    override func paste(_ sender: Any?) { pasteAsPlainText(sender) }

    override func deleteBackward(_ sender: Any?) {
        if string.isEmpty, let onDeleteEmpty { onDeleteEmpty(); return }
        super.deleteBackward(sender)
    }

    override func didChangeText() {
        super.didChangeText()
        needsDisplay = true
    }

    // MARK: Formato

    @objc func mnToggleBold(_ sender: Any?) { toggle(InlineHTML.bold) }
    @objc func mnToggleItalic(_ sender: Any?) { toggle(InlineHTML.italic) }
    @objc func mnToggleUnderline(_ sender: Any?) { toggle(.underlineStyle) }

    private func isOn(_ key: NSAttributedString.Key, _ attrs: [NSAttributedString.Key: Any]) -> Bool {
        if key == .underlineStyle { return ((attrs[key] as? Int) ?? 0) != 0 }
        return (attrs[key] as? Bool) ?? false
    }

    private func toggle(_ key: NSAttributedString.Key) {
        guard isRich, let storage = textStorage else { return }
        let range = selectedRange()
        if range.length == 0 {
            var attrs = typingAttributes
            let on = !isOn(key, attrs)
            if key == .underlineStyle { attrs[key] = on ? NSUnderlineStyle.single.rawValue : nil } else { attrs[key] = on ? true : nil }
            attrs[.font] = fontFor(isOn(InlineHTML.bold, attrs), isOn(InlineHTML.italic, attrs))
            typingAttributes = attrs
            return
        }
        var allOn = true
        storage.enumerateAttributes(in: range) { attrs, _, stop in
            if !isOn(key, attrs) { allOn = false; stop.pointee = true }
        }
        guard shouldChangeText(in: range, replacementString: nil) else { return }
        storage.beginEditing()
        if allOn { storage.removeAttribute(key, range: range) }
        else { storage.addAttribute(key, value: key == .underlineStyle ? NSUnderlineStyle.single.rawValue : true, range: range) }
        storage.enumerateAttributes(in: range) { attrs, r, _ in
            storage.addAttribute(.font, value: fontFor(isOn(InlineHTML.bold, attrs), isOn(InlineHTML.italic, attrs)), range: r)
        }
        storage.endEditing()
        didChangeText()
    }

    override func validateUserInterfaceItem(_ item: NSValidatedUserInterfaceItem) -> Bool {
        switch item.action {
        case #selector(mnToggleBold(_:)), #selector(mnToggleItalic(_:)), #selector(mnToggleUnderline(_:)): return isRich
        default: return super.validateUserInterfaceItem(item)
        }
    }
}
