import SwiftUI

/// Ajustes del servidor: dirección de la API, token, estado y desconexión.
/// Al cambiar de servidor, la app vuelve a enviar todas las notas para que el nuevo quede completo.
struct SettingsView: View {
    @Environment(SyncCoordinator.self) private var sync
    @State private var url = UserDefaults.standard.string(forKey: SyncCoordinator.serverURLKey) ?? ""
    @State private var token = Keychain.token() ?? ""
    @State private var message = ""
    @State private var testing = false
    @State private var confirmDisconnect = false

    private var savedURL: String { UserDefaults.standard.string(forKey: SyncCoordinator.serverURLKey) ?? "" }
    private var hasChanges: Bool {
        SyncCoordinator.normalize(url) != savedURL || token.trimmingCharacters(in: .whitespacesAndNewlines) != (Keychain.token() ?? "")
    }

    var body: some View {
        Form {
            Section {
                TextField("Servidor", text: $url, prompt: Text("https://notas.tudominio.com"))
                SecureField("Token", text: $token, prompt: Text("Pega el token de misnotas:token"))
            } header: {
                Text("Servidor")
            } footer: {
                VStack(alignment: .leading, spacing: 4) {
                    Text("La dirección base de la API, sin `/api`. Para probar en local: `http://127.0.0.1:8000`.")
                    Text("Genera el token en el servidor con `php artisan misnotas:token tu@correo.com`.")
                }
                .font(.caption).foregroundStyle(.secondary)
            }

            Section("Estado") {
                if case .notConfigured = sync.status {
                    Text("Sin servidor: las notas solo se guardan en este Mac.").foregroundStyle(.secondary)
                } else {
                    LabeledContent("Conectado a", value: savedURL)
                    SyncStatusRow()
                }
            }

            HStack {
                Button("Probar conexión") {
                    testing = true
                    message = "Probando…"
                    Task {
                        message = await SyncCoordinator.testConnection(url: url, token: token)
                        testing = false
                    }
                }
                .disabled(testing || url.isEmpty || token.isEmpty)

                if !savedURL.isEmpty {
                    Button("Desconectar", role: .destructive) { confirmDisconnect = true }
                }
                Spacer()
                Button("Guardar y conectar") {
                    let changingServer = !savedURL.isEmpty && hasChanges
                    sync.save(url: url, token: token)
                    url = savedURL
                    message = changingServer
                        ? "Guardado. Se enviarán todas las notas al servidor nuevo."
                        : "Guardado."
                }
                .keyboardShortcut(.defaultAction)
                .disabled(url.isEmpty || token.isEmpty || !hasChanges)
            }
            if !message.isEmpty {
                Text(message).font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
            }
        }
        .formStyle(.grouped)
        .frame(width: 480)
        .padding(.vertical, 8)
        .confirmationDialog("¿Desconectar del servidor?", isPresented: $confirmDisconnect) {
            Button("Desconectar", role: .destructive) {
                sync.disconnect()
                url = ""
                token = ""
                message = "Desconectado. Tus notas siguen en este Mac."
            }
        } message: {
            Text("Las notas no se borran: siguen en este Mac y se enviarán cuando vuelvas a conectar.")
        }
    }
}
