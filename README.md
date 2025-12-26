# Display Monitor Configuration Tool

A web-based tool for configuring and monitoring multiple display regions from camera feeds, designed for automotive display testing and validation.

## Features

### Configuration Mode
- **Live Camera Streaming**: Real-time camera feed with browser-based access
- **Hardened Hardware Discovery**: Automatic "Fuzzy Matching" reconciles camera names even if hardware IDs change between sessions.
- **Manual Area Selection**: Draw display regions by clicking and dragging
- **Drag-to-Create**: Click and drag anywhere on the camera feed to create new regions
- **Advanced Manipulation**: 
  - **Move**: Drag the interior to reposition
  - **Corners**: Resize by dragging corner handles
  - **Edges**: Resize by dragging any of the 4 sides
  - **Rotation**: Physically rotate display coordinates using a dedicated yellow handle
- **Resolution Controls**:
  - **Fit Mode**: Scales video to fit viewport while maintaining aspect ratio
  - **Native Mode**: Shows full camera resolution with scrolling
- **Overlapping Display Management**: Alt-click to select displays underneath
- **Configuration Persistence**: Save regions with persistent IDs and 4-corner coordinates to YAML

### Monitoring Mode
- **Live Dashboard**: Real-time cropped feeds from all configured display regions
- **Display Status Monitor (NEW)**: Real-time autonomous status detection for each display:
  - 🟢 **ACTIVE**: Content is moving and display is healthy.
  - 🌑 **OFF**: Detection of extremely low light/noise (power off).
  - ⬛ **BLACK**: Detection of black signal with active backlight.
  - ❄️ **FROZEN**: Detection of static content (system hang).
- **Advanced View Controls**:
  - **Maximized View (⛶)**: Expand any display to fill the entire window area
  - **Resolution Toggle (▣)**: Switch between **Fit** (scales to tile) and **Native** (1:1 pixels)
  - **Auto-Scaling**: "Fit" mode automatically upscales small regions to fill the tile
- **Perspective Correction (RECTIFY)**: High-fidelity homography using grid subdivision (16-cell warping).
- **Status Indicators**: Pulsing visual status badges with real-time feedback
- **Enhanced Snapshot Capture**: Download high-resolution PNG including status badges and metadata.
- **Stop/Resume Controls**: Pause monitoring rendering while keeping camera streams alive
### Canonical CLI & Headless Monitoring
- **Professional CLI (`display_monitor.py`)**: A powerful tool for automation, CI/CD, and remote monitoring.
- **Headless Analysis**: Ported the Status Engine to Python/OpenCV for server-side verification.
- **Smart Proportional Scaling**: Automatically handles macOS 16:9 sensor center-cropping for perfect alignment with browser-based configurations.
- **Hardware Resilience**: Aggressive exposure stabilization ensures clear captures on built-in cameras.
- **Friendly Identification**: Full support for both `--display` (ID) and `--name` (Human-readable) lookups.
- **Flexible Snapshots**: Export combined dashboards, individual name-based frames, and JSON metadata.

## Installation

### Prerequisites
- Python 3.10+
- Modern web browser (Chrome, Firefox, Safari, Edge)
- Camera access permissions

### Setup

1. **Clone or download the project**:
   ```bash
   cd /path/to/display-monitor
   ```

2. **Install Python dependencies**:
   ```bash
   pip3 install flask pyyaml
   ```

3. **Start the server**:
   ```bash
   python3 app.py
   ```

4. **Open in browser**:
   ```
   http://localhost:5000
   ```

## User Guide

### Getting Started

1. **Launch the application** and grant camera permissions when prompted
2. Choose your mode:
   - **Configuration Mode**: Set up display regions
   - **Monitoring Mode**: View live feeds from configured regions

### Configuration Mode

#### Selecting a Camera
1. Camera list appears in the left sidebar
2. Click on a camera to start the live feed
3. Use the **Refresh** button to update the camera list

#### Creating Display Regions

**Method 1: Drag-to-Create**
1. Click and drag anywhere on the camera feed
2. Release to create the region
3. Property panel opens automatically
4. Regions smaller than 20px are automatically discarded

**Method 2: Add Button**
1. Click **"+ Add Display Region"** in the toolbar
2. A region appears centered on the feed
3. Drag to reposition, use corner handle to resize

#### Manipulating Display Regions

- **Move**: Click and drag inside the region
- **Resize**: Click and drag the bottom-right corner handle
- **Select**: Click on any region to edit properties
- **Select Overlapping**: 
  - Normal click: Selects top display
  - **Alt+Click**: Selects display underneath

#### Display Properties

Configure each display region:
- **Display Name**: Custom identifier (e.g., "Instrument Cluster")
- **Orientation**: 0°, 90°, 180°, or 270° rotation
- **Perspective Correction**: Enable/disable distortion correction

#### View Modes

Toggle between viewing modes using the **"View: Fit/Native"** button:

- **Fit Mode**: 
  - Scales camera feed to fit viewport
  - Maintains aspect ratio
  - Best for overall layout

- **Native Mode**:
  - Shows camera at actual resolution
  - Enables scrolling for large feeds
  - Best for precise positioning

#### Saving Configuration

1. Click **"Save & Exit"** when done
2. Configuration saved to `display_config.yaml`
3. Returns to landing page

### Monitoring Mode

#### Starting Monitoring
1. Click **"Monitoring Mode"** from landing page
2. Saved configuration loads automatically
3. Live feeds appear in a grid layout

#### Dashboard Features

- **Live Feeds**: Real-time video from each configured region using Canvas API
- **Status Badges**: Shows health state (**ACTIVE**, **FROZEN**, **OFF**, **BLACK**)
- **Pulsing indicators**: Animated status dots show active pixel-polling is running
- **Timestamps**: Updated in real-time for each feed
- **Camera Source**: Displays resolved camera names or device IDs

#### Advanced Controls

Each display tile features dedicated control buttons:
- **▣ Resolution Toggle**: 
  - **Fit**: Scales image to fit tile area (upscales small images, downscales large ones)
  - **Native**: Shows 1:1 pixel mapping (enables scrolling for inspection)
- **⛶ Maximize/Minimize**: 
  - **Maximize**: Expands the display to take up the full browser window
  - **Minimize (❐)**: Returns the display to its position in the dashboard grid

#### Global Dashboard Controls

- **Stop**: Pauses the rendering loop (saves CPU, cameras stay active)
- **Resume**: Restarts real-time rendering
- **Capture Snapshot**: Downloads a comprehensive PNG of the entire dashboard
- **Exit Monitor**: Stops all streams and returns to landing page

#### Snapshot Features

The snapshot includes:
- All display tiles (even those requiring scrolling)
- Display names and status badges
- Live video frames
- Camera source information
- Timestamps
- Dashboard title and capture timestamp

## Keyboard Shortcuts & Tips

### Configuration Mode
- **Alt+Click**: Select display underneath overlapping displays
- **Use Sidebar List**: Click displays in "Defined Displays" to select by name

### General
- **Hard Refresh**: Cmd+Shift+R (Mac) / Ctrl+Shift+F5 (Windows) to reload code changes

## Technical Architecture

### Frontend Stack
- **HTML/CSS/JavaScript**: Vanilla implementation (ES6+)
- **Media APIs**: `navigator.mediaDevices` for cross-browser camera access
- **Canvas API**: Real-time cropping, rotation transforms, and composite snapshot generation
- **CSS Grid & Flexbox**: For responsive dashboard tiling and fullscreen overlays

### Python CLI Components
- **CLI Engine (`cli_engine.py`)**: Implements the image processing suite in Python:
  - **Capture**: Direct OpenCV access with exposure stabilization.
  - **Warping**: Corner-normalized perspective rectification matching the JS engine.
  - **Scaling**: Proportional coordinate mapping with automatic centering.
- **Status Engine**: Python port of the grayscale luminance/variance/motion analysis logic.

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

### Hardware-Resilient Selection
- **Fuzzy Matching**: Since browser camera IDs are session-specific, the system reconciles `display_config.yaml` by comparing stored labels (`camera_name`) against current hardware discovery results.

### File Structure
```
display-monitor/
├── app.py                    # Flask backend server
├── display_config.yaml       # Saved display corner coordinates
├── config.yaml               # Status engine thresholds & parameters
├── index.html                # Landing page
├── js/
│   ├── app.js               # Main application controller
│   ├── config.js            # Configuration mode logic & interactions
│   ├── monitor.js           # Monitoring mode logic & rendering
│   └── statusEngine.js      # Pixel-level analysis engine
├── styles/
│   ├── main.css             # Global styles
│   ├── config.css           # Configuration mode styles
│   └── monitor.css          # Monitoring mode styles
└── README.md                 # This documentation
```

### Configuration Format

`display_config.yaml` stores displays with 4-corner coordinates:

```yaml
displays:
- id: disp_1234567890
  name: Instrument Cluster
  camId: abc123...
  camera_name: FaceTime HD Camera
  corners:
  - {x: 250, y: 180}  # top-left
  - {x: 650, y: 180}  # top-right
  - {x: 650, y: 420}  # bottom-right
  - {x: 250, y: 420}  # bottom-left
  rotation: 0
  enablePerspective: false
```

## API Endpoints

### Camera Discovery
```
GET /api/cameras
```
Returns list of available cameras with deviceId and name.

### Configuration
```
GET /api/config/load
```
Loads saved display configuration from `display_config.yaml`.

```
POST /api/config/save
Content-Type: application/json
```
Saves display configuration. Expects array of display objects.

### Status Monitoring Config
```
GET /api/monitor/config
Loads status engine thresholds (brightness, variance, frozen timers) from `config.yaml`.

## 🧾 Canonical CLI (`display_monitor.py`)

The system includes a professional-grade CLI tool designed for headless automation and CI/CD integration. It shares the same "Upright-Normalized" coordinate policy as the web dashboard.

### Core Implementation Logic
- **Hardware Stabilization**: On macOS, cameras require significant warm-up. The CLI flushes 45 frames (~1.5s) to allow auto-exposure to settle before capturing.
- **Coordinate Parity**: Configurations created in the browser (typically 4:3) are intelligently mapped to the camera sensor (typically 16:9) using **Proportional Scaling with Centering**.
- **Slugified Artifacts**: Snapshots use "slugified" display names (e.g., `Instrument Cluster` -> `Instrument_Cluster.png`) for consistent artifact tracking.

### Command Reference

| Command | Args | Description |
| :--- | :--- | :--- |
| `list-displays` | - | Lists IDs, Names, and Camera sources for all displays. |
| `status` | `--name NAME` \| `--display ID` | Real-time health analysis (ACTIVE, OFF, BLACK, FROZEN). |
| `get-frame` | `--name NAME` \| `--display ID` | Export a corrected, upright PNG for a specific display. |
| `get-combined` | `--out FILE.png` | Export a high-res tiled dashboard of all active displays. |
| `snapshot` | `--out-dir DIR` | Full export: `combined.png`, `status.json`, and named display frames. |

### Example Usage
```bash
# Check if "Instrument Cluster" is frozen
./display_monitor.py status --name "Instrument Cluster" | jq '.frozen'

# Capture test evidence for CI
./display_monitor.py snapshot --out-dir artifacts/
```

## ⚙️ Advanced Configuration (config.yaml)

You can fine-tune the Status Engine by editing `config.yaml`:
```yaml
config:
  off_brightness: 5     # Classification of 'Off' state
  black_brightness: 15  # Classification of 'Black' state
  noise_variance: 2     # Sensor noise ceiling
  content_variance: 30  # Minimum detail for active content
  diff_threshold: 0.4   # Motion sensitivity
  frozen_frames: 60     # Frames to wait before 'frozen' (60 = ~1s)
```

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


## Troubleshooting

### Camera Access Issues

**Problem**: "Camera access denied" or black screens

**Solutions**:
1. Grant camera permissions in browser settings
2. Ensure no other app is using the camera
3. Try a hard refresh (Cmd+Shift+R)
4. Check browser console for specific errors

### Display Regions Not Saved

**Problem**: Configuration lost after restart

**Solutions**:
1. Verify `display_config.yaml` exists in project root
2. Check browser console for save errors
3. Ensure write permissions for project directory

### Overlapping Displays

**Problem**: Can't select the display I want

**Solutions**:
1. Hold **Alt** while clicking to select bottom display
2. Use the **"Defined Displays"** sidebar list
3. Temporarily move overlapping displays

### Black Screens in Monitoring Mode

**Problem**: Monitoring dashboard shows black tiles

**Solutions**:
1. Refresh the page (camera stream may be paused)
2. Check that configuration was saved correctly
3. Verify camera permissions
4. Open browser console to check for errors

### Performance Issues

**Problem**: Slow rendering or laggy interface

**Solutions**:
1. Reduce number of simultaneous display regions
2. Use "Fit" mode instead of "Native" mode
3. Close other browser tabs using cameras
4. Use Stop/Resume to pause monitoring when not needed

## Browser Compatibility

**Tested and supported**:
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

**Required features**:
- `navigator.mediaDevices` API
- Canvas 2D context
- ES6 JavaScript support

- [x] Actual perspective correction rendering
- [ ] Camera `deviceId` is session-specific (may change between browser restarts)
- [ ] Maximum display count limited by system camera/GPU capabilities
- [ ] No undo/redo for region edits

## Future Enhancements

- [ ] Actual perspective correction rendering
- [ ] Display region labels on hover in Monitoring Mode
- [ ] Keyboard shortcuts for common operations
- [ ] Undo/redo for region edits
- [ ] Multi-camera simultaneous configuration
- [ ] Export configuration to different formats
- [ ] Anomaly detection and alerts

## License

[Add your license information here]

## Support

For issues or questions, please [add contact information or issue tracker link].

---

**Version**: 1.3.0  
**Last Updated**: December 24, 2025
