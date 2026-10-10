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

    var serverURL: URL { baseURL }
    var apiToken: String { token }

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

struct LeadFounder: Decodable, Hashable {
    let name: String?
    let title: String?
    let email: String?
    let linkedin: String?
}

struct CompanyInfo: Decodable, Hashable {
    let headcount: Double?
    let headcountYoyPct: Double?
    let totalFundingUsd: Double?
    let lastRound: String?
    let lastRoundDate: String?
    let hq: String?
    let linkedin: String?

    var summary: String {
        var bits: [String] = []
        if let headcount { bits.append("\(Int(headcount)) people") }
        if let totalFundingUsd, totalFundingUsd > 0 {
            var money = String(format: "$%.1fM", totalFundingUsd / 1_000_000)
            if let lastRound, lastRound != "series_unknown" { money += " · \(lastRound.replacingOccurrences(of: "_", with: " "))" }
            if let lastRoundDate { money += " \(lastRoundDate.prefix(7))" }
            bits.append(money)
        } else if let lastRound {
            bits.append(lastRound == "series_unknown" ? "funded" : lastRound.replacingOccurrences(of: "_", with: " "))
        }
        if let hq { bits.append(hq) }
        return bits.joined(separator: " · ")
    }
}

struct StartupLead: Decodable, Identifiable, Hashable {
    let id: Int
    let kind: String
    let company: String
    let domain: String?
    let fund: String?
    let roleTitle: String?
    let jobUrl: String?
    let companyUrl: String?
    let eligibility: String?
    let salary: String?
    let score: Double
    let reasons: [String]?
    let founders: [LeadFounder]?
    let contactEmail: String?
    let pitch: String?
    var status: String
    let teamSize: Int?
    let stage: String?
    let companyInfo: CompanyInfo?
    var draftTo: String?
    var draftSubject: String?
    var draftBody: String?
    var sentAt: String?
    var sentTo: [String]?
    let deliveredAt: String?
    let warnings: [String]?

    var sentRecipients: Set<String> {
        if let sentTo, !sentTo.isEmpty { return Set(sentTo.map { $0.lowercased() }) }
        guard sentAt != nil, let draftTo else { return [] }
        return Set(draftTo.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces).lowercased() })
    }

    var isRole: Bool { kind == "role" }

    var bestEmail: String? {
        contactEmail ?? founders?.first(where: { $0.email != nil })?.email
    }

    var link: URL? {
        if let jobUrl, let url = URL(string: jobUrl) { return url }
        if let companyUrl, let url = URL(string: companyUrl) { return url }
        if let domain { return URL(string: "https://\(domain)") }
        return nil
    }

    var linkedin: URL? {
        founders?.compactMap { $0.linkedin }.first.flatMap(URL.init(string:))
    }

    var companyLinkedin: URL? {
        companyInfo?.linkedin.flatMap(URL.init(string:))
    }

    var contacts: [LeadFounder] {
        (founders ?? []).filter { $0.name != nil }
    }
}

struct StartupFindResult: Decodable {
    let returned: Int
    let remainingPool: Int
    let leads: [StartupLead]
    let warnings: [String]?
}

private struct StartupLeadList: Decodable {
    let leads: [StartupLead]
}

extension BackendClient {
    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }()

    func findStartups(count: Int, kind: String? = nil, location: String? = nil) async throws -> StartupFindResult {
        var payload: [String: Any] = ["token": apiToken, "count": count]
        if let kind { payload["kind"] = kind }
        if let location, !location.isEmpty { payload["location"] = location }
        let data = try await sendJSON(path: "api/startup-finder/run", method: "POST", payload: payload, timeout: 300)
        return try Self.decoder.decode(StartupFindResult.self, from: data)
    }

    func startupLeads(status: String = "delivered", limit: Int = 40) async throws -> [StartupLead] {
        guard !apiToken.isEmpty else { throw BackendError.noToken }
        var components = URLComponents(url: serverURL.appendingPathComponent("api/startup-finder/leads"), resolvingAgainstBaseURL: false)!
        components.queryItems = [
            URLQueryItem(name: "token", value: apiToken),
            URLQueryItem(name: "status", value: status),
            URLQueryItem(name: "limit", value: String(limit)),
        ]
        let (data, response) = try await URLSession.shared.data(from: components.url!)
        try Self.check(response, data)
        return try Self.decoder.decode(StartupLeadList.self, from: data).leads
    }

    func draftStartupEmail(id: Int) async throws -> StartupLead {
        let data = try await sendJSON(path: "api/startup-finder/leads/\(id)/draft", method: "POST", payload: ["token": apiToken], timeout: 90)
        return try Self.decoder.decode(StartupLead.self, from: data)
    }

    func sendStartupEmail(id: Int, to: [String], subject: String, body: String) async throws -> StartupLead {
        let payload: [String: Any] = ["token": apiToken, "to": to, "subject": subject, "body": body]
        let data = try await sendJSON(path: "api/startup-finder/leads/\(id)/send", method: "POST", payload: payload, timeout: 60)
        return try Self.decoder.decode(StartupLead.self, from: data)
    }

    func updateStartupLead(id: Int, status: String) async throws {
        _ = try await sendJSON(path: "api/startup-finder/leads/\(id)", method: "PATCH", payload: ["token": apiToken, "status": status], timeout: 30)
    }

    private func sendJSON(path: String, method: String, payload: [String: Any], timeout: TimeInterval) async throws -> Data {
        guard !apiToken.isEmpty else { throw BackendError.noToken }
        var request = URLRequest(url: serverURL.appendingPathComponent(path))
        request.httpMethod = method
        request.timeoutInterval = timeout
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.check(response, data)
        return data
    }

    private static func check(_ response: URLResponse, _ data: Data) throws {
        guard let http = response as? HTTPURLResponse else { throw BackendError.http(0, "no response") }
        guard http.statusCode == 200 else {
            let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            throw BackendError.http(http.statusCode, (obj?["error"] as? String) ?? "request failed")
        }
    }
}
