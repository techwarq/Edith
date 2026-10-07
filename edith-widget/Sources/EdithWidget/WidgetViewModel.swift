import SwiftUI

enum WidgetStatus: Equatable {
    case idle
    case connecting
    case listening
    case thinking
    case speaking(String)
    case error(String)
}

@MainActor
final class WidgetViewModel: ObservableObject {
    @Published var status: WidgetStatus = .connecting
    @Published var transcript: String = ""
    @Published var reply: String = ""
    @Published var isExpanded: Bool = false

    @Published var activity: String = ""
    @Published var focusInputTrigger: Int = 0

    @Published var levels: [Float] = Array(repeating: 0, count: WidgetViewModel.levelHistory)

    var isHovering = false { didSet { if isHovering { cancelAutoCollapse() } else { scheduleAutoCollapse() } } }
    var isTyping = false { didSet { if isTyping { cancelAutoCollapse() } else { scheduleAutoCollapse() } } }

    static let levelHistory = 28
    private static let autoCollapseNanoseconds: UInt64 = 8_000_000_000
    private var autoCollapseTask: Task<Void, Never>?

    private let client = BackendClient()
    private let speechRecognizer = SpeechRecognizer()
    private var sessionId: String?

    private var isCapturing = false
    private static let trailingListenNanoseconds: UInt64 = 350_000_000

    func requestTextFocus() {
        expand()
        focusInputTrigger += 1
    }

    func expand() {
        isExpanded = true
        if sessionId == nil { start() }
    }

    func collapse() {
        cancelAutoCollapse()
        if isCapturing { endVoiceCapture() }
        isExpanded = false
    }

    func toggleTyping() {
        if isExpanded && !isBusy { collapse() } else { requestTextFocus() }
    }

    func collapseIfIdle() {
        guard !isBusy, !isHovering else { return }
        collapse()
    }

    var isBusy: Bool {
        switch status {
        case .listening, .thinking, .speaking, .connecting: return true
        default: return isCapturing
        }
    }

    func toggleVoiceCapture() {
        if isCapturing { endVoiceCapture() } else { beginVoiceCapture() }
    }

    private func scheduleAutoCollapse() {
        cancelAutoCollapse()
        guard isExpanded, !isHovering, !isTyping, !isBusy else { return }
        autoCollapseTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: Self.autoCollapseNanoseconds)
            guard !Task.isCancelled else { return }
            self?.collapseIfIdle()
        }
    }

    private func cancelAutoCollapse() {
        autoCollapseTask?.cancel()
        autoCollapseTask = nil
    }

    private func pushLevel(_ level: Float) {
        levels.removeFirst()
        levels.append(level)
    }

    func start() {
        Task { _ = await ensureConnected() }
    }

    private func ensureConnected() async -> String? {
        if let sessionId { return sessionId }

        if ServerLauncher.shared.isLocal {
            activity = "Waking Eddy up…"
            if !(await ServerLauncher.shared.ensureRunning()) {
                status = .error("Couldn't start Eddy's local server — see ~/.edith/server.log")
                activity = ""
                return nil
            }
            activity = ""
        }
        do {
            let id = try await client.connect()
            sessionId = id
            if case .error = status { status = .idle }
            if case .connecting = status { status = .idle }
            return id
        } catch {
            status = .error(Self.describe(error))
            return nil
        }
    }

    func beginVoiceCapture() {
        guard !isCapturing else { return }
        isCapturing = true
        cancelAutoCollapse()
        expand()
        transcript = ""
        reply = ""
        activity = ""
        status = .listening
        Task {
            do {
                try await speechRecognizer.start(
                    onPartial: { [weak self] partial in

                        Task { @MainActor in self?.transcript = partial }
                    },
                    onLevel: { [weak self] level in
                        Task { @MainActor in self?.pushLevel(level) }
                    },
                    onError: { [weak self] message in

                        Task { @MainActor in
                            guard let self, self.isCapturing else { return }
                            self.status = .error("Speech recognition error: \(message)")
                        }
                    }
                )
            } catch {
                self.isCapturing = false
                self.status = .error(Self.describe(error))
            }
        }
    }

    func endVoiceCapture() {
        guard isCapturing else { return }
        isCapturing = false
        Task {
            try? await Task.sleep(nanoseconds: Self.trailingListenNanoseconds)
            speechRecognizer.stop()
            levels = Array(repeating: 0, count: Self.levelHistory)
            let heard = transcript.trimmingCharacters(in: .whitespacesAndNewlines)

            if heard.isEmpty, case .error = status { return }
            if heard.isEmpty {
                status = .idle
                scheduleAutoCollapse()
            } else {
                sendTyped(heard)
            }
        }
    }

    func stopWork() {
        if isCapturing {
            isCapturing = false
            speechRecognizer.stop()
            levels = Array(repeating: 0, count: Self.levelHistory)
            status = .idle
            return
        }
        guard case .thinking = status else { return }
        activity = "Stopping…"
        Task { try? await client.stop() }
    }

    func sendTyped(_ text: String) {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        transcript = text
        reply = ""
        activity = ""
        status = .thinking
        cancelAutoCollapse()
        Task {
            guard let sessionId = await ensureConnected() else { return }
            do {
                for try await event in client.sendText(sessionId: sessionId, text: text) {
                    apply(event)
                }
                settleIfStillBusy()
            } catch {
                status = .error(Self.describe(error))
            }
        }
    }

    private func settleIfStillBusy() {
        if case .thinking = status { status = .idle }
        scheduleAutoCollapse()
    }

    private func apply(_ event: SSEEvent) {
        switch event {
        case .transcript(let text):
            transcript = text
        case .status(let text):
            status = .thinking
            activity = text
        case .text(let text):
            reply = text
            activity = ""
            status = .speaking(text)
        case .session(let id):
            sessionId = id
        case .voiceEnabled:
            break
        case .error(let message):
            status = .error(message)
        }
        if case .speaking = status {
            Task {
                try? await Task.sleep(nanoseconds: 200_000_000)
                if case .speaking = self.status { self.status = .idle }
                self.scheduleAutoCollapse()
            }
        }
    }

    private nonisolated static func describe(_ error: Error) -> String {
        if let backendError = error as? BackendError {
            switch backendError {
            case .noToken: return "No API token configured"
            case .http(let code, let message): return "\(message) (\(code))"
            }
        }
        if let speechError = error as? SpeechRecognizerError {
            return speechError.message
        }
        return error.localizedDescription
    }
}
