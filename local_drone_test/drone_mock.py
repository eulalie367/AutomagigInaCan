import socket
import json

# Standard IP and Port for many small WiFi drones
# X69 likely uses something similar.
UDP_IP = "127.0.0.1" # Using localhost for mock testing
UDP_PORT = 8888

def start_mock_drone():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    
    print(f"🚀 Mock X69 Drone listening on {UDP_IP}:{UDP_PORT}")
    print("Waiting for commands...")

    try:
        while True:
            data, addr = sock.recvfrom(1024)
            try:
                message = data.decode()
                print(f"📥 Received from {addr}: {message}")
            except UnicodeDecodeError:
                print(f"📥 Received raw bytes from {addr}: {data.hex()}")
    except KeyboardInterrupt:
        print("\n🛑 Mock Drone shutting down.")
    finally:
        sock.close()

if __name__ == "__main__":
    start_mock_drone()
