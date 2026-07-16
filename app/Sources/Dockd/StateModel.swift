import Foundation
import os

struct DockdState: Equatable {
    var docked: Bool?
    var airpodsAvailable: Bool?   // nil = bluetooth unreadable
    var airpodsConnected = false
    var airpodsActiveOutput = false
    var airpodsActiveInput = false
    var obsRunning = false
    var virtualcamActive = false
    var currentProfile: String?
    var onAir = false
    var inMeeting = false
    var onairHealthy = false
    var camSleepHealthy = false
}

/// Polls the dockd CLIs, applies the dock automation rules, and supervises
/// the daemons. All state mutation happens on the main queue.
final class StateModel {
    static let log = Logger(subsystem: "com.jvogt.dockd", category: "state")

    private(set) var state = DockdState()
    var onChange: ((DockdState) -> Void)?

    private let camSleep = DaemonSupervisor(
        name: "virtualcam-sleep", tool: "dockd-virtualcam-sleep", args: ["run"]
    )
    private let onair = DaemonSupervisor(name: "onair", tool: "dockd-onair", args: ["run"])
    private var timer: Timer?
    private var polling = false
    private var repollRequested = false
    private var pollCount = 0
    /// Dock state the OBS-profile automation last acted on.
    private var appliedDockState: Bool?

    func start() {
        camSleep.start()
        poll()
        timer = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { [weak self] _ in
            self?.poll()
        }
    }

    func shutdown() {
        timer?.invalidate()
        camSleep.stop()
        onair.stop()
    }

    func poll() {
        guard !polling else {
            repollRequested = true  // run again as soon as the current poll ends
            return
        }
        polling = true
        pollCount += 1
        // system_profiler is slow; check the dock every 4th cycle (~12s)
        let checkDock = pollCount % 4 == 1
        DispatchQueue.global(qos: .utility).async { [weak self] in
            guard let self else { return }
            // Start from the previous state so one failed tool doesn't
            // read as a state change.
            var next = self.state

            if checkDock, let dock = ToolRunner.run("dockd-dock", ["status"], timeout: 40) {
                next.docked = dock["docked"] as? Bool
            }
            if let pods = ToolRunner.run("dockd-audio", ["airpods", "status"]) {
                next.airpodsAvailable = pods["available"] as? Bool
                next.airpodsConnected = pods["connected"] as? Bool ?? false
                next.airpodsActiveOutput = pods["active_output"] as? Bool ?? false
                next.airpodsActiveInput = pods["active_input"] as? Bool ?? false
                if next.airpodsAvailable == nil && next.airpodsConnected {
                    next.airpodsAvailable = true
                }
            }
            if let obs = ToolRunner.run("dockd-obs", ["status"]) {
                next.obsRunning = obs["running"] as? Bool ?? false
                next.virtualcamActive = obs["virtualcam_active"] as? Bool ?? false
                next.currentProfile = obs["current"] as? String
            }
            if let onairStatus = ToolRunner.run("dockd-onair", ["status"]) {
                next.onairHealthy = onairStatus["healthy"] as? Bool ?? false
                next.onAir = onairStatus["on_air"] as? Bool ?? false
                next.inMeeting = onairStatus["in_meeting"] as? Bool ?? false
            }
            if let camStatus = ToolRunner.run("dockd-virtualcam-sleep", ["status"]) {
                next.camSleepHealthy = camStatus["healthy"] as? Bool ?? false
            }

            DispatchQueue.main.async {
                self.polling = false
                let previous = self.state
                self.state = next
                self.applyAutomations(current: next)
                if next != previous {
                    self.onChange?(next)
                }
                if self.repollRequested {
                    self.repollRequested = false
                    self.poll()
                }
            }
        }
    }

    /// README behavior: docked → mapped "Docked" profile + on-air watch on;
    /// undocked → mapped "Undocked" profile + on-air watch off. OBS is
    /// started if it should be running but isn't.
    private func applyAutomations(current: DockdState) {
        guard let docked = current.docked else { return }

        if docked {
            if !onair.isRunning { onair.start() }
        } else {
            if onair.isRunning { onair.stop() }
        }

        guard docked != appliedDockState else { return }
        appliedDockState = docked

        let slot = docked ? "docked" : "undocked"
        Self.log.info("dock state: \(docked ? "docked" : "undocked", privacy: .public); applying profile slot \(slot, privacy: .public)")
        DispatchQueue.global(qos: .userInitiated).async {
            if !current.obsRunning {
                ToolRunner.run("dockd-obs", ["ensure-running"], timeout: 30)
            }
            ToolRunner.run("dockd-obs", ["profile", "set", "--slot", slot])
            DispatchQueue.main.async { self.poll() }
        }
    }

    // MARK: - user actions

    /// Menubar click behavior: toggle AirPods as output when possible.
    func toggleAirpods(completion: @escaping ([String: Any]?) -> Void) {
        ToolRunner.runAsync("dockd-audio", ["airpods", "toggle"], timeout: 30) { result in
            // The toggle result carries the fresh AirPods status — apply it
            // immediately so the icon updates without waiting for a poll.
            if let result, result["ok"] as? Bool == true {
                var next = self.state
                if let value = result["available"] as? Bool { next.airpodsAvailable = value }
                next.airpodsConnected = result["connected"] as? Bool ?? next.airpodsConnected
                next.airpodsActiveOutput = result["active_output"] as? Bool ?? next.airpodsActiveOutput
                next.airpodsActiveInput = result["active_input"] as? Bool ?? next.airpodsActiveInput
                if next != self.state {
                    self.state = next
                    self.onChange?(next)
                }
            }
            self.poll()
            completion(result)
        }
    }

    func toggleVirtualcam() {
        ToolRunner.runAsync("dockd-obs", ["virtualcam", "toggle"]) { _ in self.poll() }
    }
}
