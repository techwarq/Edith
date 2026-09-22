import Foundation

// Mirrors edith-desktop/main.js's resolveToken()/SERVER_URL resolution so this
// widget talks to the exact same backend with zero setup when run from the repo.
enum Config {
    static let defaultServerURL = "https://edith-production-d100.up.railway.app"

    private static let configPath = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".edith/desktop_config.json")

    private static let dashboardEnvPath = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent() // Config.swift -> EdithWidget/
        .deletingLastPathComponent() // -> Sources/
        .deletingLastPathComponent() // -> edith-widget/
        .deletingLastPathComponent() // -> edith/ (repo root)
        .appendingPathComponent("edith-dashboard/.env.local")

    private static var jsonConfig: [String: String] {
        guard let data = try? Data(contentsOf: configPath),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: String]
        else { return [:] }
        return obj
    }

    static var serverURL: String {
        if let url = jsonConfig["serverUrl"], !url.isEmpty { return url }
        if let url = ProcessInfo.processInfo.environment["EDITH_DESKTOP_URL"], !url.isEmpty { return url }
        return defaultServerURL
    }

    static var apiToken: String {
        if let token = jsonConfig["token"], !token.isEmpty { return token }
        if let token = ProcessInfo.processInfo.environment["EDITH_API_TOKEN"], !token.isEmpty { return token }
        if let contents = try? String(contentsOf: dashboardEnvPath, encoding: .utf8),
           let match = contents.range(of: #"(?m)^EDITH_API_TOKEN=(.+)$"#, options: .regularExpression) {
            let line = contents[match]
            if let eq = line.firstIndex(of: "=") {
                return String(line[line.index(after: eq)...]).trimmingCharacters(in: .whitespacesAndNewlines)
            }
        }
        return ""
    }
}
