import AppKit
import SwiftUI

/// `NSTextField` de una línea con control de Intro, Retroceso en vacío y Esc, que SwiftUI
/// no ofrece de forma fiable en macOS. Se usa en el título, las tareas, las etiquetas y los enlaces.
struct KeyTextField: NSViewRepresentable {
    var text: String
    var placeholder = ""
    var font: NSFont
    var color: NSColor = .white
    var strikethrough = false
    var focus = false
    var onFocused: () -> Void = {}
    var onChange: (String) -> Void
    var onSubmit: (() -> Void)?
    var onDeleteEmpty: (() -> Void)?
    var onEscape: (() -> Void)?
    var onEndEditing: (() -> Void)?

    final class Field: NSTextField {
        override class var cellClass: AnyClass? {
            get { Cell.self }
            set {}
        }

        var onBecomeFirstResponder: (() -> Void)?
        override func becomeFirstResponder() -> Bool {
            let ok = super.becomeFirstResponder()
            if ok {
                (currentEditor() as? NSTextView)?.insertionPointColor = .white
                onBecomeFirstResponder?()
            }
            return ok
        }
    }

    /// `NSTextFieldCell` coloca la línea base de Barlow Condensed más arriba que el editor de texto y
    /// recorta la parte superior del texto y del placeholder. Se dibuja con el sistema de texto, igual
    /// que el editor, para que coincidan.
    /// El placeholder se guarda aquí y no en `placeholderAttributedString`: si no, el editor de campo
    /// dibuja también el suyo, desplazado, mientras se edita.
    final class Cell: NSTextFieldCell {
        var placeholder: NSAttributedString?

        override func drawInterior(withFrame cellFrame: NSRect, in controlView: NSView) {
            let editor = (controlView as? NSTextField)?.currentEditor()
            let isEmpty = editor.map { $0.string.isEmpty } ?? stringValue.isEmpty
            if editor != nil && !isEmpty { return } // el editor dibuja el texto
            let source = isEmpty ? (placeholder ?? NSAttributedString()) : attributedStringValue
            guard source.length > 0 else { return }
            let s = NSMutableAttributedString(attributedString: source)
            let style = NSMutableParagraphStyle()
            style.lineBreakMode = .byTruncatingTail
            s.addAttribute(.paragraphStyle, value: style, range: NSRange(location: 0, length: s.length))
            s.draw(with: titleRect(forBounds: cellFrame), options: [.usesLineFragmentOrigin, .truncatesLastVisibleLine])
        }
    }

    /// La altura la marca la fuente (no el contenedor), para que el texto y el cursor no se recorten.
    func sizeThatFits(_ proposal: ProposedViewSize, nsView f: Field, context: Context) -> CGSize? {
        let height = ceil(f.cell?.cellSize.height ?? f.intrinsicContentSize.height)
        let width = proposal.width.flatMap { $0.isFinite ? $0 : nil } ?? f.intrinsicContentSize.width
        return CGSize(width: width, height: height)
    }

    func makeNSView(context: Context) -> Field {
        let f = Field()
        f.isBordered = false
        f.drawsBackground = false
        f.focusRingType = .none
        f.usesSingleLineMode = true
        f.cell?.isScrollable = true
        f.cell?.wraps = false
        f.lineBreakMode = .byTruncatingTail
        f.delegate = context.coordinator
        f.setContentHuggingPriority(.defaultLow, for: .horizontal)
        f.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        return f
    }

    func updateNSView(_ f: Field, context: Context) {
        context.coordinator.parent = self
        f.onBecomeFirstResponder = onFocused
        f.isEditable = context.environment.isEnabled
        f.font = font
        f.textColor = color
        (f.cell as? Cell)?.placeholder = NSAttributedString(string: placeholder, attributes: [
            .font: font, .foregroundColor: NSColor(hex: 0x666666),
        ])
        let editing = f.currentEditor() != nil
        if !editing {
            if strikethrough {
                f.attributedStringValue = NSAttributedString(string: text, attributes: [
                    .font: font, .foregroundColor: color, .strikethroughStyle: NSUnderlineStyle.single.rawValue,
                ])
            } else if f.stringValue != text || Self.hasStrikethrough(f.attributedStringValue) {
                f.stringValue = text
            }
        } else if f.stringValue != text {
            f.stringValue = text
        }
        if focus {
            DispatchQueue.main.async {
                guard let window = f.window, f.currentEditor() == nil else { return }
                window.makeFirstResponder(f)
                f.currentEditor()?.selectedRange = NSRange(location: f.stringValue.utf16.count, length: 0)
            }
        }
    }

    /// Un texto vacío no tiene atributos: preguntar por el índice 0 lanzaría una excepción.
    private static func hasStrikethrough(_ s: NSAttributedString) -> Bool {
        s.length > 0 && s.attribute(.strikethroughStyle, at: 0, effectiveRange: nil) != nil
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    final class Coordinator: NSObject, NSTextFieldDelegate {
        var parent: KeyTextField
        init(_ parent: KeyTextField) { self.parent = parent }

        func controlTextDidChange(_ obj: Notification) {
            guard let f = obj.object as? NSTextField else { return }
            f.needsDisplay = true // muestra u oculta el placeholder que dibuja `Cell`
            parent.onChange(f.stringValue)
        }

        func controlTextDidEndEditing(_ obj: Notification) {
            parent.onEndEditing?()
        }

        func control(_ control: NSControl, textView: NSTextView, doCommandBy sel: Selector) -> Bool {
            switch sel {
            case #selector(NSResponder.insertNewline(_:)):
                guard let submit = parent.onSubmit else { return false }
                submit()
                return true
            case #selector(NSResponder.deleteBackward(_:)):
                guard textView.string.isEmpty, let del = parent.onDeleteEmpty else { return false }
                del()
                return true
            case #selector(NSResponder.cancelOperation(_:)):
                guard let esc = parent.onEscape else { return false }
                esc()
                return true
            default:
                return false
            }
        }
    }
}
