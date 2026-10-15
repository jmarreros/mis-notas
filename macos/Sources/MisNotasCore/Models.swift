import Foundation
import GRDB

/// Milisegundos desde epoch: el formato de fechas que se comparte con la API.
public typealias Millis = Int64

public extension Millis {
    static var now: Millis { Millis(Date().timeIntervalSince1970 * 1000) }
    var date: Date { Date(timeIntervalSince1970: TimeInterval(self) / 1000) }
}

public func newID() -> String { UUID().uuidString.lowercased() }

public struct TodoItem: Codable, Equatable, Hashable {
    public var t: String
    public var done: Bool

    public init(t: String, done: Bool = false) {
        self.t = t
        self.done = done
    }

    enum CodingKeys: String, CodingKey { case t, done }

    /// Tolerante: registros antiguos del servidor guardaron las cadenas vacías como null.
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        t = try c.decodeIfPresent(String.self, forKey: .t) ?? ""
        done = try c.decodeIfPresent(Bool.self, forKey: .done) ?? false
    }
}

/// Un bloque de contenido. Estructura plana con campos opcionales según el tipo,
/// idéntica al JSON que guarda la API.
public struct Block: Codable, Equatable, Identifiable, Hashable {
    public enum Kind: String, Codable { case p, h, todo, code, link, img, hr }

    public var id: String
    public var type: Kind
    public var html: String?          // p, h
    public var items: [TodoItem]?     // todo
    public var lang: String?          // code
    public var text: String?          // code
    public var title: String?         // link
    public var url: String?           // link
    public var attachmentId: String?  // img
    public var caption: String?       // img
    public var width: Double?         // img: ancho en puntos (nil = ajustado al editor)

    public init(id: String = newID(), type: Kind, html: String? = nil, items: [TodoItem]? = nil,
                lang: String? = nil, text: String? = nil, title: String? = nil, url: String? = nil,
                attachmentId: String? = nil, caption: String? = nil, width: Double? = nil) {
        self.id = id; self.type = type; self.html = html; self.items = items; self.lang = lang
        self.text = text; self.title = title; self.url = url; self.attachmentId = attachmentId; self.caption = caption; self.width = width
    }

    public static func paragraph(_ html: String = "") -> Block { Block(type: .p, html: html) }
    public static func heading(_ html: String = "") -> Block { Block(type: .h, html: html) }
    public static func todo(_ items: [TodoItem] = [TodoItem(t: "")]) -> Block { Block(type: .todo, items: items) }
    public static func code(_ text: String = "", lang: String = "CÓDIGO") -> Block { Block(type: .code, lang: lang, text: text) }
    public static func link(url: String = "", title: String = "Nuevo enlace") -> Block { Block(type: .link, title: title, url: url) }
    public static func divider() -> Block { Block(type: .hr) }
    public static func image(attachmentId: String, caption: String = "") -> Block { Block(type: .img, attachmentId: attachmentId, caption: caption) }

    public var isText: Bool { type == .p || type == .h }

    public var plainText: String {
        switch type {
        case .p, .h: return InlineHTML.plainText(html ?? "")
        case .todo: return (items ?? []).map(\.t).joined(separator: " ")
        case .code: return text ?? ""
        case .link: return [title, url].compactMap { $0 }.joined(separator: " ")
        case .img: return caption ?? ""
        case .hr: return ""
        }
    }
}

public struct Notebook: Codable, Equatable, Identifiable, Hashable, FetchableRecord, PersistableRecord {
    public var id: String
    public var name: String
    public var sort: Int
    public var createdAt: Millis
    public var updatedAt: Millis
    public var deletedAt: Millis?
    /// Cambio local pendiente de enviar al servidor.
    public var dirty: Bool

    public static let databaseTableName = "notebook"

    public init(id: String = newID(), name: String, sort: Int = 0, createdAt: Millis = .now,
                updatedAt: Millis = .now, deletedAt: Millis? = nil, dirty: Bool = true) {
        self.id = id; self.name = name; self.sort = sort; self.createdAt = createdAt
        self.updatedAt = updatedAt; self.deletedAt = deletedAt; self.dirty = dirty
    }

    enum CodingKeys: String, CodingKey { case id, name, sort, createdAt, updatedAt, deletedAt, dirty }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        sort = try c.decodeIfPresent(Int.self, forKey: .sort) ?? 0
        createdAt = try c.decode(Millis.self, forKey: .createdAt)
        updatedAt = try c.decode(Millis.self, forKey: .updatedAt)
        deletedAt = try c.decodeIfPresent(Millis.self, forKey: .deletedAt)
        // Los registros que llegan del servidor no traen `dirty`.
        dirty = try c.decodeIfPresent(Bool.self, forKey: .dirty) ?? false
    }
}

public struct Note: Codable, Equatable, Identifiable, Hashable, FetchableRecord, PersistableRecord {
    public var id: String
    public var notebookId: String?
    public var title: String
    public var blocks: [Block]
    public var createdAt: Millis
    public var updatedAt: Millis
    public var trashedAt: Millis?
    public var deletedAt: Millis?
    public var dirty: Bool

    public static let databaseTableName = "note"

    public init(id: String = newID(), notebookId: String?, title: String = "", blocks: [Block] = [.paragraph()],
                createdAt: Millis = .now, updatedAt: Millis = .now,
                trashedAt: Millis? = nil, deletedAt: Millis? = nil, dirty: Bool = true) {
        self.id = id; self.notebookId = notebookId; self.title = title; self.blocks = blocks
        self.createdAt = createdAt; self.updatedAt = updatedAt; self.trashedAt = trashedAt
        self.deletedAt = deletedAt; self.dirty = dirty
    }

    enum CodingKeys: String, CodingKey {
        case id, notebookId, title, blocks, createdAt, updatedAt, trashedAt, deletedAt, dirty
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        notebookId = try c.decodeIfPresent(String.self, forKey: .notebookId)
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        blocks = try c.decodeIfPresent([Block].self, forKey: .blocks) ?? []
        createdAt = try c.decode(Millis.self, forKey: .createdAt)
        updatedAt = try c.decode(Millis.self, forKey: .updatedAt)
        trashedAt = try c.decodeIfPresent(Millis.self, forKey: .trashedAt)
        deletedAt = try c.decodeIfPresent(Millis.self, forKey: .deletedAt)
        dirty = try c.decodeIfPresent(Bool.self, forKey: .dirty) ?? false
    }

    public var isTrashed: Bool { trashedAt != nil }

    /// Texto plano del contenido (sin título), para búsqueda, extractos y recuento de palabras.
    public var bodyText: String {
        blocks.map(\.plainText).filter { !$0.isEmpty }.joined(separator: " ")
    }

    public var wordCount: Int {
        (title + " " + bodyText).split(whereSeparator: \.isWhitespace).count
    }

    public var hasImage: Bool { blocks.contains { $0.type == .img } }
}

/// Imagen local de una nota. El archivo vive en el directorio de adjuntos con nombre `<id>.<ext>`.
public struct Attachment: Codable, Equatable, FetchableRecord, PersistableRecord {
    public var id: String
    public var noteId: String?
    public var fileName: String
    public var mime: String
    /// Ya se subió al servidor.
    public var uploaded: Bool

    public static let databaseTableName = "attachment"

    public init(id: String, noteId: String?, fileName: String, mime: String, uploaded: Bool) {
        self.id = id; self.noteId = noteId; self.fileName = fileName; self.mime = mime; self.uploaded = uploaded
    }
}
