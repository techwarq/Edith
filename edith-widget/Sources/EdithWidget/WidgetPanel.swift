import SwiftUI
import AppKit

final class WidgetPanel: NSPanel {
    init(viewModel: WidgetViewModel) {
        let size = NSSize(width: 420, height: 260)
        super.init(
            contentRect: NSRect(origin: .zero, size: size),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        isOpaque = false
        backgroundColor = .clear
        hasShadow = true
        level = .floating
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        isMovableByWindowBackground = true
        contentView = NSHostingView(rootView: ContentView(viewModel: viewModel))
        dockToLeftEdge()
    }

    override var canBecomeKey: Bool { true }

    func dockToLeftEdge() {
        guard let screen = NSScreen.main else { return }
        let margin: CGFloat = 16
        let frame = screen.visibleFrame
        let origin = NSPoint(
            x: frame.minX + margin,
            y: frame.minY + (frame.height - self.frame.height) / 2
        )
        setFrameOrigin(origin)
    }

    func toggle() {
        if isVisible {
            orderOut(nil)
        } else {
            dockToLeftEdge()
            orderFrontRegardless()
        }
    }
}
