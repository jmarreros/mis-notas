import Foundation

public struct EnexNote: Equatable {
    public var title: String
    public var created: Millis?
    public var updated: Millis?
    public var tags: [String]
    public var blocks: [Block]
}

/// Lee un archivo .enex exportado de Evernote. Solo conserva texto: los recursos
/// (imágenes y adjuntos) se descartan.
public final class EnexParser: NSObject, XMLParserDelegate {
    private var notes: [EnexNote] = []
    private var current: (title: String, created: String, updated: String, tags: [String], content: String)?
    private var element = ""
    private var buffer = ""
    private var depthInResource = 0

    public static func parse(url: URL) throws -> [EnexNote] {
        guard let parser = XMLParser(contentsOf: url) else { throw CocoaError(.fileReadCorruptFile) }
        return try run(parser)
    }

    public static func parse(data: Data) throws -> [EnexNote] {
        try run(XMLParser(data: data))
    }

    private static func run(_ parser: XMLParser) throws -> [EnexNote] {
        let delegate = EnexParser()
        parser.delegate = delegate
        parser.shouldResolveExternalEntities = false
        guard parser.parse() else { throw parser.parserError ?? CocoaError(.fileReadCorruptFile) }
        return delegate.notes
    }

    public func parser(_ parser: XMLParser, didStartElement name: String, namespaceURI: String?,
                       qualifiedName: String?, attributes: [String: String] = [:]) {
        if name == "resource" { depthInResource += 1 }
        guard depthInResource == 0 else { return }
        if name == "note" { current = ("", "", "", [], "") }
        element = name
        buffer = ""
    }

    public func parser(_ parser: XMLParser, foundCharacters string: String) {
        guard depthInResource == 0, current != nil else { return }
        buffer += string
    }

    public func parser(_ parser: XMLParser, foundCDATA data: Data) {
        guard depthInResource == 0, current != nil else { return }
        buffer += String(decoding: data, as: UTF8.self)
    }

    public func parser(_ parser: XMLParser, didEndElement name: String, namespaceURI: String?, qualifiedName: String?) {
        if name == "resource" { depthInResource -= 1; return }
        guard depthInResource == 0, current != nil else { return }
        let text = buffer.trimmingCharacters(in: .whitespacesAndNewlines)
        switch name {
        case "title" where element == "title": current?.title = text
        case "created": current?.created = text
        case "updated": current?.updated = text
        case "tag": if !text.isEmpty { current?.tags.append(text) }
        case "content": current?.content = buffer
        case "note":
            if let c = current {
                notes.append(EnexNote(title: c.title, created: Self.date(c.created), updated: Self.date(c.updated),
                                      tags: c.tags, blocks: ENMLConverter.blocks(from: c.content)))
            }
            current = nil
        default: break
        }
        buffer = ""
    }

    private static let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyyMMdd'T'HHmmss'Z'"
        return f
    }()

    static func date(_ s: String) -> Millis? {
        guard !s.isEmpty else { return nil }
        return dateFormatter.date(from: s).map { Millis($0.timeIntervalSince1970 * 1000) }
    }
}

/// Convierte ENML (el XHTML de Evernote) en bloques: líneas consecutivas → un párrafo,
/// `en-todo` y listas de tareas → bloque de tareas, `h1…h6` → encabezado,
/// bloques de código y `<pre>` → código. Negrita, cursiva, subrayado y enlaces se conservan.
public struct ENMLConverter {
    private enum Mode { case normal, heading, code(preserveSpaces: Bool), skip }

    private var blocks: [Block] = []
    private var para = ""
    private var atLineStart = true
    private var todoItems: [TodoItem] = []
    private var currentTodo: TodoItem?
    private var mode = Mode.normal
    private var modeTag = ""
    private var modeDepth = 0
    private var buffer = ""
    private var lists: [(todo: Bool, ordered: Bool, counter: Int)] = []
    private var cellIndex = 0

    private static let blockTags: Set<String> = ["div", "p", "blockquote", "tr", "table", "ul", "ol", "en-note", "section", "article", "center", "dl", "dt", "dd", "hr"]

    public static func blocks(from enml: String) -> [Block] {
        var c = ENMLConverter()
        for token in HTMLTokenizer.tokens(enml) { c.handle(token) }
        c.flushTodo()
        c.flushParagraph()
        return c.blocks.isEmpty ? [.paragraph()] : c.blocks
    }

    private mutating func handle(_ token: HTMLTokenizer.Token) {
        switch mode {
        case .skip:
            if case let .open(name, _, selfClosing) = token, name == modeTag, !selfClosing { modeDepth += 1 }
            if case let .close(name) = token, name == modeTag {
                modeDepth -= 1
                if modeDepth == 0 { mode = .normal }
            }
            return
        case .heading:
            switch token {
            case let .text(t): buffer += t
            case let .close(name) where name == modeTag:
                let text = buffer.collapsingWhitespace.trimmingCharacters(in: .whitespaces)
                if !text.isEmpty { blocks.append(.heading(InlineHTML.escape(text))) }
                mode = .normal
                atLineStart = true
            default: break
            }
            return
        case let .code(preserve):
            switch token {
            case let .text(t): buffer += preserve ? t : t.replacingOccurrences(of: "\n", with: "")
            case let .open(name, _, selfClosing):
                if name == "br" { buffer += "\n" }
                else if Self.blockTags.contains(name) || name == "pre" {
                    if !buffer.isEmpty && !buffer.hasSuffix("\n") { buffer += "\n" }
                    if name == modeTag && !selfClosing { modeDepth += 1 }
                }
            case let .close(name):
                if name == modeTag {
                    modeDepth -= 1
                    if modeDepth == 0 {
                        let text = buffer.trimmingCharacters(in: .newlines)
                        if !text.isEmpty { blocks.append(.code(text)) }
                        mode = .normal
                        atLineStart = true
                        return
                    }
                }
                if Self.blockTags.contains(name), !buffer.isEmpty, !buffer.hasSuffix("\n") { buffer += "\n" }
            }
            return
        case .normal:
            break
        }

        switch token {
        case let .text(t):
            appendText(t)

        case let .open(name, attrs, selfClosing):
            let style = attrs["style"] ?? ""
            switch name {
            case "br":
                hardBreak()
            case "h1", "h2", "h3", "h4", "h5", "h6":
                flushTodo(); flushParagraph()
                mode = .heading; modeTag = name; buffer = ""
            case "pre":
                flushTodo(); flushParagraph()
                mode = .code(preserveSpaces: true); modeTag = name; modeDepth = 1; buffer = ""
            case "div" where style.contains("-en-codeblock"):
                flushTodo(); flushParagraph()
                mode = .code(preserveSpaces: false); modeTag = name; modeDepth = selfClosing ? 0 : 1; buffer = ""
            case "en-crypt", "style", "script", "title", "head":
                if !selfClosing { mode = .skip; modeTag = name; modeDepth = 1 }
            case "en-todo":
                softBreak()
                flushParagraph()
                currentTodo = TodoItem(t: "", done: attrs["checked"] == "true")
            case "ul", "ol":
                softBreak()
                lists.append((todo: style.contains("--en-todo:true"), ordered: name == "ol", counter: 0))
            case "li":
                softBreak()
                guard !lists.isEmpty else { break }
                if lists[lists.count - 1].todo {
                    flushParagraph()
                    currentTodo = TodoItem(t: "", done: style.contains("--en-checked:true"))
                } else {
                    lists[lists.count - 1].counter += 1
                    let indent = String(repeating: "    ", count: lists.count - 1)
                    let marker = lists[lists.count - 1].ordered ? "\(lists[lists.count - 1].counter). " : "• "
                    // El marcador no cuenta como contenido: el <div> interior no debe saltar de línea.
                    flushTodo()
                    para += InlineHTML.escape(indent + marker)
                }
            case "hr":
                flushTodo(); flushParagraph()
                blocks.append(.divider())
            case "td", "th":
                if cellIndex > 0 { appendText(" | ") }
                cellIndex += 1
            case "tr":
                softBreak()
                cellIndex = 0
            case "b", "strong", "i", "em", "u":
                if currentTodo == nil { appendRaw("<\(Self.inlineTag(name))>") }
            case "a":
                if currentTodo == nil, let href = attrs["href"], !href.isEmpty {
                    appendRaw("<a href=\"\(InlineHTML.escape(href))\">")
                }
            default:
                if Self.blockTags.contains(name) { softBreak() }
            }

        case let .close(name):
            switch name {
            case "ul", "ol":
                softBreak()
                if !lists.isEmpty { lists.removeLast() }
            case "li":
                softBreak()
            case "b", "strong", "i", "em", "u":
                if currentTodo == nil { appendRaw("</\(Self.inlineTag(name))>") }
            case "a":
                if currentTodo == nil { appendRaw("</a>") }
            default:
                if Self.blockTags.contains(name) { softBreak() }
            }
        }
    }

    private static func inlineTag(_ name: String) -> String {
        switch name {
        case "strong": return "b"
        case "em": return "i"
        default: return name
        }
    }

    private mutating func appendText(_ raw: String) {
        var t = raw.collapsingWhitespace
        if atLineStart { t = String(t.drop(while: { $0 == " " })) }
        guard !t.isEmpty else { return }
        if currentTodo != nil {
            currentTodo!.t += t
        } else {
            flushTodo()
            para += InlineHTML.escape(t)
        }
        atLineStart = false
    }

    private mutating func appendRaw(_ html: String) {
        flushTodo()
        para += html
        if !html.hasPrefix("<") { atLineStart = false }
    }

    /// Fin de un elemento de bloque: salta de línea si no se está ya al principio de una.
    private mutating func softBreak() {
        if let item = currentTodo {
            // Una tarea aún sin texto sigue abierta (p. ej. el <div> dentro de un <li> de tareas).
            guard !item.t.trimmingCharacters(in: .whitespaces).isEmpty else { return }
            var item = item
            item.t = item.t.trimmingCharacters(in: .whitespaces)
            todoItems.append(item)
            currentTodo = nil
            atLineStart = true
            return
        }
        guard !atLineStart else { return }
        para += "<br>"
        atLineStart = true
    }

    private mutating func hardBreak() {
        if currentTodo != nil { softBreak(); return }
        if !para.isEmpty { para += "<br>" }
        atLineStart = true
    }

    private mutating func flushTodo() {
        if currentTodo != nil { softBreak() }
        guard !todoItems.isEmpty else { return }
        flushParagraph()
        blocks.append(.todo(todoItems))
        todoItems = []
    }

    private mutating func flushParagraph() {
        var html = para
        while html.hasSuffix("<br>") { html.removeLast(4) }
        while html.hasPrefix("<br>") { html.removeFirst(4) }
        para = ""
        atLineStart = true
        guard !InlineHTML.plainText(html).trimmingCharacters(in: .whitespaces).isEmpty else { return }
        // Los todo pendientes van antes que este párrafo.
        if !todoItems.isEmpty {
            blocks.append(.todo(todoItems))
            todoItems = []
        }
        blocks.append(.paragraph(html))
    }
}

/// Tokenizador tolerante de HTML/XHTML: suficiente para ENML y el HTML de los párrafos.
public enum HTMLTokenizer {
    public enum Token: Equatable {
        case open(String, [String: String], selfClosing: Bool)
        case close(String)
        case text(String)
    }

    public static func tokens(_ s: String) -> [Token] {
        var out: [Token] = []
        var i = s.startIndex
        var text = ""
        func flush() {
            if !text.isEmpty { out.append(.text(InlineHTML.decodeEntities(text))); text = "" }
        }
        while i < s.endIndex {
            guard s[i] == "<" else { text.append(s[i]); i = s.index(after: i); continue }
            let rest = s[i...]
            if rest.hasPrefix("<!--") {
                flush()
                i = rest.range(of: "-->")?.upperBound ?? s.endIndex
                continue
            }
            if rest.hasPrefix("<![CDATA[") {
                flush()
                let start = s.index(i, offsetBy: 9)
                let end = s[start...].range(of: "]]>")
                out.append(.text(String(s[start..<(end?.lowerBound ?? s.endIndex)])))
                i = end?.upperBound ?? s.endIndex
                continue
            }
            guard let close = rest.firstIndex(of: ">") else { text.append(contentsOf: rest); break }
            let inner = s[s.index(after: i)..<close]
            i = s.index(after: close)
            if inner.hasPrefix("!") || inner.hasPrefix("?") { continue }   // DOCTYPE, <?xml ?>
            flush()
            if inner.hasPrefix("/") {
                out.append(.close(inner.dropFirst().trimmingCharacters(in: .whitespaces).lowercased()))
                continue
            }
            let selfClosing = inner.hasSuffix("/")
            let body = selfClosing ? inner.dropLast() : inner
            let name = body.prefix { !$0.isWhitespace && $0 != "/" }.lowercased()
            guard !name.isEmpty else { continue }
            out.append(.open(name, attributes(String(body.dropFirst(name.count))), selfClosing: selfClosing))
        }
        flush()
        return out
    }

    static func attributes(_ s: String) -> [String: String] {
        var attrs: [String: String] = [:]
        var i = s.startIndex
        func skipSpaces() { while i < s.endIndex, s[i].isWhitespace { i = s.index(after: i) } }
        while i < s.endIndex {
            skipSpaces()
            let nameStart = i
            while i < s.endIndex, !s[i].isWhitespace, s[i] != "=" { i = s.index(after: i) }
            let name = s[nameStart..<i].lowercased()
            skipSpaces()
            guard i < s.endIndex, s[i] == "=" else {
                if !name.isEmpty { attrs[name] = "" }
                continue
            }
            i = s.index(after: i)
            skipSpaces()
            guard i < s.endIndex else { break }
            let q = s[i]
            var value = ""
            if q == "\"" || q == "'" {
                i = s.index(after: i)
                let start = i
                while i < s.endIndex, s[i] != q { i = s.index(after: i) }
                value = String(s[start..<i])
                if i < s.endIndex { i = s.index(after: i) }
            } else {
                let start = i
                while i < s.endIndex, !s[i].isWhitespace { i = s.index(after: i) }
                value = String(s[start..<i])
            }
            if !name.isEmpty { attrs[name] = InlineHTML.decodeEntities(value) }
        }
        return attrs
    }
}

extension String {
    /// Espacios en blanco consecutivos (incluidos saltos de línea) → un espacio, como en HTML.
    /// `&nbsp;` ya decodificado se conserva.
    var collapsingWhitespace: String {
        var out = ""
        var lastSpace = false
        for ch in self {
            if ch == " " || ch == "\n" || ch == "\t" || ch == "\r" {
                if !lastSpace { out.append(" ") }
                lastSpace = true
            } else {
                out.append(ch == "\u{00A0}" ? " " : ch)
                lastSpace = false
            }
        }
        return out
    }
}
