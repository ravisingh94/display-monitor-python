import cv2
import numpy as np
import yaml
import os
import json
import time
import threading
import logging

logger = logging.getLogger('monitor_core')
from glitch_logic import GlitchDetector

class DisplayStatusEngine:
    def __init__(self, config=None):
        if config is None:
            config = {}
        
        defaults = {
            'off_brightness': 5,
            'black_brightness': 15,
            'noise_variance': 2,
            'edge_threshold': 1.2,
            'content_variance': 8,
            'diff_threshold': 0.4,
            'frozen_frames': 60
        }
        # Merge defaults with provided config (keeping all keys)
        self.config = defaults.copy()
        self.config.update(config)
        self.prev_gray = None
        self.frozen_counter = 0
        
        # Initialize GlitchDetector
        glitch_config = {
            "diff_spike": self.config.get('diff_spike', 25.0),
            "pixel_diff": self.config.get('pixel_diff', 25),
            "min_area": self.config.get('min_area', 0.005),
            "max_area": self.config.get('max_area', 0.6),
            "block_size": self.config.get('block_size', 16),
            "pixel_outlier_sigma": self.config.get('pixel_outlier_sigma', 5.0),
            "edge_energy_threshold": self.config.get('edge_energy_threshold', 8.0),
            "history": self.config.get('history', 3),
            "freeze_threshold": self.config.get('freeze_threshold', 0.05),
            "min_freeze_frames": self.config.get('min_freeze_frames', 15),
            "min_artifact_frames": self.config.get('min_artifact_frames', 2),
            "black_threshold": self.config.get('black_threshold', 2.0),
            "flicker_rel_threshold": self.config.get('flicker_rel_threshold', 0.1),
            "noise_threshold": self.config.get('noise_threshold', 500.0)
        }
        self.glitch_detector = GlitchDetector(glitch_config)
        
        # Initialize OCR
        self.ocr_reader = config.get('ocr_reader', None)
        self.ocr_interval = config.get('interval', 5.0) # Seconds
        self.ocr_mode = config.get('mode', 'ALWAYS').upper()
        self.last_ocr_time = 0
        self.negative_text_patterns = config.get('negative_text', [])
        
        # Async OCR state
        self.ocr_lock = threading.Lock()
        self.ocr_thread = None
        self.last_ocr_result = None

    def _match_negative_patterns(self, text):
        if not text:
            return None
        text_lower = text.lower()
        for pattern in self.negative_text_patterns:
            if pattern.lower() in text_lower:
                return pattern
        return None

    def _ocr_worker(self, frame, display_name=None, camera_id=None):
        """Internal worker to run OCR without blocking main loop"""
        res = self.run_ocr_core(frame, display_name, camera_id)
        with self.ocr_lock:
            self.last_ocr_result = res

    def run_ocr_core(self, frame, display_name=None, camera_id=None):
        if not self.ocr_reader:
            return None
        
        # Build context string for logging
        context = ""
        if display_name and camera_id:
            context = f"[Display: {display_name}, Camera: {camera_id}] "
        elif display_name:
            context = f"[Display: {display_name}] "
        elif camera_id:
            context = f"[Camera: {camera_id}] "
        
        try:
            # EasyOCR performs better with RGB
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # reader.readtext(...) returns list of (bbox, text, prob)
            results = self.ocr_reader.readtext(rgb_frame)
        except Exception as e:
             logger.error(f"{context}OCR error during readtext: {e}")
             return None

        detected = False
        text_found = ""
        pattern_found = None
        
        found_any = False
        for (bbox, text, prob) in results:
            if prob > 0.3: # Higher threshold for reliability
                found_any = True
                text_found += text + " "
                match = self._match_negative_patterns(text)
                if match:
                    detected = True
                    pattern_found = match
                    logger.warning(f"{context}OCR NEGATIVE PATTERN MATCHED: '{match}' in '{text}' (confidence: {prob:.2f})")
                else:
                    logger.debug(f"{context}OCR text detected: '{text}' (confidence: {prob:.2f})")
        
        if not found_any and len(results) > 0:
            logger.debug(f"{context}OCR: {len(results)} results with low confidence (<0.3) - discarded")
            for (bbox, text, prob) in results:
                print(f"[OCR Debug] LOW CONFIDENCE: '{text}' (prob: {prob:.2f})")
        
        # Log summary if any text was found
        if text_found.strip():
            logger.debug(f"{context}OCR full text: '{text_found.strip()}'")

        return {
            'detected': detected,
            'text': text_found.strip(),
            'pattern': pattern_found
        }
    
    def evaluate(self, frame, display_name=None, camera_id=None):
        """
        Evaluates a BGR frame and returns (status, metrics)
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        total_pixels = h * w

        # 1. Metrics
        brightness = np.mean(gray)
        variance = np.var(gray)

        # 2. Edge Density (Sobel approximation)
        sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        edge_mag = np.abs(sobelx) + np.abs(sobely)
        edge_sum = np.sum(edge_mag > 15) # Match JS threshold of 15
        edge_density = (edge_sum / total_pixels) * 100
        
        # print(f"DEBUG: brightness={brightness:.1f}, variance={variance:.1f}, edge={edge_density:.2f}")

        # 3. Temporal difference
        diff_score = 0
        if self.prev_gray is not None and self.prev_gray.shape == gray.shape:
            diff_score = np.mean(cv2.absdiff(gray, self.prev_gray))
        
        status = "UNKNOWN"

        # Logic
        if brightness < self.config['off_brightness'] and variance < self.config['noise_variance'] + 2 and edge_density < self.config['edge_threshold']:
            status = "OFF"
            self.frozen_counter = 0
        elif brightness < self.config['black_brightness'] and variance < self.config['noise_variance'] + 5 and edge_density < self.config['edge_threshold']:
            status = "BLACK"
            self.frozen_counter = 0
        elif variance > self.config['content_variance']:
            if self.prev_gray is not None and diff_score < self.config['diff_threshold']:
                self.frozen_counter += 1
                if self.frozen_counter >= self.config['frozen_frames']:
                    status = "FROZEN"
                else:
                    status = "ACTIVE"
            else:
                status = "ACTIVE"
                self.frozen_counter = 0
        else:
            if edge_density > self.config['edge_threshold']:
                status = "ACTIVE"
            else:
                status = "UNKNOWN"
            self.frozen_counter = 0

        self.prev_gray = gray.copy()
        
        # Glitch detection
        glitch_result = self.glitch_detector.detect(frame, display_name=display_name, camera_id=camera_id)
        
        # OCR Detection
        now = time.time()
        should_run_ocr = False
        if self.ocr_mode == "ALWAYS":
            should_run_ocr = True
        elif self.ocr_mode == "BLACK" and status == "BLACK":
            should_run_ocr = True
        elif self.ocr_mode == "FREEZE" and status == "FROZEN":
            should_run_ocr = True
        elif self.ocr_mode == "ACTIVE" and (status == "ACTIVE" or status == "Live"):
            should_run_ocr = True

        if should_run_ocr and (now - self.last_ocr_time) > self.ocr_interval:
        # Start async OCR if not currently running
            if self.ocr_thread is None or not self.ocr_thread.is_alive():
                self.ocr_thread = threading.Thread(target=self._ocr_worker, args=(frame.copy(), display_name, camera_id))
                self.ocr_thread.start()
                self.last_ocr_time = now
        
        # Get latest known OCR result
        with self.ocr_lock:
            ocr_res = self.last_ocr_result
            
        metrics = {
            'brightness': float(brightness),
            'variance': float(variance),
            'edge_density': float(edge_density),
            'diff_score': float(diff_score),
            'glitch': glitch_result['glitch'],
            'glitch_severity': glitch_result['severity'],
            'glitch_type': glitch_result['type'],
            'frozen_counter': self.frozen_counter,
            'ocr_detected': ocr_res['detected'] if ocr_res else False,
            'ocr_text': ocr_res['text'] if ocr_res else '',
            'ocr_pattern': ocr_res['pattern'] if ocr_res else None
        }
        
        return status, metrics

class CLILoader:
    def __init__(self
, display_config_path='display_config.yaml', monitor_config_path='config.yaml'):
        self.display_config_path = display_config_path
        self.monitor_config_path = monitor_config_path
        self.load_config()

    def load_config(self):
        self.displays = self._load_displays()
        self.monitor_config = self._load_monitor_config()
        logger.debug(f"[CLILoader] Loaded {len(self.displays)} displays from {self.display_config_path}")

    def _load_displays(self):
        if not os.path.exists(self.display_config_path):
            return []
        with open(self.display_config_path, 'r') as f:
            data = yaml.safe_load(f)
            displays = data.get('displays', []) if data else []
            
            # Calculate global bounds for resolution detection hints
            self.max_x = 0
            self.max_y = 0
            for d in displays:
                for c in d.get('corners', []):
                    self.max_x = max(self.max_x, c.get('x', 0))
                    self.max_y = max(self.max_y, c.get('y', 0))
                # Also check bounding box legacy fields
                self.max_x = max(self.max_x, d.get('x', 0) + d.get('w', 0))
                self.max_y = max(self.max_y, d.get('y', 0) + d.get('h', 0))
            
            return displays

    def _load_monitor_config(self):
        if not os.path.exists(self.monitor_config_path):
            return {}
        with open(self.monitor_config_path, 'r') as f:
            data = yaml.safe_load(f)
            if not data: return {}
            
            config = data.get('config', {})
            # Handle list-style config (legacy)
            if isinstance(config, list):
                flat = {}
                for item in config:
                    if isinstance(item, dict):
                        flat.update(item)
                config = flat
            
            # Merge with glitch_detector section if present
            glitch_config = data.get('glitch_detector', {})
            if isinstance(glitch_config, dict):
                config.update(glitch_config)
            
            # Load OCR configuration
            ocr_cfg = data.get('ocr_config', {})
            if isinstance(ocr_cfg, dict):
                config.update(ocr_cfg)
                if 'mode' in ocr_cfg:
                    logger.debug(f"[CLILoader] OCR Mode set to: {ocr_cfg['mode']} (Interval: {ocr_cfg.get('interval', 5.0)}s)")
            
            # Load negative_text patterns
            config['negative_text'] = data.get('negative_text', [])
            if config['negative_text']:
                logger.debug(f"[CLILoader] Loaded {len(config['negative_text'])} negative text patterns.")
            
            return config

class ImageProcessor:
    def __init__(self):
        self.caps = {}
        self._failed_caps = {} # Map ID -> timestamp of last failure

    def get_cap(self, cam_id):
        if cam_id in self.caps:
            return self.caps[cam_id]
        
        # Cooldown check (5 seconds)
        if cam_id in self._failed_caps:
            last_fail = self._failed_caps[cam_id]
            if time.time() - last_fail < 5.0:
                return None
            else:
                # Retry time!
                del self._failed_caps[cam_id]
        
        # Determine index or path
        try:
            # Try parsing cam_id as index
            idx = int(cam_id)
        except:
            # If it's a string path or hardware ID
            idx = cam_id
            
            # If it looks like a browser hash (not a path), don't even try to open it
            # Browser hashes are usually long hex strings without paths
            if isinstance(idx, str) and not (os.path.sep in idx or idx.startswith(('rtsp://', 'http://'))):
                if len(idx) > 32:
                    logger.debug(f"[ImageProcessor] Skipping browser-side ID hash: {idx[:8]}...")
                    self._failed_caps[cam_id] = time.time()
                    return None
                    
        # print(f"[ImageProcessor] Opening camera: {idx}")
        # print(f"[ImageProcessor] Opening camera: {idx}")
        
        def _try_open(config_func=None, desc="Default"):
            try:
                cap = cv2.VideoCapture(idx)
                if not cap.isOpened():
                    return None
                
                if config_func:
                    config_func(cap)
                
                # Warmup
                for _ in range(5):
                    ret, _ = cap.read()
                    if ret:
                        return cap
                    time.sleep(0.05)
                
                logger.debug(f"[ImageProcessor] Camera {idx} ({desc}) failed warmup.")
                cap.release()
            except Exception as e:
                logger.debug(f"[ImageProcessor] Error in {desc} attempt for {idx}: {e}")
            return None

        # Attempt 1: Default (OS decides)
        cap = _try_open(desc="Attempt 1: Default")
        
        # Attempt 2: Force MJPEG @ 720p (Good for bandwidth)
        if not cap:
            def config_mjpeg_720(c):
                c.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                c.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                c.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            cap = _try_open(config_mjpeg_720, desc="Attempt 2: MJPEG 720p")

        # Attempt 3: Low Res fallback (640x480)
        if not cap:
            def config_low_res(c):
                c.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                c.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap = _try_open(config_low_res, desc="Attempt 3: 640x480")

        if cap:
            self.caps[cam_id] = cap
            if cam_id in self._failed_caps: self._failed_caps.pop(cam_id, None)
            logger.debug(f"[ImageProcessor] Successfully opened camera {cam_id} via {cap.get(cv2.CAP_PROP_FRAME_WIDTH)}x{cap.get(cv2.CAP_PROP_FRAME_HEIGHT)}")
            return cap
        
        logger.debug(f"[ImageProcessor] Failed to open camera: {idx} after all attempts.")
        self._failed_caps[cam_id] = time.time()
        return None

    @staticmethod
    def discover_cameras(max_cameras=4):
        import subprocess
        import json
        
        # 1. Try to get real names and unique IDs from system_profiler (macOS specific)
        camera_info = [] # List of {'name': ..., 'hardware_id': ...}
        try:
            cmd = ["system_profiler", "SPCameraDataType", "-json"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                items = data.get('SPCameraDataType', [])
                for item in items:
                    camera_info.append({
                        'name': item.get('_name', 'Unknown Camera'),
                        'hardware_id': item.get('spcamera_unique-id', 'Unknown ID')
                    })
            logger.debug(f"[Discovery] System Profiler found: {camera_info}")
        except Exception as e:
            logger.debug(f"[Discovery] System Profiler failed: {e}")

        available_cameras = []
        
        # 2. Check indices with OpenCV and gather their "signatures"
        probed_cams = []
        common_resolutions = [
            (1920, 1080), (1280, 720), (1024, 768), 
            (800, 600), (640, 480), (320, 240), (160, 120)
        ]
        
        for i in range(max_cameras):
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                supported_count = 0
                for w_req, h_req in common_resolutions:
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w_req)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h_req)
                    w_act = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                    h_act = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                    if w_act == w_req and h_act == h_req:
                        supported_count += 1
                
                probed_cams.append({
                    'index': i,
                    'complexity': supported_count,
                    'is_high_res': supported_count > 4
                })
                cap.release()
        
        # 3. Pair Probed Cameras with System Profiler Names (Complexity-Aware)
        sys_internal = [c for c in camera_info if any(k in c['name'].lower() for k in ['macbook', 'facetime', 'built-in'])]
        sys_external = [c for c in camera_info if c not in sys_internal]
        
        probed_sorted = sorted(probed_cams, key=lambda x: x['complexity'])
        sys_sorted = sys_internal + sys_external
        
        for idx, probed in enumerate(probed_sorted):
            if idx < len(sys_sorted):
                info = sys_sorted[idx]
                name = f"{info['name']} (Device {probed['index']})"
                hw_id = info['hardware_id']
            else:
                name = f"Camera Device {probed['index']}"
                hw_id = f"UNKNOWN_{probed['index']}"
                
            logger.info(f"Camera discovered - Index: {probed['index']}, Name: {name}, HW ID: {hw_id}")
            available_cameras.append({
                'id': str(probed['index']), 
                'name': name, 
                'hardware_id': hw_id,
                'type': 'stream'
            })
                
        logger.info(f"Camera discovery complete - Found {len(available_cameras)} camera(s)")
        return available_cameras

    def read_frame(self, cam_id):
        """
        Reads a single frame from the camera. 
        Assumes the camera is already opened and being read continuously.
        """
        cap = self.get_cap(cam_id)
        if cap and cap.isOpened():
            # Retry logic for frame reading
            for _ in range(3):
                ret, frame = cap.read()
                if ret:
                    return frame
                # If fail, wait tiny bit and retry
                time.sleep(0.01)

            # If we get here, we failed 3 times in a row
            logger.debug(f"[ImageProcessor] Failed to read frame from {cam_id} (3 retries). Releasing...")
            cap.release()
            if cam_id in self.caps:
                del self.caps[cam_id]
            # Force a cooldown/fail state so we don't spam open/close
            self._failed_caps[cam_id] = time.time()
                 
        return None

    def capture_frame(self, cam_id):
        cap = self.get_cap(cam_id)
        if cap:
            # Aggressive flush for macOS/built-in cameras.
            # Reading 45 frames with a small delay (~1.5s total)
            ret, frame = False, None
            for i in range(45):
                ret, frame = cap.read()
                time.sleep(0.02) # 20ms sleep helps the driver settle
            
            if ret:
                # Save raw capture for debugging if requested via env
                if os.environ.get('DEBUG_MONITOR'):
                    cv2.imwrite(f"debug_raw_{cam_id}.png", frame)
                return frame
        return None

    def close(self):
        """Releases all video capture resources."""
        for cap in self.caps.values():
            if cap.isOpened():
                cap.release()
        self.caps.clear()

    def get_normalized_corners(self, corners):
        """
        Reorders corners to [TL, TR, BR, BL] relative to camera axes.
        Matches monitor.js logic to 'un-rotate' output.
        """
        if not corners or len(corners) != 4: return corners
        # Sort by Y
        sorted_y = sorted(corners, key=lambda c: c['y'])
        # Top two by X
        top = sorted(sorted_y[:2], key=lambda c: c['x'])
        # Bottom two by X (reversed for TR -> BR -> BL clockwise order)
        bot = sorted(sorted_y[2:], key=lambda c: c['x'], reverse=True)
        return [top[0], top[1], bot[0], bot[1]]

    def process_display(self, frame, display_data, global_max_x=None, global_max_y=None):
        """
        Crops, warps, and rotates the frame according to display_data.
        Automatically scales coordinates if frame resolution differs from 
        the standard browser resolutions (640x480 or 1280x720).
        """
        fh, fw = frame.shape[:2]
        corners = display_data.get('corners', [])
        
        # Determine reference resolution (src_w, src_h)
        # Use provided global hints or fall back to local display bounds
        ref_x = global_max_x if global_max_x is not None else (max([c['x'] for c in corners]) if corners else 0)
        ref_y = global_max_y if global_max_y is not None else (max([c['y'] for c in corners]) if corners else 0)
        
        # Determine likely source resolution with a buffer zone (common browser defaults)
        if ref_y <= 540: # Standard is 480, allowing up to 540
            src_h = 480.0
            if ref_x <= 720: # Standard is 640, allowing up to 720
                src_w = 640.0
            else: # Likely 848 (16:9 480p) or slightly larger
                src_w = 848.0
        else:
            src_h = 720.0
            src_w = 1280.0
            
        if os.environ.get('DEBUG_MONITOR'):
            logger.debug(f"DEBUG: Mapping {ref_x}x{ref_y} space to {fw}x{fh} frame. Assumed source: {src_w}x{src_h}")
            
        # Calculate uniform scale based on height matching
        # Most cameras/browsers match the height and crop or pillarbox the sides.
        scale = fh / src_h
        
        # Center the config space in the capture frame
        offset_x = (fw - (src_w * scale)) / 2.0
        offset_y = (fh - (src_h * scale)) / 2.0
        
        # Map corners: Scale + Center
        scaled_corners = [{'x': c['x'] * scale + offset_x, 'y': c['y'] * scale + offset_y} for c in corners]

        if not scaled_corners or len(scaled_corners) != 4:
            x, y = int(display_data.get('x',0)*scale + offset_x), int(display_data.get('y',0)*scale + offset_y)
            w, h = int(display_data.get('w',100)*scale), int(display_data.get('h',100)*scale)
            return frame[y:y+h, x:x+w]

        if display_data.get('enablePerspective', False):
            # Normalize corners to camera-up orientation
            norm_corners = self.get_normalized_corners(scaled_corners)
            src_pts = np.float32([[c['x'], c['y']] for c in norm_corners])
            
            # Dimensions are expected output size (from config)
            dst_w = int(display_data.get('w', 400))
            dst_h = int(display_data.get('h', 300))
            dst_pts = np.float32([[0, 0], [dst_w, 0], [dst_w, dst_h], [0, dst_h]])
            
            M = cv2.getPerspectiveTransform(src_pts, dst_pts)
            warped = cv2.warpPerspective(frame, M, (dst_w, dst_h))
            return warped
        else:
            # Standard crop (bounding box) using scaled corners
            xs = [c['x'] for c in scaled_corners]
            ys = [c['y'] for c in scaled_corners]
            
            x1, y1, x2, y2 = max(0, int(min(xs))), max(0, int(min(ys))), min(fw, int(max(xs))), min(fh, int(max(ys)))
            
            if x2 <= x1 or y2 <= y1:
                return np.zeros((display_data.get('h', 100), display_data.get('w', 100), 3), dtype=np.uint8)

            crop = frame[y1:y2, x1:x2]
            
            # Resize to target w/h to ensure consistent export size
            dst_w = int(display_data.get('w', 400))
            dst_h = int(display_data.get('h', 300))
            if crop.shape[1] != dst_w or crop.shape[0] != dst_h:
                crop = cv2.resize(crop, (dst_w, dst_h))
            
            return crop

    def __del__(self):
        for cap in self.caps.values():
            cap.release()
