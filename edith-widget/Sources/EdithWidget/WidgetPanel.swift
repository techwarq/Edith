import SwiftUI
import AppKit
import Combine

final class WidgetPanel: NSPanel, NSWindowDelegate {
    static let expandedSize = NSSize(width: 400, height: 340)
    static let collapsedSize = NSSize(width: 28, height: 120)
    private static let collapseAnimationDelay: TimeInterval = 0.45

    private let viewModel: WidgetViewModel
    private var cancellables = Set<AnyCancellable>()

    init(viewModel: WidgetViewModel) {
        self.viewModel = viewModel
        super.init(
            contentRect: NSRect(origin: .zero, size: Self.collapsedSize),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        level = .statusBar
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        isMovable = false
        delegate = self

        let hosting = NSHostingView(rootView: ContentView(viewModel: viewModel))
        hosting.sizingOptions = []
        contentView = hosting
        dock(size: Self.collapsedSize)

        viewModel.$isExpanded
            .removeDuplicates()
            .dropFirst()
            .sink { [weak self] expanded in self?.apply(expanded: expanded) }
            .store(in: &cancellables)
        viewModel.$focusInputTrigger
            .dropFirst()
            .sink { [weak self] _ in self?.makeKeyAndOrderFront(nil) }
            .store(in: &cancellables)
    }

    override var canBecomeKey: Bool { true }

    private func apply(expanded: Bool) {
        if expanded {
            dock(size: Self.expandedSize)
            orderFrontRegardless()
        } else {
            DispatchQueue.main.asyncAfter(deadline: .now() + Self.collapseAnimationDelay) { [weak self] in
                guard let self, !self.viewModel.isExpanded else { return }
                self.dock(size: Self.collapsedSize)
            }
        }
    }

    private func dock(size: NSSize) {
        let mouse = NSEvent.mouseLocation
        guard let screen = NSScreen.screens.first(where: { NSMouseInRect(mouse, $0.frame, false) }) ?? NSScreen.main
        else { return }
        let visible = screen.visibleFrame
        let origin = NSPoint(x: visible.minX, y: visible.midY - size.height / 2)
        setFrame(NSRect(origin: origin, size: size), display: true)
    }

    func windowDidResignKey(_ notification: Notification) {
        viewModel.collapseIfIdle()
    }
}
