from fastapi import FastAPI, HTTPException
import socket
import uvicorn
from pydantic import BaseModel

app = FastAPI(title="X69 Drone API")

# UDP Configuration
UDP_IP = "127.0.0.1"
UDP_PORT = 8888

# Create a UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

class Command(BaseModel):
    action: str

@app.post("/command")
async def execute_command(cmd: Command):
    """Executes a drone command via UDP."""
    msg = f"CMD:{cmd.action}"
    try:
        sock.sendto(msg.encode(), (UDP_IP, UDP_PORT))
        return {"status": "success", "command": cmd.action}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status")
async def get_status():
    """Mock status endpoint."""
    return {"connection": "online", "battery": "85%", "signal": "Excellent"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
