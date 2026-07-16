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
    var currentSceneCollection: String?
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
    private var audioPolling = false
    private var audioWatcher: AudioDeviceWatcher?
    /// Dock state the OBS scene-collection automation last acted on.
    private var appliedDockState: Bool?

    func start() {
        camSleep.start()
        // React to device swaps instantly instead of waiting for the timer.
        audioWatcher = AudioDeviceWatcher { [weak self] in
            self?.pollAudio()
        }
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
        // system_profiler is slow; check the dock every 4th cycle (~12s).
        let checkDock = pollCount % 4 == 1
        // blueutil can stall for seconds; do the full availability check
        // every 4th cycle too, and a CoreAudio-only fast check otherwise.
        let fullAirpods = pollCount % 4 == 2 || pollCount == 1
        DispatchQueue.global(qos: .utility).async { [weak self] in
            guard let self else { return }
            // Start from the previous state so one failed tool doesn't
            // read as a state change.
            var next = self.state

            if checkDock, let dock = ToolRunner.run("dockd-dock", ["status"], timeout: 40) {
                next.docked = dock["docked"] as? Bool
            }
            let airpodsArgs = fullAirpods
                ? ["airpods", "status"] : ["airpods", "status", "--fast"]
            if let pods = ToolRunner.run("dockd-audio", airpodsArgs) {
                Self.merge(airpods: pods, into: &next, fullCheck: fullAirpods)
            }
            if let obs = ToolRunner.run("dockd-obs", ["status"]) {
                next.obsRunning = obs["running"] as? Bool ?? false
                next.virtualcamActive = obs["virtualcam_active"] as? Bool ?? false
                next.currentSceneCollection = obs["current_scene_collection"] as? String
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

    /// Merge a `dockd-audio airpods status` payload into the state. On fast
    /// (CoreAudio-only) checks, `available` is unknown — keep the last full
    /// reading, but let a connected device imply availability.
    private static func merge(airpods pods: [String: Any], into next: inout DockdState, fullCheck: Bool) {
        if fullCheck, let available = pods["available"] as? Bool {
            next.airpodsAvailable = available
        }
        next.airpodsConnected = pods["connected"] as? Bool ?? false
        next.airpodsActiveOutput = pods["active_output"] as? Bool ?? false
        next.airpodsActiveInput = pods["active_input"] as? Bool ?? false
        if next.airpodsConnected {
            next.airpodsAvailable = true
        }
    }

    /// Fast, audio-only refresh triggered by CoreAudio device notifications.
    func pollAudio() {
        guard !audioPolling else { return }
        audioPolling = true
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            let pods = ToolRunner.run("dockd-audio", ["airpods", "status", "--fast"], timeout: 10)
            DispatchQueue.main.async {
                self.audioPolling = false
                guard let pods else { return }
                var next = self.state
                Self.merge(airpods: pods, into: &next, fullCheck: false)
                if next != self.state {
                    Self.log.info("audio device change applied to state")
                    self.state = next
                    self.onChange?(next)
                }
            }
        }
    }

    /// README behavior: docked → mapped "Docked" scene collection + on-air
    /// watch on; undocked → mapped "Undocked" scene collection + on-air watch
    /// off. OBS is
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
        Self.log.info("dock state: \(docked ? "docked" : "undocked", privacy: .public); applying scene-collection slot \(slot, privacy: .public)")
        DispatchQueue.global(qos: .userInitiated).async {
            if !current.obsRunning {
                ToolRunner.run("dockd-obs", ["ensure-running"], timeout: 30)
            }
            ToolRunner.run("dockd-obs", ["scene-collection", "set", "--slot", slot])
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

    /// Bounce the daemons so they pick up config changes.
    func restartDaemons() {
        camSleep.restart()
        onair.restart()
    }
}
