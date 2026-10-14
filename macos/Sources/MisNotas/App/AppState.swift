import AppKit
import MisNotasCore
import Observation

enum Nav: Hashable {
    case all
    case notebook(String)
    case tag(String)
    case trash
}

enum SearchScope { case all, current }

/// Qué control debe recibir el foco (título, un bloque, una tarea…).
struct FocusTarget: Equatable {
    var noteId: String
    var key: String
}

/// Estado de la interfaz. Copia en memoria de la réplica local: toda edición se escribe
/// en SQLite al momento y se refleja aquí.
@Observable @MainActor
final class AppState {
    let repo: NotesRepository
    let attachmentsDirectory: URL

    private(set) var notebooks: [Notebook] = []
    /// Notas vivas (también las de la Papelera), más recientes primero.
    private(set) var notes: [Note] = []

    var nav: Nav = .all
    var selectedId: String?
    var query = "" { didSet { if query != oldValue { updateSearch() } } }
    var scope: SearchScope = .all
    var sidebarOpen = true
    var importOpen = false
    var focus: FocusTarget?
    var focusSearchToken = 0
    /// Último bloque con el foco: los bloques nuevos se insertan detrás de él.
    var activeBlockId: String?
    var errorMessage: String?
    /// Cambia cuando se descarga una imagen, para refrescar las vistas que la muestran.
    var attachmentsVersion = 0

    private(set) var searchMatches: Set<String> = []
    /// Se llama tras cada cambio local (la sincronización programa un envío).
    @ObservationIgnored var onLocalChange: () -> Void = {}

    init(repo: NotesRepository, attachmentsDirectory: URL) {
        self.repo = repo
        self.attachmentsDirectory = attachmentsDirectory
        reload()
        selectedId = list.first?.id
    }

    func reload() {
        perform {
            notebooks = try repo.notebooks()
            notes = try repo.notes()
        }
        updateSearch()
        if let id = selectedId, !notes.contains(where: { $0.id == id }) { selectedId = list.first?.id }
    }

    private func perform(_ body: () throws -> Void) {
        do { try body() } catch { errorMessage = error.localizedDescription }
    }

    // MARK: Consultas

    var trimmedQuery: String { query.trimmingCharacters(in: .whitespaces) }
    var isSearching: Bool { !trimmedQuery.isEmpty }
    var liveNotes: [Note] { notes.filter { !$0.isTrashed } }
    var trashCount: Int { notes.count - liveNotes.count }

    var selectedNote: Note? { selectedId.flatMap { id in notes.first { $0.id == id } } }

    func notebookName(_ id: String?) -> String {
        guard let id else { return "" }
        return notebooks.first { $0.id == id }?.name ?? ""
    }

    func count(in notebook: Notebook) -> Int { liveNotes.filter { $0.notebookId == notebook.id }.count }

    var tagCounts: [(name: String, count: Int)] {
        var counts: [String: Int] = [:]
        for n in liveNotes { for t in n.tags { counts[t, default: 0] += 1 } }
        return counts.map { ($0.key, $0.value) }
            .sorted { $0.name.compare($1.name, locale: Locale(identifier: "es")) == .orderedAscending }
    }

    func matches(_ note: Note, _ nav: Nav) -> Bool {
        if case .trash = nav { return note.isTrashed }
        if note.isTrashed { return false }
        switch nav {
        case let .notebook(id): return note.notebookId == id
        case let .tag(t): return note.tags.contains(t)
        default: return true
        }
    }

    /// Notas de la columna central según la navegación y la búsqueda.
    var list: [Note] {
        let q = trimmedQuery
        guard !q.isEmpty else { return notes.filter { matches($0, nav) } }
        let base = scope == .all ? liveNotes : notes.filter { matches($0, nav) }
        return base.filter { n in
            searchMatches.contains(n.id) || notebookName(n.notebookId).localizedStandardContains(q)
        }
    }

    func navLabel(_ nav: Nav) -> String {
        switch nav {
        case .all: return "Todas las notas"
        case let .notebook(id): return notebookName(id)
        case let .tag(t): return "#" + t
        case .trash: return "Papelera"
        }
    }

    private func updateSearch() {
        let q = trimmedQuery
        guard !q.isEmpty else { searchMatches = []; return }
        perform { searchMatches = try repo.search(q) }
        if let id = selectedId, list.contains(where: { $0.id == id }) { return }
        selectedId = list.first?.id
    }

    // MARK: Navegación

    func select(nav: Nav) {
        self.nav = nav
        query = ""
        selectedId = list.first?.id
    }

    func select(note id: String) {
        selectedId = id
        activeBlockId = nil
    }

    // MARK: Notas

    /// Aplica un cambio a una nota y lo guarda.
    func update(_ id: String, _ change: (inout Note) -> Void) {
        guard let i = notes.firstIndex(where: { $0.id == id }) else { return }
        var n = notes[i]
        change(&n)
        guard n != notes[i] else { return }
        perform {
            let saved = try repo.save(n)
            notes.remove(at: i)
            if saved.deletedAt == nil { notes.insert(saved, at: 0) }
        }
        onLocalChange()
    }

    func updateBlock(_ noteId: String, _ blockId: String, _ change: @escaping (inout Block) -> Void) {
        update(noteId) { n in
            guard let i = n.blocks.firstIndex(where: { $0.id == blockId }) else { return }
            change(&n.blocks[i])
        }
    }

    func newNote() {
        perform {
            let notebookId: String
            if case let .notebook(id) = nav { notebookId = id }
            else if let first = notebooks.first { notebookId = first.id }
            else {
                let nb = try repo.save(Notebook(name: "Personal"))
                notebooks = [nb]
                notebookId = nb.id
            }
            var tags: [String] = []
            if case let .tag(t) = nav { tags = [t] }
            let note = try repo.save(Note(notebookId: notebookId, tags: tags))
            notes.insert(note, at: 0)
            if case .trash = nav { nav = .all }
            query = ""
            selectedId = note.id
            focus = FocusTarget(noteId: note.id, key: "title")
        }
        onLocalChange()
    }

    private func selectionAfterRemoving(_ id: String) -> String? {
        let l = list
        guard let i = l.firstIndex(where: { $0.id == id }) else { return selectedId }
        if i + 1 < l.count { return l[i + 1].id }
        return i > 0 ? l[i - 1].id : nil
    }

    func trash(_ id: String) {
        let next = selectionAfterRemoving(id)
        update(id) { $0.trashedAt = .now }
        selectedId = next
    }

    func restore(_ id: String) {
        let next = selectionAfterRemoving(id)
        update(id) { n in
            n.trashedAt = nil
            // Si su libreta ya no existe, va a la primera.
            if !notebooks.contains(where: { $0.id == n.notebookId }) { n.notebookId = notebooks.first?.id }
        }
        selectedId = next
    }

    func deleteForever(_ id: String) {
        guard let note = notes.first(where: { $0.id == id }) else { return }
        let next = selectionAfterRemoving(id)
        perform {
            try repo.deleteForever(note)
            notes.removeAll { $0.id == id }
        }
        selectedId = next
        onLocalChange()
    }

    func emptyTrash() {
        perform {
            for n in notes where n.isTrashed { try repo.deleteForever(n) }
            notes.removeAll { $0.isTrashed }
        }
        if case .trash = nav { selectedId = nil }
        onLocalChange()
    }

    func addTag(_ raw: String, to id: String) {
        let t = Note.normalizeTag(raw)
        guard !t.isEmpty else { return }
        update(id) { n in if !n.tags.contains(t) { n.tags.append(t) } }
    }

    func removeTag(_ t: String, from id: String) {
        update(id) { $0.tags.removeAll { $0 == t } }
    }

    // MARK: Bloques

    /// Inserta un bloque detrás del bloque activo (o al final) y le da el foco.
    func insertBlock(_ block: Block, focusKey: String) {
        guard let id = selectedId else { return }
        update(id) { n in
            var at = n.blocks.endIndex
            if let active = activeBlockId, let i = n.blocks.firstIndex(where: { $0.id == active }) {
                // Un párrafo vacío activo se sustituye por el bloque nuevo.
                if n.blocks[i].isText, InlineHTML.plainText(n.blocks[i].html ?? "").isEmpty, n.blocks.count > 1 || block.isText {
                    n.blocks.remove(at: i)
                    at = i
                } else {
                    at = i + 1
                }
            } else if let last = n.blocks.last, last.type == .p, InlineHTML.plainText(last.html ?? "").isEmpty {
                n.blocks.removeLast()
                at = n.blocks.endIndex
            }
            n.blocks.insert(block, at: at)
            Self.ensureTrailingParagraph(&n)
        }
        activeBlockId = block.id
        focus = FocusTarget(noteId: id, key: focusKey)
    }

    func removeBlock(_ blockId: String, in noteId: String) {
        var focusId: String?
        update(noteId) { n in
            guard let i = n.blocks.firstIndex(where: { $0.id == blockId }) else { return }
            n.blocks.remove(at: i)
            if n.blocks.isEmpty { n.blocks = [.paragraph()] }
            Self.ensureTrailingParagraph(&n)
            focusId = n.blocks[max(0, i - 1)].id
        }
        if let focusId { focus = FocusTarget(noteId: noteId, key: "block:" + focusId) }
    }

    /// Alterna el bloque activo entre párrafo y encabezado.
    func toggleHeading() {
        guard let id = selectedId, let active = activeBlockId else { return }
        updateBlock(id, active) { b in
            switch b.type {
            case .p: b.type = .h
            case .h: b.type = .p
            default: break
            }
        }
    }

    /// Siempre hay un párrafo al final para poder seguir escribiendo tras un bloque especial.
    static func ensureTrailingParagraph(_ n: inout Note) {
        if n.blocks.last?.type != .p { n.blocks.append(.paragraph()) }
    }

    // MARK: Imágenes

    func addImage(from url: URL) {
        let ext = url.pathExtension.lowercased().isEmpty ? "png" : url.pathExtension.lowercased()
        let id = newID()
        let fileName = "\(id).\(ext)"
        perform {
            try FileManager.default.createDirectory(at: attachmentsDirectory, withIntermediateDirectories: true)
            try FileManager.default.copyItem(at: url, to: attachmentsDirectory.appendingPathComponent(fileName))
            let mime = ext == "jpg" ? "image/jpeg" : "image/\(ext)"
            try repo.insert(Attachment(id: id, noteId: selectedId, fileName: fileName, mime: mime, uploaded: false))
            insertBlock(.image(attachmentId: id), focusKey: "caption:" + id)
        }
    }

    func localImageURL(_ attachmentId: String) -> URL? {
        guard let att = try? repo.attachment(id: attachmentId) else { return nil }
        let url = attachmentsDirectory.appendingPathComponent(att.fileName)
        return FileManager.default.fileExists(atPath: url.path) ? url : nil
    }

    // MARK: Libretas y etiquetas

    @discardableResult
    func createNotebook(named name: String) -> Notebook? {
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return nil }
        if let existing = notebooks.first(where: { $0.name.caseInsensitiveCompare(trimmed) == .orderedSame }) { return existing }
        var created: Notebook?
        perform {
            created = try repo.save(Notebook(name: trimmed))
            notebooks = try repo.notebooks()
        }
        onLocalChange()
        return created
    }

    func rename(_ notebook: Notebook, to name: String) {
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return }
        perform {
            var nb = notebook
            nb.name = trimmed
            try repo.save(nb)
            notebooks = try repo.notebooks()
        }
        onLocalChange()
    }

    func delete(_ notebook: Notebook) {
        perform { try repo.delete(notebook) }
        if nav == .notebook(notebook.id) { nav = .all }
        reload()
        onLocalChange()
    }

    func move(_ noteId: String, to notebookId: String) {
        update(noteId) { $0.notebookId = notebookId }
    }

    func renameTag(_ tag: String, to newName: String?) {
        perform { try repo.renameTag(tag, to: newName) }
        if nav == .tag(tag) { nav = newName.map { .tag(Note.normalizeTag($0)) } ?? .all }
        reload()
        onLocalChange()
    }
}
