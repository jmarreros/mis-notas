import AppKit
import MisNotasCore
import SwiftUI

struct BlockView: View {
    @Environment(AppState.self) private var state
    let note: Note
    let block: Block
    @State private var hover = false
    @State private var hoverButton = false

    var body: some View {
        content
            .background {
                if state.allSelectedNoteId == note.id {
                    RoundedRectangle(cornerRadius: 4).fill(Theme.orange.opacity(0.18)).padding(-4)
                }
            }
            .overlay(alignment: .topTrailing) {
                if !block.isText && !note.isTrashed {
                    // Pegada al borde del bloque y siempre presente (solo cambia la opacidad): así el ratón
                    // pasa del bloque a la ✕ sin perder el hover y se puede pulsar.
                    IconButton(systemName: "xmark", help: "Eliminar bloque", size: 9, width: 22, color: Theme.textMuted) {
                        state.removeBlock(block.id, in: note.id)
                    }
                    .padding(.leading, 8)
                    .contentShape(Rectangle())
                    .onHover { hoverButton = $0 }
                    .opacity(hover || hoverButton ? 1 : 0)
                    .alignmentGuide(.trailing) { $0[.leading] }
                    .offset(y: block.type == .todo ? 1 : block.type == .hr ? 0 : -4)
                }
            }
            .onHover { hover = $0 }
            .contextMenu {
                if block.isText {
                    Button(block.type == .h ? "Convertir en párrafo" : "Convertir en encabezado") {
                        state.updateBlock(note.id, block.id) { $0.type = $0.type == .h ? .p : .h }
                    }
                }
                Button("Eliminar bloque", role: .destructive) { state.removeBlock(block.id, in: note.id) }
                    .disabled(note.blocks.count == 1)
            }
    }

    @ViewBuilder
    private var content: some View {
        switch block.type {
        case .p, .h:
            GrowingTextView(value: block.html ?? "", mode: .rich(heading: block.type == .h),
                            placeholder: note.blocks.count == 1 ? "Empieza a escribir…" : "",
                            focus: isFocused("block:" + block.id), focusAtStart: state.focus?.atStart ?? false,
                            onFocused: { focused("block:" + block.id) },
                            onChange: { html in state.updateBlock(note.id, block.id) { $0.html = html } },
                            onDeleteEmpty: note.blocks.count > 1 ? { state.removeBlock(block.id, in: note.id) } : nil,
                            onDivider: { before, after in state.insertDivider(block.id, before: before, after: after, in: note.id) },
                            onMoveUp: { move(up: true) }, onMoveDown: { move(up: false) })
                .padding(.top, block.type == .h ? 10 : 0)
        case .todo: TodoBlockView(note: note, block: block)
        case .code: CodeBlockView(note: note, block: block)
        case .link: LinkBlockView(note: note, block: block)
        case .img: ImageBlockView(note: note, block: block)
        case .hr: DividerBlockView(note: note, block: block)
        }
    }

    private func isFocused(_ key: String) -> Bool { state.focus == FocusTarget(noteId: note.id, key: key) }

    private func move(up: Bool) { state.moveFocus(from: block.id, up: up, in: note.id) }

    private func focused(_ key: String) {
        state.activeBlockId = block.id
        if isFocused(key) { state.focus = nil }
    }
}

/// Utilidades comunes de foco para los bloques.
private extension View {
    func blockFocus(_ state: AppState, note: Note, block: Block, key: String) -> (Bool, () -> Void) {
        let target = FocusTarget(noteId: note.id, key: key)
        return (state.focus == target, {
            state.activeBlockId = block.id
            if state.focus == target { state.focus = nil }
        })
    }
}

/// Lista simple con viñetas. Se guarda como bloque `todo` (sin usar `done`) para no cambiar la API.
struct TodoBlockView: View {
    @Environment(AppState.self) private var state
    let note: Note
    let block: Block

    var body: some View {
        let items = block.items ?? []
        VStack(alignment: .leading, spacing: 2) {
            ForEach(Array(items.enumerated()), id: \.offset) { i, item in
                let key = "todo:\(block.id):\(i)"
                let (focus, onFocused) = blockFocus(state, note: note, block: block, key: key)
                HStack(spacing: 10) {
                    Circle().fill(Color(nsColor: NSColor(hex: 0xE6E6E6))).frame(width: 5, height: 5)
                        .padding(.leading, 4)
                    KeyTextField(text: item.t, placeholder: "Elemento", font: Theme.nsBody(16),
                                 color: NSColor(hex: 0xE6E6E6), focus: focus, onFocused: onFocused,
                                 onChange: { v in update { $0[i].t = v } },
                                 onSubmit: {
                                     if item.t.trimmingCharacters(in: .whitespaces).isEmpty {
                                         state.exitList(block.id, item: i, in: note.id)
                                         return
                                     }
                                     update { $0.insert(TodoItem(t: ""), at: i + 1) }
                                     state.focus = FocusTarget(noteId: note.id, key: "todo:\(block.id):\(i + 1)")
                                 },
                                 onDeleteEmpty: {
                                     if items.count > 1 {
                                         update { $0.remove(at: i) }
                                         state.focus = FocusTarget(noteId: note.id, key: "todo:\(block.id):\(max(0, i - 1))")
                                     } else {
                                         state.removeBlock(block.id, in: note.id)
                                     }
                                 },
                                 onMoveUp: { state.moveFocus(from: block.id, item: i, up: true, in: note.id) },
                                 onMoveDown: { state.moveFocus(from: block.id, item: i, up: false, in: note.id) })
                }
                .frame(maxWidth: .infinity, minHeight: 30, alignment: .leading)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func update(_ change: @escaping (inout [TodoItem]) -> Void) {
        state.updateBlock(note.id, block.id) { b in
            var items = b.items ?? []
            change(&items)
            b.items = items
        }
    }
}

/// Línea horizontal. Se selecciona con un clic y se borra con Retroceso o Suprimir.
struct DividerBlockView: View {
    @Environment(AppState.self) private var state
    let note: Note
    let block: Block
    @State private var selected = false

    var body: some View {
        Rectangle().fill(selected ? Theme.orange : Color(hex: 0x3A3A3A)).frame(height: selected ? 2 : 1)
            .frame(maxWidth: .infinity, minHeight: 28)
            .overlay {
                let target = FocusTarget(noteId: note.id, key: "hr:" + block.id)
                SelectableArea(focus: state.focus == target, onSelect: { on in
                    selected = on
                    if on {
                        state.activeBlockId = block.id
                        if state.focus == target { state.focus = nil }
                    }
                }, onDelete: { state.removeBlock(block.id, in: note.id) },
                   onMove: { up in state.moveFocus(from: block.id, up: up, in: note.id) })
            }
    }
}

/// Zona de AppKit que toma el foco al hacer clic y recibe las teclas de borrado. Con `focusable()` de
/// SwiftUI el editor de texto conservaba el foco y Retroceso nunca llegaba al bloque.
struct SelectableArea: NSViewRepresentable {
    var focus = false
    var onSelect: (Bool) -> Void
    var onDelete: () -> Void
    var onMove: (Bool) -> Void = { _ in }

    final class View: NSView {
        var onSelect: (Bool) -> Void = { _ in }
        var onDelete: () -> Void = {}
        var onMove: (Bool) -> Void = { _ in }

        override var acceptsFirstResponder: Bool { true }
        override func mouseDown(with event: NSEvent) { window?.makeFirstResponder(self) }
        override func becomeFirstResponder() -> Bool { onSelect(true); return true }
        override func resignFirstResponder() -> Bool { onSelect(false); return true }
        override func keyDown(with event: NSEvent) { interpretKeyEvents([event]) }
        override func deleteBackward(_ sender: Any?) { onDelete() }
        override func deleteForward(_ sender: Any?) { onDelete() }
        override func moveUp(_ sender: Any?) { onMove(true) }
        override func moveDown(_ sender: Any?) { onMove(false) }
        override func cancelOperation(_ sender: Any?) { window?.makeFirstResponder(nil) }
    }

    func makeNSView(context: Context) -> View { View() }

    func updateNSView(_ v: View, context: Context) {
        v.onSelect = onSelect
        v.onDelete = onDelete
        v.onMove = onMove
        if focus {
            DispatchQueue.main.async {
                guard let window = v.window, window.firstResponder !== v else { return }
                window.makeFirstResponder(v)
            }
        }
    }
}

struct CodeBlockView: View {
    @Environment(AppState.self) private var state
    let note: Note
    let block: Block
    @State private var copied = false

    var body: some View {
        let (focus, onFocused) = blockFocus(state, note: note, block: block, key: "block:" + block.id)
        VStack(spacing: 0) {
            HStack {
                KeyTextField(text: block.lang ?? "", placeholder: "LENGUAJE", font: Theme.nsBody(11), color: NSColor(hex: 0x888888),
                             onChange: { v in state.updateBlock(note.id, block.id) { $0.lang = v.uppercased() } })
                    .frame(width: 140)
                Spacer()
                Button(copied ? "COPIADO" : "COPIAR") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(block.text ?? "", forType: .string)
                    copied = true
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.4) { copied = false }
                }
                .buttonStyle(.plain)
                .font(Theme.body(11)).tracking(1.3).foregroundStyle(Color(hex: 0xAAAAAA))
            }
            .padding(.horizontal, 12).padding(.vertical, 7)
            .overlay(alignment: .bottom) { Rectangle().fill(Color(hex: 0x1E1E1E)).frame(height: 1) }

            GrowingTextView(value: block.text ?? "", mode: .plain, focus: focus,
                            focusAtStart: state.focus?.atStart ?? false, onFocused: onFocused,
                            onChange: { v in state.updateBlock(note.id, block.id) { $0.text = v } },
                            onMoveUp: { state.moveFocus(from: block.id, up: true, in: note.id) },
                            onMoveDown: { state.moveFocus(from: block.id, up: false, in: note.id) })
                .padding(.horizontal, 14).padding(.vertical, 12)
        }
        .background(RoundedRectangle(cornerRadius: 4).fill(Color(hex: 0x0E0E0E)))
        .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(Color(hex: 0x242424)))
    }
}

struct LinkBlockView: View {
    @Environment(AppState.self) private var state
    let note: Note
    let block: Block
    @State private var hover = false

    var body: some View {
        let (focus, onFocused) = blockFocus(state, note: note, block: block, key: "url:" + block.id)
        HStack(spacing: 14) {
            Image(systemName: "link").font(.system(size: 14, weight: .semibold)).foregroundStyle(Theme.orange)
                .frame(width: 36, height: 36).background(RoundedRectangle(cornerRadius: 4).fill(Theme.field))
            VStack(alignment: .leading, spacing: 2) {
                Text(block.title?.isEmpty == false ? block.title! : "Nuevo enlace")
                    .font(Theme.body(14, weight: .semibold)).foregroundStyle(.white).lineLimit(1)
                    .onTapGesture { open() }
                    .onHover { inside in if inside { NSCursor.pointingHand.push() } else { NSCursor.pop() } }
                KeyTextField(text: block.url ?? "", placeholder: "https://", font: Theme.nsBody(12), color: NSColor(hex: 0x999999),
                             focus: focus, onFocused: onFocused,
                             onChange: { v in
                                 state.updateBlock(note.id, block.id) { b in
                                     // El título sigue al dominio mientras no se haya personalizado.
                                     let auto = b.title == nil || b.title == "Nuevo enlace" || b.title == LinkBlockView.host(b.url ?? "")
                                     b.url = v
                                     if auto { b.title = LinkBlockView.host(v).isEmpty ? "Nuevo enlace" : LinkBlockView.host(v) }
                                 }
                             },
                             onSubmit: { state.focus = nil },
                             onMoveUp: { state.moveFocus(from: block.id, up: true, in: note.id) },
                             onMoveDown: { state.moveFocus(from: block.id, up: false, in: note.id) })
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(hover ? Color(hex: 0x444444) : Theme.fieldBorder))
        .onHover { hover = $0 }
    }

    static func host(_ url: String) -> String {
        var s = url
        for prefix in ["https://", "http://"] where s.hasPrefix(prefix) { s.removeFirst(prefix.count) }
        return String(s.split(separator: "/").first ?? "")
    }

    private func open() {
        var s = (block.url ?? "").trimmingCharacters(in: .whitespaces)
        guard !s.isEmpty else { return }
        if !s.contains("://") { s = "https://" + s }
        if let url = URL(string: s) { NSWorkspace.shared.open(url) }
    }
}

struct ImageBlockView: View {
    @Environment(AppState.self) private var state
    @Environment(SyncCoordinator.self) private var sync
    let note: Note
    let block: Block
    @State private var available: CGFloat = 0
    @State private var liveWidth: CGFloat?
    @State private var dragStart: CGFloat?
    @State private var hover = false

    var body: some View {
        let id = block.attachmentId ?? ""
        let (focus, onFocused) = blockFocus(state, note: note, block: block, key: "caption:" + id)
        VStack(alignment: .leading, spacing: 8) {
            Group {
                if let image = loadImage(id) {
                    resizable(image)
                } else {
                    HatchedRect()
                        .frame(height: 220)
                        .overlay(Text("imagen").font(.system(size: 12, design: .monospaced)).foregroundStyle(Theme.textMuted)
                            .padding(.horizontal, 8).padding(.vertical, 4).background(Color.black))
                        .clipShape(RoundedRectangle(cornerRadius: 4))
                        .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(Color(hex: 0x242424)))
                        .onAppear { if !id.isEmpty { sync.fetchAttachment(id) } }
                }
            }
            KeyTextField(text: block.caption ?? "", placeholder: "Pie de foto", font: Theme.nsBody(12),
                         color: NSColor(hex: 0x999999), focus: focus, onFocused: onFocused,
                         onChange: { v in state.updateBlock(note.id, block.id) { $0.caption = v } },
                         onMoveUp: { state.moveFocus(from: block.id, up: true, in: note.id) },
                         onMoveDown: { state.moveFocus(from: block.id, up: false, in: note.id) })
        }
        .padding(.vertical, 4)
    }

    /// Imagen con asas en las esquinas para cambiar su tamaño manteniendo la proporción.
    @ViewBuilder
    private func resizable(_ image: NSImage) -> some View {
        let aspect = image.size.width > 0 ? image.size.height / image.size.width : 1
        let fitted = available > 0 ? min(available, 420 / max(aspect, 0.01)) : 0
        let width = max(40, min(liveWidth ?? CGFloat(block.width ?? Double(fitted)), max(available, 40)))
        ZStack(alignment: .topLeading) {
            Color.clear.frame(height: 1)
                .background(GeometryReader { geo in Color.clear.onAppear { available = geo.size.width }
                    .onChange(of: geo.size.width) { _, w in available = w } })
            Image(nsImage: image).resizable().scaledToFit()
                .frame(width: width, height: width * aspect)
                .clipShape(RoundedRectangle(cornerRadius: 4))
                .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(Theme.orange, lineWidth: hover || dragStart != nil ? 1 : 0))
                .overlay {
                    if hover || dragStart != nil {
                        handles(width: width, height: width * aspect, current: width)
                    }
                }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .onHover { hover = $0 }
    }

    private func handles(width: CGFloat, height: CGFloat, current: CGFloat) -> some View {
        ZStack {
            ForEach(0..<4, id: \.self) { i in
                let right = i % 2 == 1, bottom = i >= 2
                RoundedRectangle(cornerRadius: 2).fill(Theme.orange)
                    .overlay(RoundedRectangle(cornerRadius: 2).strokeBorder(.white, lineWidth: 1.5))
                    .frame(width: 11, height: 11)
                    .contentShape(Rectangle().inset(by: -5))
                    .position(x: right ? width : 0, y: bottom ? height : 0)
                    .gesture(DragGesture(minimumDistance: 1, coordinateSpace: .global)
                        .onChanged { v in
                            if dragStart == nil { dragStart = current }
                            let dx = right ? v.translation.width : -v.translation.width
                            liveWidth = max(40, min(available, (dragStart ?? current) + dx))
                        }
                        .onEnded { _ in
                            if let w = liveWidth { state.updateBlock(note.id, block.id) { $0.width = Double(w.rounded()) } }
                            liveWidth = nil; dragStart = nil
                        })
                    .onHover { inside in if inside { NSCursor.crosshair.push() } else { NSCursor.pop() } }
            }
        }
        .frame(width: width, height: height)
    }

    private func loadImage(_ id: String) -> NSImage? {
        _ = state.attachmentsVersion
        guard let url = state.localImageURL(id) else { return nil }
        return ImageCache.shared.image(for: url)
    }
}

final class ImageCache {
    static let shared = ImageCache()
    private let cache = NSCache<NSURL, NSImage>()
    func image(for url: URL) -> NSImage? {
        if let img = cache.object(forKey: url as NSURL) { return img }
        guard let img = NSImage(contentsOf: url) else { return nil }
        cache.setObject(img, forKey: url as NSURL)
        return img
    }
}
