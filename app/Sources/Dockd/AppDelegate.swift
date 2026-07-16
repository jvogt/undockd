import AppKit
import os

final class AppDelegate: NSObject, NSApplicationDelegate {
    static let log = Logger(subsystem: "com.jvogt.dockd", category: "app")

    private var statusItem: NSStatusItem!
    private let model = StateModel()
    private let settings = SettingsWindowController()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.image = StatusIcon.image(for: model.state)
            button.toolTip = StatusIcon.tooltip(for: model.state)
            button.target = self
            button.action = #selector(statusItemClicked)
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
        model.onChange = { [weak self] state in
            self?.statusItem.button?.image = StatusIcon.image(for: state)
            self?.statusItem.button?.toolTip = StatusIcon.tooltip(for: state)
        }
        model.start()
        Self.log.info("Dockd started; tools at \(ToolRunner.binDir()?.path ?? "NOT FOUND", privacy: .public)")
        // Debug hook: DOCKD_OPEN_SETTINGS=1 opens the settings window on launch.
        if ProcessInfo.processInfo.environment["DOCKD_OPEN_SETTINGS"] == "1" {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.settings.show() }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        model.shutdown()
    }

    // MARK: - clicks

    @objc private func statusItemClicked() {
        let event = NSApp.currentEvent
        let isRightClick = event?.type == .rightMouseUp
            || (event?.modifierFlags.contains(.control) ?? false)
        if isRightClick {
            openMenu()
            return
        }
        // Left click: toggle AirPods; fall back to the menu when unavailable.
        let available = model.state.airpodsAvailable ?? model.state.airpodsConnected
        if available {
            Self.log.info("menubar click: toggling airpods")
            model.toggleAirpods { _ in }
        } else {
            openMenu()
        }
    }

    private func openMenu() {
        statusItem.menu = buildMenu()
        statusItem.button?.performClick(nil)
        statusItem.menu = nil  // detach so left-click keeps its custom action
    }

    private func buildMenu() -> NSMenu {
        let state = model.state
        let menu = NSMenu()

        func statusLine(_ title: String) {
            let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
        }

        switch state.docked {
        case .some(true): statusLine("Docked")
        case .some(false): statusLine("Undocked")
        case .none: statusLine("Dock state unknown")
        }

        if state.airpodsAvailable == nil && !state.airpodsConnected {
            statusLine("AirPods state unknown (Bluetooth permission?)")
        } else {
            statusLine(state.airpodsConnected ? "AirPods connected" : "AirPods disconnected")
        }

        statusLine(state.onAir ? "On air" : "Not on air")

        if state.obsRunning {
            statusLine(state.virtualcamActive ? "OBS virtual camera on" : "OBS virtual camera off")
            if let profile = state.currentProfile {
                statusLine("OBS profile: \(profile)")
            }
        } else {
            statusLine("OBS not running")
        }

        statusLine("virtualcam-sleep: \(state.camSleepHealthy ? "healthy" : "not running")")
        let onairHealth = state.docked == false
            ? "off (undocked)"
            : (state.onairHealthy ? "healthy" : "not running")
        statusLine("on-air watch: \(onairHealth)")

        menu.addItem(.separator())

        let toggleCam = NSMenuItem(
            title: state.virtualcamActive ? "Stop virtual camera" : "Start virtual camera",
            action: #selector(toggleVirtualcam), keyEquivalent: ""
        )
        toggleCam.target = self
        menu.addItem(toggleCam)

        let toggleAirpods = NSMenuItem(
            title: state.airpodsActiveOutput ? "Switch to system output" : "Use AirPods",
            action: #selector(toggleAirpodsAction), keyEquivalent: ""
        )
        toggleAirpods.target = self
        menu.addItem(toggleAirpods)

        menu.addItem(.separator())

        let settingsItem = NSMenuItem(
            title: "Settings…", action: #selector(openSettings), keyEquivalent: ","
        )
        settingsItem.target = self
        menu.addItem(settingsItem)

        let quit = NSMenuItem(title: "Quit Dockd", action: #selector(quitApp), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)

        return menu
    }

    @objc private func toggleVirtualcam() { model.toggleVirtualcam() }
    @objc private func toggleAirpodsAction() { model.toggleAirpods { _ in } }
    @objc private func openSettings() { settings.show() }
    @objc private func quitApp() { NSApp.terminate(nil) }
}
