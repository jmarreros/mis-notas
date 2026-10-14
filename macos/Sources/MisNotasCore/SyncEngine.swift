import Foundation

/// Un ciclo de sincronización: subir imágenes pendientes → enviar cambios locales →
/// adoptar los rechazados → descargar todo lo nuevo desde el último `rev`.
public final class SyncEngine {
    public let repo: NotesRepository
    public let transport: SyncTransport
    public let attachmentsDirectory: URL

    public init(repo: NotesRepository, transport: SyncTransport, attachmentsDirectory: URL) {
        self.repo = repo
        self.transport = transport
        self.attachmentsDirectory = attachmentsDirectory
    }

    public struct Result: Equatable {
        public var pushed: Int
        public var pulled: Int
    }

    public func sync() async throws -> Result {
        for att in try repo.pendingUploads() {
            let url = attachmentsDirectory.appendingPathComponent(att.fileName)
            guard let data = try? Data(contentsOf: url) else { continue }
            try await transport.upload(attachment: att, data: data)
            try repo.markUploaded(att.id)
        }

        let dirty = try repo.dirtyRecords()
        var changed = 0
        if !dirty.notebooks.isEmpty || !dirty.notes.isEmpty {
            let res = try await transport.push(notebooks: dirty.notebooks, notes: dirty.notes)
            try repo.markClean(notebooks: dirty.notebooks, notes: dirty.notes)
            changed += try repo.applyRemote(notebooks: res.notebooks, notes: res.notes, rev: nil)
        }

        let pulled = try await transport.pull(since: try repo.lastRev())
        changed += try repo.applyRemote(notebooks: pulled.notebooks, notes: pulled.notes, rev: pulled.rev)

        return Result(pushed: dirty.notebooks.count + dirty.notes.count, pulled: changed)
    }

    /// Descarga una imagen que no está en este Mac.
    public func fetchAttachment(id: String, fileExtension: String = "png") async throws -> URL {
        let data = try await transport.download(attachmentId: id)
        let fileName = "\(id).\(fileExtension)"
        let url = attachmentsDirectory.appendingPathComponent(fileName)
        try FileManager.default.createDirectory(at: attachmentsDirectory, withIntermediateDirectories: true)
        try data.write(to: url, options: .atomic)
        try repo.insert(Attachment(id: id, noteId: nil, fileName: fileName, mime: "image/\(fileExtension)", uploaded: true))
        return url
    }
}
