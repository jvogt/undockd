import Foundation
import os

/// Keeps a dockd daemon (virtualcam-sleep, onair) running as a child process,
/// restarting with backoff, forwarding its stderr into the unified log.
final class DaemonSupervisor {
    let name: String
    let tool: String
    let args: [String]
    private let log: Logger
    private var process: Process?
    private var desired = false
    private var restartDelay: TimeInterval = 1

    init(name: String, tool: String, args: [String]) {
        self.name = name
        self.tool = tool
        self.args = args
        self.log = Logger(subsystem: "com.jvogt.dockd", category: name)
    }

    var isRunning: Bool { process?.isRunning ?? false }

    func start() {
        desired = true
        launchIfNeeded()
    }

    func stop() {
        desired = false
        guard let process, process.isRunning else { return }
        log.info("stopping \(self.name, privacy: .public)")
        process.terminate()
    }

    /// Terminate the child; the termination handler relaunches it (used to
    /// pick up config changes).
    func restart() {
        guard desired else { return }
        if let process, process.isRunning {
            log.info("restarting \(self.name, privacy: .public)")
            restartDelay = 1
            process.terminate()
        } else {
            launchIfNeeded()
        }
    }

    private func launchIfNeeded() {
        guard desired, !(process?.isRunning ?? false) else { return }
        guard let url = ToolRunner.toolURL(tool) else {
            log.error("cannot start \(self.name, privacy: .public): tool \(self.tool, privacy: .public) not found")
            scheduleRetry()
            return
        }
        let proc = Process()
        proc.executableURL = url
        proc.arguments = args
        let stderr = Pipe()
        proc.standardError = stderr
        proc.standardOutput = Pipe()
        stderr.fileHandleForReading.readabilityHandler = { [log] handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            for line in text.split(separator: "\n") {
                log.info("\(line, privacy: .public)")
            }
        }
        proc.terminationHandler = { [weak self] finished in
            DispatchQueue.main.async {
                guard let self else { return }
                stderr.fileHandleForReading.readabilityHandler = nil
                if self.desired {
                    self.log.warning("\(self.name, privacy: .public) exited (\(finished.terminationStatus)); restarting in \(self.restartDelay)s")
                    self.scheduleRetry()
                } else {
                    self.log.info("\(self.name, privacy: .public) stopped")
                }
            }
        }
        do {
            try proc.run()
            process = proc
            restartDelay = 1
            log.info("started \(self.name, privacy: .public) (pid \(proc.processIdentifier))")
        } catch {
            log.error("failed to start \(self.name, privacy: .public): \(error.localizedDescription, privacy: .public)")
            scheduleRetry()
        }
    }

    private func scheduleRetry() {
        let delay = restartDelay
        restartDelay = min(restartDelay * 2, 60)
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            self?.launchIfNeeded()
        }
    }
}
