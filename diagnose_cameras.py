
import cv2
import time
import os

def diagnose():
    print("Diagnosing available cameras...")
    res = {}
    for i in range(4):
        print(f"Checking index {i}...", end="", flush=True)
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            # Warmup
            
            # Set high res to ensure we see full FOV
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            
            for _ in range(10): cap.read()
            
            ret, frame = cap.read()
            if ret:
                fname = f"diagnostic_cam_{i}.jpg"
                cv2.imwrite(fname, frame)
                print(f" OPEN - Saved {fname}")
                res[i] = True
            else:
                print(" OPEN - Failed to read frame")
            cap.release()
        else:
            print(" CLOSED")
            
    print("\n--------------------------")
    print("Please check the generated diagnostic_cam_*.jpg files.")
    print("Compare these images with your expected 'Host Camera 0' vs 'Host Camera 1'.")
    print("This will definitively tell us which index maps to which physical device.")

if __name__ == "__main__":
    diagnose()
