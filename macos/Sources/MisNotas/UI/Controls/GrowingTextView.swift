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
    var focusAtStart = false
    var onFocused: () -> Void = {}
    var onChange: (String) -> Void
    var onDeleteEmpty: (() -> Void)?
    /// Intro tras una línea `---`: recibe el HTML de antes y de después de esa línea.
    var onDivider: ((String, String) -> Void)?
    /// ↑ en la primera línea / ↓ en la última: salir al bloque anterior o siguiente.
    var onMoveUp: (() -> Void)?
    var onMoveDown: (() -> Void)?

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
        // Las acciones de deshacer del texto anterior ya no casan con el nuevo contenido.
        if let storage = tv.textStorage { tv.undoManager?.removeAllActions(withTarget: storage) }
        tv.textStorage?.setAttributedString(content)
        tv.typingAttributes = attrs
        tv.placeholder = placeholder
        context.coordinator.lastValue = value
    }

    func updateNSView(_ tv: BlockTextView, context: Context) {
        context.coordinator.parent = self
        tv.onBecomeFirstResponder = onFocused
        tv.onDeleteEmpty = onDeleteEmpty
        tv.onDivider = mode == .plain ? nil : onDivider
        tv.onMoveUp = onMoveUp
        tv.onMoveDown = onMoveDown
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
                tv.setSelectedRange(NSRange(location: focusAtStart ? 0 : tv.string.utf16.count, length: 0))
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

    static func dismantleNSView(_ tv: BlockTextView, coordinator: Coordinator) { coordinator.flush() }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: GrowingTextView
        var lastValue = ""
        init(_ parent: GrowingTextView) { self.parent = parent }

        private weak var pendingView: BlockTextView?
        private var pending: DispatchWorkItem?

        /// El guardado (HTML, base de datos, lista de notas) se agrupa: hacerlo en cada pulsación
        /// bloqueaba el hilo principal y el cursor iba por detrás del texto al escribir rápido.
        func textDidChange(_ notification: Notification) {
            guard let tv = notification.object as? BlockTextView else { return }
            tv.invalidateIntrinsicContentSize()
            pendingView = tv
            pending?.cancel()
            let work = DispatchWorkItem { [weak self] in self?.flush() }
            pending = work
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3, execute: work)
        }

        func textDidEndEditing(_ notification: Notification) { flush() }

        func flush() {
            pending?.cancel()
            pending = nil
            guard let tv = pendingView else { return }
            pendingView = nil
            let value = parent.mode == .plain ? tv.string : InlineHTML.html(from: tv.attributedString())
            guard value != lastValue else { return }
            lastValue = value
            parent.onChange(value)
        }

        func textView(_ textView: NSTextView, clickedOnLink link: Any, at charIndex: Int) -> Bool {
            if let url = link as? URL { NSWorkspace.shared.open(url); return true }
            return false
        }
    }
}

/// Copia al portapapeles lo que el usuario selecciona y avisa a la barra de estado del editor.
enum AutoCopy {
    static let notification = Notification.Name("mn.textCopied")

    static func copy(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        NotificationCenter.default.post(name: notification, object: nil)
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
    var onDivider: ((String, String) -> Void)?
    var onMoveUp: (() -> Void)?
    var onMoveDown: (() -> Void)?

    /// Oculta el puntero del ratón mientras se escribe; reaparece al moverlo.
    override func keyDown(with event: NSEvent) {
        if event.modifierFlags.intersection([.command, .control]).isEmpty { NSCursor.setHiddenUntilMouseMoves(true) }
        super.keyDown(with: event)
        // Selección con el teclado (⇧ + flechas).
        if event.modifierFlags.contains(.shift) { copySelectionToPasteboard() }
    }

    /// `mouseDown` retiene el control hasta soltar el botón: al volver, la selección ya está hecha.
    override func mouseDown(with event: NSEvent) {
        super.mouseDown(with: event)
        copySelectionToPasteboard()
    }

    /// Lo seleccionado se copia solo al portapapeles, como texto sin formato.
    private func copySelectionToPasteboard() {
        let range = selectedRange()
        guard range.length > 0 else { return }
        AutoCopy.copy((string as NSString).substring(with: range))
    }

    override func moveUp(_ sender: Any?) {
        if let onMoveUp, selectedRange().length == 0, caretLine().minY <= 0.5 { onMoveUp(); return }
        super.moveUp(sender)
    }

    override func moveDown(_ sender: Any?) {
        if let onMoveDown, selectedRange().length == 0, let lm = layoutManager, let tc = textContainer,
           caretLine().maxY >= lm.usedRect(for: tc).maxY - 0.5 { onMoveDown(); return }
        super.moveDown(sender)
    }

    /// Rectángulo de la línea donde está el cursor, en coordenadas del contenedor de texto.
    private func caretLine() -> NSRect {
        guard let lm = layoutManager, let tc = textContainer else { return .zero }
        lm.ensureLayout(for: tc)
        let text = string as NSString
        let loc = selectedRange().location
        if text.length == 0 { return lm.extraLineFragmentRect }
        if loc >= text.length, text.character(at: text.length - 1) == 0x0A { return lm.extraLineFragmentRect }
        let glyph = lm.glyphIndexForCharacter(at: min(loc, text.length - 1))
        return lm.lineFragmentRect(forGlyphAt: glyph, effectiveRange: nil)
    }

    /// El deshacer no retiene su destino: al quitar el bloque se borran sus acciones de texto
    /// para que ⌘Z no apunte a un texto que ya no existe.
    override func viewWillMove(toWindow newWindow: NSWindow?) {
        if newWindow == nil, let storage = textStorage { undoManager?.removeAllActions(withTarget: storage) }
        super.viewWillMove(toWindow: newWindow)
    }

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

    /// Intro al final de una línea que solo contiene `---` la convierte en una línea horizontal,
    /// como en Evernote. El texto de antes y de después se queda en párrafos aparte.
    override func insertNewline(_ sender: Any?) {
        let text = string as NSString
        let cursor = selectedRange()
        if let onDivider, cursor.length == 0 {
            let line = text.lineRange(for: NSRange(location: cursor.location, length: 0))
            var content = line
            if content.length > 0, text.character(at: NSMaxRange(content) - 1) == 0x0A { content.length -= 1 }
            if NSMaxRange(content) == cursor.location,
               text.substring(with: content).trimmingCharacters(in: .whitespaces) == "---" {
                let full = attributedString()
                let beforeEnd = max(0, content.location - 1) // sin el salto de línea anterior
                let before = InlineHTML.html(from: full.attributedSubstring(from: NSRange(location: 0, length: content.location == 0 ? 0 : beforeEnd)))
                let afterStart = NSMaxRange(line)
                let after = InlineHTML.html(from: full.attributedSubstring(from: NSRange(location: afterStart, length: text.length - afterStart)))
                // Suelta el foco para que el bloque recargue su texto (no se recarga mientras se escribe).
                window?.makeFirstResponder(nil)
                onDivider(before, after)
                return
            }
        }
        super.insertNewline(sender)
    }

    /// Parte el texto por el cursor (o la selección) para insertar un bloque en medio. Quita los saltos de
    /// línea pegados al corte y suelta el foco para que el bloque recargue su contenido. Solo en texto enriquecido.
    func splitAtCaret() -> (before: String, after: String)? {
        guard isRich else { return nil }
        let text = string as NSString
        let sel = selectedRange()
        var end = sel.location
        while end > 0, text.character(at: end - 1) == 0x0A { end -= 1 }
        var start = NSMaxRange(sel)
        while start < text.length, text.character(at: start) == 0x0A { start += 1 }
        let full = attributedString()
        let before = InlineHTML.html(from: full.attributedSubstring(from: NSRange(location: 0, length: end)))
        let after = InlineHTML.html(from: full.attributedSubstring(from: NSRange(location: start, length: text.length - start)))
        window?.makeFirstResponder(nil)
        return (before, after)
    }

    /// El interlineado se suma a la altura de la línea y alargaba el cursor: se ajusta a la altura de la letra.
    override func drawInsertionPoint(in rect: NSRect, color: NSColor, turnedOn flag: Bool) {
        var r = rect
        if let font = typingAttributes[.font] as? NSFont {
            let height = ceil(font.ascender - font.descender)
            if height < r.height { r.size.height = height }
        }
        super.drawInsertionPoint(in: r, color: color, turnedOn: flag)
    }

    override func didChangeText() {
        super.didChangeText()
        needsDisplay = true
    }

    // MARK: Formato

    @objc func mnToggleBold(_ sender: Any?) { toggle(InlineHTML.bold) }
    @objc func mnToggleItalic(_ sender: Any?) { toggle(InlineHTML.italic) }
    @objc func mnToggleUnderline(_ sender: Any?) { toggle(.underlineStyle) }

    /// Enlace dentro del texto: convierte la selección en enlace (o edita el enlace bajo el cursor).
    /// Con una dirección vacía quita el enlace.
    @objc func mnLink(_ sender: Any?) {
        guard isRich, let storage = textStorage, window != nil else { return }
        var range = selectedRange()
        var current: String?
        let probe = range.length > 0 ? range.location : max(0, range.location - 1)
        if storage.length > 0, probe < storage.length {
            var linkRange = NSRange()
            if let value = storage.attribute(.link, at: probe, longestEffectiveRange: &linkRange,
                                             in: NSRange(location: 0, length: storage.length)) {
                current = (value as? URL)?.absoluteString ?? value as? String
                if range.length == 0 { range = linkRange }
            }
        }
        let selectedText = range.length > 0 ? (string as NSString).substring(with: range) : ""

        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
        field.placeholderString = "https://…"
        field.stringValue = current ?? ""
        let alert = NSAlert()
        alert.messageText = current == nil ? "Añadir enlace" : "Editar enlace"
        alert.informativeText = range.length > 0 ? "Dirección para «\(selectedText.prefix(40))»"
            : "Dirección del enlace (se insertará como texto)"
        alert.accessoryView = field
        alert.addButton(withTitle: "Aceptar")
        alert.addButton(withTitle: "Cancelar")
        alert.window.initialFirstResponder = field
        guard alert.runModal() == .alertFirstButtonReturn else { window?.makeFirstResponder(self); return }
        window?.makeFirstResponder(self)

        var address = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        if !address.isEmpty, !address.contains("://"), !address.lowercased().hasPrefix("mailto:") { address = "https://" + address }
        let url = address.isEmpty ? nil : URL(string: address)
        if !address.isEmpty, url == nil { NSSound.beep(); return }

        if range.length == 0 {
            // Sin selección: se inserta la propia dirección como texto del enlace.
            guard let url else { return }
            insertText(url.absoluteString, replacementRange: range)
            range = NSRange(location: range.location, length: (url.absoluteString as NSString).length)
        }
        guard shouldChangeText(in: range, replacementString: nil) else { return }
        storage.beginEditing()
        if let url {
            storage.addAttribute(.link, value: url, range: range)
            storage.addAttribute(.foregroundColor, value: GrowingTextView.linkColor, range: range)
        } else {
            storage.removeAttribute(.link, range: range)
            storage.addAttribute(.foregroundColor, value: baseAttributes[.foregroundColor] ?? NSColor.white, range: range)
        }
        storage.endEditing()
        didChangeText()
        setSelectedRange(NSRange(location: NSMaxRange(range), length: 0))
        typingAttributes[.link] = nil
        if let color = baseAttributes[.foregroundColor] { typingAttributes[.foregroundColor] = color }
    }

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
        case #selector(mnToggleBold(_:)), #selector(mnToggleItalic(_:)), #selector(mnToggleUnderline(_:)), #selector(mnLink(_:)): return isRich
        default: return super.validateUserInterfaceItem(item)
        }
    }
}
