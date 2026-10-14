import AppKit

/// Conversión entre el subconjunto de HTML de los párrafos (`<b> <i> <u> <a href> <br>`)
/// y `NSAttributedString`. El formato se guarda en atributos propios (no en la fuente) para
/// que no dependa de que la tipografía tenga variante negrita o cursiva.
public enum InlineHTML {
    public static let bold = NSAttributedString.Key("mn.bold")
    public static let italic = NSAttributedString.Key("mn.italic")

    public struct Style: Equatable {
        public var bold = false
        public var italic = false
        public var underline = false
        public var link: String?
        public init(bold: Bool = false, italic: Bool = false, underline: Bool = false, link: String? = nil) {
            self.bold = bold; self.italic = italic; self.underline = underline; self.link = link
        }
    }

    public struct Run: Equatable {
        public var text: String
        public var style: Style
    }

    // MARK: - Lectura

    /// Interpreta el HTML en tramos de texto con estilo. Las etiquetas desconocidas se ignoran
    /// (su texto se conserva); `<div>`/`<p>` y `<br>` se convierten en saltos de línea.
    public static func parse(_ html: String) -> [Run] {
        var runs: [Run] = []
        var style = Style()
        var stack: [(tag: String, prev: Style)] = []
        var text = ""

        func flush() {
            guard !text.isEmpty else { return }
            let decoded = decodeEntities(text)
            if let last = runs.last, last.style == style { runs[runs.count - 1].text += decoded }
            else { runs.append(Run(text: decoded, style: style)) }
            text = ""
        }
        func newline() {
            flush()
            if let last = runs.last, last.style == style { runs[runs.count - 1].text += "\n" }
            else { runs.append(Run(text: "\n", style: style)) }
        }

        var i = html.startIndex
        while i < html.endIndex {
            let c = html[i]
            guard c == "<", let close = html[i...].firstIndex(of: ">") else {
                // Los saltos de línea literales del HTML equivalen a espacios.
                text.append(c == "\n" || c == "\r" ? " " : c)
                i = html.index(after: i)
                continue
            }
            let raw = String(html[html.index(after: i)..<close])
            i = html.index(after: close)
            let closing = raw.hasPrefix("/")
            let body = closing ? String(raw.dropFirst()) : raw
            let name = body.split(whereSeparator: { $0 == " " || $0 == "/" || $0 == "\t" }).first.map { $0.lowercased() } ?? ""

            switch name {
            case "br":
                newline()
            case "div", "p":
                // Un bloque separa líneas, salvo al principio o justo después de otro salto.
                let atLineStart = text.isEmpty && (runs.last.map { $0.text.hasSuffix("\n") } ?? true)
                if !atLineStart { newline() }
            case "b", "strong", "i", "em", "u", "a":
                flush()
                if closing {
                    if let idx = stack.lastIndex(where: { $0.tag == name }) {
                        style = stack[idx].prev
                        stack.removeSubrange(idx...)
                    }
                } else {
                    stack.append((name, style))
                    switch name {
                    case "b", "strong": style.bold = true
                    case "i", "em": style.italic = true
                    case "u": style.underline = true
                    default: style.link = attribute("href", in: body).map(decodeEntities)
                    }
                }
            default:
                break
            }
        }
        flush()
        // Quita el salto final que deja un `</div>` de cierre.
        if let last = runs.last, last.text.hasSuffix("\n") {
            runs[runs.count - 1].text.removeLast()
            if runs[runs.count - 1].text.isEmpty { runs.removeLast() }
        }
        return runs
    }

    public static func plainText(_ html: String) -> String {
        parse(html).map(\.text).joined()
            .replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespaces)
    }

    public static func attributedString(_ html: String, font: (_ bold: Bool, _ italic: Bool) -> NSFont,
                                        color: NSColor, linkColor: NSColor) -> NSAttributedString {
        let out = NSMutableAttributedString()
        for run in parse(html) {
            out.append(NSAttributedString(string: run.text,
                                          attributes: attributes(for: run.style, font: font, color: color, linkColor: linkColor)))
        }
        return out
    }

    public static func attributes(for style: Style, font: (Bool, Bool) -> NSFont,
                                  color: NSColor, linkColor: NSColor) -> [NSAttributedString.Key: Any] {
        var a: [NSAttributedString.Key: Any] = [.font: font(style.bold, style.italic), .foregroundColor: color]
        if style.bold { a[bold] = true }
        if style.italic { a[italic] = true }
        if style.underline { a[.underlineStyle] = NSUnderlineStyle.single.rawValue }
        if let link = style.link, let url = URL(string: link) {
            a[.link] = url
            a[.foregroundColor] = linkColor
        }
        return a
    }

    // MARK: - Escritura

    public static func html(from attributed: NSAttributedString) -> String {
        var out = ""
        var open = Style()
        func closeAll() {
            if open.link != nil { out += "</a>" }
            if open.underline { out += "</u>" }
            if open.italic { out += "</i>" }
            if open.bold { out += "</b>" }
            open = Style()
        }
        attributed.enumerateAttributes(in: NSRange(location: 0, length: attributed.length)) { attrs, range, _ in
            let s = style(of: attrs)
            if s != open {
                closeAll()
                if s.bold { out += "<b>" }
                if s.italic { out += "<i>" }
                if s.underline { out += "<u>" }
                if let link = s.link { out += "<a href=\"\(escape(link))\">" }
                open = s
            }
            let text = (attributed.string as NSString).substring(with: range)
            out += escape(text).replacingOccurrences(of: "\n", with: "<br>")
        }
        closeAll()
        return out
    }

    public static func style(of attrs: [NSAttributedString.Key: Any]) -> Style {
        var s = Style()
        s.bold = attrs[bold] as? Bool ?? false
        s.italic = attrs[italic] as? Bool ?? false
        s.underline = ((attrs[.underlineStyle] as? Int) ?? 0) != 0
        if let url = attrs[.link] as? URL { s.link = url.absoluteString }
        else if let str = attrs[.link] as? String { s.link = str }
        return s
    }

    // MARK: - Utilidades

    static func attribute(_ name: String, in tag: String) -> String? {
        guard let r = tag.range(of: name + "=", options: .caseInsensitive) else { return nil }
        let rest = tag[r.upperBound...]
        guard let q = rest.first else { return nil }
        if q == "\"" || q == "'" {
            let after = rest.dropFirst()
            return after.firstIndex(of: q).map { String(after[..<$0]) }
        }
        return String(rest.prefix { !$0.isWhitespace && $0 != ">" })
    }

    public static func escape(_ s: String) -> String {
        s.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
            .replacingOccurrences(of: "\"", with: "&quot;")
    }

    public static func decodeEntities(_ s: String) -> String {
        guard s.contains("&") else { return s }
        var out = ""
        var i = s.startIndex
        while i < s.endIndex {
            if s[i] == "&", let semi = s[i...].prefix(10).firstIndex(of: ";") {
                let entity = String(s[s.index(after: i)..<semi])
                if let ch = decodeEntity(entity) {
                    out.append(ch)
                    i = s.index(after: semi)
                    continue
                }
            }
            out.append(s[i])
            i = s.index(after: i)
        }
        return out
    }

    private static func decodeEntity(_ e: String) -> Character? {
        switch e {
        case "amp": return "&"
        case "lt": return "<"
        case "gt": return ">"
        case "quot": return "\""
        case "apos", "#39": return "'"
        case "nbsp": return " "
        default:
            if e.hasPrefix("#x") || e.hasPrefix("#X"), let v = UInt32(e.dropFirst(2), radix: 16), let u = Unicode.Scalar(v) { return Character(u) }
            if e.hasPrefix("#"), let v = UInt32(e.dropFirst()), let u = Unicode.Scalar(v) { return Character(u) }
            return nil
        }
    }
}
