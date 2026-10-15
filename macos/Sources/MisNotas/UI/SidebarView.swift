import MisNotasCore
import SwiftUI

struct SidebarView: View {
    @Environment(AppState.self) private var state
    @Environment(SyncCoordinator.self) private var sync
    @State private var creatingNotebook = false
    @State private var newNotebookName = ""
    @State private var renaming: Notebook?
    @State private var renamingTag: String?
    @State private var renameText = ""
    @State private var deleting: Notebook?

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Spacer()
                IconButton(systemName: "sidebar.left", help: "Ocultar barra lateral", color: Color(hex: 0x999999)) {
                    withAnimation(.easeOut(duration: 0.18)) { state.sidebarOpen = false }
                }
            }
            .padding(.leading, 16).padding(.trailing, 12)
            .frame(height: 52)
            .background(WindowDragArea())

            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    NavRow(icon: "doc.text", title: "Todas las notas", count: state.liveNotes.count,
                           active: isActive(.all), height: 30, weight: .medium) { state.select(nav: .all) }

                    section("LIBRETAS", trailing: AnyView(
                        IconButton(systemName: "plus", help: "Nueva libreta", size: 11, width: 22, color: Theme.textMuted) {
                            newNotebookName = ""
                            creatingNotebook = true
                        })) {
                        ForEach(state.notebooks) { nb in
                            NavRow(icon: "book.closed", title: nb.name, count: state.count(in: nb),
                                   active: isActive(.notebook(nb.id))) {
                                state.select(nav: .notebook(nb.id))
                            }
                            .dropDestination(for: String.self) { ids, _ in
                                ids.forEach { state.move($0, to: nb.id) }
                                return !ids.isEmpty
                            }
                            .contextMenu {
                                Button("Renombrar…") { renameText = nb.name; renaming = nb }
                                Button("Eliminar…", role: .destructive) { deleting = nb }
                            }
                        }
                    }

                    let tags = state.tagCounts
                    if !tags.isEmpty {
                        section("ETIQUETAS") {
                            ForEach(tags, id: \.name) { tag in
                                NavRow(icon: "number", title: tag.name, count: tag.count, active: isActive(.tag(tag.name))) {
                                    state.select(nav: .tag(tag.name))
                                }
                                .contextMenu {
                                    Button("Renombrar…") { renameText = tag.name; renamingTag = tag.name }
                                    Button("Quitar de todas las notas", role: .destructive) { state.renameTag(tag.name, to: nil) }
                                }
                            }
                        }
                    }
                }
                .padding(.horizontal, 10).padding(.top, 4).padding(.bottom, 12)
            }

            VStack(alignment: .leading, spacing: 2) {
                NavRow(icon: "trash", title: "Papelera", count: state.trashCount, active: isActive(.trash)) {
                    state.select(nav: .trash)
                }
                .contextMenu {
                    Button("Vaciar Papelera", role: .destructive) { state.emptyTrash() }.disabled(state.trashCount == 0)
                }
                HoverRow { state.importOpen = true } label: {
                    Image(systemName: "square.and.arrow.down").frame(width: 16)
                    Text("Importar de Evernote…")
                }
                HStack(spacing: 0) {
                    SyncStatusRow()
                    SettingsLink {
                        Image(systemName: "gearshape").font(.system(size: 12)).foregroundStyle(Theme.textMuted)
                            .frame(width: 26, height: 24).contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .help("Servidor y sincronización  ⌘,")
                }
            }
            .padding(.horizontal, 10).padding(.vertical, 8)
            .overlay(alignment: .top) { Rectangle().fill(Theme.border).frame(height: 1) }
        }
        .frame(width: 232)
        .background(Theme.sidebar)
        .overlay(alignment: .trailing) { Rectangle().fill(Theme.border).frame(width: 1) }
        .alert("Nueva libreta", isPresented: $creatingNotebook) {
            TextField("Nombre", text: $newNotebookName)
            Button("Crear") {
                if let nb = state.createNotebook(named: newNotebookName) { state.select(nav: .notebook(nb.id)) }
            }
            Button("Cancelar", role: .cancel) {}
        }
        .alert("Renombrar libreta", isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
            TextField("Nombre", text: $renameText)
            Button("Renombrar") { if let nb = renaming { state.rename(nb, to: renameText) } }
            Button("Cancelar", role: .cancel) {}
        }
        .alert("Renombrar etiqueta", isPresented: Binding(get: { renamingTag != nil }, set: { if !$0 { renamingTag = nil } })) {
            TextField("Nombre", text: $renameText)
            Button("Renombrar") { if let t = renamingTag { state.renameTag(t, to: renameText) } }
            Button("Cancelar", role: .cancel) {}
        }
        .alert("¿Eliminar la libreta «\(deleting?.name ?? "")»?", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } })) {
            Button("Eliminar", role: .destructive) { if let nb = deleting { state.delete(nb) } }
            Button("Cancelar", role: .cancel) {}
        } message: {
            Text("Sus notas se moverán a la Papelera.")
        }
    }

    private func isActive(_ nav: Nav) -> Bool { !state.isSearching && state.nav == nav }

    private func section<Content: View>(_ title: String, trailing: AnyView? = nil, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text(title).font(Theme.body(11, weight: .medium)).tracking(1.3).foregroundStyle(Theme.textMuted)
                Spacer()
                trailing
            }
            .frame(height: 22)
            .padding(.leading, 9).padding(.bottom, 2)
            content()
        }
    }
}

struct NavRow: View {
    let icon: String
    let title: String
    let count: Int
    let active: Bool
    var height: CGFloat = 28
    var weight: Font.Weight = .regular
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        HStack(spacing: 9) {
            Image(systemName: icon).font(.system(size: 13)).frame(width: 16)
            Text(title).font(Theme.body(14, weight: weight)).lineLimit(1).truncationMode(.tail)
            Spacer(minLength: 4)
            Text("\(count)").font(Theme.body(12)).foregroundStyle(active ? Theme.textSoft : Theme.textMuted)
        }
        .foregroundStyle(active ? Color.white : Theme.text)
        .padding(.horizontal, 9)
        .frame(height: height)
        .background(RoundedRectangle(cornerRadius: 5).fill(active ? Color(hex: 0x2A2A2A) : hover ? Color(hex: 0x1C1C1C) : .clear))
        .contentShape(Rectangle())
        .onTapGesture(perform: action)
        .onHover { hover = $0 }
    }
}

struct HoverRow<Label: View>: View {
    let action: () -> Void
    @ViewBuilder let label: () -> Label
    @State private var hover = false

    var body: some View {
        HStack(spacing: 9) { label() }
            .font(Theme.body(14))
            .foregroundStyle(hover ? .white : Color(hex: 0xBBBBBB))
            .padding(.horizontal, 9)
            .frame(maxWidth: .infinity, minHeight: 28, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 5).fill(hover ? Color(hex: 0x1C1C1C) : .clear))
            .contentShape(Rectangle())
            .onTapGesture(perform: action)
            .onHover { hover = $0 }
    }
}

struct SyncStatusRow: View {
    @Environment(SyncCoordinator.self) private var sync

    var body: some View {
        switch sync.status {
        case .notConfigured:
            SettingsLink {
                row("icloud.slash", "Configurar servidor…", Theme.orange)
            }
            .buttonStyle(.plain)
        default:
            row(icon, text, color)
                .contentShape(Rectangle())
                .onTapGesture { Task { await sync.syncNow() } }
                .help("Sincronizar ahora")
        }
    }

    private func row(_ icon: String, _ text: String, _ color: Color) -> some View {
        HStack(spacing: 7) {
            Image(systemName: icon).font(.system(size: 11)).frame(width: 16)
            Text(text).lineLimit(1)
        }
        .font(Theme.body(11.5))
        .foregroundStyle(color)
        .padding(.horizontal, 9)
        .frame(maxWidth: .infinity, minHeight: 24, alignment: .leading)
    }

    private var icon: String {
        switch sync.status {
        case .syncing: return "arrow.triangle.2.circlepath"
        case .offline: return "wifi.slash"
        case .error: return "exclamationmark.triangle"
        default: return "checkmark.icloud"
        }
    }

    private var text: String {
        switch sync.status {
        case .syncing: return "Sincronizando…"
        case .offline: return "Sin conexión: cambios guardados en este Mac"
        case let .error(msg): return msg
        case let .idle(date?): return "Sincronizado " + date.formatted(.relative(presentation: .named, unitsStyle: .wide))
        default: return "Sincronizado"
        }
    }

    private var color: Color {
        switch sync.status {
        case .error: return Theme.orange
        case .offline: return Theme.yellow
        default: return Color(hex: 0x666666)
        }
    }
}
