import cv2

def probe(i):
    print(f"--- Probing Camera {i} ---")
    cap = cv2.VideoCapture(i)
    if not cap.isOpened():
        print("Failed to open")
        return
    
    resolutions = [
        (1920, 1080),
        (1280, 720),
        (1024, 768),
        (800, 600),
        (640, 480),
        (320, 240),
        (160, 120)
    ]
    
    supported = []
    for w_req, h_req in resolutions:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w_req)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h_req)
        w_act = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        h_act = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        if w_act == w_req and h_act == h_req:
            supported.append(f"{w_req}x{h_req}")
            
    print(f"Supported Resolutions: {', '.join(supported)}")
    cap.release()

probe(0)
probe(1)
