import cv2
import numpy as np
from collections import deque
from datetime import datetime
import argparse
import os
import sys
import logging

logger = logging.getLogger('glitch_logic')

class GlitchDetector:
    """
    Unified visual glitch detector for camera-captured display frames.
    Refined to suppress false positives in proper videos and handle static scenes.
    """

    def __init__(self, config):
        self.cfg = config
        self.prev_gray = None
        self.prev_glitch_now = False
        self.history = deque(maxlen=self.cfg.get("history", 3))
        
        # For flicker detection
        self.brightness_history = deque(maxlen=20)
        
        # For freeze detection refinement
        self.consecutive_freeze_frames = 0
        self.consecutive_anomaly_frames = 0
        self.last_metrics = {
            "diff_score": 0.0, "area_ratio": 0.0, "block_score": 0.0, 
            "edge_energy": 0.0, 
            "glitch_signals": {
                "temporal_spike": False, "localized_area": False, "pixel_glitch": False,
                "block_glitch": False, "artifacting": False, "frame_corruption": False,
                "freeze": False, "black": False, "flicker": False, "noise_pixel": False
            }, 
            "visual_artifact": False,
            "mean_brightness": 0.0
        }

    def detect(self, frame, display_name=None, camera_id=None):
        # Build context string for logging
        context = ""
        if display_name and camera_id:
            context = f"[Display: {display_name}, Camera: {camera_id}] "
        elif display_name:
            context = f"[Display: {display_name}] "
        elif camera_id:
            context = f"[Camera: {camera_id}] "

        # Resize large frames to improve performance (max width 640px)
        h, w = frame.shape[:2]
        if w > 640:
            target_w = 640
            target_h = int(h * (target_w / w))
            frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)

        gray_raw = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        noise_variance = cv2.Laplacian(gray_raw, cv2.CV_64F).var()

        gray = cv2.GaussianBlur(gray_raw, (5, 5), 0)

        if self.prev_gray is None or self.prev_gray.shape != gray.shape:
            self.prev_gray = gray
            return self._empty_result()

        diff = cv2.absdiff(gray, self.prev_gray)
        diff_score = diff.mean()

        # --- Spatial difference mask ---
        diff_mask = diff > self.cfg["pixel_diff"]
        area_ratio = diff_mask.sum() / (diff_mask.size + 1e-5)

        # --- Pixel outliers ---
        mu, sigma = gray.mean(), gray.std()
        pixel_outliers = np.abs(gray - mu) > (
            self.cfg["pixel_outlier_sigma"] * sigma
        )
        outlier_ratio = pixel_outliers.sum() / (gray.size + 1e-5)

        # --- Block variance (block glitches) ---
        block_anomaly_score = self._block_variance_score(gray)

        # --- Edge energy (artifacting) ---
        # Resize for edge detection to speed up 
        small_gray = cv2.resize(gray, (0,0), fx=0.5, fy=0.5, interpolation=cv2.INTER_NEAREST)
        edges = cv2.Canny(small_gray, 50, 150)
        edge_energy = edges.mean()

        # --- Region-based corruption detection ---
        region_scores = self._region_diff_scores(diff)
        # Require higher contrast between regional anomaly and average, 
        # plus a minimum mean difference to avoid noise in dark scenes.
        region_anomaly = (max(region_scores) > (8 * (np.mean(region_scores) + 1e-5))) and (max(region_scores) > 2.0)

        # --- Flicker detection (relative brightness oscillation) ---
        mean_brightness = mu
        self.brightness_history.append(mean_brightness)
        flicker_detected = False
        flicker_intensity = 0.0
        if len(self.brightness_history) >= 6:
            recent_mean = np.mean(self.brightness_history)
            relative_jump = abs(self.brightness_history[-1] - self.brightness_history[-2]) / (recent_mean + 1e-5)
            flicker_intensity = relative_jump  # Store intensity for severity calculation
            if relative_jump > self.cfg.get("flicker_rel_threshold", 0.1): 
                flicker_detected = True

        # --- Freeze detection refinement ---
        is_frame_frozen = diff_score < self.cfg.get("freeze_threshold", 0.05)
        if is_frame_frozen:
            self.consecutive_freeze_frames += 1
        else:
            self.consecutive_freeze_frames = 0
            
        freeze_detected = self.consecutive_freeze_frames >= self.cfg.get("min_freeze_frames", 15)

        # --- Glitch signal aggregation ---
        glitch_signals = {
            "temporal_spike": diff_score > self.cfg["diff_spike"],
            "localized_area": self.cfg["min_area"] < area_ratio < self.cfg["max_area"],
            "pixel_glitch": (outlier_ratio > 0.05 and diff_score > 1.0), 
            "block_glitch": (block_anomaly_score > self.cfg.get("block_anomaly_threshold", 15.0) and diff_score > self.cfg.get("block_diff_threshold", 5.0)),
            "artifacting": (edge_energy > self.cfg["edge_energy_threshold"] and diff_score > 2.0),
            "frame_corruption": region_anomaly,
            "freeze": freeze_detected,
            "black": (mean_brightness < self.cfg.get("black_threshold", 2.0)),
            "flicker": flicker_detected,
            "noise_pixel": noise_variance > self.cfg.get("noise_threshold", 500.0)
        }

        # --- Artifact logic ---
        visual_artifact = (
            glitch_signals["temporal_spike"]
            and (glitch_signals["localized_area"] or area_ratio > self.cfg["max_area"])
            and (
                glitch_signals["pixel_glitch"]
                or glitch_signals["block_glitch"]
                or glitch_signals["artifacting"]
                or glitch_signals["frame_corruption"]
                or glitch_signals["noise_pixel"]
            )
        )

        # Decide final glitch status
        # NOTE: BLACK_FRAME and FREEZE are excluded from "Glitch" status per user request
        # as they often occur during normal display state changes (OFF/Static).
        has_visual_anomaly = visual_artifact or glitch_signals["flicker"] or glitch_signals["noise_pixel"]
        
        if has_visual_anomaly:
            self.consecutive_anomaly_frames += 1
        else:
            self.consecutive_anomaly_frames = 0
            
        persistent_visual_anomaly = self.consecutive_anomaly_frames >= self.cfg.get("min_artifact_frames", 2)
        glitch_now = persistent_visual_anomaly

        self.history.append(glitch_now)
        is_start = glitch_now and not self.prev_glitch_now
        
        self.prev_glitch_now = glitch_now
        self.prev_gray = gray

        if not glitch_now:
            return self._empty_result()

        # Pass additional metrics for dynamic severity calculation
        severity = self._severity(
            diff_score, 
            area_ratio, 
            outlier_ratio, 
            glitch_signals,
            flicker_intensity=flicker_intensity,
            freeze_duration=self.consecutive_freeze_frames,
            noise_variance=noise_variance
        )
        
        glitch_types = self._glitch_types(glitch_signals, visual_artifact or persistent_visual_anomaly)
        
        # Log glitch detection
        if is_start:
            logger.warning(f"{context}GLITCH DETECTED - Type: {', '.join(glitch_types)}, Severity: {severity}")
        logger.debug(f"{context}Glitch active - Types: {glitch_types}, Diff: {diff_score:.2f}, Noise: {noise_variance:.1f}")

        return {
            "glitch": True,
            "is_start": is_start,
            "severity": severity,
            "type": glitch_types,
            "metrics": {
                "diff": float(diff_score),
                "area": float(area_ratio),
                "outliers": float(outlier_ratio),
                "noise": float(noise_variance),
                "signals": glitch_signals
            },
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

    def _block_variance_score(self, gray):
        """Vectorized block variance calculation using NumPy."""
        h, w = gray.shape
        bs = self.cfg["block_size"]
        min_v = self.cfg.get("block_min_variance", 2.0)
        
        # Crop to be divisible by block size
        h_pad = h - (h % bs)
        w_pad = w - (w % bs)
        if h_pad <= 0 or w_pad <= 0: return 0.0
        
        blocks = gray[:h_pad, :w_pad].reshape(h_pad // bs, bs, w_pad // bs, bs)
        blocks = blocks.transpose(0, 2, 1, 3).reshape(-1, bs * bs)
        
        variances = blocks.var(axis=1)
        valid_vars = variances[variances > min_v]
        
        if valid_vars.size == 0: return 0.0
        return np.max(valid_vars) / (np.mean(valid_vars) + 1e-5)

    def _region_diff_scores(self, diff, rows=4, cols=4):
        h, w = diff.shape
        scores = []
        for i in range(rows):
            for j in range(cols):
                r = diff[i*h//rows:(i+1)*h//rows, j*w//cols:(j+1)*w//cols]
                scores.append(r.mean())
        return scores

    def _severity(self, diff, area, outliers, signals, flicker_intensity=0.0, freeze_duration=0, noise_variance=0.0):
        """
        Calculate dynamic severity based on actual glitch intensity.
        
        Args:
            diff: Temporal difference score
            area: Area ratio of change
            outliers: Pixel outlier ratio
            signals: Dict of glitch type flags
            flicker_intensity: Relative brightness change (0.0-1.0+)
            freeze_duration: Number of consecutive frozen frames
            noise_variance: Variance of Laplacian
        
        Returns:
            str: 'LOW', 'MEDIUM', or 'HIGH'
        """
        # Black screen is always HIGH severity
        if signals["black"]: 
            return "HIGH"
        
        # Freeze severity based on duration
        if signals["freeze"]:
            if freeze_duration > 60:  # > 2 seconds at 30fps
                return "HIGH"
            elif freeze_duration > 30:  # > 1 second
                return "MEDIUM"
            else:
                return "LOW"
        
        # Flicker severity based on intensity
        if signals["flicker"]:
            if flicker_intensity > 0.3:  # >30% brightness change
                return "HIGH"
            elif flicker_intensity > 0.15:  # >15% brightness change
                return "MEDIUM"
            else:
                return "LOW"
        
        # Visual artifacts - calculate composite score
        # Normalize noise_variance to a comparable scale (approx 0-100 range for typical glitches)
        noise_norm = min(noise_variance / 50.0, 100.0) 
        score = diff * 0.5 + area * 100 + outliers * 200 + noise_norm
        
        # Higher thresholds for visual artifacts
        if score > 150: 
            return "HIGH"
        elif score > 75: 
            return "MEDIUM"
        else:
            return "LOW"

    def _glitch_types(self, signals, visual_artifact):
        res = []
        # Freeze and Black Frame removed from Glitch reporting per user request
        if signals["flicker"]: res.append("FLICKER")
        if visual_artifact:
            if signals["pixel_glitch"]: res.append("PIXEL_GLITCH")
            if signals["block_glitch"]: res.append("BLOCK_GLITCH")
            if signals["artifacting"]: res.append("ARTIFACTING")
            if signals["frame_corruption"]: res.append("FRAME_CORRUPTION")
            if signals["noise_pixel"]: res.append("NOISE_PIXEL")
        return res

    def _empty_result(self):
        return {
            "glitch": False,
            "severity": None,
            "type": [],
            "metrics": {},
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

def process_video_second_wise(video_path, config):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.debug(f"Error: Could not open video file {video_path}")
        return None
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if fps <= 0: fps = 30 
    detector = GlitchDetector(config)
    second_wise_glitches = {}
    second_wise_severity = {}
    severity_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, None: 0}
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret: break
        result = detector.detect(frame, display_name=os.path.basename(video_path))
        if result["glitch"]:
            second = int(frame_idx / fps)
            if second not in second_wise_glitches:
                second_wise_glitches[second] = set()
                second_wise_severity[second] = "LOW"
            for g_type in result["type"]:
                second_wise_glitches[second].add(g_type)
            current_max = second_wise_severity[second]
            if severity_rank[result["severity"]] > severity_rank[current_max]:
                second_wise_severity[second] = result["severity"]
        frame_idx += 1
        if frame_idx % 100 == 0:
            logger.debug(f"Processed {frame_idx}/{frame_count} frames...", end='\r')
    cap.release()
    logger.debug("\nProcessing complete.")
    return second_wise_glitches, second_wise_severity

def main():
    parser = argparse.ArgumentParser(description="Unified Glitch Detector with second-wise reporting.")
    parser.add_argument("input", help="Path to the video file")
    parser.add_argument("--diff_spike", type=float, default=25.0) 
    parser.add_argument("--pixel_diff", type=int, default=25) 
    parser.add_argument("--min_area", type=float, default=0.005) 
    parser.add_argument("--max_area", type=float, default=0.6) 
    parser.add_argument("--block_size", type=int, default=16)
    parser.add_argument("--pixel_outlier_sigma", type=float, default=5.0) 
    parser.add_argument("--edge_energy_threshold", type=float, default=8.0)
    parser.add_argument("--history", type=int, default=3)
    parser.add_argument("--freeze_threshold", type=float, default=0.05) 
    parser.add_argument("--min_freeze_frames", type=int, default=15) 
    parser.add_argument("--min_artifact_frames", type=int, default=2) 
    parser.add_argument("--black_threshold", type=float, default=2.0) 
    parser.add_argument("--flicker_rel_threshold", type=float, default=0.1)
    parser.add_argument("--noise_threshold", type=float, default=500.0)
    args = parser.parse_args()
    video_path = args.input
    if not os.path.exists(video_path):
        print(f"Error: File {video_path} not found.")
        sys.exit(1)
    config = vars(args).copy()
    if 'input' in config: del config['input']
    print(f"Analyzing video: {video_path}")
    result = process_video_second_wise(video_path, config)
    if result is None: return
    glitches, severities = result
    if not glitches:
        print("No glitches detected.")
    else:
        print(f"\nSecond-wise Glitch Report:")
        print(f"{'Second':<8} | {'Severity':<10} | {'Glitch Types'}")
        print("-" * 50)
        for sec in sorted(glitches.keys()):
            g_types = ", ".join(sorted(list(glitches[sec])))
            sev = severities[sec]
            print(f"{sec:<8} | {sev:<10} | {g_types}")

if __name__ == "__main__":
    main()
