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
        NotificationCenter.default.addObserver(
            forName: .dockdConfigChanged, object: nil, queue: .main
        ) { [weak self] _ in
            Self.log.info("config changed; restarting daemons")
            self?.model.restartDaemons()
            self?.model.poll()
        }
        // Docking/undocking almost always changes the display layout; use that
        // as an instant trigger for a dock re-check instead of waiting for the
        // poll cadence.
        NotificationCenter.default.addObserver(
            forName: NSApplication.didChangeScreenParametersNotification,
            object: nil, queue: .main
        ) { [weak self] _ in
            Self.log.info("screen parameters changed; re-checking dock")
            self?.model.recheckDock()
        }
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
            model.toggleAirpods { [weak self] in self?.reportAirpodsToggle($0) }
        } else {
            openMenu()
        }
    }

    /// Surface an explicit toggle failure to the user — a menubar click that
    /// silently does nothing (e.g. AirPods held by a phone) is confusing.
    private func reportAirpodsToggle(_ result: [String: Any]?) {
        guard let result, result["ok"] as? Bool == false else { return }
        let detail = result["error"] as? String
            ?? "The AirPods didn't respond. Try selecting them from the macOS Sound menu."
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "Couldn't switch to AirPods"
        alert.informativeText = detail
        alert.runModal()
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

        // Without the helper tools nothing below can report real state; say so
        // up front rather than showing a menu full of "unknown"s.
        if ToolRunner.binDir() == nil {
            statusLine("⚠ Helper tools not found — reinstall Dockd")
            menu.addItem(.separator())
        }

        switch state.docked {
        case .some(true): statusLine("Docked")
        case .some(false): statusLine("Undocked")
        case .none: statusLine("Dock state unknown")
        }

        if state.airpodsAvailable == nil && !state.airpodsConnected {
            statusLine("AirPods state unknown — grant Bluetooth in System Settings")
        } else {
            statusLine(state.airpodsConnected ? "AirPods connected" : "AirPods disconnected")
        }

        statusLine(state.onAir ? "On air" : "Not on air")

        if state.obsRunning {
            statusLine(state.virtualcamActive ? "OBS virtual camera on" : "OBS virtual camera off")
            if let collection = state.currentSceneCollection {
                statusLine("OBS scene collection: \(collection)")
            }
        } else {
            statusLine("OBS not running")
        }

        statusLine("virtualcam-sleep: \(state.camSleepHealthy ? "healthy" : "not running")")
        let quickkeysHealth: String
        if !state.quickkeysHealthy {
            quickkeysHealth = "not running"
        } else {
            quickkeysHealth = state.quickkeysConnected ? "connected" : "no device"
        }
        statusLine("Quick Keys: \(quickkeysHealth)")
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
    @objc private func toggleAirpodsAction() {
        model.toggleAirpods { [weak self] in self?.reportAirpodsToggle($0) }
    }
    @objc private func openSettings() { settings.show() }
    @objc private func quitApp() { NSApp.terminate(nil) }
}
