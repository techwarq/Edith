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
    @Published var isPanelVisible: Bool = false
    @Published var focusInputTrigger: Int = 0

    private let client = BackendClient()
    private let speechRecognizer = SpeechRecognizer()
    private var sessionId: String?

    // Set the instant capture is requested, not once recognition actually
    // starts — starting involves an async permission round trip, and a
    // caller invoking beginVoiceCapture() twice inside that window would
    // pass an isRunning-based guard both times.
    private var isCapturing = false
    private var pendingTickTask: Task<Void, Never>?
    private var lastSentTranscript = ""

    // Matches edith/computer_use/voice_loop.py's own DEFAULT_DEBOUNCE_SECONDS
    // (0.18s) — the Speech framework can fire partials faster than that, and
    // there's no point round-tripping to Jev more often than the tick loop
    // itself is designed to reason about a new transcript snapshot.
    private static let tickDebounceNanoseconds: UInt64 = 190_000_000

    func requestTextFocus() {
        focusInputTrigger += 1
    }

    func start() {
        Task {
            do {
                sessionId = try await client.connect()
                status = .idle
            } catch {
                status = .error(Self.describe(error))
            }
        }
    }

    /// True push-to-talk: called on key-down, starts live streaming speech
    /// recognition immediately. Every partial transcript update is shown live
    /// and (debounced) sent to /api/voice_tick, which can act mid-sentence —
    /// there is no "record the whole thing, then send" step anymore. Safe to
    /// call repeatedly for a single hold — no-ops past the first call.
    func beginVoiceCapture() {
        guard !isCapturing else { return }
        isCapturing = true
        isPanelVisible = true
        transcript = ""
        reply = ""
        lastSentTranscript = ""
        status = .listening
        Task {
            do {
                try await speechRecognizer.start(
                    onPartial: { [weak self] partial in
                        // onPartial/onError are typed @Sendable (SpeechRecognizer.start
                        // crosses a nonisolated closure boundary internally — see its doc
                        // comment) — hop back explicitly rather than assuming the caller
                        // already did, since the compiler can't see that SpeechRecognizer
                        // always invokes these via Task { @MainActor }/assumeIsolated.
                        Task { @MainActor in self?.handlePartial(partial) }
                    },
                    onError: { [weak self] message in
                        // Previously silent: the recognition task's error case only
                        // tore down internally, so a real recognition failure (e.g. the
                        // on-device model unavailable) looked identical to "did nothing."
                        Task { @MainActor in self?.status = .error("Speech recognition error: \(message)") }
                    }
                )
            } catch {
                self.isCapturing = false
                self.status = .error(Self.describe(error))
            }
        }
    }

    /// Called on key-up — stops live recognition and tells the server to
    /// close out this voice-tick session (drop the pinned window/history).
    /// Whatever needed to happen already happened tick by tick while you
    /// were talking; there's nothing left to upload.
    func endVoiceCapture() {
        guard isCapturing else { return }
        isCapturing = false
        speechRecognizer.stop()
        pendingTickTask?.cancel()
        pendingTickTask = nil
        if let sessionId {
            Task { try? await client.voiceTickEnd(sessionId: sessionId) }
        }
        if case .error = status {
            // leave the error visible
        } else {
            status = .idle
        }
    }

    private func handlePartial(_ text: String) {
        transcript = text
        pendingTickTask?.cancel()
        pendingTickTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: Self.tickDebounceNanoseconds)
            guard !Task.isCancelled else { return }
            await self?.sendTick(text)
        }
    }

    private func sendTick(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, text != lastSentTranscript else { return }
        guard let sessionId else { return }
        lastSentTranscript = text
        do {
            let result = try await client.voiceTick(sessionId: sessionId, transcript: text)
            applyTick(result)
        } catch {
            status = .error(Self.describe(error))
        }
    }

    /// Surfaces each tick's outcome live: an executed action briefly shows
    /// its result, then — if still capturing — settles back to "listening"
    /// so the pill reflects that Edith is still with you, not that the turn
    /// is over (there is no "turn" here, just a continuous session).
    private func applyTick(_ result: VoiceTickResult) {
        guard isCapturing else { return } // hold already ended; ignore a late in-flight tick
        if result.blocked {
            reply = result.message
            status = .error(result.message)
            return
        }
        if result.executed || result.done {
            reply = result.message
            status = .speaking(result.message)
            Task { [weak self] in
                try? await Task.sleep(nanoseconds: 900_000_000)
                guard let self, self.isCapturing else { return }
                if case .speaking = self.status { self.status = .listening }
            }
        }
        // WAIT / not-complete-enough-yet ticks: no status change beyond the
        // live transcript, which handlePartial already updated.
    }

    func sendTyped(_ text: String) {
        guard let sessionId else {
            status = .error("Not connected")
            return
        }
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        transcript = text
        reply = ""
        status = .thinking
        Task {
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

    /// The backend silently drops a turn with no further events (e.g. audio
    /// transcribed to empty text) — without this the pill would stay stuck on
    /// "thinking" forever since no terminal event ever arrives.
    private func settleIfStillBusy() {
        if case .thinking = status { status = .idle }
    }

    private func apply(_ event: SSEEvent) {
        switch event {
        case .transcript(let text):
            transcript = text
        case .status(let text):
            status = .thinking
            reply = text
        case .text(let text):
            reply = text
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
