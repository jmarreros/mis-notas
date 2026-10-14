import Foundation
import MisNotasCore
import Network
import Observation

/// Decide cuándo sincronizar: al abrir, cada 30 s, 2 s después de cada edición
/// y al recuperar la conexión. Expone el estado para la barra lateral.
@Observable @MainActor
final class SyncCoordinator {
    enum Status: Equatable {
        case notConfigured
        case idle(Date?)
        case syncing
        case offline
        case error(String)
    }

    static let serverURLKey = "serverURL"

    private(set) var status: Status = .notConfigured
    private let state: AppState
    @ObservationIgnored private var engine: SyncEngine?
    @ObservationIgnored private var timer: Timer?
    @ObservationIgnored private var debounce: Task<Void, Never>?
    @ObservationIgnored private var running = false
    @ObservationIgnored private var again = false
    @ObservationIgnored private let monitor = NWPathMonitor()
    @ObservationIgnored private var downloading: Set<String> = []

    init(state: AppState) {
        self.state = state
        state.onLocalChange = { [weak self] in self?.scheduleSoon() }
        monitor.pathUpdateHandler = { [weak self] path in
            guard path.status == .satisfied else { return }
            Task { @MainActor in self?.scheduleSoon(delay: 1) }
        }
        monitor.start(queue: .global(qos: .utility))
        configure()
        timer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            Task { @MainActor in await self?.syncNow() }
        }
    }

    var serverURL: String { UserDefaults.standard.string(forKey: Self.serverURLKey) ?? "" }

    /// Lee servidor y token y prepara el motor. Se llama al iniciar y al guardar los Ajustes.
    func configure() {
        guard let url = URL(string: serverURL.trimmingCharacters(in: .whitespaces)), url.scheme != nil,
              let token = Keychain.token(), !token.isEmpty else {
            engine = nil
            status = .notConfigured
            return
        }
        engine = SyncEngine(repo: state.repo, transport: APIClient(baseURL: url, token: token),
                            attachmentsDirectory: state.attachmentsDirectory)
        status = .idle(nil)
        Task { await syncNow() }
    }

    func scheduleSoon(delay: Double = 2) {
        debounce?.cancel()
        debounce = Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard !Task.isCancelled else { return }
            await self?.syncNow()
        }
    }

    func syncNow() async {
        guard let engine else { return }
        if running { again = true; return }
        running = true
        status = .syncing
        defer { running = false }
        do {
            let result = try await engine.sync()
            if result.pulled > 0 { state.reload() }
            status = .idle(Date())
        } catch let error as URLError where [.notConnectedToInternet, .networkConnectionLost, .cannotConnectToHost,
                                             .cannotFindHost, .timedOut, .dnsLookupFailed].contains(error.code) {
            status = .offline
        } catch {
            status = .error(error.localizedDescription)
        }
        if again {
            again = false
            scheduleSoon(delay: 0.2)
        }
    }

    /// Descarga una imagen creada en otro Mac.
    func fetchAttachment(_ id: String) {
        guard let engine, !downloading.contains(id) else { return }
        downloading.insert(id)
        Task {
            defer { downloading.remove(id) }
            if (try? await engine.fetchAttachment(id: id)) != nil { state.attachmentsVersion += 1 }
        }
    }

    /// Comprueba servidor y token sin modificar nada.
    static func testConnection(url: String, token: String) async -> String {
        guard let base = URL(string: url.trimmingCharacters(in: .whitespaces)), base.scheme != nil else { return "URL no válida." }
        do {
            let r = try await APIClient(baseURL: base, token: token).pull(since: Int.max / 2)
            return "Conexión correcta (revisión \(r.rev))."
        } catch {
            return error.localizedDescription
        }
    }
}
