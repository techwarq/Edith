import Foundation

@MainActor
final class ServerLauncher {
    static let shared = ServerLauncher()

    private var process: Process?
    private let baseURL = URL(string: Config.serverURL)

    private static let startupTimeout: TimeInterval = 60
    private static let logPath = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".edith/server.log")

    var isLocal: Bool {
        guard let host = baseURL?.host else { return false }
        return host == "127.0.0.1" || host == "localhost"
    }

    func ensureRunning() async -> Bool {
        if await isHealthy() { return true }
        guard isLocal, process?.isRunning != true else { return await waitUntilHealthy() }
        guard launch() else { return false }
        return await waitUntilHealthy()
    }

    func shutdown() {
        guard let process, process.isRunning else { return }
        process.terminate()
        process.waitUntilExit()
    }

    private func launch() -> Bool {
        let repo = Config.repoRoot
        let python = repo.appendingPathComponent(".venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { return false }
        let port = baseURL?.port ?? 8787

        let logURL = Self.logPath
        try? FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        guard let log = try? FileHandle(forWritingTo: logURL) else { return false }
        log.seekToEndOfFile()
        log.write(Data("\n=== started by Edith Widget \(Date()) ===\n".utf8))

        let process = Process()
        process.executableURL = python
        process.arguments = ["-m", "uvicorn", "edith.server:app", "--host", "127.0.0.1", "--port", String(port)]
        process.currentDirectoryURL = repo
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        process.environment = env
        process.standardOutput = log
        process.standardError = log
        do {
            try process.run()
        } catch {
            return false
        }
        self.process = process
        return true
    }

    private func waitUntilHealthy() async -> Bool {
        let deadline = Date().addingTimeInterval(Self.startupTimeout)
        while Date() < deadline {
            if await isHealthy() { return true }
            if let process, !process.isRunning { return false }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
        return false
    }

    private func isHealthy() async -> Bool {
        guard let baseURL else { return false }
        var request = URLRequest(url: baseURL)
        request.timeoutInterval = 1.5
        guard let (_, response) = try? await URLSession.shared.data(for: request),
              let http = response as? HTTPURLResponse
        else { return false }
        return http.statusCode < 500
    }
}
