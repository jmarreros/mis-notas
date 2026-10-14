import Foundation

public struct PullResponse: Codable {
    public var rev: Int
    public var notebooks: [Notebook]
    public var notes: [Note]
}

public struct PushResponse: Codable {
    public var rev: Int
    /// Registros rechazados porque el servidor tiene una versión más reciente.
    public var notebooks: [Notebook]
    public var notes: [Note]
}

/// Lo que el `SyncEngine` necesita del servidor.
public protocol SyncTransport {
    func pull(since: Int) async throws -> PullResponse
    func push(notebooks: [Notebook], notes: [Note]) async throws -> PushResponse
    func upload(attachment: Attachment, data: Data) async throws
    func download(attachmentId: String) async throws -> Data
}

public enum APIError: LocalizedError {
    case notConfigured
    case unauthorized
    case http(Int, String)

    public var errorDescription: String? {
        switch self {
        case .notConfigured: return "Configura el servidor en Ajustes."
        case .unauthorized: return "Token no válido."
        case let .http(code, msg): return "Error del servidor (\(code)): \(msg)"
        }
    }
}

public final class APIClient: SyncTransport {
    public let baseURL: URL
    private let token: String
    private let session: URLSession

    public init(baseURL: URL, token: String, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.token = token
        self.session = session
    }

    static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()

    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private func request(_ path: String, method: String = "GET") -> URLRequest {
        var r = URLRequest(url: baseURL.appendingPathComponent("api").appendingPathComponent(path))
        r.httpMethod = method
        r.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        r.setValue("application/json", forHTTPHeaderField: "Accept")
        r.timeoutInterval = 30
        return r
    }

    private func send(_ r: URLRequest) async throws -> Data {
        let (data, response) = try await session.data(for: r)
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        if code == 401 { throw APIError.unauthorized }
        guard (200..<300).contains(code) else {
            let msg = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["message"] as? String
            throw APIError.http(code, msg ?? HTTPURLResponse.localizedString(forStatusCode: code))
        }
        return data
    }

    public func pull(since: Int) async throws -> PullResponse {
        var r = request("sync")
        r.url = URL(string: r.url!.absoluteString + "?since=\(since)")
        return try Self.decoder.decode(PullResponse.self, from: try await send(r))
    }

    private struct PushBody: Encodable {
        let notebooks: [Notebook]
        let notes: [Note]
    }

    public func push(notebooks: [Notebook], notes: [Note]) async throws -> PushResponse {
        var r = request("sync", method: "POST")
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try Self.encoder.encode(PushBody(notebooks: notebooks, notes: notes))
        return try Self.decoder.decode(PushResponse.self, from: try await send(r))
    }

    public func upload(attachment: Attachment, data: Data) async throws {
        var r = request("attachments", method: "POST")
        let boundary = "mn-\(UUID().uuidString)"
        r.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data()
        func field(_ name: String, _ value: String) {
            body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".data(using: .utf8)!)
        }
        field("id", attachment.id)
        if let noteId = attachment.noteId { field("note_id", noteId) }
        body.append("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"\(attachment.fileName)\"\r\nContent-Type: \(attachment.mime)\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        r.httpBody = body
        r.timeoutInterval = 120
        _ = try await send(r)
    }

    public func download(attachmentId: String) async throws -> Data {
        try await send(request("attachments/\(attachmentId)"))
    }
}
