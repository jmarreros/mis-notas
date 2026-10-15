import AppKit
import MisNotasCore
import Observation

enum Nav: Hashable {
    case all
    case notebook(String)
    case trash
}

enum SearchScope { case all, current }

/// Qué control debe recibir el foco (título, un bloque, una tarea…).
struct FocusTarget: Equatable {
    var noteId: String
    var key: String
    /// Cursor al principio en vez de al final (al bajar con ↓ desde el bloque anterior).
    var atStart = false

    static func == (a: Self, b: Self) -> Bool { a.noteId == b.noteId && a.key == b.key }
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
    /// Nota con todos sus bloques seleccionados (⌘A con el bloque actual ya seleccionado entero).
    var allSelectedNoteId: String?
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

    func matches(_ note: Note, _ nav: Nav) -> Bool {
        if case .trash = nav { return note.isTrashed }
        if note.isTrashed { return false }
        switch nav {
        case let .notebook(id): return note.notebookId == id
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
            let note = try repo.save(Note(notebookId: notebookId))
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

    // MARK: Bloques

    /// Inserta un bloque detrás del bloque activo (o al final) y le da el foco.
    func insertBlock(_ block: Block, focusKey: String) {
        guard let id = selectedId else { return }
        registerUndo(id, name: "Insertar bloque")
        // Si el cursor está dentro de un texto, el bloque entra justo ahí y el resto del texto pasa a un párrafo nuevo.
        var split: (before: String, after: String)?
        if let active = activeBlockId, notes.first(where: { $0.id == id })?.blocks.first(where: { $0.id == active })?.isText == true,
           let tv = NSApp.keyWindow?.firstResponder as? BlockTextView {
            split = tv.splitAtCaret()
        }
        update(id) { n in
            var at = n.blocks.endIndex
            if let active = activeBlockId, let i = n.blocks.firstIndex(where: { $0.id == active }) {
                if let split, !InlineHTML.plainText(split.before).isEmpty || !InlineHTML.plainText(split.after).isEmpty {
                    let hasBefore = !InlineHTML.plainText(split.before).isEmpty
                    if hasBefore { n.blocks[i].html = split.before } else { n.blocks.remove(at: i) }
                    at = hasBefore ? i + 1 : i
                    n.blocks.insert(block, at: at)
                    if !InlineHTML.plainText(split.after).isEmpty { n.blocks.insert(.paragraph(split.after), at: at + 1) }
                    Self.ensureTrailingParagraph(&n)
                    return
                }
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
        registerUndo(noteId, name: "Eliminar bloque")
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

    /// `---` + Intro en un párrafo: lo parte en texto anterior, línea horizontal y texto posterior.
    func insertDivider(_ blockId: String, before: String, after: String, in noteId: String) {
        registerUndo(noteId, name: "Insertar línea")
        var focusId: String?
        update(noteId) { n in
            guard let i = n.blocks.firstIndex(where: { $0.id == blockId }) else { return }
            var at = i + 1
            if InlineHTML.plainText(before).isEmpty {
                n.blocks[i] = .divider()
            } else {
                n.blocks[i].html = before
                n.blocks.insert(.divider(), at: at)
                at += 1
            }
            // Si no queda texto detrás y ya hay un párrafo vacío debajo, se reutiliza.
            if InlineHTML.plainText(after).isEmpty, at < n.blocks.count, n.blocks[at].type == .p,
               InlineHTML.plainText(n.blocks[at].html ?? "").isEmpty {
                focusId = n.blocks[at].id
            } else {
                let p = Block.paragraph(InlineHTML.plainText(after).isEmpty ? "" : after)
                n.blocks.insert(p, at: at)
                focusId = p.id
            }
        }
        if let focusId {
            activeBlockId = focusId
            focus = FocusTarget(noteId: noteId, key: "block:" + focusId)
        }
    }

    // MARK: Deshacer

    /// Guarda los bloques actuales de la nota en el deshacer de la ventana (el mismo que usa el texto,
    /// así ⌘Z sigue el orden real). Al deshacer se registra el estado de ese momento para rehacer.
    private func registerUndo(_ noteId: String, name: String) {
        guard let um = NSApp.keyWindow?.undoManager,
              let blocks = notes.first(where: { $0.id == noteId })?.blocks else { return }
        um.registerUndo(withTarget: self) { s in
            MainActor.assumeIsolated { s.restoreBlocks(blocks, in: noteId, name: name) }
        }
        um.setActionName(name)
    }

    private func restoreBlocks(_ blocks: [Block], in noteId: String, name: String) {
        registerUndo(noteId, name: name)
        allSelectedNoteId = nil
        update(noteId) { $0.blocks = blocks }
        if let first = blocks.first {
            activeBlockId = first.id
            focus = FocusTarget(noteId: noteId, key: Self.focusKey(first, last: false), atStart: true)
        }
    }

    // MARK: Selección de todos los bloques

    func selectAllBlocks() {
        guard let id = selectedId else { return }
        focus = nil
        allSelectedNoteId = id
    }

    /// Texto plano de todos los bloques, para copiar.
    func plainText(of noteId: String) -> String {
        guard let n = notes.first(where: { $0.id == noteId }) else { return "" }
        return n.blocks.map { b -> String in
            switch b.type {
            case .todo: return (b.items ?? []).map { "• " + $0.t }.joined(separator: "\n")
            case .code: return b.text ?? ""
            case .link: return b.url ?? ""
            case .hr: return "---"
            default: return b.plainText
            }
        }.joined(separator: "\n")
    }

    /// Sustituye todos los bloques por un párrafo (vacío o con el texto tecleado) y lo enfoca.
    func replaceAllBlocks(in noteId: String, with text: String = "") {
        let p = Block.paragraph(InlineHTML.escape(text))
        registerUndo(noteId, name: text.isEmpty ? "Eliminar todo" : "Escribir")
        update(noteId) { $0.blocks = [p] }
        allSelectedNoteId = nil
        activeBlockId = p.id
        focus = FocusTarget(noteId: noteId, key: "block:" + p.id)
    }

    /// Clic en la zona vacía del editor: cursor al final del último bloque (siempre hay un párrafo al final).
    func focusEnd(of noteId: String) {
        guard let n = notes.first(where: { $0.id == noteId }), !n.isTrashed else { return }
        var last = n.blocks.last
        if last?.type != .p {
            update(noteId) { Self.ensureTrailingParagraph(&$0) }
            last = notes.first(where: { $0.id == noteId })?.blocks.last
        }
        guard let last else { return }
        allSelectedNoteId = nil
        activeBlockId = last.id
        focus = FocusTarget(noteId: noteId, key: Self.focusKey(last, last: true))
    }

    // MARK: Navegación con flechas

    /// Clave de foco de un bloque; en las listas, el primer o el último elemento.
    static func focusKey(_ b: Block, last: Bool) -> String {
        switch b.type {
        case .p, .h, .code: return "block:" + b.id
        case .todo: return "todo:\(b.id):\(last ? max(0, (b.items?.count ?? 1) - 1) : 0)"
        case .link: return "url:" + b.id
        case .img: return "caption:" + (b.attachmentId ?? "")
        case .hr: return "hr:" + b.id
        }
    }

    /// ↑/↓ en el borde de un bloque: pasa al bloque anterior o siguiente (o al título).
    /// `blockId == nil` es el título. `item` es el elemento actual si el bloque es una lista.
    func moveFocus(from blockId: String?, item: Int? = nil, up: Bool, in noteId: String) {
        guard let n = notes.first(where: { $0.id == noteId }) else { return }
        let target: Int
        if let blockId {
            guard let i = n.blocks.firstIndex(where: { $0.id == blockId }) else { return }
            let b = n.blocks[i]
            if b.type == .todo, let item {
                let next = item + (up ? -1 : 1)
                if (b.items ?? []).indices.contains(next) {
                    focus = FocusTarget(noteId: noteId, key: "todo:\(b.id):\(next)")
                    return
                }
            }
            target = i + (up ? -1 : 1)
            if target < 0 {
                focus = FocusTarget(noteId: noteId, key: "title")
                return
            }
        } else {
            guard !up else { return }
            target = 0
        }
        guard n.blocks.indices.contains(target) else { return }
        let b = n.blocks[target]
        activeBlockId = b.id
        focus = FocusTarget(noteId: noteId, key: Self.focusKey(b, last: up), atStart: !up)
    }

    /// Intro en un elemento vacío de una lista: termina la lista y sigue en un párrafo.
    /// Si quedaban elementos debajo, pasan a una lista nueva tras el párrafo.
    func exitList(_ blockId: String, item: Int, in noteId: String) {
        registerUndo(noteId, name: "Terminar lista")
        var focusId: String?
        update(noteId) { n in
            guard let i = n.blocks.firstIndex(where: { $0.id == blockId }) else { return }
            let items = n.blocks[i].items ?? []
            guard items.indices.contains(item) else { return }
            let before = Array(items[..<item]), after = Array(items[(item + 1)...])
            var at = i + 1
            if before.isEmpty {
                n.blocks.remove(at: i)
                at = i
            } else {
                n.blocks[i].items = before
            }
            // Si justo debajo ya hay un párrafo vacío, se reutiliza.
            if after.isEmpty, at < n.blocks.count, n.blocks[at].type == .p,
               InlineHTML.plainText(n.blocks[at].html ?? "").isEmpty {
                focusId = n.blocks[at].id
            } else {
                let p = Block.paragraph()
                n.blocks.insert(p, at: at)
                if !after.isEmpty { n.blocks.insert(.todo(after), at: at + 1) }
                focusId = p.id
            }
            Self.ensureTrailingParagraph(&n)
        }
        if let focusId {
            activeBlockId = focusId
            focus = FocusTarget(noteId: noteId, key: "block:" + focusId)
        }
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
            let mime = ["jpg": "image/jpeg", "svg": "image/svg+xml"][ext] ?? "image/\(ext)"
            try repo.insert(Attachment(id: id, noteId: selectedId, fileName: fileName, mime: mime, uploaded: false))
            insertBlock(.image(attachmentId: id), focusKey: "caption:" + id)
        }
    }

    func localImageURL(_ attachmentId: String) -> URL? {
        guard let att = try? repo.attachment(id: attachmentId) else { return nil }
        let url = attachmentsDirectory.appendingPathComponent(att.fileName)
        return FileManager.default.fileExists(atPath: url.path) ? url : nil
    }

    // MARK: Libretas

    @discardableResult
    func createNotebook(named name: String) -> Notebook? {
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return nil }
        if let existing = notebooks.first(where: { $0.name.caseInsensitiveCompare(trimmed) == .orderedSame }) { return existing }
        var created: Notebook?
        perform {
            created = try repo.save(Notebook(name: trimmed, sort: notebooks.count))
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

    /// Coloca `id` en la posición que ocupa `target` (arrastrar y soltar en la barra lateral).
    func moveNotebook(_ id: String, onto target: String) {
        guard id != target, let from = notebooks.firstIndex(where: { $0.id == id }),
              let to = notebooks.firstIndex(where: { $0.id == target }) else { return }
        var order = notebooks
        order.insert(order.remove(at: from), at: to)
        perform {
            try repo.reorderNotebooks(order.map(\.id))
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

}
