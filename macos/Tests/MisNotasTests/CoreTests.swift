import AppKit
import Foundation
import Testing
@testable import MisNotasCore

typealias Attachment = MisNotasCore.Attachment

@Suite struct EnexTests {
    @Test func parsesSampleExport() throws {
        let url = try #require(Bundle.module.url(forResource: "muestra", withExtension: "enex", subdirectory: "Fixtures"))
        let notes = try EnexParser.parse(url: url)
        #expect(notes.count == 2)

        let n = notes[0]
        #expect(n.title == "Viaje a Asturias")
        #expect(n.created == 1_755_250_200_000)
        #expect(n.updated != nil)

        let kinds = n.blocks.map(\.type)
        #expect(kinds == [.p, .h, .todo, .p, .code, .p, .todo])

        #expect(n.blocks[0].html == "Ruta del <b>Cares</b> en un día, salir desde Poncebos.<br>Ver <a href=\"https://example.com/cares?a=1&amp;b=2\">mapa</a>.")
        #expect(n.blocks[1].html == "Equipaje")
        #expect(n.blocks[2].items == [TodoItem(t: "Botas", done: true), TodoItem(t: "Chubasquero", done: false)])
        #expect(n.blocks[3].html == "Después del todo.")
        #expect(n.blocks[4].text == "ssh nas.local\n  ls -la")
        #expect(n.blocks[5].html == "• uno<br>• dos")
        #expect(n.blocks[6].items == [TodoItem(t: "Hecho v10", done: true), TodoItem(t: "Pendiente v10", done: false)])

        #expect(notes[1].blocks == [Block(id: notes[1].blocks[0].id, type: .p, html: "")])
        #expect(notes[1].updated == nil)
    }
}

@Suite struct InlineHTMLTests {
    private func font(_ b: Bool, _ i: Bool) -> NSFont { .systemFont(ofSize: 14) }

    @Test func roundTrip() {
        let html = "Hola <b>mundo <i>feliz</i></b> y <u>sub</u><br>línea <a href=\"https://a.com/?x=1&amp;y=2\">enlace</a> &lt;3"
        let attr = InlineHTML.attributedString(html, font: font, color: .white, linkColor: .orange)
        #expect(attr.string == "Hola mundo feliz y sub\nlínea enlace <3")
        #expect(InlineHTML.html(from: attr) == "Hola <b>mundo </b><b><i>feliz</i></b> y <u>sub</u><br>línea <a href=\"https://a.com/?x=1&amp;y=2\">enlace</a> &lt;3")
        // Una segunda vuelta es estable.
        let again = InlineHTML.attributedString(InlineHTML.html(from: attr), font: font, color: .white, linkColor: .orange)
        #expect(again.isEqual(to: attr))
    }

    @Test func divsBecomeLines() {
        #expect(InlineHTML.parse("<div>a</div><div><br></div><div>b</div>").map(\.text).joined() == "a\n\nb")
        #expect(InlineHTML.plainText("Uno&nbsp;<b>dos</b>\n tres") == "Uno dos  tres")
    }
}

/// Servidor en memoria que imita la API Laravel (rev global + last-write-wins).
final class FakeServer: SyncTransport {
    var rev = 0
    var notebooks: [String: (Notebook, Int)] = [:]
    var notes: [String: (Note, Int)] = [:]
    var uploads: [String: Data] = [:]

    func pull(since: Int) async throws -> PullResponse {
        PullResponse(rev: rev,
                     notebooks: notebooks.values.filter { $0.1 > since }.sorted { $0.1 < $1.1 }.map(\.0),
                     notes: notes.values.filter { $0.1 > since }.sorted { $0.1 < $1.1 }.map(\.0))
    }

    func push(notebooks nbs: [Notebook], notes ns: [Note]) async throws -> PushResponse {
        var rejected = PushResponse(rev: 0, notebooks: [], notes: [])
        for var nb in nbs {
            if let ex = notebooks[nb.id]?.0, ex.updatedAt > nb.updatedAt { rejected.notebooks.append(ex); continue }
            nb.dirty = false; rev += 1; notebooks[nb.id] = (nb, rev)
        }
        for var n in ns {
            if let ex = notes[n.id]?.0, ex.updatedAt > n.updatedAt || (ex.deletedAt != nil && n.deletedAt == nil) { rejected.notes.append(ex); continue }
            n.dirty = false; rev += 1; notes[n.id] = (n, rev)
        }
        rejected.rev = rev
        return rejected
    }

    func upload(attachment: Attachment, data: Data) async throws { uploads[attachment.id] = data }
    func download(attachmentId: String) async throws -> Data { uploads[attachmentId] ?? Data() }
}

@Suite struct SyncTests {
    let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("mn-tests-\(UUID().uuidString)")

    private func client(_ server: FakeServer) throws -> (NotesRepository, SyncEngine) {
        let repo = NotesRepository(try AppDatabase.inMemory())
        return (repo, SyncEngine(repo: repo, transport: server, attachmentsDirectory: tmp))
    }

    @Test func twoDevicesConverge() async throws {
        let server = FakeServer()
        let (a, syncA) = try client(server)
        let (b, syncB) = try client(server)

        let nb = try a.save(Notebook(name: "Viajes"))
        var note = try a.save(Note(notebookId: nb.id, title: "Kioto", blocks: [.paragraph("ryokan")]))
        #expect(try await syncA.sync() == .init(pushed: 2, pulled: 0))
        #expect(try a.dirtyRecords().notes.isEmpty)

        _ = try await syncB.sync()
        #expect(try b.notes().map(\.title) == ["Kioto"])
        #expect(try b.notebooks().map(\.name) == ["Viajes"])
        #expect(try b.search("kioto") == [note.id])
        #expect(try b.search("RYOK") == [note.id])

        // B edita, A recibe.
        var onB = try #require(try b.note(id: note.id))
        onB.title = "Kioto y Nara"
        try b.save(onB)
        _ = try await syncB.sync()
        _ = try await syncA.sync()
        note = try #require(try a.note(id: note.id))
        #expect(note.title == "Kioto y Nara")
        #expect(!note.dirty)
    }

    @Test func localPendingEditIsNotOverwrittenByOlderRemote() async throws {
        let server = FakeServer()
        let (a, syncA) = try client(server)
        let (b, syncB) = try client(server)
        let note = try a.save(Note(notebookId: nil, title: "v1"))
        _ = try await syncA.sync()
        _ = try await syncB.sync()

        // A edita primero (más antiguo), B después (más reciente) y sincroniza antes.
        var onA = try #require(try a.note(id: note.id)); onA.title = "de A"; onA.updatedAt = .now + 10_000
        try a.save(onA, touch: false)
        var onB = try #require(try b.note(id: note.id)); onB.title = "de B"; onB.updatedAt = .now + 20_000
        try b.save(onB, touch: false)

        _ = try await syncB.sync()
        _ = try await syncA.sync()   // A pierde: el servidor rechaza y A adopta la de B.
        #expect(try a.note(id: note.id)?.title == "de B")
        #expect(try a.dirtyRecords().notes.isEmpty)

        // Al revés: un remoto más viejo no pisa un cambio local más nuevo pendiente.
        var newer = try #require(try a.note(id: note.id)); newer.title = "local"; newer.updatedAt = .now + 30_000
        try a.save(newer, touch: false)
        try a.applyRemote(notebooks: [], notes: [onB], rev: nil)
        #expect(try a.note(id: note.id)?.title == "local")
    }

    @Test func deletionsPropagate() async throws {
        let server = FakeServer()
        let (a, syncA) = try client(server)
        let (b, syncB) = try client(server)
        let note = try a.save(Note(notebookId: nil, title: "borrar"))
        _ = try await syncA.sync(); _ = try await syncB.sync()
        try a.deleteForever(note)
        _ = try await syncA.sync(); _ = try await syncB.sync()
        #expect(try b.notes().isEmpty)
        #expect(try b.search("borrar").isEmpty)
    }

    @Test func notebookOrderSyncs() async throws {
        let server = FakeServer()
        let (a, syncA) = try client(server)
        let (b, syncB) = try client(server)
        let x = try a.save(Notebook(name: "A"))
        let y = try a.save(Notebook(name: "B"))
        let z = try a.save(Notebook(name: "C"))
        #expect(try a.notebooks().map(\.name) == ["A", "B", "C"])

        try a.reorderNotebooks([z.id, x.id, y.id])
        #expect(try a.notebooks().map(\.name) == ["C", "A", "B"])

        _ = try await syncA.sync(); _ = try await syncB.sync()
        #expect(try b.notebooks().map(\.name) == ["C", "A", "B"])
    }

    @Test func attachmentsUploadBeforePush() async throws {
        let server = FakeServer()
        let (a, syncA) = try client(server)
        try FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
        try Data([1, 2, 3]).write(to: tmp.appendingPathComponent("x.png"))
        try a.insert(Attachment(id: "att1", noteId: nil, fileName: "x.png", mime: "image/png", uploaded: false))
        _ = try await syncA.sync()
        #expect(server.uploads["att1"] == Data([1, 2, 3]))
        #expect(try a.pendingUploads().isEmpty)
    }

    @Test func serverJSONShape() throws {
        // El JSON que produce Laravel (snake_case, rev, campos extra) se decodifica bien.
        let json = """
        {"rev":3,"notebooks":[{"id":"nb1","name":"Viajes","sort":0,"created_at":1,"updated_at":2,"deleted_at":null,"rev":1}],
         "notes":[{"id":"n1","notebook_id":"nb1","title":"T","blocks":[{"id":"b","type":"img","attachment_id":"a1","caption":"c"}],
                   "tags":["x"],"created_at":1,"updated_at":2,"trashed_at":null,"deleted_at":null,"rev":3}]}
        """
        let r = try APIClient.decoder.decode(PullResponse.self, from: Data(json.utf8))
        #expect(r.notes[0].blocks[0].attachmentId == "a1")
        #expect(r.notes[0].notebookId == "nb1")
        #expect(!r.notes[0].dirty)

        let out = String(decoding: try APIClient.encoder.encode(r.notes[0]), as: UTF8.self)
        #expect(out.contains("\"attachment_id\":\"a1\""))
        #expect(out.contains("\"notebook_id\":\"nb1\""))
    }
}
