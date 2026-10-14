import Foundation
import GRDB

/// Réplica local en SQLite. Todas las operaciones son síncronas y rápidas; la app
/// trabaja contra esta base y el `SyncEngine` la reconcilia con el servidor.
public final class AppDatabase {
    public let writer: any DatabaseWriter

    public init(_ writer: any DatabaseWriter) throws {
        self.writer = writer
        try Self.migrator.migrate(writer)
    }

    /// Base en `~/Library/Application Support/MisNotas/notas.sqlite`.
    public static func onDisk(directory: URL) throws -> AppDatabase {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var config = Configuration()
        config.foreignKeysEnabled = false
        let pool = try DatabasePool(path: directory.appendingPathComponent("notas.sqlite").path, configuration: config)
        return try AppDatabase(pool)
    }

    public static func inMemory() throws -> AppDatabase {
        try AppDatabase(DatabaseQueue())
    }

    static var migrator: DatabaseMigrator {
        var m = DatabaseMigrator()
        m.registerMigration("v1") { db in
            try db.create(table: "notebook") { t in
                t.primaryKey("id", .text)
                t.column("name", .text).notNull()
                t.column("sort", .integer).notNull().defaults(to: 0)
                t.column("createdAt", .integer).notNull()
                t.column("updatedAt", .integer).notNull()
                t.column("deletedAt", .integer)
                t.column("dirty", .boolean).notNull().defaults(to: false)
            }
            try db.create(table: "note") { t in
                t.primaryKey("id", .text)
                t.column("notebookId", .text)
                t.column("title", .text).notNull().defaults(to: "")
                t.column("blocks", .text).notNull()
                t.column("tags", .text).notNull()
                t.column("createdAt", .integer).notNull()
                t.column("updatedAt", .integer).notNull()
                t.column("trashedAt", .integer)
                t.column("deletedAt", .integer)
                t.column("dirty", .boolean).notNull().defaults(to: false)
            }
            try db.create(index: "note_dirty", on: "note", columns: ["dirty"])
            try db.create(table: "attachment") { t in
                t.primaryKey("id", .text)
                t.column("noteId", .text)
                t.column("fileName", .text).notNull()
                t.column("mime", .text).notNull()
                t.column("uploaded", .boolean).notNull().defaults(to: false)
            }
            try db.create(table: "meta") { t in
                t.primaryKey("key", .text)
                t.column("value", .text)
            }
            // Índice de búsqueda. unicode61 ignora mayúsculas y tildes ("japon" encuentra "Japón").
            try db.create(virtualTable: "noteSearch", using: FTS5()) { t in
                t.tokenizer = .unicode61()
                t.column("noteId").notIndexed()
                t.column("title")
                t.column("body")
            }
        }
        return m
    }
}
