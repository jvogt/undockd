import Foundation
import os

/// Locates and runs the dockd-* Python CLIs, decoding their JSON stdout.
struct ToolRunner {
    static let log = Logger(subsystem: "com.jvogt.dockd", category: "tools")

    /// Directory containing the dockd-* entry points. Resolution order:
    /// 1. DOCKD_TOOLS_BIN env var
    /// 2. config key tools.bin_dir
    /// 3. the bundled frozen tools inside
    ///    Dockd.app/Contents/Resources/dockd-tools.app/Contents/MacOS
    ///    (a PyInstaller app carrying the Bluetooth usage string; the dockd-*
    ///    names are symlinks to the shared `dockd` executable)
    static func binDir() -> URL? {
        let fm = FileManager.default
        var candidates: [URL] = []
        if let env = ProcessInfo.processInfo.environment["DOCKD_TOOLS_BIN"] {
            candidates.append(URL(fileURLWithPath: (env as NSString).expandingTildeInPath))
        }
        if let configured = Config.get("tools.bin_dir") as? String {
            candidates.append(URL(fileURLWithPath: (configured as NSString).expandingTildeInPath))
        }
        let bundled = Bundle.main.bundleURL
            .appendingPathComponent("Contents/Resources/dockd-tools.app/Contents/MacOS")
        candidates.append(bundled)
        for candidate in candidates
        where fm.isExecutableFile(atPath: candidate.appendingPathComponent("dockd-obs").path) {
            return candidate
        }
        return nil
    }

    static func toolURL(_ name: String) -> URL? {
        binDir()?.appendingPathComponent(name)
    }

    /// Run a tool synchronously; returns parsed JSON object from stdout.
    @discardableResult
    static func run(_ name: String, _ args: [String], timeout: TimeInterval = 20) -> [String: Any]? {
        guard let url = toolURL(name) else {
            log.error("tool \(name, privacy: .public) not found; set tools.bin_dir in config")
            return nil
        }
        let process = Process()
        process.executableURL = url
        process.arguments = args
        let stdout = Pipe()
        let stderr = Pipe()
        process.standardOutput = stdout
        process.standardError = stderr
        do {
            try process.run()
        } catch {
            log.error("failed to run \(name, privacy: .public): \(error.localizedDescription, privacy: .public)")
            return nil
        }
        let group = DispatchGroup()
        group.enter()
        DispatchQueue.global().async {
            process.waitUntilExit()
            group.leave()
        }
        if group.wait(timeout: .now() + timeout) == .timedOut {
            process.terminate()
            log.error("\(name, privacy: .public) timed out after \(timeout)s")
            return nil
        }
        let errData = stderr.fileHandleForReading.readDataToEndOfFile()
        if let err = String(data: errData, encoding: .utf8), !err.isEmpty {
            for line in err.split(separator: "\n") {
                log.info("[\(name, privacy: .public)] \(line, privacy: .public)")
            }
        }
        let outData = stdout.fileHandleForReading.readDataToEndOfFile()
        guard let json = try? JSONSerialization.jsonObject(with: outData) as? [String: Any] else {
            if process.terminationStatus != 0 {
                log.error("\(name, privacy: .public) exited \(process.terminationStatus)")
            }
            return nil
        }
        return json
    }

    /// Run on a background queue and deliver the result on the main queue.
    static func runAsync(
        _ name: String, _ args: [String], timeout: TimeInterval = 20,
        completion: @escaping ([String: Any]?) -> Void
    ) {
        DispatchQueue.global(qos: .userInitiated).async {
            let result = run(name, args, timeout: timeout)
            DispatchQueue.main.async { completion(result) }
        }
    }
}
