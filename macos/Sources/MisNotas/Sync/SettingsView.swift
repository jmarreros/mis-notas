import SwiftUI

struct SettingsView: View {
    @Environment(SyncCoordinator.self) private var sync
    @State private var url = UserDefaults.standard.string(forKey: SyncCoordinator.serverURLKey) ?? ""
    @State private var token = Keychain.token() ?? ""
    @State private var message = ""
    @State private var testing = false

    var body: some View {
        Form {
            Section {
                TextField("Servidor", text: $url, prompt: Text("https://notas.tudominio.com"))
                SecureField("Token", text: $token, prompt: Text("Pega el token de misnotas:token"))
            } footer: {
                Text("Genera el token en el servidor con `php artisan misnotas:token tu@correo.com`.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            HStack {
                Button("Probar conexión") {
                    testing = true
                    Task {
                        message = await SyncCoordinator.testConnection(url: url, token: token)
                        testing = false
                    }
                }
                .disabled(testing || url.isEmpty || token.isEmpty)
                Spacer()
                Button("Guardar") {
                    UserDefaults.standard.set(url.trimmingCharacters(in: .whitespaces), forKey: SyncCoordinator.serverURLKey)
                    Keychain.setToken(token.trimmingCharacters(in: .whitespacesAndNewlines))
                    sync.configure()
                    message = "Guardado."
                }
                .keyboardShortcut(.defaultAction)
            }
            if !message.isEmpty {
                Text(message).font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
            }
        }
        .formStyle(.grouped)
        .frame(width: 460)
        .padding(.vertical, 8)
    }
}
