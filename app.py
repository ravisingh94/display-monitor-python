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
        self.latest_status = {} # { display_id: { status, metrics } }
        self.engines = {}
        self.thread = None
        
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
        # Release hardware
        self.processor.close()

    def _capture_loop(self):
        frame_idx = 0
        while self.run_flag:
            try:
                # Group displays by camera to optimize capture
                cam_displays = {}
                for d in self.loader.displays:
                    cid = d.get('camId', 0)
                    if cid not in cam_displays: cam_displays[cid] = []
                    cam_displays[cid].append(d)
                
                # Iterate cameras
                cids = list(cam_displays.keys())
                for cid in cids:
                    displays = cam_displays[cid]
                    frame = self.processor.read_frame(cid)
                    if frame is None:
                        continue
                        
                    for d in displays:
                        did = d['id']
                        try:
                            # Extract region
                            disp_frame = self.processor.process_display(frame, d)
                            if disp_frame is None:
                                continue
                            
                            if did not in self.engines:
                                 reader = get_ocr_reader()
                                 engine_config = copy.deepcopy(self.loader.monitor_config)
                                 engine_config['ocr_reader'] = reader
                                 self.engines[did] = DisplayStatusEngine(engine_config)
                            
                            engine = self.engines[did]
                            status, metrics = engine.evaluate(disp_frame)
                            
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
                            self.latest_status[did] = {
                                'id': did,
                                'name': d.get('name', did),
                                'timestamp': time.time() * 1000,
                                'status': status,
                                'metrics': metrics
                            }
                
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
    """Returns a single latest JPEG frame for a display"""
    with monitor_sys.lock:
        frame = monitor_sys.latest_frames.get(display_id)
    if frame:
        return Response(frame, mimetype='image/jpeg')
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
    """Returns status AND base64 frames for all displays in one go (Bypasses connection limits)"""
    import base64
    with monitor_sys.lock:
        snapshot = {
            'statuses': list(monitor_sys.latest_status.values()),
            'frames': {
                did: base64.b64encode(frame).decode('utf-8')
                for did, frame in monitor_sys.latest_frames.items()
            }
        }
    return jsonify(snapshot)

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
        return jsonify({'status': 'success'})
        
    except Exception as e:
        print(f"Config Save Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/cameras')
def get_cameras():
    """Returns cameras detected on the host machine"""
    return jsonify(ImageProcessor.discover_cameras())


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
                result = detector.detect(frame)
                
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
