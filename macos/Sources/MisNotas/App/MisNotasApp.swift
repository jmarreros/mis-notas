import AppKit
import MisNotasCore
import SwiftUI

@main
struct MisNotasApp: App {
    @NSApplicationDelegateAdaptor private var appDelegate: AppDelegate
    @State private var state: AppState
    @State private var sync: SyncCoordinator

    init() {
        Theme.registerFonts()
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("MisNotas", isDirectory: true)
        let db: AppDatabase
        do { db = try AppDatabase.onDisk(directory: support) }
        catch { fatalError("No se pudo abrir la base de datos local: \(error)") }
        let state = AppState(repo: NotesRepository(db), attachmentsDirectory: support.appendingPathComponent("attachments"))
        _state = State(initialValue: state)
        _sync = State(initialValue: SyncCoordinator(state: state))
    }

    var body: some Scene {
        Window("Mis Notas", id: "main") {
            ContentView()
                .environment(state)
                .environment(sync)
                .frame(minWidth: 900, minHeight: 560)
                .preferredColorScheme(.dark)
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1320, height: 820)
        .commands { AppCommands(state: state, sync: sync) }

        Settings {
            SettingsView()
                .environment(sync)
                .preferredColorScheme(.dark)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Al lanzarse con `swift run` no hay bundle: hay que pedir ser una app normal.
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

struct AppCommands: Commands {
    let state: AppState
    let sync: SyncCoordinator

    var body: some Commands {
        CommandGroup(replacing: .newItem) {
            Button("Nueva nota") { state.newNote() }.keyboardShortcut("n")
            Button("Importar de Evernote…") { state.importOpen = true }.keyboardShortcut("i", modifiers: [.command, .shift])
        }
        CommandGroup(after: .textEditing) {
            Button("Buscar") { state.focusSearchToken += 1 }.keyboardShortcut("f")
        }
        CommandMenu("Formato") {
            Button("Negrita") { Formatting.send(#selector(BlockTextView.mnToggleBold(_:))) }.keyboardShortcut("b")
            Button("Cursiva") { Formatting.send(#selector(BlockTextView.mnToggleItalic(_:))) }.keyboardShortcut("i")
            Button("Subrayado") { Formatting.send(#selector(BlockTextView.mnToggleUnderline(_:))) }.keyboardShortcut("u")
            Divider()
            Button("Encabezado") { state.toggleHeading() }.keyboardShortcut("h", modifiers: [.command, .option])
            Button("Lista") { BlockActions.addTodo(state) }.keyboardShortcut("l", modifiers: [.command, .option])
            Button("Bloque de código") { BlockActions.addCode(state) }.keyboardShortcut("c", modifiers: [.command, .option])
            Button("Enlace") { BlockActions.addLink(state) }.keyboardShortcut("k", modifiers: [.command, .option])
            Button("Imagen…") { BlockActions.addImage(state) }
        }
        CommandMenu("Nota") {
            Button("Mover a la Papelera") { if let id = state.selectedId { state.trash(id) } }
                .keyboardShortcut(.delete, modifiers: .command)
            Divider()
            Button("Mostrar u ocultar barra lateral") { state.sidebarOpen.toggle() }
                .keyboardShortcut("s", modifiers: [.command, .control])
            Button("Sincronizar ahora") { Task { await sync.syncNow() } }
                .keyboardShortcut("r")
        }
    }
}

struct ContentView: View {
    @Environment(AppState.self) private var state

    var body: some View {
        @Bindable var state = state
        ZStack {
            HStack(spacing: 0) {
                if state.sidebarOpen {
                    SidebarView().transition(.move(edge: .leading))
                }
                NoteListView()
                EditorView().frame(maxWidth: .infinity)
            }
            if state.importOpen {
                ImportView()
            }
        }
        .background(Theme.window)
        .ignoresSafeArea()
        .font(Theme.body())
        .foregroundStyle(.white)
        .alert("Error", isPresented: Binding(get: { state.errorMessage != nil }, set: { if !$0 { state.errorMessage = nil } })) {
            Button("Aceptar", role: .cancel) {}
        } message: {
            Text(state.errorMessage ?? "")
        }
    }
}
