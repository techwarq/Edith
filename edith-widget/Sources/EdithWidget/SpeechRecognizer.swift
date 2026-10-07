import AVFoundation
import Speech

final class SpeechRecognizerError: Error {
    let message: String
    init(_ message: String) { self.message = message }
}

extension SpeechRecognizerError: CustomStringConvertible {
    var description: String { message }
}

@MainActor
final class SpeechRecognizer: @unchecked Sendable {
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))

    private var captureSession: AVCaptureSession?
    private var audioDelegate: AudioBufferForwarder?
    private let captureQueue = DispatchQueue(label: "edith.widget.mic")
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?

    var isRunning: Bool { task != nil }

    func start(
        onPartial: @escaping @Sendable (String) -> Void,
        onLevel: @escaping @Sendable (Float) -> Void,
        onError: @escaping @Sendable (String) -> Void
    ) async throws {
        guard !isRunning else { return }

        try await requestSpeechAuthorization()
        try await requestMicrophoneAuthorization()

        guard let recognizer, recognizer.isAvailable else {
            throw SpeechRecognizerError("Speech recognizer unavailable for this locale/device.")
        }
        Self.debugLog("recognizer available, supportsOnDevice=\(recognizer.supportsOnDeviceRecognition)")

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true

        request.contextualStrings = [
            "Eddy", "Brave", "YC", "Y Combinator", "Hacker News", "Zed", "WhatsApp", "Slack",
            "Gmail", "Notion", "LinkedIn", "GitHub", "Vercel", "Spotify",
        ]
        if recognizer.supportsOnDeviceRecognition {
            request.requiresOnDeviceRecognition = true
        }
        self.request = request

        guard let device = AVCaptureDevice.default(for: .audio) else {
            self.request = nil
            throw SpeechRecognizerError("No microphone found.")
        }
        let session = AVCaptureSession()
        do {
            let input = try AVCaptureDeviceInput(device: device)
            guard session.canAddInput(input) else { throw SpeechRecognizerError("Microphone is busy.") }
            session.addInput(input)
        } catch {
            self.request = nil
            throw SpeechRecognizerError("Couldn't open the microphone: \(error.localizedDescription)")
        }
        let output = AVCaptureAudioDataOutput()

        output.audioSettings = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVLinearPCMBitDepthKey: 32,
            AVLinearPCMIsFloatKey: true,
            AVLinearPCMIsNonInterleaved: false,
        ]
        let forwarder = AudioBufferForwarder(request: request, onLevel: onLevel)
        output.setSampleBufferDelegate(forwarder, queue: captureQueue)
        guard session.canAddOutput(output) else {
            self.request = nil
            throw SpeechRecognizerError("Couldn't attach to the microphone's audio output.")
        }
        session.addOutput(output)
        session.startRunning()
        guard session.isRunning else {
            self.request = nil
            throw SpeechRecognizerError("The microphone didn't start — is another app using it exclusively?")
        }
        captureSession = session
        audioDelegate = forwarder

        let onFinal: @Sendable () -> Void = { [weak self] in
            Task { @MainActor in self?.teardown() }
        }
        task = recognizer.recognitionTask(
            with: request,
            resultHandler: Self.makeResultHandler(onPartial: onPartial, onError: onError, onFinal: onFinal)
        )
        Self.debugLog("recognitionTask started")
    }

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
            if let error, !isBenign(error) {
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

    nonisolated private static func isBenign(_ error: Error) -> Bool {
        let ns = error as NSError

        return ["kAFAssistantErrorDomain", "kLSRErrorDomain"].contains(ns.domain)
            && [203, 216, 301, 1110].contains(ns.code)
    }

    func stop() {
        teardown()
    }

    private func teardown() {
        guard isRunning || captureSession != nil else { return }
        captureSession?.stopRunning()
        captureSession = nil
        audioDelegate = nil
        request?.endAudio()
        request = nil
        task?.cancel()
        task = nil
    }

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

private final class AudioBufferForwarder: NSObject, AVCaptureAudioDataOutputSampleBufferDelegate, @unchecked Sendable {
    private let request: SFSpeechAudioBufferRecognitionRequest
    private let onLevel: @Sendable (Float) -> Void

    init(request: SFSpeechAudioBufferRecognitionRequest, onLevel: @escaping @Sendable (Float) -> Void) {
        self.request = request
        self.onLevel = onLevel
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        request.appendAudioSampleBuffer(sampleBuffer)
        let level = Self.normalizedLevel(of: sampleBuffer)
        let onLevel = self.onLevel
        DispatchQueue.main.async { onLevel(level) }
    }

    private static func normalizedLevel(of sampleBuffer: CMSampleBuffer) -> Float {
        guard let block = CMSampleBufferGetDataBuffer(sampleBuffer) else { return 0 }
        var length = 0
        var pointer: UnsafeMutablePointer<CChar>?
        guard CMBlockBufferGetDataPointer(block, atOffset: 0, lengthAtOffsetOut: nil, totalLengthOut: &length, dataPointerOut: &pointer) == noErr,
              let pointer, length >= 4
        else { return 0 }
        let count = length / 4
        var sum: Float = 0
        pointer.withMemoryRebound(to: Float.self, capacity: count) { samples in
            for i in 0..<count { sum += samples[i] * samples[i] }
        }
        let rms = (sum / Float(count)).squareRoot()
        return min(1, rms.squareRoot() * 2.2)
    }
}
