import SwiftUI
import AppKit

struct ContentView: View {
    @ObservedObject var viewModel: WidgetViewModel
    @State private var typed: String = ""
    @State private var hovering = false
    @State private var showingSetup = false
    @State private var showingLeads = false
    @StateObject private var leads = LeadsModel()
    @StateObject private var permissions = PermissionsManager()
    @FocusState private var inputFocused: Bool

    @ObservedObject private var layout = PanelLayout.shared
    @State private var dragStart: (mouse: NSPoint, size: CGSize)?
    private var expanded: CGSize { layout.size }
    private let collapsed = WidgetPanel.collapsedSize

    private var isOpen: Bool { viewModel.isExpanded }
    private var flare: CGFloat { isOpen ? 16 : 8 }
    private var notchShape: NotchShape { NotchShape(flare: flare, radius: isOpen ? 26 : 7) }

    var body: some View {
        ZStack(alignment: .leading) {
            notch
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .animation(.spring(response: 0.42, dampingFraction: 0.8), value: isOpen)
        .onAppear { viewModel.start() }
        .onChange(of: viewModel.focusInputTrigger) { _, _ in inputFocused = true }
        .onChange(of: inputFocused) { _, focused in viewModel.isTyping = focused }
        .onExitCommand { viewModel.isBusy ? viewModel.stopWork() : viewModel.collapse() }
        .onChange(of: isOpen) { _, open in
            permissions.refresh()

            if open && !permissions.allGranted && !viewModel.isBusy { showingSetup = true }
        }
        .onChange(of: showingSetup) { _, showing in
            if showing { permissions.startPolling() } else { permissions.stopPolling() }
        }
        .onChange(of: showingLeads) { _, showing in viewModel.isPinned = showing }
    }

    private var notch: some View {
        ZStack(alignment: .topLeading) {
            notchShape
                .fill(Color.black)
                .overlay(notchShape.stroke(Color.white.opacity(isOpen ? 0.09 : 0.05), lineWidth: 1))
                .shadow(color: .black.opacity(isOpen ? 0.45 : 0), radius: 18, x: 6)

            if isOpen {
                expandedContent
                    .padding(.vertical, flare)
                    .transition(.opacity.combined(with: .scale(scale: 0.92, anchor: .leading)))
                resizeHandles
                    .padding(.vertical, flare)
                    .transition(.opacity)
            } else {
                collapsedTab
                    .transition(.opacity)
            }
        }
        .frame(
            width: isOpen ? expanded.width - 24 : (hovering ? collapsed.width - 6 : collapsed.width - 14),
            height: isOpen ? expanded.height : collapsed.height
        )
        .onHover { inside in
            hovering = inside
            viewModel.isHovering = inside
        }
    }

    private var resizeHandles: some View {
        GeometryReader { geo in
            ZStack {
                Capsule()
                    .fill(Color.white.opacity(dragStart == nil ? 0.18 : 0.45))
                    .frame(width: 4, height: 44)
                    .frame(width: 14, height: geo.size.height)
                    .contentShape(Rectangle())
                    .position(x: geo.size.width - 6, y: geo.size.height / 2)
                    .gesture(resizeDrag(width: true, height: false))
                    .onHover { inside in (inside ? NSCursor.resizeLeftRight : NSCursor.arrow).set() }
                    .help("Drag to resize · double-click for full height")
                    .onTapGesture(count: 2) { layout.toggleFullHeight() }
                Image(systemName: "arrow.up.left.and.arrow.down.right")
                    .font(.system(size: 9, weight: .bold))
                    .foregroundStyle(.white.opacity(dragStart == nil ? 0.25 : 0.6))
                    .frame(width: 22, height: 22)
                    .contentShape(Rectangle())
                    .position(x: geo.size.width - 14, y: geo.size.height - 14)
                    .gesture(resizeDrag(width: true, height: true))
                    .onHover { inside in (inside ? NSCursor.crosshair : NSCursor.arrow).set() }
                    .help("Drag to resize")
            }
        }
    }

    private func resizeDrag(width: Bool, height: Bool) -> some Gesture {
        DragGesture(minimumDistance: 1, coordinateSpace: .global)
            .onChanged { _ in
                let mouse = NSEvent.mouseLocation
                if dragStart == nil { dragStart = (mouse, layout.size) }
                guard let start = dragStart else { return }
                viewModel.isPinned = true
                var next = start.size
                if width { next.width = start.size.width + (mouse.x - start.mouse.x) }
                if height { next.height = start.size.height + 2 * (start.mouse.y - mouse.y) }
                layout.resize(to: next)
            }
            .onEnded { _ in
                dragStart = nil
                viewModel.isPinned = showingLeads
            }
    }

    private var collapsedTab: some View {
        VStack {
            Spacer()
            Capsule()
                .fill(accent)
                .frame(width: 3, height: viewModel.isBusy ? 22 : 14)
                .shadow(color: accent.opacity(0.9), radius: viewModel.isBusy ? 6 : 2)
                .opacity(viewModel.isBusy ? 1 : 0.55)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .contentShape(Rectangle())
        .onTapGesture { viewModel.requestTextFocus() }
        .help("Eddy — hold ⌃ to talk, ⌃⌘ to type")
    }

    private var expandedContent: some View {
        VStack(alignment: .leading, spacing: 12) {
            header
            if case .listening = viewModel.status {
                Waveform(levels: viewModel.levels, color: accent)
                    .frame(height: 30)
                    .transition(.opacity)
            }
            if showingSetup {
                setupList
                    .transition(.opacity)
            } else if showingLeads {
                LeadsView(model: leads, accent: accent)
                    .transition(.opacity)
            } else {
                if !permissions.allGranted { setupBanner }
                conversation
                inputBar
            }
        }
        .padding(.leading, 20)
        .padding(.trailing, 18)
        .padding(.vertical, 16)
    }

    private var header: some View {
        HStack(spacing: 10) {
            Orb(color: accent, level: viewModel.levels.last ?? 0, busy: viewModel.isBusy)
                .frame(width: 26, height: 26)
            VStack(alignment: .leading, spacing: 1) {
                Text("Eddy")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.white)
                Text(statusLabel)
                    .font(.system(size: 11))
                    .foregroundStyle(.white.opacity(0.45))
                    .contentTransition(.opacity)
            }
            Spacer()
            iconButton(showingLeads ? "bubble.left.fill" : "briefcase.fill",
                       help: showingLeads ? "Back to chat" : "Find startups",
                       tint: leads.isSearching ? accent : nil) {
                withAnimation(.easeOut(duration: 0.2)) {
                    showingSetup = false
                    showingLeads.toggle()
                }
            }
            iconButton(showingSetup ? "bubble.left.fill" : "lock.shield",
                       help: showingSetup ? "Back to chat" : "Permissions",
                       tint: permissions.allGranted ? nil : Color.orange) {
                withAnimation(.easeOut(duration: 0.2)) {
                    showingLeads = false
                    showingSetup.toggle()
                }
            }
            iconButton("chevron.left", help: "Tuck away (esc)") { viewModel.collapse() }
        }
        .contextMenu {
            Button("Quit Eddy") { NSApplication.shared.terminate(nil) }
        }
    }

    @ViewBuilder
    private var conversation: some View {
        ScrollViewReader { proxy in
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                if viewModel.transcript.isEmpty && viewModel.reply.isEmpty {
                    hints
                } else {
                    if !viewModel.transcript.isEmpty {
                        Text(viewModel.transcript)
                            .font(.system(size: 13))
                            .foregroundStyle(.white.opacity(0.5))
                            .textSelection(.enabled)
                    }
                    if !viewModel.reply.isEmpty {
                        Text(Self.markdown(viewModel.reply))
                            .font(.system(size: 14.5))
                            .foregroundStyle(.white.opacity(0.94))
                            .lineSpacing(2)
                            .textSelection(.enabled)
                    }
                }
                if case .error(let message) = viewModel.status {
                    Label(message, systemImage: "exclamationmark.triangle.fill")
                        .font(.system(size: 12))
                        .foregroundStyle(.red.opacity(0.85))
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            Color.clear.frame(height: 1).id(Self.bottomID)
        }
        .scrollIndicators(.never)
        .frame(maxHeight: .infinity)

        .onChange(of: viewModel.reply) { _, _ in proxy.scrollTo(Self.bottomID, anchor: .bottom) }
        }
    }

    private static let bottomID = "bottom"

    private static func markdown(_ text: String) -> AttributedString {
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        return (try? AttributedString(markdown: text, options: options)) ?? AttributedString(text)
    }

    private var setupBanner: some View {
        Button {
            withAnimation(.easeOut(duration: 0.2)) { showingSetup = true }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: "exclamationmark.shield.fill")
                    .foregroundStyle(.orange)
                Text("\(permissions.missing.count) permission\(permissions.missing.count == 1 ? "" : "s") needed")
                    .foregroundStyle(.white.opacity(0.8))
                Spacer()
                Text("Set up")
                    .foregroundStyle(.orange)
            }
            .font(.system(size: 12, weight: .medium))
            .padding(.horizontal, 12)
            .frame(height: 30)
            .background(Color.orange.opacity(0.12), in: Capsule())
        }
        .buttonStyle(.plain)
    }

    private var setupList: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(permissions.allGranted ? "Eddy has full access" : "Give Eddy access")
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(.white.opacity(0.9))
            VStack(spacing: 2) {
                ForEach(Permission.allCases) { permission in
                    permissionRow(permission)
                }
            }
            Spacer(minLength: 0)
            HStack {
                Text("Turned one on and it's still grey?")
                    .font(.system(size: 11))
                    .foregroundStyle(.white.opacity(0.4))
                Button("Relaunch") { permissions.relaunch() }
                    .buttonStyle(.plain)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(accent)
                Spacer()
                Button("Done") { withAnimation(.easeOut(duration: 0.2)) { showingSetup = false } }
                    .buttonStyle(.plain)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.black)
                    .padding(.horizontal, 12)
                    .frame(height: 26)
                    .background(Color.white, in: Capsule())
            }
        }
        .frame(maxHeight: .infinity, alignment: .top)
    }

    private func permissionRow(_ permission: Permission) -> some View {
        let granted = permissions.granted[permission] == true
        return HStack(spacing: 10) {
            Image(systemName: permission.symbol)
                .font(.system(size: 11))
                .foregroundStyle(.white.opacity(0.7))
                .frame(width: 24, height: 24)
                .background(Color.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 6))
            VStack(alignment: .leading, spacing: 0) {
                Text(permission.title)
                    .font(.system(size: 12.5, weight: .medium))
                    .foregroundStyle(.white.opacity(0.9))
                Text(permission.purpose)
                    .font(.system(size: 10.5))
                    .foregroundStyle(.white.opacity(0.4))
            }
            Spacer()
            if granted {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 15))
                    .foregroundStyle(Color(red: 0.35, green: 0.9, blue: 0.6))
            } else {
                Button("Allow") { permissions.request(permission) }
                    .buttonStyle(.plain)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 10)
                    .frame(height: 22)
                    .background(Color.white.opacity(0.14), in: Capsule())
            }
        }
        .padding(.vertical, 3)
    }

    private var hints: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("What can I do for you?")
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(.white.opacity(0.85))
            HStack(spacing: 14) {
                hint(keys: "⌃", label: "hold to talk")
                hint(keys: "⌃⌘", label: "type")
                hint(keys: "esc", label: "close")
            }
        }
        .padding(.top, 4)
    }

    private func hint(keys: String, label: String) -> some View {
        HStack(spacing: 5) {
            Text(keys)
                .font(.system(size: 10, weight: .medium, design: .rounded))
                .foregroundStyle(.white.opacity(0.7))
                .padding(.horizontal, 5)
                .padding(.vertical, 2)
                .background(Color.white.opacity(0.1), in: RoundedRectangle(cornerRadius: 4))
            Text(label)
                .font(.system(size: 11))
                .foregroundStyle(.white.opacity(0.4))
        }
    }

    private var inputBar: some View {
        HStack(spacing: 6) {
            TextField("Ask Eddy anything…", text: $typed)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .foregroundStyle(.white)
                .tint(accent)
                .focused($inputFocused)
                .onSubmit(send)
                .padding(.leading, 12)

            iconButton(isListening ? "stop.fill" : "mic.fill",
                       help: isListening ? "Stop listening" : "Talk",
                       tint: isListening ? accent : nil) {
                viewModel.toggleVoiceCapture()
            }
            if !typed.isEmpty {
                iconButton("arrow.up", help: "Send", filled: true, action: send)
                    .transition(.scale.combined(with: .opacity))
            }
        }
        .padding(.trailing, 4)
        .frame(height: 38)
        .background(Color.white.opacity(0.07), in: Capsule())
        .overlay(Capsule().stroke(Color.white.opacity(inputFocused ? 0.22 : 0.1), lineWidth: 1))
        .animation(.easeOut(duration: 0.15), value: typed.isEmpty)
    }

    private func iconButton(
        _ symbol: String,
        help: String,
        tint: Color? = nil,
        filled: Bool = false,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(filled ? .black : (tint ?? .white.opacity(0.7)))
                .frame(width: 28, height: 28)
                .background(filled ? Color.white : Color.white.opacity(0.08), in: Circle())
        }
        .buttonStyle(.plain)
        .help(help)
    }

    private func send() {
        let text = typed.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        viewModel.sendTyped(text)
        typed = ""
    }

    private var isListening: Bool {
        if case .listening = viewModel.status { return true }
        return false
    }

    private var statusLabel: String {
        if !viewModel.activity.isEmpty, case .thinking = viewModel.status { return viewModel.activity }
        switch viewModel.status {
        case .idle: return "Ready"
        case .connecting: return "Connecting…"
        case .listening: return "Listening…"
        case .thinking: return "Working on it…"
        case .speaking: return "Replying"
        case .error: return "Something went wrong"
        }
    }

    private var accent: Color {
        switch viewModel.status {
        case .listening: return Color(red: 1.0, green: 0.36, blue: 0.42)
        case .thinking: return Color(red: 1.0, green: 0.78, blue: 0.3)
        case .speaking: return Color(red: 0.35, green: 0.9, blue: 0.6)
        case .error: return .red
        case .idle, .connecting: return Color(red: 0.45, green: 0.65, blue: 1.0)
        }
    }
}

private struct Orb: View {
    let color: Color
    let level: Float
    let busy: Bool

    var body: some View {
        TimelineView(.animation(paused: !busy)) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            ZStack {
                Circle()
                    .fill(color.opacity(0.35))
                    .blur(radius: 6)
                    .scaleEffect(1 + CGFloat(level) * 0.6)
                Circle()
                    .fill(AngularGradient(
                        colors: [color, color.opacity(0.4), .white.opacity(0.9), color],
                        center: .center,
                        angle: .degrees(busy ? t * 120 : 0)
                    ))
                    .overlay(Circle().stroke(.white.opacity(0.25), lineWidth: 0.5))
                    .scaleEffect(0.82 + CGFloat(level) * 0.25)
            }
        }
        .animation(.easeOut(duration: 0.12), value: level)
    }
}

private struct Waveform: View {
    let levels: [Float]
    let color: Color

    var body: some View {
        HStack(alignment: .center, spacing: 3) {
            ForEach(Array(levels.enumerated()), id: \.offset) { _, level in
                Capsule()
                    .fill(color.opacity(0.35 + Double(level) * 0.65))
                    .frame(width: 3, height: max(3, CGFloat(level) * 30))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .animation(.easeOut(duration: 0.08), value: levels)
    }
}
