import cv2
import numpy as np
import yaml
import os
import json
import time
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
            "flicker_rel_threshold": self.config.get('flicker_rel_threshold', 0.1)
        }
        self.glitch_detector = GlitchDetector(glitch_config)
        
        # Initialize OCR
        self.ocr_reader = config.get('ocr_reader', None)
        self.ocr_interval = config.get('ocr_interval', 5.0) # Seconds
        self.last_ocr_time = 0
        self.last_ocr_result = None
        self.negative_text_patterns = config.get('negative_text', [])

    def _match_negative_patterns(self, text):
        if not text:
            return None
        text_lower = text.lower()
        for pattern in self.negative_text_patterns:
            if pattern.lower() in text_lower:
                return pattern
        return None

    def run_ocr(self, frame):
        if self.ocr_reader is None:
            return None
            
        try:
            # EasyOCR expects RGB (CV2 is BGR) or file path or bytes
            # CV2 internal is BGR, EasyOCR readtext handles numpy arrays
            # But better to convert to RGB to be safe/correct for model
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            results = self.ocr_reader.readtext(rgb_frame)
            # results is list of (bbox, text, prob)
            
            detected_text = []
            detected_pattern = None
            max_conf = 0
            
            for (bbox, text, prob) in results:
                if prob > 0.3: # Minimum confidence
                    detected_text.append(text)
                    if not detected_pattern:
                        detected_pattern = self._match_negative_patterns(text)
                    max_conf = max(max_conf, prob)
            
            full_text = " ".join(detected_text)
            
            return {
                'detected': bool(detected_pattern),
                'text': full_text,
                'pattern': detected_pattern,
                'confidence': float(max_conf)
            }
        except Exception as e:
            print(f"OCR Error: {e}")
            return None
    def evaluate(self, frame):
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
        glitch_result = self.glitch_detector.detect(frame)
        
        # OCR Detection
        now = time.time()
        if (now - self.last_ocr_time) > self.ocr_interval:
            ocr_res = self.run_ocr(frame)
            if ocr_res:
                self.last_ocr_result = ocr_res
                # print(f"DEBUG: OCR Result: {ocr_res}")
            self.last_ocr_time = now
            
        metrics = {
            'brightness': float(brightness),
            'variance': float(variance),
            'edge_density': float(edge_density),
            'diff_score': float(diff_score),
            'glitch': glitch_result['glitch'],
            'glitch_severity': glitch_result['severity'],
            'glitch_type': glitch_result['type'],
            'frozen_counter': self.frozen_counter,
            'ocr_detected': self.last_ocr_result['detected'] if self.last_ocr_result else False,
            'ocr_text': self.last_ocr_result['text'] if self.last_ocr_result else '',
            'ocr_pattern': self.last_ocr_result['pattern'] if self.last_ocr_result else None
        }
        
        return status, metrics

class CLILoader:
    def __init__(self, display_config_path='display_config.yaml', monitor_config_path='config.yaml'):
        self.display_config_path = display_config_path
        self.monitor_config_path = monitor_config_path
        self.load_config()

    def load_config(self):
        self.displays = self._load_displays()
        self.monitor_config = self._load_monitor_config()
        print(f"[CLILoader] Loaded {len(self.displays)} displays from {self.display_config_path}")

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
            
            return config

class ImageProcessor:
    def __init__(self):
        self.caps = {}

    def get_cap(self, cam_id):
        if cam_id in self.caps:
            return self.caps[cam_id]
        
        # In macOS, cam_id passed is usually the label if system_profiler was used, 
        # or it could be an index. CV2 needs index or a string for some drivers.
        # We'll try index 0 for now as a fallback or try to find index from device name logic.
        # For this tool, we assume cam_id is either an index or we try common indices.
        
        try:
            # Try parsing cam_id as index
            idx = int(cam_id)
        except:
            # Fallback to index 0 if not numeric
            idx = 0
            
        cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            # Explicitly set resolution to a common stable format
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.caps[cam_id] = cap
            return cap
        return None

    def read_frame(self, cam_id):
        """
        Reads a single frame from the camera. 
        Assumes the camera is already opened and being read continuously.
        """
        cap = self.get_cap(cam_id)
        if cap and cap.isOpened():
            ret, frame = cap.read()
            if ret:
                return frame
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
            print(f"DEBUG: Mapping {ref_x}x{ref_y} space to {fw}x{fh} frame. Assumed source: {src_w}x{src_h}")
            
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
