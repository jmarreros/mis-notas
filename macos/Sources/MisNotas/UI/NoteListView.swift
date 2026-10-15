import MisNotasCore
import SwiftUI

struct NoteListView: View {
    @Environment(AppState.self) private var state
    @FocusState private var searchFocused: Bool
    @State private var nbMenuOpen = false

    var body: some View {
        @Bindable var state = state
        let list = state.list

        VStack(spacing: 0) {
            HStack(spacing: 8) {
                if !state.sidebarOpen {
                    // Hueco para los botones de la ventana.
                    Color.clear.frame(width: 62, height: 1)
                    IconButton(systemName: "sidebar.left", help: "Mostrar barra lateral", color: Color(hex: 0x999999)) {
                        withAnimation(.easeOut(duration: 0.18)) { state.sidebarOpen = true }
                    }
                }
                HStack(spacing: 7) {
                    Image(systemName: "magnifyingglass").font(.system(size: 12))
                    TextField("", text: $state.query, prompt: Text("Buscar  ⌘F").foregroundStyle(Theme.textMuted))
                        .textFieldStyle(.plain)
                        .font(Theme.body(13))
                        .foregroundStyle(.white)
                        .focused($searchFocused)
                        .onKeyPress(.escape) {
                            state.query = ""
                            searchFocused = false
                            return .handled
                        }
                    if state.isSearching {
                        Button { state.query = "" } label: {
                            Image(systemName: "xmark").font(.system(size: 7, weight: .bold)).foregroundStyle(.black)
                                .frame(width: 16, height: 16).background(Circle().fill(Color(hex: 0x555555)))
                        }
                        .buttonStyle(.plain)
                    }
                }
                .foregroundStyle(Theme.textMuted)
                .padding(.horizontal, 9)
                .frame(height: 30)
                .background(RoundedRectangle(cornerRadius: 6).fill(Theme.field))
                .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Theme.fieldBorder))
                IconButton(systemName: "square.and.pencil", help: "Nueva nota  ⌘N", size: 15, width: 32) { state.newNote() }
            }
            .padding(.horizontal, 12)
            .frame(height: 52)
            .background(WindowDragArea())

            header(list.count)

            if list.isEmpty {
                Text(emptyText)
                    .font(Theme.body(13)).foregroundStyle(Theme.textMuted).multilineTextAlignment(.center)
                    .padding(.horizontal, 16).padding(.top, 48)
                Spacer()
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 2) {
                            ForEach(list) { note in
                                NoteRow(note: note, active: note.id == state.selectedId)
                                    .id(note.id)
                                    .onTapGesture { state.select(note: note.id) }
                                    .draggable(note.id)
                                    .contextMenu { rowMenu(note) }
                            }
                        }
                        .padding(.horizontal, 8).padding(.vertical, 6)
                    }
                    .onChange(of: state.selectedId) { _, id in
                        if let id { withAnimation { proxy.scrollTo(id) } }
                    }
                }
            }
        }
        .frame(width: 330)
        .overlay(alignment: .trailing) { Rectangle().fill(Theme.border).frame(width: 1) }
        .onChange(of: state.focusSearchToken) { _, _ in searchFocused = true }
    }

    private var emptyText: String {
        if state.isSearching { return "Nada coincide con «\(state.trimmedQuery)»." }
        if state.nav == .trash { return "La Papelera está vacía." }
        return "No hay notas aquí. Pulsa ⌘N para crear una."
    }

    @ViewBuilder
    private func header(_ count: Int) -> some View {
        @Bindable var state = state
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                HStack(spacing: 6) {
                    Text(state.isSearching ? "Resultados" : state.navLabel(state.nav))
                        .font(Theme.display(26)).textCase(.uppercase).lineLimit(1).foregroundStyle(.white)
                    if !state.sidebarOpen && !state.isSearching {
                        Image(systemName: "chevron.down").font(.system(size: 11, weight: .semibold)).foregroundStyle(Theme.textMuted)
                    }
                }
                .contentShape(Rectangle())
                .onTapGesture { if !state.sidebarOpen && !state.isSearching { nbMenuOpen.toggle() } }
                .help(state.sidebarOpen ? "" : "Cambiar de libreta")
                .popover(isPresented: $nbMenuOpen, arrowEdge: .bottom) { notebookMenu }
                Spacer()
                Text(count == 1 ? "1 nota" : "\(count) notas").font(Theme.body(12)).foregroundStyle(Color(hex: 0x999999))
            }
            if state.isSearching {
                HStack(spacing: 0) {
                    scopeButton("Todas las notas", .all)
                    scopeButton(state.nav == .all ? "Vista actual" : state.navLabel(state.nav), .current)
                }
                .padding(2)
                .background(RoundedRectangle(cornerRadius: 6).fill(Color(hex: 0x151515)))
                .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Color(hex: 0x262626)))
            }
        }
        .padding(.horizontal, 18).padding(.top, 10).padding(.bottom, 14)
        .overlay(alignment: .bottom) { Rectangle().fill(Theme.divider).frame(height: 1) }
    }

    private func scopeButton(_ title: String, _ scope: SearchScope) -> some View {
        let on = state.scope == scope
        return Text(title)
            .font(Theme.body(12, weight: .medium)).lineLimit(1)
            .foregroundStyle(on ? Color.black : Color(hex: 0xBBBBBB))
            .frame(maxWidth: .infinity, minHeight: 24)
            .background(RoundedRectangle(cornerRadius: 4).fill(on ? Color.white : .clear))
            .contentShape(Rectangle())
            .onTapGesture { state.scope = scope }
    }

    private var notebookMenu: some View {
        VStack(alignment: .leading, spacing: 1) {
            menuItem("Todas las notas", state.liveNotes.count, state.nav == .all) { state.select(nav: .all) }
            ForEach(state.notebooks) { nb in
                menuItem(nb.name, state.count(in: nb), state.nav == .notebook(nb.id)) { state.select(nav: .notebook(nb.id)) }
            }
            Rectangle().fill(Color(hex: 0x262626)).frame(height: 1).padding(.vertical, 4)
            HoverRow {
                nbMenuOpen = false
                state.sidebarOpen = true
            } label: { Text("Mostrar barra lateral").font(Theme.body(13)) }
        }
        .padding(5)
        .frame(width: 240)
        .background(Theme.popover)
    }

    private func menuItem(_ title: String, _ count: Int, _ on: Bool, action: @escaping () -> Void) -> some View {
        NavRow(icon: "book.closed", title: title, count: count, active: on) {
            action()
            nbMenuOpen = false
        }
    }

    @ViewBuilder
    private func rowMenu(_ note: Note) -> some View {
        if note.isTrashed {
            Button("Restaurar") { state.restore(note.id) }
            Button("Eliminar definitivamente", role: .destructive) { state.deleteForever(note.id) }
        } else {
            Menu("Mover a") {
                ForEach(state.notebooks) { nb in
                    Button(nb.name) { state.move(note.id, to: nb.id) }.disabled(nb.id == note.notebookId)
                }
            }
            Button("Mover a la Papelera") { state.trash(note.id) }
        }
    }
}

struct NoteRow: View {
    @Environment(AppState.self) private var state
    let note: Note
    let active: Bool

    var body: some View {
        let q = state.trimmedQuery
        let text = note.bodyText
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Highlighted(text: note.title.isEmpty ? "Sin título" : note.title, query: q)
                    .font(Theme.body(14, weight: .semibold)).foregroundStyle(.white).lineLimit(1)
                Highlighted(text: snippet(text, q), query: q)
                    .font(Theme.body(13)).foregroundStyle(Theme.textSoft).lineLimit(2).lineSpacing(2)
                HStack(spacing: 8) {
                    Text(RelativeDate.short(note.updatedAt.date)).fixedSize()
                    Text(meta).lineLimit(1).truncationMode(.tail)
                }
                .font(Theme.body(12)).foregroundStyle(Theme.textMuted)
            }
            Spacer(minLength: 0)
            if let thumb = thumbnail {
                Image(nsImage: thumb).resizable().scaledToFill().frame(width: 46, height: 46)
                    .clipShape(RoundedRectangle(cornerRadius: 4))
                    .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(Theme.fieldBorder))
            } else if note.hasImage {
                HatchedRect(spacing: 6).frame(width: 46, height: 46)
                    .clipShape(RoundedRectangle(cornerRadius: 4))
                    .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(Theme.fieldBorder))
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 11)
        .background {
            if active {
                RoundedRectangle(cornerRadius: 6).fill(Color(hex: 0x1A1A1A))
                    .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Theme.gradient, lineWidth: 1))
            }
        }
        .contentShape(Rectangle())
    }

    private var meta: String {
        var parts: [String] = []
        if case .notebook = state.nav, !state.isSearching {} else {
            let nb = state.notebookName(note.notebookId)
            if !nb.isEmpty { parts.append(nb) }
        }
        return parts.joined(separator: "  ")
    }

    private func snippet(_ text: String, _ q: String) -> String {
        guard !text.isEmpty else { return "Sin contenido" }
        if !q.isEmpty, let r = text.range(of: q, options: [.caseInsensitive, .diacriticInsensitive]),
           text.distance(from: text.startIndex, to: r.lowerBound) > 50 {
            let start = text.index(r.lowerBound, offsetBy: -40)
            return "…" + text[start...].prefix(160)
        }
        return String(text.prefix(160))
    }

    private var thumbnail: NSImage? {
        _ = state.attachmentsVersion
        guard let id = note.blocks.first(where: { $0.type == .img })?.attachmentId,
              let url = state.localImageURL(id) else { return nil }
        return ThumbnailCache.shared.image(for: url)
    }
}

/// Texto con las coincidencias de la búsqueda resaltadas en amarillo.
struct Highlighted: View {
    let text: String
    let query: String

    var body: some View {
        Text(attributed)
    }

    private var attributed: AttributedString {
        var a = AttributedString(text)
        let terms = query.split(separator: " ").map(String.init).filter { !$0.isEmpty }
        guard !terms.isEmpty else { return a }
        for term in terms {
            var searchStart = text.startIndex
            while let r = text.range(of: term, options: [.caseInsensitive, .diacriticInsensitive], range: searchStart..<text.endIndex) {
                if let lower = AttributedString.Index(r.lowerBound, within: a), let upper = AttributedString.Index(r.upperBound, within: a) {
                    a[lower..<upper].backgroundColor = Theme.yellow
                    a[lower..<upper].foregroundColor = .black
                }
                searchStart = r.upperBound
            }
        }
        return a
    }
}

/// Fondo rayado del diseño para imágenes sin cargar.
struct HatchedRect: View {
    var spacing: CGFloat = 10
    var body: some View {
        Canvas { ctx, size in
            ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(Color(hex: 0x121212)))
            var x: CGFloat = -size.height
            while x < size.width {
                var p = Path()
                p.move(to: CGPoint(x: x, y: size.height))
                p.addLine(to: CGPoint(x: x + size.height, y: 0))
                ctx.stroke(p, with: .color(Color(hex: 0x1A1A1A)), lineWidth: spacing)
                x += spacing * 2
            }
        }
    }
}

final class ThumbnailCache {
    static let shared = ThumbnailCache()
    private let cache = NSCache<NSURL, NSImage>()

    func image(for url: URL) -> NSImage? {
        if let img = cache.object(forKey: url as NSURL) { return img }
        guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
              let cg = CGImageSourceCreateThumbnailAtIndex(src, 0, [
                  kCGImageSourceCreateThumbnailFromImageAlways: true,
                  kCGImageSourceThumbnailMaxPixelSize: 120,
                  kCGImageSourceCreateThumbnailWithTransform: true,
              ] as CFDictionary) else { return nil }
        let img = NSImage(cgImage: cg, size: NSSize(width: cg.width / 2, height: cg.height / 2))
        cache.setObject(img, forKey: url as NSURL)
        return img
    }
}

enum RelativeDate {
    private static let es = Locale(identifier: "es_ES")

    /// Como en el diseño: hora si es de hoy, «Ayer», día de la semana o «12 oct».
    static func short(_ date: Date, now: Date = Date()) -> String {
        let cal = Calendar.current
        let days = cal.dateComponents([.day], from: cal.startOfDay(for: date), to: cal.startOfDay(for: now)).day ?? 0
        switch days {
        case 0: return date.formatted(Date.FormatStyle(date: .omitted, time: .shortened).locale(es))
        case 1: return "Ayer"
        case 2..<7: return date.formatted(Date.FormatStyle().weekday(.wide).locale(es)).capitalized(with: es)
        default:
            var style = Date.FormatStyle().day().month(.abbreviated).locale(es)
            if !cal.isDate(date, equalTo: now, toGranularity: .year) { style = style.year() }
            return date.formatted(style)
        }
    }
}
