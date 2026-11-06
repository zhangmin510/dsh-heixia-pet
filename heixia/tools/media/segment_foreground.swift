import Foundation
import Vision
import CoreImage
import CoreVideo
import ImageIO
import UniformTypeIdentifiers
import CoreML

// API contract read from this machine's macOS 26 SDK:
// Vision/VNGenerateForegroundInstanceMaskRequest.h and VNObservation.h.
// All operations run locally; no image is uploaded or generatively repainted.

enum SegmentationError: Error, CustomStringConvertible {
    case failed(String)
    var description: String {
        switch self { case .failed(let message): return message }
    }
}

struct FrameReport: Codable {
    let input: String
    let output: String
    let width: Int
    let height: Int
    let allInstances: [Int]
    let selectedInstance: Int
    let maskPixelFormat: UInt32
    let configuredComputeDevices: [String: String]
    let bbox: [Int]
    let alphaMin: Int
    let alphaMax: Int
    let transparentPixels: Int
    let foregroundPixels: Int
    let partialAlphaPixels: Int
    let elapsedSeconds: Double
}

struct Report: Codable {
    let engine: String
    let requestRevision: Int
    let focusPointTopLeftNormalized: [Double]
    let startedAt: String
    let finishedAt: String
    let pid: Int32
    let frames: [FrameReport]
}

let args = Array(CommandLine.arguments.dropFirst())
guard args.count == 3 || args.count == 5 else {
    fputs("Usage: segment_foreground INPUT_FILE_OR_PNG_DIR OUTPUT_DIR REPORT_JSON [FOCUS_X FOCUS_Y]\n", stderr)
    exit(2)
}
let inputURL = URL(fileURLWithPath: args[0]).standardizedFileURL
let outputURL = URL(fileURLWithPath: args[1]).standardizedFileURL
let reportURL = URL(fileURLWithPath: args[2]).standardizedFileURL
let focusX = args.count == 5 ? Double(args[3]) ?? -1 : 0.5
let focusY = args.count == 5 ? Double(args[4]) ?? -1 : 0.5
guard (0...1).contains(focusX), (0...1).contains(focusY) else {
    fputs("Focus coordinates must be normalized top-left coordinates in [0,1].\n", stderr)
    exit(2)
}

let formatter = ISO8601DateFormatter()
let started = formatter.string(from: Date())
let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!
let context = CIContext(options: [.workingColorSpace: colorSpace, .outputColorSpace: colorSpace])

func segment(_ input: URL, to output: URL) throws -> FrameReport {
    let start = Date()
    guard let source = CGImageSourceCreateWithURL(input as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        throw SegmentationError.failed("Cannot decode input: \(input.path)")
    }
    let handler = VNImageRequestHandler(cgImage: image, orientation: .up, options: [:])
    let request = VNGenerateForegroundInstanceMaskRequest()
    request.revision = VNGenerateForegroundInstanceMaskRequestRevision1
    // Sandbox access to ANE can fail despite the system model being present.
    // Use advertised CPU devices explicitly; no model download or fallback matte.
    var configuredDevices: [String: String] = [:]
    for (stage, devices) in try request.supportedComputeStageDevices {
        if let cpu = devices.first(where: { if case .cpu = $0 { return true }; return false }) {
            request.setComputeDevice(cpu, for: stage)
            configuredDevices[stage.rawValue] = cpu.description
        }
    }
    try handler.perform([request])
    guard let observation = request.results?.first, !observation.allInstances.isEmpty else {
        throw SegmentationError.failed("Vision found no foreground instance: \(input.path)")
    }
    let labels = observation.instanceMask
    guard CVPixelBufferGetPixelFormatType(labels) == kCVPixelFormatType_OneComponent8 else {
        throw SegmentationError.failed("Unexpected Vision instance-mask format: \(CVPixelBufferGetPixelFormatType(labels))")
    }
    CVPixelBufferLockBaseAddress(labels, .readOnly)
    defer { CVPixelBufferUnlockBaseAddress(labels, .readOnly) }
    let labelWidth = CVPixelBufferGetWidth(labels)
    let labelHeight = CVPixelBufferGetHeight(labels)
    let stride = CVPixelBufferGetBytesPerRow(labels)
    let labelData = CVPixelBufferGetBaseAddress(labels)!.assumingMemoryBound(to: UInt8.self)
    let px = min(labelWidth - 1, max(0, Int(focusX * Double(labelWidth))))
    let py = min(labelHeight - 1, max(0, Int(focusY * Double(labelHeight))))
    var selected = Int(labelData[py * stride + px])
    if selected == 0 || !observation.allInstances.contains(selected) {
        // Search a small region around the reviewed focus point, not all objects.
        let radius = max(1, min(labelWidth, labelHeight) / 12)
        var counts: [Int: Int] = [:]
        for y in max(0, py - radius)...min(labelHeight - 1, py + radius) {
            for x in max(0, px - radius)...min(labelWidth - 1, px + radius) {
                let value = Int(labelData[y * stride + x])
                if value != 0 { counts[value, default: 0] += 1 }
            }
        }
        guard let nearby = counts.max(by: { $0.value < $1.value })?.key else {
            throw SegmentationError.failed("No foreground at reviewed focus point; do not choose unrelated objects: \(input.path)")
        }
        selected = nearby
    }
    let scaledMask = try observation.generateScaledMaskForImage(forInstances: IndexSet(integer: selected), from: handler)
    let original = CIImage(cgImage: image)
    let mask = CIImage(cvPixelBuffer: scaledMask)
    let clear = CIImage(color: CIColor.clear).cropped(to: original.extent)
    guard let blend = CIFilter(name: "CIBlendWithMask", parameters: [
        kCIInputImageKey: original,
        kCIInputBackgroundImageKey: clear,
        kCIInputMaskImageKey: mask,
    ])?.outputImage,
    let result = context.createCGImage(blend, from: original.extent, format: .RGBA8, colorSpace: colorSpace),
    let data = result.dataProvider?.data,
    let pixels = CFDataGetBytePtr(data) else {
        throw SegmentationError.failed("Could not create transparent RGBA output: \(input.path)")
    }
    let width = result.width, height = result.height
    var minX = width, minY = height, maxX = -1, maxY = -1
    var alphaMin = 255, alphaMax = 0, transparent = 0, foreground = 0, partial = 0
    for y in 0..<height {
        for x in 0..<width {
            let alpha = Int(pixels[y * result.bytesPerRow + x * 4 + 3])
            alphaMin = min(alphaMin, alpha); alphaMax = max(alphaMax, alpha)
            if alpha == 0 { transparent += 1 }
            if alpha > 0 && alpha < 255 { partial += 1 }
            if alpha >= 12 {
                foreground += 1
                minX = min(minX, x); minY = min(minY, y)
                maxX = max(maxX, x); maxY = max(maxY, y)
            }
        }
    }
    guard maxX >= minX, maxY >= minY, alphaMin == 0, alphaMax > 200 else {
        throw SegmentationError.failed("Invalid/opaque foreground mask: \(input.path)")
    }
    guard let destination = CGImageDestinationCreateWithURL(output as CFURL, UTType.png.identifier as CFString, 1, nil) else {
        throw SegmentationError.failed("Could not create output PNG: \(output.path)")
    }
    CGImageDestinationAddImage(destination, result, nil)
    guard CGImageDestinationFinalize(destination) else { throw SegmentationError.failed("PNG write failed") }
    return FrameReport(input: input.path, output: output.path, width: width, height: height,
                       allInstances: observation.allInstances.map { $0 }, selectedInstance: selected,
                       maskPixelFormat: CVPixelBufferGetPixelFormatType(labels),
                       configuredComputeDevices: configuredDevices,
                       bbox: [minX, minY, maxX - minX + 1, maxY - minY + 1], alphaMin: alphaMin, alphaMax: alphaMax,
                       transparentPixels: transparent, foregroundPixels: foreground,
                       partialAlphaPixels: partial, elapsedSeconds: Date().timeIntervalSince(start))
}

do {
    try FileManager.default.createDirectory(at: outputURL, withIntermediateDirectories: true)
    var isDirectory: ObjCBool = false
    guard FileManager.default.fileExists(atPath: inputURL.path, isDirectory: &isDirectory) else {
        throw SegmentationError.failed("Input does not exist")
    }
    let inputs = isDirectory.boolValue
        ? try FileManager.default.contentsOfDirectory(at: inputURL, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension.lowercased() == "png" }.sorted { $0.lastPathComponent < $1.lastPathComponent }
        : [inputURL]
    guard !inputs.isEmpty else { throw SegmentationError.failed("No PNG frames") }
    var frames: [FrameReport] = []
    for input in inputs {
        let output = outputURL.appendingPathComponent(input.deletingPathExtension().lastPathComponent + ".png")
        let frame: FrameReport = try autoreleasepool { try segment(input, to: output) }
        frames.append(frame)
        print("\(frames.count)/\(inputs.count) \(input.lastPathComponent) instance=\(frame.selectedInstance) bbox=\(frame.bbox)")
        fflush(stdout)
    }
    let report = Report(engine: "Apple Vision VNGenerateForegroundInstanceMaskRequest, local system framework", requestRevision: 1,
                        focusPointTopLeftNormalized: [focusX, focusY], startedAt: started,
                        finishedAt: formatter.string(from: Date()), pid: ProcessInfo.processInfo.processIdentifier, frames: frames)
    let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    try encoder.encode(report).write(to: reportURL, options: .atomic)
} catch {
    fputs("ERROR: \(error)\n", stderr)
    exit(1)
}
