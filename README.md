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

### UI Metrics Explained

When monitoring displays, you'll see real-time metrics below each display card:

- **L** (Luminance): Average brightness (0-255). Indicates overall screen brightness.
- **V** (Variance): Pixel variation measure. High values indicate textured/detailed content, low values indicate flat/uniform screens.
- **Diff** (Difference): Frame-to-frame pixel change. Near 0 when static, increases with motion.
- **Frz** (Freeze Counter): Consecutive static frames detected. Increments when Diff < threshold, resets on motion. When this reaches `frozen_frames`, status changes to FROZEN.

### Configuration Parameters Detailed

#### **off_brightness: 5**
- **What it is**: Average brightness threshold (0-255 scale)
- **Significance**: If the display's average brightness is below 5, it's considered completely **OFF** (powered down)
- **Impact**: Very strict - only near-black screens (< 2% brightness) are marked as OFF
- **Adjust if**: Getting false OFF detections on very dark scenes → increase to 8-10

#### **black_brightness: 15**
- **What it is**: Threshold for backlight-on but no content
- **Significance**: Brightness between 5-15 means the display is on, but showing a black screen (no signal/content)
- **Impact**: Distinguishes between "OFF" (no power) and "BLACK" (powered but no content)
- **Adjust if**: Dark content is being flagged as BLACK → increase to 20-25

#### **noise_variance: 2**
- **What it is**: Pixel variance threshold for sensor noise
- **Significance**: Variance below 2 indicates uniform/flat pixels (no texture)
- **Impact**: Used with brightness to distinguish OFF/BLACK from very dark content
- **Adjust if**: Rarely needs changing (sensor noise baseline)

#### **content_variance: 30**
- **What it is**: Minimum variance for "interesting" content
- **Significance**: If variance > 30, the display has texture/detail (not just flat colors)
- **Impact**: Helps classify ACTIVE vs UNKNOWN status
- **Adjust if**: Static backgrounds are being marked UNKNOWN → lower to 15-20

#### **diff_threshold: 0.5**
- **What it is**: Mean pixel difference between consecutive frames
- **Significance**: If difference < 0.5, the frame is considered "static" (no motion)
- **Impact**: **Critical for freeze detection** - lower = more sensitive
- **Adjust if**:
  - Not detecting freezes → **increase to 1.0-2.0** (less strict)
  - False freeze alarms → **decrease to 0.2-0.3** (more strict)

#### **edge_threshold: 1.2**
- **What it is**: Percentage of pixels with high-frequency edges
- **Significance**: Edge density > 1.2% means the display has sharp details/text
- **Impact**: Helps distinguish content-rich frames from flat ones
- **Adjust if**: Simple UIs are being marked UNKNOWN → lower to 0.8

#### **frozen_frames: 5**
- **What it is**: Number of consecutive static frames before declaring FROZEN
- **Significance**: Balance between responsiveness and false positives. Lower = faster detection
- **Impact**: With typical sampling rates, determines how quickly freezes are detected
- **Adjust if**:
  - Too many false freezes → increase to 10-30
  - Freezes not detected fast enough → decrease to 3-5

## 🏗 Implementation Details

### Perspective Correction Engine
The monitoring system uses a **Bilinear Grid Interpolation** method to approximate 3D perspective transformations (homography) using the 2D Canvas API:
- **Subdivision**: Instead of rendering as two large triangles, each display region is subdivided into a **4x4 grid (16 cells / 32 triangles)**.
- **Seam-Prevention**: A 0.5px sub-pixel expansion is applied to each triangle to prevent rendering gaps usually caused by browser rounding.
- **Performance**: Optimized to run at 60 FPS by calculating the transformation matrix once and applying it per-frame using the `transform()` API.

### Display Status Engine (DSE)
The system performs autonomous health monitoring using pixel-level analysis:
1.  **Preprocessing**: Frames are sampled at 6 FPS and converted to a luminance-weighted grayscale mapping.
2.  **Luminance & Variance**: Calculates the mean brightness and statistical variance to detect power states.
3.  **Edge Density**: Uses a Sobel-based high-frequency filter to detect "meaningful" content vs. flat signals.
4.  **Temporal Difference**: Tracks frame-to-frame pixel delta to detect system freezes.
5.  **States**:
    - **OFF**: Low brightness AND low variance AND low edge density.
    - **BLACK**: Moderate brightness (backlight) AND low variance.
    - **FROZEN**: High variance (content) AND Zero temporal movement for >1 second.
    - **ACTIVE**: High variance AND detected motion.
    
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

**Version**: 1.4.0  
**Last Updated**: December 27, 2025
