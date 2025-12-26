import cv2
import numpy as np
import os
import yaml
from glitch_logic import GlitchDetector

video_path = "/Users/nehakumari/glitch_detection/flicker_video/6041713-uhd_3840_2160_24fps.mp4"
config_path = "config.yaml"

def debug_video_at_19s():
    # Load config
    with open(config_path, 'r') as f:
        data = yaml.safe_load(f)
    
    detector_config = {
        "diff_spike": 25.0,
        "pixel_diff": 25,
        "min_area": 0.005,
        "max_area": 0.6,
        "block_size": 16,
        "block_anomaly_threshold": 10.0,
        "block_diff_threshold": 2.0,
        "block_min_variance": 0.5,
        "pixel_outlier_sigma": 5.0,
        "edge_energy_threshold": 8.0,
        "history": 3,
        "freeze_threshold": 0.05,
        "min_freeze_frames": 15,
        "min_artifact_frames": 1,
        "flicker_rel_threshold": 0.1
    }
    if data and 'glitch_detector' in data:
        detector_config.update(data['glitch_detector'])

    detector = GlitchDetector(detector_config)
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0: fps = 24
    
    start_sec = 18
    end_sec = 21
    start_frame = int(start_sec * fps)
    end_frame = int(end_sec * fps)
    
    print(f"--- Debugging {os.path.basename(video_path)} (FPS: {fps}) ---")
    print(f"Analyzing from {start_sec}s to {end_sec}s (Frames {start_frame} to {end_frame})")
    
    # Fast forward to start_frame
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    
    frame_idx = start_frame
    while frame_idx <= end_frame:
        ret, frame = cap.read()
        if not ret: break
        
        res = detector.detect(frame)
        m = detector.last_metrics
        s = m['glitch_signals']
        
        sig_str = f"S:{int(s['temporal_spike'])} A:{int(s['localized_area'])} B:{int(s['block_glitch'])} Art:{int(s['artifacting'])} VA:{int(m['visual_artifact'])}"
        
        print(f"F{frame_idx:04d} ({frame_idx/fps:.2f}s) | G:{int(res['glitch'])} | {res['type']} | D:{m['diff_score']:.2f} | Area:{m['area_ratio']:.4f} | B:{m['block_score']:.2f} | {sig_str}")

        frame_idx += 1
    
    cap.release()

if __name__ == "__main__":
    debug_video_at_19s()
