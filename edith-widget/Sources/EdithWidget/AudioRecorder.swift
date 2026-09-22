import AVFoundation

// Whisper hallucinates a short filler word ("No,", "Thank you.") when a clip
// opens with a beat of near-silence before speech starts — the mic starts
// capturing the instant the hotkey fires, before you've actually begun
// talking. Same fix as edith/web/app.js's trimLeadingSilence (commit
// 6017599) — that one only ever covered the browser dashboard's recorder,
// never this native one. Trims to just before the first window whose RMS
// crosses the threshold, keeping a small pre-roll so the onset of the word
// isn't clipped.
private let silenceRMSThreshold: Float = 0.02
private let silenceWindowSeconds: Double = 0.02
private let preRollSeconds: Double = 0.15
private let minTrimSeconds: Double = 0.1

final class AudioRecorder {
    private var recorder: AVAudioRecorder?
    private var fileURL: URL?

    var isRecording: Bool { recorder?.isRecording ?? false }

    func requestPermission(_ completion: @escaping @MainActor (Bool) -> Void) {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            Task { @MainActor in completion(true) }
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                Task { @MainActor in completion(granted) }
            }
        default:
            Task { @MainActor in completion(false) }
        }
    }

    func start() throws {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathExtension("m4a")
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatMPEG4AAC,
            AVSampleRateKey: 44_100,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
        ]
        let recorder = try AVAudioRecorder(url: url, settings: settings)
        recorder.record()
        self.recorder = recorder
        self.fileURL = url
    }

    /// Stops recording and returns (base64 audio, mime type), or nil if nothing was captured.
    func stop() -> (base64: String, mimeType: String)? {
        guard let recorder, let fileURL else { return nil }
        recorder.stop()
        self.recorder = nil
        defer { try? FileManager.default.removeItem(at: fileURL) }
        guard let data = try? Data(contentsOf: fileURL), !data.isEmpty else { return nil }

        if let trimmed = Self.trimLeadingSilence(fileURL: fileURL) {
            return (trimmed.base64EncodedString(), "audio/wav")
        }
        return (data.base64EncodedString(), "audio/mp4")
    }

    /// Returns re-encoded WAV data with leading silence trimmed, or nil if no
    /// clear speech onset was found / the lead-in was negligible — callers
    /// should fall back to sending the original clip untouched in that case,
    /// same as app.js's trimLeadingSilence.
    private static func trimLeadingSilence(fileURL: URL) -> Data? {
        guard let file = try? AVAudioFile(forReading: fileURL) else { return nil }
        let format = file.processingFormat
        let frameCount = AVAudioFrameCount(file.length)
        guard frameCount > 0,
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount),
              let channelData = buffer.floatChannelData
        else { return nil }
        do { try file.read(into: buffer) } catch { return nil }

        let sampleRate = format.sampleRate
        let channelCount = Int(format.channelCount)
        let length = Int(buffer.frameLength)

        var mono = [Float](repeating: 0, count: length)
        for i in 0..<length {
            var sum: Float = 0
            for c in 0..<channelCount { sum += channelData[c][i] }
            mono[i] = sum / Float(channelCount)
        }

        let windowSize = max(1, Int((sampleRate * silenceWindowSeconds).rounded()))
        var speechStart = -1
        var start = 0
        while start < length {
            let end = min(start + windowSize, length)
            var sumSq: Float = 0
            for i in start..<end { sumSq += mono[i] * mono[i] }
            if sqrt(sumSq / Float(end - start)) > silenceRMSThreshold {
                speechStart = start
                break
            }
            start += windowSize
        }
        guard speechStart >= 0 else { return nil } // no clear onset — send original untouched

        let trimStart = max(0, speechStart - Int((sampleRate * preRollSeconds).rounded()))
        guard Double(trimStart) >= sampleRate * minTrimSeconds else { return nil } // negligible lead-in

        return encodeWav(samples: Array(mono[trimStart...]), sampleRate: sampleRate)
    }

    private static func encodeWav(samples: [Float], sampleRate: Double) -> Data {
        let sr = UInt32(sampleRate)
        let dataSize = UInt32(samples.count * 2)
        var data = Data()

        func appendString(_ s: String) { data.append(s.data(using: .ascii)!) }
        func appendU32(_ v: UInt32) { var le = v.littleEndian; withUnsafeBytes(of: &le) { data.append(contentsOf: $0) } }
        func appendU16(_ v: UInt16) { var le = v.littleEndian; withUnsafeBytes(of: &le) { data.append(contentsOf: $0) } }

        appendString("RIFF")
        appendU32(36 + dataSize)
        appendString("WAVE")
        appendString("fmt ")
        appendU32(16)
        appendU16(1) // PCM
        appendU16(1) // mono
        appendU32(sr)
        appendU32(sr * 2) // byte rate (mono, 16-bit)
        appendU16(2) // block align
        appendU16(16) // bits per sample
        appendString("data")
        appendU32(dataSize)

        for s in samples {
            let clipped = max(-1.0, min(1.0, s))
            let intVal = Int16(clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff)
            var le = intVal.littleEndian
            withUnsafeBytes(of: &le) { data.append(contentsOf: $0) }
        }
        return data
    }
}
