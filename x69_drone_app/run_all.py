import subprocess
import time
import sys
import os

def start_system():
    print("🚀 INITIALIZING X69 DRONE ECOSYSTEM...")
    
    # 1. Start Mock Drone (UDP Receiver)
    print("📡 Launching Mock Hardware...")
    mock_proc = subprocess.Popen([sys.executable, "drone_mock.py"])
    
    # 2. Start API (FastAPI)
    print("🔌 Starting Command API...")
    api_proc = subprocess.Popen([sys.executable, "drone_api.py"])
    
    # 3. Start UI (Gradio)
    print("🖥️  Opening Cockpit HUD...")
    ui_proc = subprocess.Popen([sys.executable, "drone_ui.py"])
    
    print("\n✅ ALL SYSTEMS ONLINE")
    print("   API: http://localhost:8000")
    print("   UI:  http://localhost:7860")
    print("\nPress Ctrl+C to terminate all systems.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 SHUTTING DOWN SYSTEMS...")
        mock_proc.terminate()
        api_proc.terminate()
        ui_proc.terminate()
        print("Done.")

if __name__ == "__main__":
    start_system()
