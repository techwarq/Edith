import SwiftUI
import AppKit

// Matches the reference mock: a dark glass rounded rect with a thin light
// border. Only the OUTER panel gets .glassEffect() — elements sitting on top
// of glass (the input bar, the status dot) use plain fills, never a second
// glassEffect. Glass can't sample glass; stacking them renders as noise.
struct ContentView: View {
    @ObservedObject var viewModel: WidgetViewModel
    @State private var typed: String = ""
    @FocusState private var inputFocused: Bool

    private let panelShape = RoundedRectangle(cornerRadius: 28, style: .continuous)
    private let inputShape = RoundedRectangle(cornerRadius: 16, style: .continuous)

    var body: some View {
        ZStack(alignment: .bottom) {
            panelShape
                .glassEffect(.regular, in: panelShape)
                .overlay(panelShape.stroke(Color.white.opacity(0.28), lineWidth: 1))
                // isMovableByWindowBackground alone doesn't work here — the SwiftUI
                // NSHostingView covers the whole panel and swallows mouse events before
                // AppKit ever sees a "background" click. WindowDragGesture is the
                // SwiftUI-native way to make a borderless panel draggable from content.
                .gesture(WindowDragGesture())

            VStack(spacing: 8) {
                ScrollView {
                    conversationArea
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(.horizontal, 20)
                .padding(.top, 20)

                inputBar
                    .padding(.horizontal, 14)
                    .padding(.bottom, 14)
            }
        }
        .frame(width: 420, height: 260)
        .overlay(alignment: .topTrailing) { closeButton }
        .onAppear { viewModel.start() }
        .onChange(of: viewModel.focusInputTrigger) { _, _ in inputFocused = true }
    }

    // Quits the whole widget process — not just hiding the panel — so there's
    // always one unambiguous "stop for now" regardless of what state (voice
    // capture, mid-reply, error) the widget was in when clicked.
    private var closeButton: some View {
        Button {
            NSApplication.shared.terminate(nil)
        } label: {
            Image(systemName: "xmark")
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(.white.opacity(0.6))
                .frame(width: 20, height: 20)
                .background(Color.white.opacity(0.1), in: Circle())
        }
        .buttonStyle(.plain)
        .padding(10)
    }

    @ViewBuilder
    private var conversationArea: some View {
        if viewModel.transcript.isEmpty && viewModel.reply.isEmpty {
            Text("hold \u{2303} to talk \u{00b7} \u{2303}\u{2318} to type")
                .font(.system(size: 13))
                .foregroundStyle(.white.opacity(0.35))
        } else {
            VStack(alignment: .leading, spacing: 10) {
                if !viewModel.transcript.isEmpty {
                    Text(viewModel.transcript)
                        .font(.system(size: 13))
                        .foregroundStyle(.white.opacity(0.55))
                }
                if !viewModel.reply.isEmpty {
                    Text(viewModel.reply)
                        .font(.system(size: 15))
                        .foregroundStyle(.white.opacity(0.92))
                }
            }
        }
        if case .error(let message) = viewModel.status {
            Text(message)
                .font(.system(size: 12))
                .foregroundStyle(.red.opacity(0.85))
                .padding(.top, 6)
        }
    }

    private var inputBar: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(pillDotColor)
                .frame(width: 6, height: 6)
                .opacity(isBusy ? 1 : 0.5)
                .padding(.leading, 8)

            TextField("Message Edith…", text: $typed)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .foregroundStyle(.white)
                .tint(.white)
                .focused($inputFocused)
                .onSubmit(send)

            Spacer(minLength: 0)
        }
        .frame(height: 36)
        .background(Color.white.opacity(0.08), in: inputShape)
        .overlay(inputShape.stroke(Color.white.opacity(0.28), lineWidth: 1))
    }

    private func send() {
        let text = typed.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        viewModel.sendTyped(text)
        typed = ""
    }

    private var isBusy: Bool {
        switch viewModel.status {
        case .listening, .thinking, .speaking: return true
        default: return false
        }
    }

    private var pillDotColor: Color {
        switch viewModel.status {
        case .listening: return .red
        case .thinking: return .yellow
        case .speaking: return .green
        case .error: return .red
        default: return .white
        }
    }
}
