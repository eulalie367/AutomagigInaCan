import gradio as gr
import socket
import numpy as np
import time

# UDP Config
UDP_IP = "127.0.0.1"
UDP_PORT = 8888
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_cmd(cmd):
    try:
        sock.sendto(f"CMD:{cmd}".encode(), (UDP_IP, UDP_PORT))
        return f"✅ Sent: {cmd}"
    except Exception as e:
        return f"❌ Error: {e}"

def get_frame():
    # Ultra-simple frame to avoid CV2 overhead/crashes
    frame = np.zeros((300, 400, 3), dtype=np.uint8)
    # Simple crosshair
    frame[150, :] = [0, 255, 0]
    frame[:, 200] = [0, 255, 0]
    return frame

with gr.Blocks(title="X69 LOCAL TEST") as demo:
    gr.Markdown("# 🛸 X69 Drone - Local Test HUD")
    with gr.Row():
        with gr.Column():
            video = gr.Image(label="Mock Feed", value=get_frame, streaming=True)
            timer = gr.Timer(0.2)
            timer.tick(get_frame, outputs=video)
        with gr.Column():
            status = gr.Textbox(label="Uplink Status", value="Ready")
            with gr.Row():
                gr.Button("TAKEOFF", variant="primary").click(lambda: send_cmd("TAKEOFF"), outputs=status)
                gr.Button("LAND", variant="stop").click(lambda: send_cmd("LAND"), outputs=status)
            with gr.Row():
                gr.Button("⬆️").click(lambda: send_cmd("UP"), outputs=status)
            with gr.Row():
                gr.Button("⬅️").click(lambda: send_cmd("LEFT"), outputs=status)
                gr.Button("⬇️").click(lambda: send_cmd("DOWN"), outputs=status)
                gr.Button("➡️").click(lambda: send_cmd("RIGHT"), outputs=status)

if __name__ == "__main__":
    # Binding to 127.0.0.1 specifically for local access
    print("🚀 Starting Gradio on http://127.0.0.1:7860")
    demo.launch(server_name="127.0.0.1", server_port=7860, share=False)
