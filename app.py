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
from flask import Flask, send_from_directory, jsonify, request, Response

# Fix for macOS SSL certificate errors (Critical for EasyOCR)
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

from monitor_core import CLILoader, ImageProcessor, DisplayStatusEngine

app = Flask(__name__, static_folder='.')

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
        self.latest_status = {} # { display_id: { status, metrics } }
        self.engines = {}
        
        # Init Engines with OCR
        reader = get_ocr_reader()
        global_config = self.loader.monitor_config
        
        # Inject OCR dependencies into config for engines
        engine_config = copy.deepcopy(global_config)
        engine_config['ocr_reader'] = reader
        # Default 5s if not set
        engine_config['ocr_interval'] = engine_config.get('ocr_interval', 5.0) 
        
        # Load pattern config if exists on top level
        # (cli_engine expects it in config dict)
        
        for d in self.loader.displays:
            self.engines[d['id']] = DisplayStatusEngine(engine_config)
            
        print(f"[MonitorSystem] Initialized {len(self.engines)} display engines.")

    def start(self):
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        print("[MonitorSystem] Background capture thread started")

    def stop(self):
        self.run_flag = False
        if self.thread:
            self.thread.join()

    def _capture_loop(self):
        while self.run_flag:
            try:
                # Group displays by camera to optimize capture
                cam_displays = {}
                for d in self.loader.displays:
                    cid = d.get('camId', 0)
                    if cid not in cam_displays: cam_displays[cid] = []
                    cam_displays[cid].append(d)
                
                # Iterate cameras
                for cid, displays in cam_displays.items():
                    # Read single frame (efficient)
                    frame = self.processor.read_frame(cid)
                    
                    if frame is None:
                        # Try to initialize if not open? processor methods handle this?
                        # read_frame calls get_cap which opens if needed.
                        continue
                        
                    # Process displays
                    for d in displays:
                        # Extract region
                        disp_frame = self.processor.process_display(frame, d)
                        
                        # Analyze
                        did = d['id']
                        try:
                            if did not in self.engines:
                                 print(f"[MonitorDebug] Missing engine for {did}. Initializing...", flush=True)
                                 reader = get_ocr_reader()
                                 global_config = self.loader.monitor_config
                                 engine_config = copy.deepcopy(global_config)
                                 engine_config['ocr_reader'] = reader
                                 engine_config['ocr_interval'] = engine_config.get('ocr_interval', 5.0)
                                 self.engines[did] = DisplayStatusEngine(engine_config)
                                 print(f"[MonitorDebug] Engine created for {did}. Current keys: {list(self.engines.keys())}", flush=True)
                            
                            if did in self.engines:
                                engine = self.engines[did]
                                status, metrics = engine.evaluate(disp_frame)
                            else:
                                print(f"[MonitorDebug] CRITICAL: Engine for {did} missing after init attempt!", flush=True)
                                continue
                        except Exception as inner_e:
                             print(f"[MonitorDebug] Error processing display {did}: {inner_e}", flush=True)
                             continue
                        
                        # Encode for Stream
                        # Resize for bandwidth? Optional. For now send full processed res.
                        ret, jpeg = cv2.imencode('.jpg', disp_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                        jpeg_bytes = jpeg.tobytes()
                        
                        # Update State
                        with self.lock:
                            self.latest_frames[d['id']] = jpeg_bytes
                            self.latest_status[d['id']] = {
                                'id': d['id'],
                                'name': d['name'],
                                'timestamp': time.time() * 1000,
                                'status': status,
                                'metrics': metrics
                            }
                
                # Loop rate control (~20 FPS)
                time.sleep(0.05)
                
            except Exception as e:
                print(f"[MonitorSystem] Loop error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(1)

# Global System
monitor_sys = MonitorSystem()
# Start strictly if main (debugger reloader safeguard)
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
    monitor_sys.start()
else:
    # First run of reloader, or non-debug
    monitor_sys.start()

# --- Routes ---

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

@app.route('/video_feed/<display_id>')
def video_feed(display_id):
    """MJPEG Streaming Endpoint"""
    return Response(generate_stream(display_id),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

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

@app.route('/api/monitor/status')
def get_monitor_status():
    """Returns current status of all displays"""
    with monitor_sys.lock:
        data = list(monitor_sys.latest_status.values())
    return jsonify(data)

@app.route('/api/config/load')
def load_config():
    """Returns display layout config"""
    # Force reload from disk to ensure latest config is served
    monitor_sys.loader.load_config()
    return jsonify({'displays': monitor_sys.loader.displays})

@app.route('/api/config/save', methods=['POST'])
def save_config():
    """Saves display layout config"""
    try:
        data = request.json
        if not isinstance(data, list):
            return jsonify({'error': 'Invalid format, expected list'}), 400
        
        # Structure for YAML
        yaml_data = {'displays': data}
        
        with open('display_config.yaml', 'w') as f:
            yaml.dump(yaml_data, f, default_flow_style=False)
            
        # Reload monitor system with new config
        monitor_sys.loader.load_config()
        # Re-initialize engines if needed (optional, for now just updating displays list)
        # Note: In a full implementation, we might want to restart capture loops or re-init engines
        # but for simple layout updates, reloading loader.displays might be enough if MonitorSystem references it dynamically.
        # Actually MonitorSystem.loader IS the CLILoader instance, so reloading it there updates it.
        # However, MonitorSystem.engines are dicts keyed by ID. If IDs change, we might have stale engines.
        # For now, let's just save. The user usually restarts for major changes or we can add re-init logic.
        
        return jsonify({'status': 'success'})
        
    except Exception as e:
        print(f"Config Save Error: {e}")
        return jsonify({'error': str(e)}), 500


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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
