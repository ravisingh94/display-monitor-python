import requests
import base64
import cv2
import numpy as np
import json
import os

def test_analyze_api():
    url = "http://127.0.0.1:5001/api/monitor/analyze"
    
    # Create a dummy frame with some "glitchy" patterns
    frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    # Add a bright block
    frame[100:200, 100:200] = 255
    
    _, buffer = cv2.imencode('.jpg', frame)
    img_b64 = base64.b64encode(buffer).decode('utf-8')
    
    payload = {
        "display_id": "test_display",
        "frame": img_b64
    }
    
    print(f"Sending request to {url}...")
    try:
        response = requests.post(url, json=payload)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            print("Response:")
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Failed to connect: {e}")

if __name__ == "__main__":
    test_analyze_api()
