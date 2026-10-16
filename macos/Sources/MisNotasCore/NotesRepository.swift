import Foundation
import GRDB

/// Acceso a la réplica local. Toda escritura del usuario marca el registro como `dirty`
/// para que el `SyncEngine` lo envíe.
public final class NotesRepository {
    public let db: AppDatabase
    private var writer: any DatabaseWriter { db.writer }

    public init(_ db: AppDatabase) { self.db = db }

    // MARK: Lectura

    public func notebooks() throws -> [Notebook] {
        try writer.read { db in
            try Notebook.filter(Column("deletedAt") == nil)
                .order(Column("sort"), Column("name").collating(.localizedCaseInsensitiveCompare))
                .fetchAll(db)
        }
    }

    /// Todas las notas vivas (también las de la Papelera), más recientes primero.
    public func notes() throws -> [Note] {
        try writer.read { db in
            try Note.filter(Column("deletedAt") == nil).order(Column("updatedAt").desc).fetchAll(db)
        }
    }

    public func note(id: String) throws -> Note? {
        try writer.read { db in try Note.fetchOne(db, key: id) }
    }

    /// IDs de las notas que coinciden con todos los prefijos de la consulta.
    public func search(_ query: String) throws -> Set<String> {
        guard let pattern = FTS5Pattern(matchingAllPrefixesIn: query) else { return [] }
        return try writer.read { db in
            let ids = try String.fetchAll(db, sql: "SELECT noteId FROM noteSearch WHERE noteSearch MATCH ?", arguments: [pattern])
            return Set(ids)
        }
    }

    // MARK: Escritura local

    /// Guarda una nota editada por el usuario. Actualiza `updatedAt` salvo que se indique otra fecha.
    @discardableResult
    public func save(_ note: Note, touch: Bool = true) throws -> Note {
        var n = note
        if touch { n.updatedAt = max(Millis.now, note.updatedAt + 1) }
        n.dirty = true
        try writer.write { db in
            try n.save(db)
            try Self.index(n, db)
        }
        return n
    }

    @discardableResult
    public func save(_ notebook: Notebook) throws -> Notebook {
        var nb = notebook
        nb.updatedAt = max(Millis.now, notebook.updatedAt + 1)
        nb.dirty = true
        try writer.write { db in try nb.save(db) }
        return nb
    }

    /// Fija el orden manual de las libretas: `ids` es el orden deseado. Solo toca las que cambian.
    public func reorderNotebooks(_ ids: [String]) throws {
        try writer.write { db in
            let now = Millis.now
            for (index, id) in ids.enumerated() {
                guard var nb = try Notebook.fetchOne(db, key: id), nb.deletedAt == nil, nb.sort != index else { continue }
                nb.sort = index
                nb.updatedAt = max(now, nb.updatedAt + 1)
                nb.dirty = true
                try nb.save(db)
            }
        }
    }

    /// Guarda varias notas en una sola transacción (importación). Respeta sus fechas.
    public func insert(notes: [Note], notebooks: [Notebook]) throws {
        try writer.write { db in
            for var nb in notebooks { nb.dirty = true; try nb.save(db) }
            for var n in notes { n.dirty = true; try n.save(db); try Self.index(n, db) }
        }
    }

    /// Borrado definitivo: deja una lápida para propagarlo al servidor.
    public func deleteForever(_ note: Note) throws {
        var n = note
        n.deletedAt = .now
        n.blocks = []
        n.title = ""
        try save(n)
    }

    /// Elimina una libreta y manda sus notas a la Papelera.
    public func delete(_ notebook: Notebook) throws {
        try writer.write { db in
            let now = Millis.now
            var nb = notebook
            nb.deletedAt = now
            nb.updatedAt = max(now, nb.updatedAt + 1)
            nb.dirty = true
            try nb.save(db)
            let notes = try Note.filter(Column("notebookId") == notebook.id && Column("deletedAt") == nil).fetchAll(db)
            for var n in notes where n.trashedAt == nil {
                n.trashedAt = now
                n.updatedAt = max(now, n.updatedAt + 1)
                n.dirty = true
                try n.save(db)
            }
        }
    }

    // MARK: Adjuntos

    public func insert(_ attachment: Attachment) throws {
        try writer.write { db in try attachment.save(db) }
    }

    public func attachment(id: String) throws -> Attachment? {
        try writer.read { db in try Attachment.fetchOne(db, key: id) }
    }

    public func pendingUploads() throws -> [Attachment] {
        try writer.read { db in try Attachment.filter(Column("uploaded") == false).fetchAll(db) }
    }

    public func markUploaded(_ id: String) throws {
        try writer.write { db in
            try db.execute(sql: "UPDATE attachment SET uploaded = 1 WHERE id = ?", arguments: [id])
        }
    }

    // MARK: Vistas recientes (solo locales, no se sincronizan)

    public func recentIDs() throws -> [String] {
        try writer.read { db in
            let json = try String.fetchOne(db, sql: "SELECT value FROM meta WHERE key = 'recentIds'")
            return json.flatMap { try? JSONDecoder().decode([String].self, from: Data($0.utf8)) } ?? []
        }
    }

    public func setRecentIDs(_ ids: [String]) throws {
        let json = String(decoding: try JSONEncoder().encode(ids), as: UTF8.self)
        try writer.write { db in
            try db.execute(sql: "INSERT OR REPLACE INTO meta (key, value) VALUES ('recentIds', ?)", arguments: [json])
        }
    }

    // MARK: Sincronización

    public func lastRev() throws -> Int {
        try writer.read { db in
            try String.fetchOne(db, sql: "SELECT value FROM meta WHERE key = 'lastRev'").flatMap(Int.init) ?? 0
        }
    }

    /// Al cambiar de servidor: todo vuelve a enviarse (notas, libretas e imágenes) y se descarga
    /// desde el principio. Si el servidor ya tenía los datos, gana la versión más reciente.
    public func resetSyncState() throws {
        try writer.write { db in
            try db.execute(sql: "UPDATE notebook SET dirty = 1")
            try db.execute(sql: "UPDATE note SET dirty = 1")
            try db.execute(sql: "UPDATE attachment SET uploaded = 0")
            try db.execute(sql: "DELETE FROM meta WHERE key = 'lastRev'")
        }
    }

    public func dirtyRecords() throws -> (notebooks: [Notebook], notes: [Note]) {
        try writer.read { db in
            (try Notebook.filter(Column("dirty") == true).fetchAll(db),
             try Note.filter(Column("dirty") == true).fetchAll(db))
        }
    }

    /// Limpia `dirty` solo si el registro no cambió mientras se enviaba.
    public func markClean(notebooks: [Notebook], notes: [Note]) throws {
        try writer.write { db in
            for nb in notebooks {
                try db.execute(sql: "UPDATE notebook SET dirty = 0 WHERE id = ? AND updatedAt = ?", arguments: [nb.id, nb.updatedAt])
            }
            for n in notes {
                try db.execute(sql: "UPDATE note SET dirty = 0 WHERE id = ? AND updatedAt = ?", arguments: [n.id, n.updatedAt])
            }
        }
    }

    /// Aplica registros del servidor según `SyncMerge`. Devuelve cuántos cambiaron localmente.
    @discardableResult
    public func applyRemote(notebooks: [Notebook], notes: [Note], rev: Int?) throws -> Int {
        try writer.write { db in
            var changed = 0
            for var remote in notebooks {
                let local = try Notebook.fetchOne(db, key: remote.id)
                guard SyncMerge.shouldApply(remoteUpdatedAt: remote.updatedAt, local: local.map { ($0.updatedAt, $0.dirty) }) else { continue }
                remote.dirty = false
                if remote != local { changed += 1 }
                try remote.save(db)
            }
            for var remote in notes {
                let local = try Note.fetchOne(db, key: remote.id)
                guard SyncMerge.shouldApply(remoteUpdatedAt: remote.updatedAt, local: local.map { ($0.updatedAt, $0.dirty) }) else { continue }
                remote.dirty = false
                if remote != local { changed += 1 }
                try remote.save(db)
                try Self.index(remote, db)
            }
            if let rev {
                try db.execute(sql: "INSERT OR REPLACE INTO meta (key, value) VALUES ('lastRev', ?)", arguments: [String(rev)])
            }
            return changed
        }
    }

    // MARK: Índice

    private static func index(_ n: Note, _ db: Database) throws {
        try db.execute(sql: "DELETE FROM noteSearch WHERE noteId = ?", arguments: [n.id])
        guard n.deletedAt == nil else { return }
        let body = n.bodyText
        try db.execute(sql: "INSERT INTO noteSearch (noteId, title, body) VALUES (?, ?, ?)", arguments: [n.id, n.title, body])
    }
}

/// Regla de fusión: last-write-wins por `updatedAt`, pero un cambio local pendiente
/// solo se pisa si el remoto es igual o más reciente.
public enum SyncMerge {
    public static func shouldApply(remoteUpdatedAt: Millis, local: (updatedAt: Millis, dirty: Bool)?) -> Bool {
        guard let local else { return true }
        if !local.dirty { return true }
        return remoteUpdatedAt >= local.updatedAt
    }
}
