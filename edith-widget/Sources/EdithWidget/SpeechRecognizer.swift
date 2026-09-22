import AVFoundation
import Speech

// Native Swift port of edith/computer_use/speech_stream.py's
// MicPartialTranscriptSource — same idea (SFSpeechRecognizer +
// SFSpeechAudioBufferRecognitionRequest fed by AVAudioEngine's input tap,
// requesting on-device recognition so it never round-trips through Apple's
// servers), but native here since this runs in-process in the widget
// itself, no PyObjC bridge needed. Fires onPartial repeatedly with the
// growing transcript for as long as start()...stop() spans.
final class SpeechRecognizerError: Error {
    let message: String
    init(_ message: String) { self.message = message }
}

extension SpeechRecognizerError: CustomStringConvertible {
    var description: String { message }
}

// @unchecked Sendable: this class is @MainActor-isolated and all of its
// mutable state is only ever touched on the main actor — the only reason a
// reference to it needs to cross into the nonisolated tap/result-handler
// closures below is a weak capture that immediately hops back via
// `Task { @MainActor in ... }` before touching anything. That pattern is
// safe; it's exactly what @unchecked Sendable is for.
@MainActor
final class SpeechRecognizer: @unchecked Sendable {
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private let audioEngine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?

    var isRunning: Bool { task != nil }

    /// Starts streaming recognition, calling `onPartial` with the growing
    /// transcript on every update. Throws immediately (synchronously, after
    /// the async permission round trip) if Speech Recognition or Microphone
    /// access isn't granted, rather than silently doing nothing.
    /// @Sendable: onPartial gets captured by the nonisolated result-handler
    /// closure below (built off the MainActor) before being invoked back on
    /// it via Task { @MainActor in ... } — the type itself must cross that
    /// boundary safely even though every actual call happens on the main actor.
    func start(onPartial: @escaping @Sendable (String) -> Void, onError: @escaping @Sendable (String) -> Void) async throws {
        guard !isRunning else { return }

        try await requestSpeechAuthorization()
        try await requestMicrophoneAuthorization()

        guard let recognizer, recognizer.isAvailable else {
            throw SpeechRecognizerError("Speech recognizer unavailable for this locale/device.")
        }
        Self.debugLog("recognizer available, supportsOnDevice=\(recognizer.supportsOnDeviceRecognition)")

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition {
            request.requiresOnDeviceRecognition = true
        }
        self.request = request

        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)
        // A stale render graph from a previous start/stop cycle (fixed below in
        // teardown() via audioEngine.reset()) can otherwise leave this format
        // with a zero sample rate — installTap silently accepts it, but
        // engine.start() then fails deep in CoreAudio with an opaque
        // "com.apple.coreaudio.avfaudio error 2003329396 ('what')". Catching it
        // here gives a message that actually explains what's wrong.
        guard format.sampleRate > 0, format.channelCount > 0 else {
            throw SpeechRecognizerError("No audio input format available yet — try holding Control again in a moment.")
        }
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format, block: Self.makeTapBlock(request: request))

        audioEngine.prepare()
        do {
            try audioEngine.start()
        } catch {
            inputNode.removeTap(onBus: 0)
            self.request = nil
            throw SpeechRecognizerError("Couldn't start the audio engine: \(error.localizedDescription)")
        }

        let onFinal: @Sendable () -> Void = { [weak self] in
            Task { @MainActor in self?.teardown() }
        }
        task = recognizer.recognitionTask(
            with: request,
            resultHandler: Self.makeResultHandler(onPartial: onPartial, onError: onError, onFinal: onFinal)
        )
        Self.debugLog("recognitionTask started")
    }

    // Temporary — writes to /tmp/edith-widget-debug.log so recognition
    // behavior is diagnosable across process boundaries (this is a GUI app
    // launched via `open`, its stdout isn't visible in a terminal). Remove
    // once live voice capture is confirmed working end to end.
    nonisolated private static func debugLog(_ message: String) {
        let line = "[\(Date())] \(message)\n"
        guard let data = line.data(using: .utf8) else { return }
        let path = "/tmp/edith-widget-debug.log"
        if let handle = FileHandle(forWritingAtPath: path) {
            handle.seekToEndOfFile()
            handle.write(data)
            handle.closeFile()
        } else {
            try? data.write(to: URL(fileURLWithPath: path))
        }
    }

    // nonisolated: both AVAudioEngine's tap block (a dedicated real-time audio
    // thread) and SFSpeechRecognizer's result handler (an arbitrary background
    // queue) invoke their closures off the MainActor. A closure literal written
    // inline inside a method of this @MainActor class inherits MainActor
    // isolation by default — which makes the Swift runtime assert the calling
    // thread matches that actor's executor, and crash (EXC_BREAKPOINT) the
    // instant the framework actually invokes it from its real thread. This
    // already crashed once for requestSpeechAuthorization's completion handler
    // (fixed the same way) and again here for the tap block — building both
    // closures in nonisolated static functions keeps them free of that
    // inference instead of relying on inline-closure isolation to "just work".
    nonisolated private static func makeTapBlock(
        request: SFSpeechAudioBufferRecognitionRequest
    ) -> (AVAudioPCMBuffer, AVAudioTime) -> Void {
        { buffer, _ in request.append(buffer) }
    }

    // DispatchQueue.main.async + MainActor.assumeIsolated, not
    // Task { @MainActor in ... } — spawning a new unstructured Task here trips
    // Swift 6's "sending risks data race" checker on values crossing into it,
    // even when provably safe. GCD's main queue always corresponds to the
    // MainActor's executor for a plain @MainActor class like this one, so
    // assumeIsolated is exactly what it's for. onFinal is built by the caller
    // (an instance method, where capturing self weakly is unremarkable) and
    // handed in as a plain @Sendable closure, instead of passing `owner`
    // itself across this nonisolated boundary — that was still tripping the
    // same "sending" diagnostic even with @unchecked Sendable on the class.
    nonisolated private static func makeResultHandler(
        onPartial: @escaping @Sendable (String) -> Void,
        onError: @escaping @Sendable (String) -> Void,
        onFinal: @escaping @Sendable () -> Void
    ) -> (SFSpeechRecognitionResult?, Error?) -> Void {
        { result, error in
            if let result {
                let text = result.bestTranscription.formattedString
                debugLog("partial: \(text.isEmpty ? "(empty)" : text)")
                DispatchQueue.main.async {
                    MainActor.assumeIsolated { onPartial(text) }
                }
            }
            if let error {
                debugLog("error: \(error)")
                DispatchQueue.main.async {
                    MainActor.assumeIsolated { onError(error.localizedDescription) }
                }
            }
            if error != nil || (result?.isFinal ?? false) {
                onFinal()
            }
        }
    }

    /// Stops recognition. Safe to call even if never started / already stopped.
    func stop() {
        teardown()
    }

    private func teardown() {
        guard isRunning || audioEngine.isRunning else { return }
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        // Without this, the engine's render graph can retain stale state from
        // this session into the next start() call — see the format guard above.
        audioEngine.reset()
        request?.endAudio()
        request = nil
        task?.cancel()
        task = nil
    }

    // nonisolated: SFSpeechRecognizer.requestAuthorization's completion handler
    // fires on an arbitrary TCC/XPC background thread, not the MainActor. If
    // this closure is left MainActor-isolated (the default for a method on an
    // @MainActor class), the runtime inserts an isolation check that traps
    // (EXC_BREAKPOINT/SIGTRAP) the instant that callback actually fires on the
    // wrong thread — confirmed via a real crash report, not theoretical.
    // Neither of these touches any actor-isolated stored state, so nonisolated
    // is safe; callers already `await` them from start(), which re-enters the
    // MainActor for whatever runs after.
    nonisolated private func requestSpeechAuthorization() async throws {
        switch SFSpeechRecognizer.authorizationStatus() {
        case .authorized:
            return
        case .notDetermined:
            let status = await withCheckedContinuation { continuation in
                SFSpeechRecognizer.requestAuthorization { status in
                    continuation.resume(returning: status)
                }
            }
            guard status == .authorized else {
                throw SpeechRecognizerError(
                    "Speech Recognition permission wasn't granted — enable it in System Settings > "
                    + "Privacy & Security > Speech Recognition."
                )
            }
        default:
            throw SpeechRecognizerError(
                "Speech Recognition permission denied — enable it in System Settings > "
                + "Privacy & Security > Speech Recognition."
            )
        }
    }

    nonisolated private func requestMicrophoneAuthorization() async throws {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            return
        case .notDetermined:
            let granted = await withCheckedContinuation { continuation in
                AVCaptureDevice.requestAccess(for: .audio) { granted in
                    continuation.resume(returning: granted)
                }
            }
            guard granted else {
                throw SpeechRecognizerError(
                    "Microphone access denied — enable it in System Settings > Privacy & Security > Microphone."
                )
            }
        default:
            throw SpeechRecognizerError(
                "Microphone access denied — enable it in System Settings > Privacy & Security > Microphone."
            )
        }
    }
}
