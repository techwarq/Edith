import Foundation

enum SSEEvent {
    case transcript(String)
    case status(String)
    case text(String)
    case session(String)
    case voiceEnabled(Bool)
    case error(String)
}

enum BackendError: Error {
    case noToken
    case http(Int, String)
}

final class BackendClient: @unchecked Sendable {
    private let baseURL: URL
    private let token: String

    init(baseURL: String = Config.serverURL, token: String = Config.apiToken) {
        self.baseURL = URL(string: baseURL)!
        self.token = token
    }

    func connect() async throws -> String {
        guard !token.isEmpty else { throw BackendError.noToken }
        var request = URLRequest(url: baseURL.appendingPathComponent("api/connect"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["token": token])

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            throw BackendError.http(status, "connect failed")
        }
        let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        guard let sessionId = obj?["session_id"] as? String else {
            throw BackendError.http(200, "missing session_id")
        }
        return sessionId
    }

    func sendText(sessionId: String, text: String, voiceEnabled: Bool = false) -> AsyncThrowingStream<SSEEvent, Error> {
        stream(path: "api/message", payload: [
            "session_id": sessionId,
            "text": text,
            "voice_enabled": voiceEnabled,
            "token": token,
        ])
    }

    func sendAudio(sessionId: String, base64Data: String, mimeType: String) -> AsyncThrowingStream<SSEEvent, Error> {
        stream(path: "api/audio", payload: [
            "session_id": sessionId,
            "data": base64Data,
            "mime_type": mimeType,
            "token": token,
        ])
    }

    func stop() async throws {
        guard !token.isEmpty else { throw BackendError.noToken }
        var request = URLRequest(url: baseURL.appendingPathComponent("api/stop"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["token": token])
        _ = try await URLSession.shared.data(for: request)
    }

    private func stream(path: String, payload: [String: Any]) -> AsyncThrowingStream<SSEEvent, Error> {
        AsyncThrowingStream { continuation in
            guard !token.isEmpty else {
                continuation.finish(throwing: BackendError.noToken)
                return
            }
            var request = URLRequest(url: baseURL.appendingPathComponent(path))
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            do {
                request.httpBody = try JSONSerialization.data(withJSONObject: payload)
            } catch {
                continuation.finish(throwing: error)
                return
            }

            let task = Task {
                do {
                    let (bytes, response) = try await URLSession.shared.bytes(for: request)
                    guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
                        throw BackendError.http(status, "request failed")
                    }

                    let delimiter = Data([0x0A, 0x0A])
                    var buffer = Data()
                    for try await byte in bytes {
                        buffer.append(byte)
                        while let range = buffer.range(of: delimiter) {
                            let block = buffer.subdata(in: buffer.startIndex..<range.lowerBound)
                            buffer.removeSubrange(buffer.startIndex..<range.upperBound)
                            if let text = String(data: block, encoding: .utf8), let parsed = Self.parseBlock(text) {
                                continuation.yield(parsed)
                            }
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    private static func parseBlock(_ block: String) -> SSEEvent? {
        var eventName = "message"
        var dataLine: String?
        for line in block.split(separator: "\n", omittingEmptySubsequences: false) {
            if line.hasPrefix("event: ") {
                eventName = String(line.dropFirst(7))
            } else if line.hasPrefix("data: ") {
                dataLine = String(line.dropFirst(6))
            }
        }
        guard let raw = dataLine else { return nil }
        return parse(event: eventName, data: raw)
    }

    private static func parse(event: String, data: String) -> SSEEvent? {
        guard let jsonData = data.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any]
        else { return nil }

        switch event {
        case "transcript": return (obj["content"] as? String).map(SSEEvent.transcript)
        case "status": return (obj["content"] as? String).map(SSEEvent.status)
        case "text": return (obj["content"] as? String).map(SSEEvent.text)
        case "session": return (obj["session_id"] as? String).map(SSEEvent.session)
        case "voice_enabled": return (obj["voice_enabled"] as? Bool).map(SSEEvent.voiceEnabled)
        default: return nil
        }
    }
}
