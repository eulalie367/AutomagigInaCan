import gradio as gr
import socket
import time
import cv2
import numpy as np

# UDP Configuration
UDP_IP = "127.0.0.1"
UDP_PORT = 8888
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Custom CSS for HUD aesthetic
CSS = """
.hud-container { background-color: #0d0d0d; border: 2px solid #00ff00; padding: 20px; border-radius: 10px; }
.telemetry-box { color: #00ff00; font-family: 'Courier New', Courier, monospace; background-color: rgba(0, 255, 0, 0.1); border: 1px solid #00ff00; border-radius: 5px; padding: 10px; }
.control-btn { font-weight: bold; border-radius: 8px; transition: transform 0.2s; }
.control-btn:hover { transform: scale(1.05); }
.primary-btn { background: linear-gradient(135deg, #00ff00, #008000); color: white; border: none; }
.stop-btn { background: linear-gradient(135deg, #ff0000, #800000); color: white; border: none; }
.secondary-btn { background: linear-gradient(135deg, #444, #222); color: #00ff00; border: 1px solid #00ff00; }
"""

def send_command(cmd_name):
    msg = f"CMD:{cmd_name}"
    try:
        sock.sendto(msg.encode(), (UDP_IP, UDP_PORT))
        return f"📡 {cmd_name} SENT"
    except Exception as e:
        return f"🚨 ERROR: {e}"

def get_video_frame():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    # Background Grid
    for i in range(0, 640, 40): cv2.line(frame, (i, 0), (i, 480), (20, 20, 20), 1)
    for j in range(0, 480, 40): cv2.line(frame, (0, j), (640, j), (20, 20, 20), 1)
    
    # HUD Elements
    cv2.putText(frame, "X69 HUD v1.0", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.putText(frame, f"ALT: {10 + int(np.sin(time.time())*5)}m", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.putText(frame, f"SPD: {15}km/h", (20, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    cv2.putText(frame, f"BAT: {85}%", (540, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
    
    # Artificial Horizon
    roll = int(np.sin(time.time()*2) * 10)
    cv2.line(frame, (320-100, 240+roll), (320+100, 240-roll), (0, 255, 0), 2)
    cv2.circle(frame, (320, 240), 100, (0, 255, 0), 1)
    
    return frame

with gr.Blocks(css=CSS, title="X69 COCKPIT") as demo:
    with gr.Column(elem_classes=["hud-container"]):
        gr.HTML("<h1 style='text-align: center; color: #00ff00; margin-bottom: 20px;'>🛸 X69 DRONE COCKPIT</h1>")
        
        with gr.Row():
            with gr.Column(scale=3):
                video_feed = gr.Image(label="HUD Feed", value=get_video_frame, streaming=True, show_label=False)
                timer = gr.Timer(0.1)
                timer.tick(get_video_frame, outputs=video_feed)
                
            with gr.Column(scale=1, elem_classes=["telemetry-box"]):
                gr.Markdown("### 📡 TELEMETRY")
                status_box = gr.Label(label="Signal Link", value="LINK ACTIVE")
                last_cmd = gr.Textbox(label="Last Uplink", value="Ready", interactive=False)
                
                with gr.Group():
                    gr.Markdown("### 🛫 IGNITION")
                    with gr.Row():
                        takeoff_btn = gr.Button("TAKEOFF", elem_classes=["control-btn", "primary-btn"])
                        land_btn = gr.Button("LAND", elem_classes=["control-btn", "stop-btn"])
                        stop_btn = gr.Button("EMERGENCY", variant="secondary", elem_classes=["control-btn"])

        with gr.Row():
            with gr.Column(scale=1):
                gr.Markdown("### 🕹️ NAVIGATION")
                with gr.Row():
                    gr.Button("", variant="secondary", size="sm").interactive = False
                    up_btn = gr.Button("⬆️", elem_classes=["control-btn", "secondary-btn"])
                    gr.Button("", variant="secondary", size="sm").interactive = False
                with gr.Row():
                    left_btn = gr.Button("⬅️", elem_classes=["control-btn", "secondary-btn"])
                    down_btn = gr.Button("⬇️", elem_classes=["control-btn", "secondary-btn"])
                    right_btn = gr.Button("➡️", elem_classes=["control-btn", "secondary-btn"])

            with gr.Column(scale=1):
                gr.Markdown("### 🔄 STUNTS")
                flip_btn = gr.Button("360 FLIP", elem_classes=["control-btn", "primary-btn"])
                headless_btn = gr.Button("HEADLESS MODE", elem_classes=["control-btn", "secondary-btn"])

    # Events
    takeoff_btn.click(lambda: send_command("TAKEOFF"), outputs=last_cmd)
    land_btn.click(lambda: send_command("LAND"), outputs=last_cmd)
    stop_btn.click(lambda: send_command("EMERGENCY"), outputs=last_cmd)
    up_btn.click(lambda: send_command("UP"), outputs=last_cmd)
    down_btn.click(lambda: send_command("DOWN"), outputs=last_cmd)
    left_btn.click(lambda: send_command("LEFT"), outputs=last_cmd)
    right_btn.click(lambda: send_command("RIGHT"), outputs=last_cmd)
    flip_btn.click(lambda: send_command("FLIP"), outputs=last_cmd)
    headless_btn.click(lambda: send_command("HEADLESS"), outputs=last_cmd)

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
