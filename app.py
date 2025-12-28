import json
import subprocess
import os
import ssl
import threading
import time
import copy
import cv2
import numpy as np
import yaml
from flask import Flask, send_from_directory, jsonify, request, Response, send_file

# Fix for macOS SSL certificate errors (Critical for EasyOCR)
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

from monitor_core import CLILoader, ImageProcessor, DisplayStatusEngine
from glitch_logic import process_video_second_wise
import logging
import logging.handlers

# --- Logging Setup ---
def setup_logging(config):
    """Configure file-based logging from config"""
    log_config = config.get('logging', {})
    if not log_config.get('enabled', False):
        # Logging disabled, configure minimal console logging
        logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s')
        return
    
    # Create logs directory
    log_file = log_config.get('file', 'logs/monitor.log')
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    # Configure rotating file handler
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=log_config.get('max_bytes', 10*1024*1024),
        backupCount=log_config.get('backup_count', 5)
    )
    
    # Console handler for INFO and above
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Set format
    log_format = log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    formatter = logging.Formatter(log_format)
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    
    # Configure root logger
    logger = logging.getLogger()
    log_level = log_config.get('level', 'INFO').upper()
    logger.setLevel(getattr(logging, log_level, logging.INFO))
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.info(f"Logging initialized - Level: {log_level}, File: {log_file}")

app = Flask(__name__, static_folder='.')
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# --- OCR Initialization ---
ocr_reader = None
def get_ocr_reader():
    global ocr_reader
    if ocr_reader is None:
        try:
            import easyocr
            print("[OCR] Initializing easyOCR reader...", flush=True)
            try:
                ocr_reader = easyocr.Reader(['en'], gpu=True, verbose=False)
                print("[OCR] Reader initialized successfully (GPU)", flush=True)
            except Exception as gpu_error:
                print(f"[OCR] GPU initialization failed: {gpu_error}. Falling back to CPU...", flush=True)
                ocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
                print("[OCR] Reader initialized successfully (CPU)", flush=True)
        except Exception as e:
            print(f"[OCR] Failed to initialize: {e}", flush=True)
            import traceback
            traceback.print_exc()
            ocr_reader = False
    return ocr_reader if ocr_reader is not False else None

# --- Monitor System (Background Thread) ---
class MonitorSystem:
    def __init__(self):
        self.loader = CLILoader()
        self.processor = ImageProcessor()
        self.run_flag = True
        self.lock = threading.Lock()
        
        # State
        self.latest_frames = {} # { display_id: jpeg_bytes }
        self.latest_frames_raw = {} # { display_id: frame_numpy }
        self.latest_status = {} # { display_id: { status, metrics } }
        self.engines = {}
        self.thread = None
        
        # Session / Recording
        self.sess_id = None
        self.sess_path = None
        self.sess_log_path = None
        self.sess_video = None
        self.sess_start_time = 0
        self.sess_last_record_time = 0
        self.sess_lock = threading.Lock()
        
        # Hardware Cache
        self.cached_hardware_cams = None
        
        # Init Engines with OCR
        reader = get_ocr_reader()
        global_config = self.loader.monitor_config
        
        # Inject OCR dependencies into config for engines
        engine_config = copy.deepcopy(global_config)
        engine_config['ocr_reader'] = reader
        # Default 5s if not set
        engine_config['ocr_interval'] = engine_config.get('ocr_interval', 5.0) 
        
        for d in self.loader.displays:
            self.engines[d['id']] = DisplayStatusEngine(engine_config)
            
        # Perform initial reconciliation
        self.reconcile_cameras()
        print(f"[MonitorSystem] Initialized {len(self.engines)} display engines.")

    def _apply_display_annotations(self, frame, d_name, c_name, is_small=False, show_timestamp=True):
        """Adds borders, metadata labels, and optional timestamp to a frame."""
        import datetime
        h, w = frame.shape[:2]
        
        # 1. Border (White, 1px)
        cv2.rectangle(frame, (0, 0), (w-1, h-1), (255, 255, 255), 1)
        
        font = cv2.FONT_HERSHEY_SIMPLEX
        f_scale = 0.4 if is_small else 0.6
        f_thick = 1
        
        # 2. Timestamp (If enabled)
        if show_timestamp:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            (tw, th), baseline = cv2.getTextSize(timestamp, font, f_scale, f_thick)
            tx, ty = w - tw - 10, th + 10
            
            # Timestamp Box
            overlay = frame.copy()
            cv2.rectangle(overlay, (tx - 5, ty - th - 5), (w - 5, ty + 5), (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
            cv2.putText(frame, timestamp, (tx, ty), font, f_scale, (255, 255, 255), f_thick, cv2.LINE_AA)
        
        # 3. Bottom label (Display | Camera)
        label = f"{d_name} | {c_name}"
        (lw, lh), l_baseline = cv2.getTextSize(label, font, f_scale, f_thick)
        lx, ly = 10, h - 10
        
        # Label Box
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, h - lh - 15), (w, h), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
        cv2.putText(frame, label, (lx, ly), font, f_scale, (255, 255, 255), f_thick, cv2.LINE_AA)
        
        return frame

    def _get_no_signal_frame(self, display_name, target_size=(1280, 720)):
        """Generates a black frame with a prominent 'NO SIGNAL' message."""
        w, h = target_size
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        
        # Draw "NO SIGNAL"
        text = "NO SIGNAL"
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = 3.0
        thick = 10
        (tw, th), baseline = cv2.getTextSize(text, font, scale, thick)
        tx, ty = (w - tw) // 2, (h + th) // 2 - 50
        
        # Red neon effect
        cv2.putText(frame, text, (tx+2, ty+2), font, scale, (0, 0, 150), thick+2, cv2.LINE_AA)
        cv2.putText(frame, text, (tx, ty), font, scale, (0, 0, 255), thick, cv2.LINE_AA)
        
        # Sub-title
        sub_text = f"Source: {display_name}"
        sub_scale = 1.0
        sub_thick = 2
        (sw, sh), s_baseline = cv2.getTextSize(sub_text, font, sub_scale, sub_thick)
        sx, sy = (w - sw) // 2, ty + 100
        cv2.putText(frame, sub_text, (sx, sy), font, sub_scale, (200, 200, 200), sub_thick, cv2.LINE_AA)
        
        return frame

    def start(self):
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        print("[MonitorSystem] Background capture thread started")

    def _resize_with_aspect(self, frame, target_size):
        """Resizes a frame to fit target_size while preserving aspect ratio, using black padding."""
        t_w, t_h = target_size
        f_h, f_w = frame.shape[:2]
        
        # Calculate scaling factor
        aspect_f = f_w / f_h
        aspect_t = t_w / t_h
        
        if aspect_f > aspect_t:
            # Width limited
            new_w = t_w
            new_h = int(t_w / aspect_f)
        else:
            # Height limited
            new_h = t_h
            new_w = int(t_h * aspect_f)
            
        resized = cv2.resize(frame, (new_w, new_h))
        
        # Create black canvas and center the resized frame
        canvas = np.zeros((t_h, t_w, 3), dtype=np.uint8)
        x_off = (t_w - new_w) // 2
        y_off = (t_h - new_h) // 2
        canvas[y_off:y_off+new_h, x_off:x_off+new_w] = resized
        
        return canvas

    def stop(self):
        self.run_flag = False
        if self.thread:
            self.thread.join()
        # Ensure session is closed
        self.stop_continuous_monitor()
        # Release hardware
        self.processor.close()

    def start_continuous_monitor(self):
        with self.sess_lock:
            if self.sess_id:
                return self.sess_id, self.sess_path
            
            ts = time.strftime("%Y%m%d_%H%M%S")
            self.sess_id = f"session_{ts}"
            self.sess_path = os.path.join(os.getcwd(), "sessions", self.sess_id)
            os.makedirs(self.sess_path, exist_ok=True)
            
            self.sess_log_path = os.path.join(self.sess_path, "events.log")
            self.sess_start_time = time.time()
            self.sess_last_record_time = self.sess_start_time
            
            self.log_event("SESSION_STARTED", f"Continuous monitoring started for session {self.sess_id}")
            print(f"[MonitorSystem] Started continuous monitor: {self.sess_path}")
            return self.sess_id, self.sess_path

    def stop_continuous_monitor(self):
        with self.sess_lock:
            if not self.sess_id:
                return None
            
            path = self.sess_path
            self.log_event("SESSION_STOPPED", f"Continuous monitoring stopped for session {self.sess_id}")
            
            if self.sess_video:
                self.sess_video.release()
                self.sess_video = None
            
            self.sess_id = None
            self.sess_path = None
            print(f"[MonitorSystem] Stopped continuous monitor: {path}")
            return path

    def log_event(self, event_type, message, display_name=None):
        if not self.sess_log_path:
            return
        
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        context = f"[{display_name}] " if display_name else ""
        log_line = f"[{ts}] {context}{event_type}: {message}\n"
        
        try:
            with open(self.sess_log_path, 'a') as f:
                f.write(log_line)
        except Exception as e:
            print(f"[MonitorSystem] Log error: {e}")

    def _get_tiled_frame(self):
        """Creates a tiled view of all displays for recording with borders and labels"""
        # Map display IDs to metadata for labeling
        display_map = {d['id']: d for d in self.loader.displays}
        
        with self.lock:
            # Get a snapshot of current frames and their IDs
            display_items = list(self.latest_frames_raw.items())
        
        if not display_items:
            return None
        
        # Target tile size (preserving aspect ratio via letterboxing)
        t_w, t_h = 640, 360
        count = len(display_items)
        cols = int(np.ceil(np.sqrt(count)))
        rows = int(np.ceil(count / cols))
        
        canvas = np.zeros((rows * t_h, cols * t_w, 3), dtype=np.uint8)
        
        for i, (did, frame) in enumerate(display_items):
            r = i // cols
            c = i % cols
            
            # Step 1: Resize with aspect ratio
            resized = self._resize_with_aspect(frame, (t_w, t_h))
            
            # Step 2: Add visual annotations (Borders and Labels)
            d_meta = display_map.get(did, {})
            d_name = d_meta.get('name', did)
            c_name = d_meta.get('camera_name', 'Unknown Cam')
            
            # Apply focused annotations for the tile size (NO timestamp per tile)
            self._apply_display_annotations(resized, d_name, c_name, is_small=True, show_timestamp=False)
            
            # Place on canvas
            canvas[r*t_h:(r+1)*t_h, c*t_w:(c+1)*t_w] = resized
        
        # Step 3: Global Timestamp at top-right of entire canvas
        import datetime
        h, w = canvas.shape[:2]
        timestamp = f"GLOBAL TIME: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        font = cv2.FONT_HERSHEY_SIMPLEX
        f_scale = 0.8
        f_thick = 2
        (tw, th), baseline = cv2.getTextSize(timestamp, font, f_scale, f_thick)
        tx, ty = w - tw - 20, th + 20
        
        # Overlay box for readability
        overlay = canvas.copy()
        cv2.rectangle(overlay, (tx - 10, ty - th - 10), (w - 10, ty + 10), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.5, canvas, 0.5, 0, canvas)
        cv2.putText(canvas, timestamp, (tx, ty), font, f_scale, (255, 255, 255), f_thick, cv2.LINE_AA)
            
        return canvas

    def _reconcile_cameras(self, force_discovery=False):
        """Matches configured camera groups to current hardware using unique IDs and names."""
        import re
        logger = logging.getLogger('MonitorSystem')

        def normalize_name(n):
            if not n: return ""
            base = re.sub(r'\s*\(Device \d+\)$', '', n, flags=re.IGNORECASE).strip().lower()
            return base

        logger.info("=" * 50)
        logger.info(f"STABLE CAMERA RECONCILIATION START (Force={force_discovery})")
        logger.info("=" * 50)
        
        if force_discovery or not self.cached_hardware_cams:
            self.cached_hardware_cams = self.processor.discover_cameras()
            logger.info(f"Hardware discovery completed: {len(self.cached_hardware_cams)} found.")
        
        hardware_cams = self.cached_hardware_cams
        
        # 1. Group Logical Displays by their intended source (ID or Name)
        source_groups = {} # key -> list of display objects
        for d in self.loader.displays:
            # Use hardware_id as primary key if we have it, else fallback to name
            key = d.get('hardware_id') or d.get('camera_name')
            if not key: continue
            
            if key not in source_groups:
                source_groups[key] = []
            source_groups[key].append(d)

        # 2. Match each Source Group to a Physical Hardware Camera
        assigned_hardware_ids = set() # Unique spcamera_unique-id or simulated HW ID
        
        for key, group in source_groups.items():
            representative = group[0]
            target_hw_id = representative.get('hardware_id')
            target_name = representative.get('camera_name')
            target_norm = normalize_name(target_name)
            
            matched_cam = None

            # Pass 1: Match by Unique Hardware ID (Most stable)
            if target_hw_id:
                for h in hardware_cams:
                    if h.get('hardware_id') == target_hw_id:
                        matched_cam = h
                        break
            
            # Pass 2: Exact Name Match
            if not matched_cam and target_name:
                for h in hardware_cams:
                    if h['hardware_id'] in assigned_hardware_ids: continue
                    if h['name'] == target_name:
                        matched_cam = h
                        break
            
            # Pass 3: Fuzzy Name Match
            if not matched_cam and target_norm:
                for h in hardware_cams:
                    if h['hardware_id'] in assigned_hardware_ids: continue
                    h_norm = normalize_name(h['name'])
                    if target_norm == h_norm or target_norm in h_norm or h_norm in target_norm:
                        matched_cam = h
                        break

            # 3. Apply matches or mark as missing
            if matched_cam:
                new_idx = matched_cam['id']
                hw_id = matched_cam['hardware_id']
                hw_name = matched_cam['name']
                assigned_hardware_ids.add(hw_id)
                
                for d in group:
                    if d.get('camId') != new_idx or d.get('hardware_id') != hw_id:
                        logger.info(f"MAPPED GROUP: source '{key}' -> idx {new_idx} ('{hw_name}')")
                    
                    d['camId'] = new_idx
                    d['hardware_id'] = hw_id
                    d['camera_name'] = hw_name # Keep in sync
                    d['missing_camera'] = False
                    # Preserve preferred_resolution if it exists in the config
                    # d['preferred_resolution'] = d.get('preferred_resolution') 
            else:
                logger.warning(f"MISSING GROUP: Source '{key}' NOT FOUND.")
                for d in group:
                    d['missing_camera'] = True
        
        logger.info("CAMERA RECONCILIATION COMPLETE")
        logger.info("=" * 50)

    def reconcile_cameras(self, force_discovery=False):
        """Thread-safe public reconciliation"""
        with self.lock:
            self._reconcile_cameras(force_discovery=force_discovery)

    def refresh_config(self, force_discovery=False):
        """Reloads config from disk and reapplies mappings safely"""
        with self.lock:
            # Release all cameras to allow them to be re-opened with new resolutions
            self.processor.close()
            self.loader.load_config()
            self._reconcile_cameras(force_discovery=force_discovery)
            print(f"[MonitorSystem] Configuration refreshed and reconciled. All cameras re-initialized.")

    def _capture_loop(self):
        logger = logging.getLogger('MonitorSystem')
        frame_idx = 0
        while self.run_flag:
            try:
                # Group displays by camera to optimize capture
                # Use lock to snapshot the list to avoid race with config reloads
                with self.lock:
                    active_displays = copy.deepcopy(self.loader.displays)
                
                cam_displays = {}
                for d in active_displays:
                    if d.get('missing_camera', False):
                        # Force status update to OFFLINE for missing cams
                        with self.lock:
                             self.latest_status[d['id']] = {
                                'id': d['id'],
                                'name': d.get('name', d['id']),
                                'camId': d.get('camId', '?'),
                                'timestamp': time.time() * 1000,
                                'status': 'OFFLINE',
                                'metrics': {'error': 'Camera Not Found'}
                             }
                             
                             # Inject "NO SIGNAL" placeholder
                             placeholder = self._get_no_signal_frame(d.get('name', d['id']))
                             self.latest_frames_raw[d['id']] = placeholder
                             ret, jpeg = cv2.imencode('.jpg', placeholder, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
                             if ret:
                                 self.latest_frames[d['id']] = jpeg.tobytes()
                        continue

                    cid = d.get('camId', 0)
                    if cid not in cam_displays: cam_displays[cid] = []
                    cam_displays[cid].append(d)
                
                # Iterate cameras
                cids = list(cam_displays.keys())
                for cid in cids:
                    displays = cam_displays[cid]
                    
                    # Determine target resolution if specified in config for this camera group
                    # Determine target resolution from camera config
                    target_res = None
                    # Find hardware ID for this camId
                    representative = displays[0] if displays else None
                    hw_id = representative.get('hardware_id') if representative else None
                    
                    if hw_id:
                        cam_conf = self.loader.camera_configs.get(hw_id, {})
                        res_str = cam_conf.get('resolution')
                        if res_str and 'x' in res_str:
                             try:
                                w, h = map(int, res_str.split('x'))
                                target_res = (w, h)
                             except:
                                pass
                        
                        if frame_idx % 100 == 0:
                             print(f"[Debug] Cam {cid} HW_ID: {hw_id} Target Res: {target_res}")

                    frame = self.processor.read_frame(cid, target_res=target_res)
                    
                    # Debug log every 500 frames (~5s)
                    if frame_idx % 500 == 0:
                         status_str = "OK" if frame is not None else "FAIL"
                         print(f"[CaptureLoop] Cam {cid}: {status_str} | Displays: {len(displays)}")

                    if frame is None:
                        # Camera offline/failed
                        with self.lock:
                            for d in displays:
                                self.latest_status[d['id']] = {
                                    'id': d['id'],
                                    'name': d.get('name', d['id']),
                                    'camId': d.get('camId', cid),
                                    'camera_name': d.get('camera_name', f"Camera {cid}"),
                                    'timestamp': time.time() * 1000,
                                    'status': 'NO_SIGNAL',
                                    'metrics': {'error': 'Camera Disconnected'}
                                }
                                # Inject "NO SIGNAL" placeholder for disconnected cam
                                placeholder = self._get_no_signal_frame(d.get('name', d['id']))
                                self.latest_frames_raw[d['id']] = placeholder
                                ret, jpeg = cv2.imencode('.jpg', placeholder, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
                                if ret:
                                    self.latest_frames[d['id']] = jpeg.tobytes()
                        continue
                        
                    for d in displays:
                        did = d['id']
                        try:
                            # Extract region (KEEP CLEAN in internal storage)
                            disp_frame = self.processor.process_display(frame, d)
                            if disp_frame is None:
                                continue
                            
                            if did not in self.engines:
                                 reader = get_ocr_reader()
                                 engine_config = copy.deepcopy(self.loader.monitor_config)
                                 engine_config['ocr_reader'] = reader
                                 self.engines[did] = DisplayStatusEngine(engine_config)
                            
                            engine = self.engines[did]
                            status, metrics = engine.evaluate(disp_frame, display_name=d.get('name'), camera_id=str(cid))
                            
                        except Exception as inner_e:
                             print(f"[MonitorDebug] Error processing display {did}: {inner_e}")
                             continue
                        
                        # Encode for Stream
                        ret, jpeg = cv2.imencode('.jpg', disp_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60]) # Lower quality for speed
                        if not ret:
                            continue

                        jpeg_bytes = jpeg.tobytes()
                        
                        # Update State
                        with self.lock:
                            self.latest_frames[did] = jpeg_bytes
                            self.latest_frames_raw[did] = disp_frame
                            
                            # Check for status changes to log
                            prev_data = self.latest_status.get(did)
                            prev_status = prev_data.get('status') if prev_data else None
                            
                            self.latest_status[did] = {
                                'id': did,
                                'name': d.get('name', did),
                                'timestamp': time.time() * 1000,
                                'status': status,
                                'metrics': metrics
                            }
                            
                            if status != prev_status and self.sess_id:
                                self.log_event("STATUS_CHANGE", f"Status: {status} (was {prev_status})", display_name=d.get('name'))
                            
                            if metrics.get('glitch') and self.sess_id:
                                g_types = metrics.get('glitch_type', [])
                                severity = metrics.get('glitch_severity', 'LOW')
                                # Include status and OCR context in glitch log as requested
                                ocr_context = f" | OCR: {metrics.get('ocr_text')[:50]}" if metrics.get('ocr_text') else ""
                                self.log_event("GLITCH_DETECTED", f"Status: {status} | Severity: {severity} | Types: {g_types}{ocr_context}", display_name=d.get('name'))
                            
                            if metrics.get('ocr_pattern') and self.sess_id:
                                pattern = metrics.get('ocr_pattern')
                                full_text = metrics.get('ocr_text', '')
                                self.log_event("OCR_NEGATIVE_MATCH", f"Status: {status} | Pattern: {pattern} | Text: {full_text}", display_name=d.get('name'))
                            elif metrics.get('ocr_detected') and self.sess_id:
                                # Regular OCR recording
                                full_text = metrics.get('ocr_text', '')
                                self.log_event("OCR_DETECTED", f"Status: {status} | Text: {full_text}", display_name=d.get('name'))

                # Handling recording in the loop (Time-Based Synchronization)
                if self.sess_id:
                    now = time.time()
                    elapsed = now - self.sess_last_record_time
                    interval = 0.1 # 10 FPS = 0.1s interval
                    
                    if elapsed >= interval:
                        num_frames = int(elapsed / interval)
                        tiled = self._get_tiled_frame()
                        
                        if tiled is not None and self.sess_path:
                            with self.sess_lock:
                                if self.sess_video is None:
                                    h, w = tiled.shape[:2]
                                    v_path = os.path.join(self.sess_path, "combined_monitoring.mp4")
                                    # Use avc1 (H.264) for web compatibility
                                    fourcc = cv2.VideoWriter_fourcc(*'avc1')
                                    # Use a higher bitrate if possible, but standard is fine
                                    self.sess_video = cv2.VideoWriter(v_path, fourcc, 10.0, (w, h))
                                
                                # Write frames to catch up to real time
                                for _ in range(num_frames):
                                    if self.sess_video:
                                        self.sess_video.write(tiled)
                                        
                        self.sess_last_record_time += num_frames * interval
                
                # Faster capture loop (~30 FPS potential)
                time.sleep(0.01)
                frame_idx += 1
            except Exception as e:
                print(f"[MonitorSystem] Loop error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(1)

# Global System
monitor_sys = MonitorSystem()
# Start removed for lazy loading
# if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
#     monitor_sys.start()
# else:
#     # First run of reloader, or non-debug
#     monitor_sys.start()

# --- Routes ---

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

@app.route('/uploads/<path:filename>')
def serve_uploads(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/video_feed/<display_id>')
def video_feed(display_id):
    """MJPEG Streaming Endpoint (kept for compatibility)"""
    return Response(generate_stream(display_id),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/monitor/frame/<display_id>')
def get_display_frame(display_id):
    """Returns a single latest JPEG frame for a display (RAW)"""
    with monitor_sys.lock:
        raw = monitor_sys.latest_frames_raw.get(display_id)
        # Deep copy to avoid modifying shared state
        frame = raw.copy() if raw is not None else None
    
    if frame is not None:
        ret, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if ret:
            return Response(jpeg.tobytes(), mimetype='image/jpeg')
            
    return "No Frame", 404

def generate_stream(display_id):
    while True:
        frame = None
        with monitor_sys.lock:
            frame = monitor_sys.latest_frames.get(display_id)
        
        if frame:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        else:
            # Wait a bit if no frame yet
            pass
        time.sleep(0.05) # Limit stream FPS to ~20

@app.route('/api/monitor/snapshot')
def get_monitor_snapshot():
    """Returns status AND base64 frames for all displays (RAW)"""
    import base64
    with monitor_sys.lock:
        statuses = list(monitor_sys.latest_status.values())
        raw_frames = {k: v.copy() for k, v in monitor_sys.latest_frames_raw.items()}
        
    encoded_frames = {}
    for did, frame in raw_frames.items():
        try:
            ret, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
            if ret:
                encoded_frames[did] = base64.b64encode(jpeg.tobytes()).decode('utf-8')
        except:
            continue

    return jsonify({
        'statuses': statuses,
        'frames': encoded_frames
    })

@app.route('/api/monitor/status')
def get_monitor_status():
    """Returns current status of all displays"""
    with monitor_sys.lock:
        data = list(monitor_sys.latest_status.values())
    return jsonify(data)

@app.route('/api/monitor/start', methods=['POST'])
def start_monitor_system():
    try:
        if monitor_sys.thread and monitor_sys.thread.is_alive():
            return jsonify({'status': 'already_running'})
        
        monitor_sys.run_flag = True
        monitor_sys.start()
        return jsonify({'status': 'started'})
    except Exception as e:
        print(f"Start Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/monitor/stop', methods=['POST'])
def stop_monitor_system():
    try:
        monitor_sys.stop()
        return jsonify({'status': 'stopped'})
    except Exception as e:
        print(f"Stop Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/config/load')
def load_config():
    """Returns display layout config"""
    # Force reload and reconcile to ensure accuracy
    monitor_sys.refresh_config()
    return jsonify({
        'displays': monitor_sys.loader.displays,
        'cameras': monitor_sys.loader.camera_configs # Send camera configs too
    })

@app.route('/api/config/save', methods=['POST'])
def save_config():
    """Saves display layout config"""
    try:
        data = request.json
        if not data:
             return jsonify({'error': 'Invalid format, data required'}), 400

        # Support both legacy list and new dict format
        if isinstance(data, list):
             displays = data
             cameras = {}
        else:
             displays = data.get('displays', [])
             cameras = data.get('cameras', {})
        
        # Structure for YAML
        yaml_data = {'displays': displays, 'cameras': cameras}
        
        with open('display_config.yaml', 'w') as f:
            yaml.dump(yaml_data, f, default_flow_style=False)
            
        # Reload and reconcile monitor system with new config
        monitor_sys.refresh_config()
        return jsonify({'status': 'success'})
        
    except Exception as e:
        print(f"Config Save Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/cameras')
def get_cameras():
    """Returns cameras detected on the host machine"""
    # Optional: Release monitor_sys cameras momentarily to ensure discovery works?
    # monitor_sys.processor.close() # Might disrupt dashboard
    return jsonify(ImageProcessor.discover_cameras())

@app.route('/api/cameras/reset', methods=['POST'])
def reset_cameras():
    print("[API] Resetting camera connections...")
    with monitor_sys.lock:
        monitor_sys.processor.close()
        monitor_sys.latest_frames.clear()
        monitor_sys.latest_status.clear()
    return jsonify({'status': 'reset'})


@app.route('/api/monitor/config')
def get_config():
    """Returns monitor param config"""
    return jsonify(monitor_sys.loader.monitor_config)

import base64

@app.route('/api/ocr/detect', methods=['POST'])
def detect_ocr():
    """Standalone OCR endpoint for client-side analysis (e.g. Upload Video)"""
    try:
        data = request.json
        if not data or 'image' not in data:
            return jsonify({'error': 'No image provided'}), 400
            
        # Decode base64
        img_str = data['image']
        if ',' in img_str:
            img_str = img_str.split(',')[1]
        image_bytes = base64.b64decode(img_str)
        np_arr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        reader = get_ocr_reader()
        if not reader:
             return jsonify({'detected': False, 'error': 'OCR not initialized', 'confidence': 0}), 200

        # Pattern Match Config
        patterns = monitor_sys.loader.monitor_config.get('negative_text', [])
        
        # Run OCR
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = reader.readtext(rgb_frame)
        
        detected_text = []
        detected_pattern = None
        max_conf = 0.0
        
        for (bbox, text, prob) in results:
            if prob > 0.3:
                detected_text.append(text)
                if not detected_pattern:
                    text_lower = text.lower()
                    for p in patterns:
                        if p.lower() in text_lower:
                            detected_pattern = p
                max_conf = max(max_conf, prob)
        
        return jsonify({
            'detected': bool(detected_pattern),
            'text': " ".join(detected_text),
            'pattern': detected_pattern,
            'confidence': float(max_conf)
        })

    except Exception as e:
        print(f"OCR Endpoint Error: {e}")
        return jsonify({'error': str(e)}), 500

# Session storage for video analysis
analysis_sessions = {}  # { session_id: { 'filepath': ..., 'status': ..., 'report': [] } }
analysis_lock = threading.Lock()

@app.route('/api/utils/pick-file', methods=['GET'])
def pick_file():
    """Triggers a native macOS file picker and returns the absolute path."""
    try:
        # Use osascript to open a native Mac file picker
        cmd = ["osascript", "-e", 'POSIX path of (choose file with prompt "Select a video file:")']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            path = result.stdout.strip()
            return jsonify({'path': path})
        else:
            # User likely cancelled
            return jsonify({'error': 'User cancelled or picker failed'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analyze/local-path', methods=['POST'])
def analyze_local_path():
    """Starts analysis from a local system path."""
    data = request.json
    if not data or 'path' not in data:
        return jsonify({'error': 'No path provided'}), 400
    
    filepath = data['path']
    if not os.path.exists(filepath):
        return jsonify({'error': f'Path does not exist: {filepath}'}), 404
    
    if not os.path.isfile(filepath):
        return jsonify({'error': f'Not a file: {filepath}'}), 400

    timestamp = int(time.time())
    session_id = f"session_local_{timestamp}"
    filename = os.path.basename(filepath)

    with analysis_lock:
        analysis_sessions[session_id] = {
            'filepath': filepath,
            'filename': filename,
            'status': 'pending',
            'report': [],
            'is_local': True
        }

    return jsonify({
        'status': 'ready',
        'session_id': session_id,
        'video_url': f'/api/video/local?path={filepath}'
    })

@app.route('/api/video/local')
def serve_local_video():
    """Proxy for serving local video files to the browser."""
    path = request.args.get('path')
    if not path or not os.path.exists(path):
        return "File not found", 404
    
    # Optional: Basic security check to ensure it's a video file or in allowed path
    return send_file(path)

@app.route('/api/analyze/stream/<session_id>')
def stream_analysis(session_id):
    """SSE endpoint for streaming live analysis results."""  
    def generate():
        # Check session exists
        with analysis_lock:
            if session_id not in analysis_sessions:
                yield f"data: {json.dumps({'error': 'Invalid session'})}\n\n"
                return
            
            session = analysis_sessions[session_id]
            filepath = session['filepath']
            
            # Mark as processing
            session['status'] = 'processing'
        
        # Default Analysis config
        config = {
            "diff_spike": 25.0,
            "pixel_diff": 25,
            "min_area": 0.005,
            "max_area": 0.6,
            "block_size": 16,
            "pixel_outlier_sigma": 5.0,
            "edge_energy_threshold": 8.0,
            "history": 3,
            "freeze_threshold": 0.05,
            "min_freeze_frames": 15,
            "min_artifact_frames": 2,
            "black_threshold": 2.0,
            "flicker_rel_threshold": 0.1
        }
        
        # Override with config.yaml if present
        try:
            if os.path.exists('config.yaml'):
                with open('config.yaml', 'r') as f:
                    yaml_data = yaml.safe_load(f)
                    if yaml_data and 'glitch_detector' in yaml_data:
                        config.update(yaml_data['glitch_detector'])
                        print(f"[Analysis] Loaded custom glitch detector config: {yaml_data['glitch_detector']}")
        except Exception as e:
            print(f"[Analysis] Error loading config.yaml: {e}")
        
        try:
            # Check GPU availability
            use_gpu = False
            gpu_warning = None
            import platform
            
            try:
                # Check if running on Apple Silicon
                is_apple_silicon = platform.machine() == 'arm64' and platform.system() == 'Darwin'
                
                if is_apple_silicon:
                    # Apple Silicon - check for actual Metal/CoreML/Accelerate support
                    gpu_detected = False
                    gpu_backend = None
                    
                    try:
                        # Check OpenCV build info for GPU support
                        build_info = cv2.getBuildInformation()
                        
                        # Check for various GPU frameworks
                        has_metal = 'Metal' in build_info or 'METAL' in build_info
                        has_opencl = 'OpenCL' in build_info
                        has_accelerate = 'Accelerate' in build_info or 'LAPACK' in build_info
                        
                        if has_metal:
                            gpu_detected = True
                            gpu_backend = 'Metal'
                            use_gpu = True
                        elif has_opencl:
                            gpu_detected = True
                            gpu_backend = 'OpenCL'
                            use_gpu = True
                        elif has_accelerate:
                            gpu_detected = True
                            gpu_backend = 'Accelerate (CPU-optimized)'
                            use_gpu = False  # Accelerate is CPU optimization, not GPU
                        
                        if gpu_detected and use_gpu:
                            print(f"[Analysis] Apple Silicon GPU acceleration enabled via {gpu_backend}")
                            success_data = {
                                'type': 'gpu_status',
                                'available': True,
                                'message': f'GPU Accelerated ({gpu_backend})'
                            }
                            yield f"data: {json.dumps(success_data)}\n\n"
                        else:
                            backend_info = gpu_backend if gpu_backend else 'CPU-only build'
                            gpu_warning = f"Apple Silicon M4 detected. Using {backend_info}."
                            print(f"[Analysis] {gpu_warning}")
                            
                    except Exception as e:
                        gpu_warning = f"Apple Silicon detected. Using CPU (OpenCV build info unavailable)."
                        print(f"[Analysis] {gpu_warning}")
                else:
                    # Check for NVIDIA CUDA
                    cuda_available = cv2.cuda.getCudaEnabledDeviceCount() > 0
                    if cuda_available:
                        use_gpu = True
                        print(f"[Analysis] GPU acceleration enabled (CUDA devices: {cv2.cuda.getCudaEnabledDeviceCount()})")
                        success_data = {
                            'type': 'gpu_status',
                            'available': True,
                            'message': 'GPU Accelerated (CUDA)'
                        }
                        yield f"data: {json.dumps(success_data)}\n\n"
                    else:
                        gpu_warning = "GPU not available. Using CPU (analysis will be slower)."
                        print(f"[Analysis] {gpu_warning}")
            except AttributeError:
                # cv2.cuda module not available
                gpu_warning = "OpenCV not built with CUDA support. Using CPU (analysis will be slower)."
                print(f"[Analysis] {gpu_warning}")
            except Exception as e:
                gpu_warning = f"GPU check failed: {str(e)}. Using CPU (analysis will be slower)."
                print(f"[Analysis] {gpu_warning}")
            
            # Send GPU warning to frontend if needed
            if gpu_warning:
                warning_data = {
                    'type': 'warning',
                    'message': gpu_warning
                }
                yield f"data: {json.dumps(warning_data)}\n\n"
            
            # Process video and stream results live
            from glitch_logic import GlitchDetector
            
            cap = cv2.VideoCapture(filepath)
            if not cap.isOpened():
                yield f"data: {json.dumps({'error': 'Could not open video'})}\n\n"
                return
            
            # Try to use hardware acceleration for decoding if available
            if use_gpu:
                try:
                    # Set backend to CUDA if available (this may not work on all systems)
                    cap.set(cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_ANY)
                except:
                    pass  # Hardware acceleration not supported, continue with software decoding
            
            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0:
                fps = 30
            
            detector = GlitchDetector(config)
            second_wise_glitches = {}
            second_wise_severity = {}
            severity_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, None: 0}
            
            # OCR State for Video Analysis
            reader = get_ocr_reader()
            ocr_cfg = config.get('ocr_config', {})
            ocr_mode = ocr_cfg.get('mode', 'ALWAYS').upper()
            ocr_interval = ocr_cfg.get('interval', 5.0)
            last_ocr_time = -ocr_interval # Force initial OCR
            negative_patterns = config.get('negative_text', [])
            
            frame_idx = 0
            last_sent_second = -1
            frame_skip = 2 # Process every 2nd frame
            
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Frame skipping logic
                if frame_idx % frame_skip != 0:
                    frame_idx += 1
                    continue
                
                current_time = frame_idx / fps
                current_second = int(current_time)
                
                # 1. Glitch Detection
                result = detector.detect(frame, display_name=os.path.basename(filepath))
                
                # 2. OCR Detection (Interval based)
                should_run_ocr = False
                if ocr_mode == "ALWAYS":
                    should_run_ocr = True
                elif ocr_mode == "BLACK" and result["metrics"]["signals"]["black"]:
                    should_run_ocr = True
                elif ocr_mode == "FREEZE" and result["metrics"]["signals"]["freeze"]:
                    should_run_ocr = True
                elif ocr_mode == "ACTIVE" and not (result["metrics"]["signals"]["black"] or result["metrics"]["signals"]["freeze"]):
                    should_run_ocr = True

                if reader and should_run_ocr and (current_time - last_ocr_time) >= ocr_interval:
                    try:
                        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        ocr_results = reader.readtext(rgb_frame)
                        
                        for (bbox, text, prob) in ocr_results:
                            if prob > 0.3:
                                # Check against negative patterns
                                text_lower = text.lower()
                                matched = None
                                for p in negative_patterns:
                                    if p.lower() in text_lower:
                                        matched = p
                                        break
                                
                                if matched:
                                    if current_second not in second_wise_glitches:
                                        second_wise_glitches[current_second] = set()
                                        second_wise_severity[current_second] = "LOW"
                                    
                                    second_wise_glitches[current_second].add(f"TEXT: {matched}")
                                    second_wise_severity[current_second] = "HIGH" # Pattern match is high severity
                        
                        last_ocr_time = current_time
                    except Exception as ocr_err:
                        print(f"[Analysis OCR] Error: {ocr_err}")

                if result["glitch"]:
                    if current_second not in second_wise_glitches:
                        second_wise_glitches[current_second] = set()
                        second_wise_severity[current_second] = "LOW"
                    
                    for g_type in result["type"]:
                        second_wise_glitches[current_second].add(g_type)
                    
                    current_max = second_wise_severity[current_second]
                    if severity_rank[result["severity"]] > severity_rank[current_max]:
                        second_wise_severity[current_second] = result["severity"]
                
                # Stream out results for each new second
                if current_second != last_sent_second and current_second in second_wise_glitches:
                    event_data = {
                        'second': current_second,
                        'severity': second_wise_severity[current_second],
                        'types': sorted(list(second_wise_glitches[current_second]))
                    }
                    
                    # Send SSE event
                    yield f"data: {json.dumps(event_data)}\n\n"
                    
                    # Update session
                    with analysis_lock:
                        session['report'].append(event_data)
                    
                    last_sent_second = current_second
                
                frame_idx += 1
                
                # Optional: yield progress updates every N frames
                if frame_idx % 60 == 0:  # Every ~2 seconds at 30fps
                    progress_data = {
                        'type': 'progress',
                        'second': current_second
                    }
                    yield f"data: {json.dumps(progress_data)}\n\n"
            
            cap.release()
            
            # Send completion event
            completion_data = {'type': 'complete', 'total_seconds': current_second}
            yield f"data: {json.dumps(completion_data)}\n\n"
            
            # Update session
            with analysis_lock:
                session['status'] = 'complete'
        
        except Exception as e:
            print(f"Stream Analysis Error: {e}")
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
            with analysis_lock:
                if session_id in analysis_sessions:
                    analysis_sessions[session_id]['status'] = 'error'
    
    return Response(generate(), mimetype='text/event-stream')

# --- New Management APIs ---

@app.route('/api/displays/list')
def api_list_displays():
    """Returns a list of all configured displays"""
    # Force reload and reconcile to ensure accuracy
    monitor_sys.refresh_config()
    return jsonify({
        'displays': [
            {'id': d['id'], 'name': d.get('name'), 'camera_name': d.get('camera_name')}
            for d in monitor_sys.loader.displays
        ]
    })

def find_display(name_or_id):
    """Helper to find display by name or ID"""
    with monitor_sys.lock:
        # Try ID match
        if name_or_id in monitor_sys.latest_status:
            return name_or_id
        # Try Name match
        for did, status in monitor_sys.latest_status.items():
            if status.get('name') == name_or_id:
                return did
    return None

@app.route('/api/displays/status')
def api_get_status():
    """Query real-time status by name or ID"""
    name = request.args.get('name')
    did_input = request.args.get('id')
    
    target_id = find_display(did_input or name)
    if not target_id:
        return jsonify({'error': 'Display not found'}), 404
    
    with monitor_sys.lock:
        return jsonify(monitor_sys.latest_status[target_id])

@app.route('/api/displays/get-frame')
def api_get_frame():
    """Returns JPEG of current frame for specified display (RAW)"""
    name = request.args.get('name')
    did_input = request.args.get('id')
    
    target_id = find_display(did_input or name)
    if not target_id:
        return "Display not found", 404
        
    with monitor_sys.lock:
        raw = monitor_sys.latest_frames_raw.get(target_id)
        frame = raw.copy() if raw is not None else None
        
    if frame is not None:
        ret, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if ret:
            return Response(jpeg.tobytes(), mimetype='image/jpeg')
            
    return "No Frame", 404

@app.route('/api/displays/get-combined')
def api_get_combined():
    """Returns a tiled JPEG of all active displays"""
    tiled = monitor_sys._get_tiled_frame()
    if tiled is None:
        return "No displays active", 404
    
    ret, jpeg = cv2.imencode('.jpg', tiled, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ret:
        return "Encoding Error", 500
        
    return Response(jpeg.tobytes(), mimetype='image/jpeg')

@app.route('/api/monitor/continuous/start', methods=['POST'])
def api_monitor_start():
    sid, path = monitor_sys.start_continuous_monitor()
    return jsonify({
        'status': 'started',
        'session_id': sid,
        'path': path
    })

@app.route('/api/monitor/continuous/stop', methods=['POST'])
def api_monitor_stop():
    path = monitor_sys.stop_continuous_monitor()
    if not path:
        return jsonify({'status': 'not_running'}), 200
    return jsonify({
        'status': 'stopped',
        'path': path
    })

@app.route('/api/sessions/list')
def list_sessions():
    """List all recorded monitor sessions"""
    sessions_dir = os.path.join(os.getcwd(), "sessions")
    if not os.path.exists(sessions_dir):
        return jsonify({'sessions': []})
    
    sessions = []
    for d in sorted(os.listdir(sessions_dir), reverse=True):
        path = os.path.join(sessions_dir, d)
        if os.path.isdir(path) and d.startswith("session_"):
            # Check for events.log and video
            has_log = os.path.exists(os.path.join(path, "events.log"))
            has_video = os.path.exists(os.path.join(path, "combined_monitoring.mp4"))
            
            # Get folder creation time
            mtime = os.path.getmtime(path)
            
            sessions.append({
                'id': d,
                'path': path,
                'created': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime)),
                'timestamp': mtime,
                'has_log': has_log,
                'has_video': has_video
            })
    
    return jsonify({'sessions': sessions})

@app.route('/api/sessions/<session_id>/events')
def get_session_events(session_id):
    """Parse and return events from a session's events.log"""
    sessions_dir = os.path.join(os.getcwd(), "sessions")
    log_path = os.path.join(sessions_dir, session_id, "events.log")
    
    if not os.path.exists(log_path):
        return jsonify({'error': 'Log file not found'}), 404
    
    events = []
    # Regex: [2025-12-28 01:43:17] [display_name] TYPE: MESSAGE
    import re
    # Match [ts] [display] TYPE: MSG  OR [ts] TYPE: MSG
    pattern = re.compile(r'\[(?P<ts>.*?)\]\s+(?:\[(?P<display>.*?)\]\s+)?(?P<type>.*?):\s+(?P<msg>.*)')
    
    try:
        with open(log_path, 'r') as f:
            for line in f:
                match = pattern.match(line.strip())
                if match:
                    events.append(match.groupdict())
    except Exception as e:
        return jsonify({'error': str(e)}), 500
        
    return jsonify({
        'session_id': session_id,
        'events': events,
        'video_url': f'/api/sessions/{session_id}/video'
    })

@app.route('/api/sessions/<session_id>/video')
def get_session_video(session_id):
    """Serve the combined monitoring video for a session"""
    sessions_dir = os.path.join(os.getcwd(), "sessions")
    video_path = os.path.join(sessions_dir, session_id, "combined_monitoring.mp4")
    
    if not os.path.exists(video_path):
        return "Video not found", 404
        
    # conditional=True enables Range requests (seeking)
    return send_file(video_path, mimetype='video/mp4', as_attachment=False, conditional=True)

@app.route('/api/monitor/continuous/timer', methods=['POST'])
def api_monitor_timer():
    """Starts monitoring for X seconds and returns result summary"""
    seconds = request.args.get('seconds', type=int)
    if not seconds:
        return jsonify({'error': 'Missing seconds parameter'}), 400
    
    sid, path = monitor_sys.start_continuous_monitor()
    
    # Wait for X seconds
    time.sleep(seconds)
    
    # Stop and return
    final_path = monitor_sys.stop_continuous_monitor()
    
    return jsonify({
        'status': 'completed',
        'session_id': sid,
        'path': final_path,
        'duration': seconds
    })

if __name__ == '__main__':
    # Initialize directory for sessions
    os.makedirs(os.path.join(os.getcwd(), 'sessions'), exist_ok=True)
    
    # Initialize logging
    try:
        with open('config.yaml', 'r') as f:
            config_data = yaml.safe_load(f)
        setup_logging(config_data)
    except Exception as e:
        print(f"Logging setup failed: {e}")
        logging.basicConfig(level=logging.INFO)

    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("Display Monitor Application Starting (Advanced API Mode)")
    logger.info("=" * 60)
    
    # Start the monitor system by default if running directly
    monitor_sys.start()
    
    # Use 5001 as default port (often cleaner on Mac)
    app.run(host='0.0.0.0', port=5001, debug=False)
