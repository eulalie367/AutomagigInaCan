import gradio as gr
import socket
import time
import cv2
import numpy as np

# UDP Configuration (Matches drone_mock.py)
UDP_IP = "127.0.0.1" 
UDP_PORT = 8888

# Create a UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_command(cmd_name):
    """Sends a UDP command to the drone."""
    msg = f"CMD:{cmd_name}"
    try:
        sock.sendto(msg.encode(), (UDP_IP, UDP_PORT))
        return f"Sent: {cmd_name}"
    except Exception as e:
        return f"Error: {e}"

# --- Simulated Video Feed ---
def get_video_frame():
    """Generates a mock video frame."""
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    # Add some text to simulate an overlay
    cv2.putText(frame, f"X69 LIVE - {time.strftime('%H:%M:%S')}", (10, 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    cv2.putText(frame, "STATUS: CONNECTED", (10, 70), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
    # Simulate some moving noise/lines
    y = int(time.time() * 50) % 480
    cv2.line(frame, (0, y), (640, y), (50, 50, 50), 1)
    return frame

with gr.Blocks(title="X69 Drone Control Center") as demo:
    gr.Markdown("# 🛸 X69 Drone Control Center")
    
    with gr.Row():
        with gr.Column(scale=2):
            # Video feed placeholder
            video_feed = gr.Image(label="Live Stream", value=get_video_frame, streaming=True)
            # Update video feed every 0.1s
            timer = gr.Timer(0.1)
            timer.tick(get_video_frame, outputs=video_feed)
            
        with gr.Column(scale=1):
            status_box = gr.Textbox(label="Last Command Sent", value="Ready")
            
            with gr.Group():
                gr.Markdown("### 🚀 Flight Control")
                with gr.Row():
                    takeoff_btn = gr.Button("TAKEOFF", variant="primary")
                    land_btn = gr.Button("LAND", variant="stop")
                    emergency_btn = gr.Button("STOP", variant="secondary")

            with gr.Group():
                gr.Markdown("### 🕹️ Maneuvering")
                with gr.Row():
                    gr.Button(" ").interactive = False
                    up_btn = gr.Button("⬆️")
                    gr.Button(" ").interactive = False
                with gr.Row():
                    left_btn = gr.Button("⬅️")
                    back_btn = gr.Button("⬇️")
                    right_btn = gr.Button("➡️")
                with gr.Row():
                    fwd_btn = gr.Button("F")
                    rev_btn = gr.Button("B")

            with gr.Accordion("Advanced Modes", open=False):
                with gr.Row():
                    flip_btn = gr.Button("360 FLIP")
                    headless_btn = gr.Button("HEADLESS")

    # --- Event Handlers ---
    takeoff_btn.click(lambda: send_command("TAKEOFF"), outputs=status_box)
    land_btn.click(lambda: send_command("LAND"), outputs=status_box)
    emergency_btn.click(lambda: send_command("EMERGENCY_STOP"), outputs=status_box)
    
    up_btn.click(lambda: send_command("UP"), outputs=status_box)
    back_btn.click(lambda: send_command("DOWN"), outputs=status_box)
    left_btn.click(lambda: send_command("LEFT"), outputs=status_box)
    right_btn.click(lambda: send_command("RIGHT"), outputs=status_box)
    fwd_btn.click(lambda: send_command("FORWARD"), outputs=status_box)
    rev_btn.click(lambda: send_command("BACKWARD"), outputs=status_box)
    
    flip_btn.click(lambda: send_command("FLIP"), outputs=status_box)
    headless_btn.click(lambda: send_command("HEADLESS_MODE"), outputs=status_box)

if __name__ == "__main__":
    demo.launch()
