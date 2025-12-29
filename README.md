# Display Monitor Configuration & Analysis Tool

A professional-grade system for configuring, monitoring, and analyzing multiple display regions from camera feeds. Designed for automotive display testing, validation, and long-term stability monitoring.

## 🚀 Recent Major Updates

- **Unified Glitch Engine**: Detects transient visual anomalies (flicker, block corruption, pixel artifacts) with severity levels.
- **OCR Intelligence**: Integrated EasyOCR for identifying textual error states (e.g., "NO SIGNAL") with negative pattern matching.
- **Post-Capture Video Analysis**: Native file picker and analysis engine for recorded sessions with live playback synchronization.
- **Context-Aware Logging**: Every log entry is prefixed with `[Display: Name, Camera: ID]` for granular debugging.

## Features

### Configuration Mode
- **Live Camera Streaming**: Real-time camera feed with browser-based access.
- **Hardened Hardware Discovery**: "Fuzzy Matching" reconciles camera names even if hardware IDs change.
- **Manual Area Selection**: Draw and rotate display regions with intuitive handles.
- **Robust Resolution Handling**: Intelligent width-based scaling ensures correct region capture even if camera resolution falls back (e.g. 1080p -> 480p).
- **Perspective Correction (RECTIFY)**: Bilinear homography using 16-cell subdivision for high-fidelity warping.
- **Configuration Persistence**: Save to `display_config.yaml` with persistent Display IDs.

### Monitoring Mode
- **Live Dashboard**: Real-time cropped feeds with per-display health status.
- **Health Indicators**: 🟢 ACTIVE, 🌑 OFF, ⬛ BLACK, ❄️ FROZEN.
- **Anomaly Overlay**: Visual alerts for detected glitches and OCR matches.
- **Global Snapshot**: Capture high-res PNGs of the entire dashboard with metadata.

### Video Analysis (NEW)
- **Local File Analysis**: Open local video files via native macOS file picker.
- **SSE Streaming**: Live multi-threaded analysis reporting for large video files.
- **Synchronized Timeline**: View detected glitches frame-by-frame with a unified results dashboard.

### Canonical CLI & Headless Monitoring
- **`display_monitor.py`**: A powerful CLI tool for automation and CI/CD pipelines.
- **Headless Snapshots**: Generate reports, individual frames, and JSON metadata without a GUI.
- **Hardware Stabilization**: Aggressive exposure flushing for consistent captures on built-in cameras.

## Installation

### Prerequisites
- **Python 3.10+** (Apple Silicon M-Series fully supported)
- **OpenCV 4.x** with MJPEG support
- **EasyOCR** (requires `torch`)

### Setup

1. **Clone the project**:
   ```bash
   cd display-monitor-python
   ```

2. **Install dependencies**:
   ```bash
   pip3 install -r requirements.txt
   ```

3. **Start the server**:
   ```bash
   python3 app.py
   ```

4. **Access the Web UI**:
   `http://localhost:5001` (Default)

## Technical Architecture

### Display Status Engine (DSE)
The engine evaluates frames at ~6 FPS using four pillars of analysis:
1. **Luminance**: Detects powered-down (OFF) states.
2. **Variance**: Differentiates signal-black (BLACK) from texture-rich content.
3. **Edge Density**: Sharpness filter for detecting UI elements and text.
4. **Temporal Delta**: Frame-to-frame motion analysis for freeze detection.

### Unified Glitch Engine (`glitch_logic.py`)
Detects visual anomalies categorized by:
- **FLICKER**: Sharp relative brightness jumps.
- **BLOCK_GLITCH**: Macro-blocking and regional variance anomalies.
- **ARTIFACTING**: High-frequency noise typical of compression or cable failure.
- **FRAME_CORRUPTION**: Regional diff anomalies.
- **PIXEL_GLITCH**: Statistical outliers in pixel distribution.

### OCR Engine
Runs asynchronously to prevent UI lag. Uses `negative_text` patterns from `config.yaml` to flag critical errors:
```yaml
negative_text:
  - "No Signal"
  - "Signal Lost"
  - "Error"
```

## ⚙️ Advanced Configuration (`config.yaml`)

| Parameter | Default | Description |
| :--- | :--- | :--- |
| `off_brightness` | 5 | Threshold for total darkness (Power Off). |
| `black_brightness` | 15 | Threshold for signal-black (Backlight On). |
| `content_variance` | 30 | Min variation for valid graphical content. |
| `diff_threshold` | 0.4 | Motion sensitivity (adjust for sensor noise). |
| `frozen_frames` | 60 | Frames to wait (~2s) before marking FROZEN. |
| `ocr_interval` | 5.0 | Seconds between OCR scans to save processing. |

## Troubleshooting

- **Camera Not Found**: If hardware IDs change, the system uses "Fuzzy Matching" on camera names. Ensure your `display_config.yaml` has the correct `camera_name`.
- **Performance**: OCR and Perspective Correction are CPU/GPU intensive. Use "Fit" mode in the dashboard to reduce rendering overhead.
- **Permission Errors**: On macOS, ensure Terminal/VSCode has "Camera" permissions in System Settings.

## 🏗 Roadmap & Future
- [x] Perspective correction rendering
- [x] Visual Glitch Anomaly Detection
- [x] Async OCR Analysis
- [x] Multi-camera simultaneous configuration mode
- [ ] Prometheus/Grafana integration for long-term health metrics
- [ ] Automated email/Slack notifications for critical anomalies

---

**Version**: 1.4.1  
**Last Updated**: December 29, 2025
