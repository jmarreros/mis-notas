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
        f.placeholderAttributedString = NSAttributedString(string: placeholder, attributes: [
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
