import AppKit
import MisNotasCore
import SwiftUI
import UniformTypeIdentifiers

/// Importación de archivos .enex, con las etapas del diseño: elegir → revisar → importar → listo.
struct ImportView: View {
    @Environment(AppState.self) private var state

    private struct ParsedFile: Identifiable {
        let id = UUID()
        let url: URL
        let notes: [EnexNote]
        var name: String { url.lastPathComponent }
    }

    private enum Stage { case pick, parsing, ready, running, done }

    @State private var stage = Stage.pick
    @State private var files: [ParsedFile] = []
    @State private var failures: [String] = []
    @State private var perFile = false
    @State private var progress = 0.0
    @State private var summary = ""
    @State private var targetNav: Nav = .all
    @State private var dropHover = false
    @State private var task: Task<Void, Never>?

    var body: some View {
        ZStack(alignment: .top) {
            Color.black.opacity(0.55).ignoresSafeArea()
                .onTapGesture { if stage != .running { close() } }
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("IMPORTAR DE EVERNOTE").font(Theme.display(24)).foregroundStyle(.white)
                    Text("En Evernote, selecciona una libreta y usa Archivo › Exportar como .enex.")
                        .font(Theme.body(13)).foregroundStyle(Theme.textSoft)
                }
                switch stage {
                case .pick, .parsing: dropZone
                case .ready: review
                case .running: running
                case .done: done
                }
                buttons
            }
            .padding(24)
            .frame(width: 480)
            .background(RoundedRectangle(cornerRadius: 10).fill(Theme.popover))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color(hex: 0x2C2C2C)))
            .shadow(color: .black.opacity(0.6), radius: 30, y: 20)
            .padding(.top, 60)
        }
        .onKeyPress(.escape) { if stage != .running { close() }; return .handled }
    }

    private var dropZone: some View {
        VStack(spacing: 10) {
            if stage == .parsing {
                ProgressView().controlSize(.small)
                Text("Leyendo archivos…").font(Theme.body(13))
            } else {
                Image(systemName: "square.and.arrow.down").font(.system(size: 26, weight: .light))
                Text("Arrastra archivos .enex aquí o haz clic para elegirlos").font(Theme.body(13))
            }
        }
        .foregroundStyle(dropHover ? .white : Color(hex: 0xAAAAAA))
        .frame(maxWidth: .infinity).frame(height: 150)
        .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(dropHover ? Theme.orange : Color(hex: 0x3A3A3A),
                                                               style: StrokeStyle(lineWidth: 1.5, dash: [5, 4])))
        .contentShape(Rectangle())
        .onHover { dropHover = $0 }
        .onTapGesture { pick() }
        .dropDestination(for: URL.self) { urls, _ in
            load(urls.filter { $0.pathExtension.lowercased() == "enex" })
            return true
        } isTargeted: { dropHover = $0 }
    }

    private var review: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(spacing: 0) {
                ForEach(files) { f in
                    HStack {
                        Text(f.name).font(.system(size: 12, design: .monospaced)).lineLimit(1)
                        Spacer()
                        Text(f.notes.count == 1 ? "1 nota" : "\(f.notes.count) notas").foregroundStyle(Color(hex: 0x999999))
                    }
                    .font(Theme.body(13))
                    .padding(.horizontal, 14).padding(.vertical, 10)
                    .overlay(alignment: .bottom) { Rectangle().fill(Theme.border).frame(height: 1) }
                }
                ForEach(failures, id: \.self) { name in
                    Text("\(name): no se pudo leer").font(Theme.body(12)).foregroundStyle(Theme.orange)
                        .padding(.horizontal, 14).padding(.vertical, 8)
                }
            }
            .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(Theme.fieldBorder))
            VStack(alignment: .leading, spacing: 10) {
                option("Crear una libreta por archivo", $perFile)
            }
        }
    }

    private func option(_ title: String, _ value: Binding<Bool>) -> some View {
        HStack(spacing: 10) {
            GradientCheckbox(checked: value.wrappedValue, size: 16)
            Text(title).font(Theme.body(13)).foregroundStyle(.white)
        }
        .contentShape(Rectangle())
        .onTapGesture { value.wrappedValue.toggle() }
    }

    private var running: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Importando notas…").font(Theme.body(13))
                Spacer()
                Text("\(Int(progress * 100))%").font(Theme.body(13)).foregroundStyle(Theme.textMuted)
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color(hex: 0x262626))
                    Capsule().fill(Theme.gradient).frame(width: geo.size.width * progress)
                }
            }
            .frame(height: 6)
        }
        .foregroundStyle(.white)
    }

    private var done: some View {
        HStack(spacing: 10) {
            Image(systemName: "checkmark.circle.fill").foregroundStyle(Theme.gradient).font(.system(size: 18))
            Text(summary).font(Theme.body(13)).foregroundStyle(.white)
        }
    }

    private var buttons: some View {
        HStack(spacing: 8) {
            Spacer()
            if stage != .done {
                secondary("Cancelar") { task?.cancel(); close() }
            }
            switch stage {
            case .ready: primary("Importar", disabled: files.isEmpty) { runImport() }
            case .done: primary("Ver notas") { state.select(nav: targetNav); close() }
            default: EmptyView()
            }
        }
    }

    private func primary(_ title: String, disabled: Bool = false, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(Theme.body(13, weight: .semibold)).foregroundStyle(.black)
                .padding(.horizontal, 16).frame(height: 32)
                .background(RoundedRectangle(cornerRadius: 4).fill(.white))
        }
        .buttonStyle(.plain).disabled(disabled).opacity(disabled ? 0.4 : 1)
        .keyboardShortcut(.defaultAction)
    }

    private func secondary(_ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(Theme.body(13)).foregroundStyle(.white)
                .padding(.horizontal, 16).frame(height: 32)
                .overlay(RoundedRectangle(cornerRadius: 4).strokeBorder(Color(hex: 0x333333)))
        }
        .buttonStyle(.plain)
    }

    private func close() { state.importOpen = false }

    private func pick() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [UTType(filenameExtension: "enex") ?? .xml]
        panel.allowsMultipleSelection = true
        guard panel.runModal() == .OK else { return }
        load(panel.urls)
    }

    private func load(_ urls: [URL]) {
        guard !urls.isEmpty else { return }
        stage = .parsing
        Task {
            let results = await Task.detached(priority: .userInitiated) {
                urls.map { url in (url, try? EnexParser.parse(url: url)) }
            }.value
            files = results.compactMap { url, notes in notes.map { ParsedFile(url: url, notes: $0) } }
            failures = results.filter { $0.1 == nil }.map { $0.0.lastPathComponent }
            stage = files.isEmpty && failures.isEmpty ? .pick : .ready
        }
    }

    private func runImport() {
        stage = .running
        progress = 0
        let total = max(1, files.reduce(0) { $0 + $1.notes.count })
        task = Task {
            var imported = 0
            var notebookIds: [String] = []
            for file in files {
                let name = perFile ? file.url.deletingPathExtension().lastPathComponent : "Importado de Evernote"
                guard let nb = state.createNotebook(named: name) else { continue }
                if !notebookIds.contains(nb.id) { notebookIds.append(nb.id) }
                // Lotes pequeños para que la barra de progreso avance.
                for chunk in stride(from: 0, to: file.notes.count, by: 40).map({ Array(file.notes[$0..<min($0 + 40, file.notes.count)]) }) {
                    if Task.isCancelled { return }
                    let notes = chunk.map { e -> Note in
                        let created = e.created ?? .now
                        var blocks = e.blocks
                        if blocks.last?.type != .p { blocks.append(.paragraph()) }
                        return Note(notebookId: nb.id, title: e.title, blocks: blocks,
                                    createdAt: created, updatedAt: e.updated ?? created)
                    }
                    do { try state.repo.insert(notes: notes, notebooks: []) } catch { state.errorMessage = error.localizedDescription; return }
                    imported += notes.count
                    progress = Double(imported) / Double(total)
                    await Task.yield()
                }
            }
            state.reload()
            state.onLocalChange()
            targetNav = notebookIds.count == 1 ? .notebook(notebookIds[0]) : .all
            let nbText = notebookIds.count == 1 ? "1 libreta" : "\(notebookIds.count) libretas"
            summary = (imported == 1 ? "1 nota importada" : "\(imported) notas importadas") + " en " + nbText + "."
            stage = .done
        }
    }
}
