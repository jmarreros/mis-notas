import AppKit
import MisNotasCore
import SwiftUI

struct EditorView: View {
    @Environment(AppState.self) private var state
    @State private var copiedNotice = false
    @State private var noticeTask: Task<Void, Never>?

    var body: some View {
        if let note = state.selectedNote {
            VStack(spacing: 0) {
                toolbar(note)
                if note.isTrashed { trashBanner(note) }
                GeometryReader { geo in
                    ScrollView {
                        NoteBody(note: note)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 48).padding(.top, 32).padding(.bottom, 64)
                            // Ocupa al menos el alto visible: un clic en la zona vacía empieza a escribir.
                            .frame(minHeight: geo.size.height, alignment: .top)
                            .background {
                                Color.black.opacity(0.001)
                                    .onTapGesture { state.focusEnd(of: note.id) }
                            }
                    }
                }
                .scrollIndicators(.automatic)
                .background(SelectionKeySink(active: state.allSelectedNoteId == note.id, noteId: note.id))
                footer(note)
            }
            .disabled(false)
            .onAppear { SelectAllMonitor.install(state) }
        } else {
            VStack(spacing: 14) {
                Text("NINGUNA NOTA SELECCIONADA").font(Theme.display(22, weight: .bold)).tracking(0.4)
                    .foregroundStyle(Color(hex: 0x666666))
                Button { state.newNote() } label: {
                    Text("Nueva nota").font(Theme.body(13, weight: .semibold)).foregroundStyle(.black)
                        .padding(.horizontal, 16).frame(height: 32)
                        .background(RoundedRectangle(cornerRadius: 4).fill(.white))
                }
                .buttonStyle(.plain)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(WindowDragArea())
        }
    }

    private func toolbar(_ note: Note) -> some View {
        HStack(spacing: 2) {
            IconButton(systemName: "bold", help: "Negrita  ⌘B") { Formatting.send(#selector(BlockTextView.mnToggleBold(_:))) }
            IconButton(systemName: "italic", help: "Cursiva  ⌘I") { Formatting.send(#selector(BlockTextView.mnToggleItalic(_:))) }
            IconButton(systemName: "underline", help: "Subrayado  ⌘U") { Formatting.send(#selector(BlockTextView.mnToggleUnderline(_:))) }
            IconButton(systemName: "textformat.size", help: "Encabezado  ⌥⌘H") { state.toggleHeading() }
            Rectangle().fill(Theme.fieldBorder).frame(width: 1, height: 18).padding(.horizontal, 6)
            IconButton(systemName: "list.bullet", help: "Lista  ⌥⌘L") { BlockActions.addTodo(state) }
            IconButton(systemName: "chevron.left.forwardslash.chevron.right", help: "Bloque de código  ⌥⌘C", size: 12) { BlockActions.addCode(state) }
            IconButton(systemName: "link", help: "Enlace  ⌘K") { Formatting.send(#selector(BlockTextView.mnLink(_:))) }
            IconButton(systemName: "photo", help: "Imagen") { BlockActions.addImage(state) }
            Spacer()
            NotebookPicker(note: note)
            IconButton(systemName: note.favorite ? "star.fill" : "star",
                       help: note.favorite ? "Quitar de favoritas  ⇧⌘F" : "Añadir a favoritas  ⇧⌘F",
                       color: note.favorite ? Color(hex: 0xF5C542) : Theme.icon) {
                state.toggleFavorite(note.id)
            }
            IconButton(systemName: "trash", help: note.isTrashed ? "Eliminar definitivamente" : "Mover a la Papelera  ⌘⌫") {
                note.isTrashed ? state.deleteForever(note.id) : state.trash(note.id)
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 52)
        .background(WindowDragArea())
        .overlay(alignment: .bottom) { Rectangle().fill(Theme.divider).frame(height: 1) }
        .disabled(note.isTrashed)
    }

    private func trashBanner(_ note: Note) -> some View {
        HStack(spacing: 12) {
            Text("Esta nota está en la Papelera.").font(Theme.body(13)).foregroundStyle(Theme.icon)
            Spacer()
            Button { state.restore(note.id) } label: {
                Text("Restaurar").font(Theme.body(12, weight: .semibold)).foregroundStyle(.black)
                    .padding(.horizontal, 12).frame(height: 26).background(RoundedRectangle(cornerRadius: 4).fill(.white))
            }.buttonStyle(.plain)
            Button { state.deleteForever(note.id) } label: {
                Text("Eliminar").font(Theme.body(12)).foregroundStyle(.white)
                    .padding(.horizontal, 12).frame(height: 26)
                    .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(Color(hex: 0x333333)))
            }.buttonStyle(.plain)
        }
        .padding(.horizontal, 20).padding(.vertical, 10)
        .background(Color(hex: 0x141414))
        .overlay(alignment: .bottom) { Rectangle().fill(Theme.border).frame(height: 1) }
    }

    private func footer(_ note: Note) -> some View {
        let words = note.wordCount
        let nb = state.notebookName(note.notebookId)
        return HStack {
            Text((nb.isEmpty ? "" : nb + " · ") + "Editada " + RelativeDate.short(note.updatedAt.date).lowercased())
            Spacer()
            if copiedNotice {
                Label("Texto copiado al portapapeles", systemImage: "checkmark")
                    .transition(.opacity)
                Spacer()
            }
            Text(words == 1 ? "1 palabra" : "\(words) palabras")
        }
        .font(Theme.body(12)).foregroundStyle(Theme.textMuted)
        .padding(.horizontal, 16)
        .frame(height: 28)
        .overlay(alignment: .top) { Rectangle().fill(Theme.divider).frame(height: 1) }
        .onReceive(NotificationCenter.default.publisher(for: AutoCopy.notification)) { _ in
            withAnimation(.easeOut(duration: 0.15)) { copiedNotice = true }
            noticeTask?.cancel()
            noticeTask = Task {
                try? await Task.sleep(for: .seconds(2))
                guard !Task.isCancelled else { return }
                withAnimation(.easeOut(duration: 0.3)) { copiedNotice = false }
            }
        }
    }
}

/// Envía una acción de formato al editor de texto que tiene el foco.
enum Formatting {
    static func send(_ action: Selector) {
        NSApp.sendAction(action, to: nil, from: nil)
    }
}

/// Acciones de la barra de herramientas, compartidas con los menús.
@MainActor
enum BlockActions {
    static func addTodo(_ s: AppState) {
        let b = Block.todo()
        s.insertBlock(b, focusKey: "todo:\(b.id):0")
    }

    static func addCode(_ s: AppState) {
        let b = Block.code()
        s.insertBlock(b, focusKey: "block:" + b.id)
    }

    static func addImage(_ s: AppState) {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.image]
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        s.addImage(from: url)
    }
}

struct NotebookPicker: View {
    @Environment(AppState.self) private var state
    let note: Note

    var body: some View {
        Menu {
            ForEach(state.notebooks) { nb in
                Button { state.move(note.id, to: nb.id) } label: {
                    if nb.id == note.notebookId { Label(nb.name, systemImage: "checkmark") } else { Text(nb.name) }
                }
            }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: "book.closed").font(.system(size: 12)).foregroundStyle(Theme.icon)
                Text(state.notebookName(note.notebookId).isEmpty ? "Sin libreta" : state.notebookName(note.notebookId))
                    .font(Theme.body(13)).foregroundStyle(.white).lineLimit(1)
                Image(systemName: "chevron.up.chevron.down").font(.system(size: 9)).foregroundStyle(Theme.textMuted)
            }
            .padding(.horizontal, 8).frame(height: 28)
            .overlay(RoundedRectangle(cornerRadius: 5).strokeBorder(Theme.fieldBorder))
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
    }
}

/// Título y bloques.
struct NoteBody: View {
    @Environment(AppState.self) private var state
    let note: Note

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            KeyTextField(text: note.title, placeholder: "Sin título", font: Theme.nsDisplay(42, weight: .bold),
                         focus: isFocused("title"), onFocused: { clearFocus("title") },
                         onChange: { v in state.update(note.id) { $0.title = v } },
                         onSubmit: { focusFirstBlock() },
                         onMoveDown: { focusFirstBlock() })

            ForEach(note.blocks) { block in
                BlockView(note: note, block: block)
            }
        }
        .disabled(note.isTrashed)
    }

    private func isFocused(_ key: String) -> Bool { state.focus == FocusTarget(noteId: note.id, key: key) }
    private func clearFocus(_ key: String) { if isFocused(key) { state.focus = nil } }

    private func focusFirstBlock() { state.moveFocus(from: nil, up: false, in: note.id) }
}

/// ⌘A: si el bloque con el foco ya está seleccionado entero (o vacío), selecciona todos los bloques
/// de la nota. Cada bloque es un campo de texto aparte, así que no hay una selección nativa común.
@MainActor
enum SelectAllMonitor {
    private static var installed = false

    static func install(_ state: AppState) {
        guard !installed else { return }
        installed = true
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            guard event.modifierFlags.intersection(.deviceIndependentFlagsMask) == .command,
                  event.charactersIgnoringModifiers?.lowercased() == "a",
                  let responder = event.window?.firstResponder else { return event }
            let wholeBlock: Bool
            switch responder {
            case is SelectionKeySink.View: return nil
            case is SelectableArea.View: wholeBlock = true
            case let tv as NSTextView where tv is BlockTextView || tv.delegate is KeyTextField.Field:
                wholeBlock = tv.selectedRange().length == tv.string.utf16.count
            default: return event
            }
            guard wholeBlock else { return event }
            state.selectAllBlocks()
            return nil
        }
    }
}

/// Recibe el teclado mientras todos los bloques están seleccionados: copiar, cortar, borrar
/// o escribir encima. Cualquier otro clic o flecha quita la selección.
struct SelectionKeySink: NSViewRepresentable {
    @Environment(AppState.self) private var state
    var active: Bool
    var noteId: String

    final class View: NSView {
        weak var state: AppState?
        var noteId = ""

        override var acceptsFirstResponder: Bool { true }

        override func resignFirstResponder() -> Bool {
            if state?.allSelectedNoteId == noteId { state?.allSelectedNoteId = nil }
            return true
        }

        override func keyDown(with event: NSEvent) { interpretKeyEvents([event]) }

        @objc func copy(_ sender: Any?) {
            guard let state else { return }
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(state.plainText(of: noteId), forType: .string)
        }

        @objc func cut(_ sender: Any?) {
            copy(sender)
            state?.replaceAllBlocks(in: noteId)
        }

        override func selectAll(_ sender: Any?) {}
        override func deleteBackward(_ sender: Any?) { state?.replaceAllBlocks(in: noteId) }
        override func deleteForward(_ sender: Any?) { state?.replaceAllBlocks(in: noteId) }

        override func insertText(_ insertString: Any) {
            let text = (insertString as? NSAttributedString)?.string ?? (insertString as? String) ?? ""
            state?.replaceAllBlocks(in: noteId, with: text)
        }

        private func exit() { window?.makeFirstResponder(nil) }
        override func cancelOperation(_ sender: Any?) { exit() }
        override func moveUp(_ sender: Any?) { exit() }
        override func moveDown(_ sender: Any?) { exit() }
        override func moveLeft(_ sender: Any?) { exit() }
        override func moveRight(_ sender: Any?) { exit() }
        override func insertNewline(_ sender: Any?) { exit() }
        /// Ejecuta las acciones que implementa esta vista; el resto se ignora (sin pitido).
        override func doCommand(by selector: Selector) {
            if responds(to: selector) { perform(selector, with: nil) }
        }
    }

    func makeNSView(context: Context) -> View { View() }

    func updateNSView(_ v: View, context: Context) {
        v.state = state
        v.noteId = noteId
        if active {
            DispatchQueue.main.async {
                guard let window = v.window, window.firstResponder !== v else { return }
                window.makeFirstResponder(v)
            }
        }
    }
}
