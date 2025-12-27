import requests
import json
import time
import os

BASE_URL = "http://localhost:5001"

def test_display_list():
    print("\n--- Testing: /api/displays/list ---")
    resp = requests.get(f"{BASE_URL}/api/displays/list")
    print(f"Status: {resp.status_code}")
    data = resp.json()
    print(f"Data: {json.dumps(data, indent=2)}")
    return data.get('displays', [])

def test_display_status(display_id, display_name):
    print(f"\n--- Testing: /api/displays/status (id: {display_id}) ---")
    resp = requests.get(f"{BASE_URL}/api/displays/status?id={display_id}")
    print(f"Status (by ID): {resp.status_code}")
    if resp.status_code == 200:
        print(f"Data: {json.dumps(resp.json(), indent=2)}")

    print(f"\n--- Testing: /api/displays/status (name: {display_name}) ---")
    resp = requests.get(f"{BASE_URL}/api/displays/status?name={display_name}")
    print(f"Status (by Name): {resp.status_code}")
    if resp.status_code == 200:
        print("Success: Found by Name")

def test_get_frame(display_id):
    print(f"\n--- Testing: /api/displays/get-frame (id: {display_id}) ---")
    resp = requests.get(f"{BASE_URL}/api/displays/get-frame?id={display_id}")
    print(f"Status: {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('Content-Type')}")
    if resp.status_code == 200:
        with open("test_frame.jpg", "wb") as f:
            f.write(resp.content)
        print("Success: Frame saved to test_frame.jpg")

def test_get_combined():
    print("\n--- Testing: /api/displays/get-combined ---")
    resp = requests.get(f"{BASE_URL}/api/displays/get-combined")
    print(f"Status: {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('Content-Type')}")
    if resp.status_code == 200:
        with open("test_combined.jpg", "wb") as f:
            f.write(resp.content)
        print("Success: Combined frame saved to test_combined.jpg")

def test_continuous_monitor():
    print("\n--- Testing: Continuous Monitor (Start/Stop) ---")
    
    # Start
    resp = requests.post(f"{BASE_URL}/api/monitor/continuous/start")
    print(f"Start Status: {resp.status_code}")
    start_data = resp.json()
    print(f"Start Data: {json.dumps(start_data, indent=2)}")
    session_id = start_data.get('session_id')
    
    if session_id:
        print("Waiting 5 seconds for recording...")
        time.sleep(5)
        
        # Stop
        resp = requests.post(f"{BASE_URL}/api/monitor/continuous/stop")
        print(f"Stop Status: {resp.status_code}")
        stop_data = resp.json()
        print(f"Stop Data: {json.dumps(stop_data, indent=2)}")

def test_timer(seconds=10):
    print(f"\n--- Testing: /api/monitor/continuous/timer (duration: {seconds}s) ---")
    print("This will block until completed...")
    resp = requests.post(f"{BASE_URL}/api/monitor/continuous/timer?seconds={seconds}")
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        print(f"Data: {json.dumps(resp.json(), indent=2)}")

if __name__ == "__main__":
    try:
        # 1. Get List
        displays = test_display_list()
        print(displays)
        
        if displays:
            first_disp = displays[0]
            did = first_disp['id']
            name = first_disp['name']
            print(did)
            print(name)
            
        #     # 2. Test status lookup
            print(test_display_status(did, name))
            
            # 3. Test frame capture
            print(test_get_frame(did))
            
        # #     # 4. Test combined capture
            print(test_get_combined())
            
        # #     # 5. Test continuous monitor
            # print(test_continuous_monitor())
            
        # #     # 6. Test timer (short)
            print(test_timer(10))
            
        # else:
        #     print("No displays configured. Skipping lookup tests.")
            
    except Exception as e:
        print(f"Test Failed: {e}")
