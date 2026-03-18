#!/usr/bin/env bash
# setup_drone_env.sh — Robust local setup for X69 Drone System

VENV_NAME="venv_x69"
PORT_UI=7860
PORT_API=8000

echo "🚀 Setting up Project Acropolis: X69 Drone Environment..."

# 1. Check for Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found. Please install it."
    exit 1
fi

# 2. Create Venv
if [ ! -d "$VENV_NAME" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv "$VENV_NAME"
fi

source "$VENV_NAME/bin/activate"

# 3. Install Dependencies
echo "📥 Installing required packages..."
pip install --upgrade pip
pip install gradio fastapi uvicorn numpy requests opencv-python-headless pydantic

# 4. Cleanup old processes
echo "🧹 Checking for hanging processes on ports $PORT_UI and $PORT_API..."
fuser -k $PORT_UI/tcp 2>/dev/null || true
fuser -k $PORT_API/tcp 2>/dev/null || true

# 5. Launch System
echo "🛰️  Launching X69 Ecosystem (Local Mode)..."

# Ensure we are using 127.0.0.1 for maximum compatibility
export DRONE_TARGET_IP="127.0.0.1"

# Start Mock Drone
python3 x69_drone_app/drone_mock.py > drone_mock.log 2>&1 &
MOCK_PID=$!

# Start API
python3 x69_drone_app/drone_api.py > drone_api.log 2>&1 &
API_PID=$!

sleep 2

echo "✨ System is LIVE."
echo "   UI:  http://127.0.0.1:$PORT_UI"
echo "   API: http://127.0.0.1:$PORT_API"
echo ""
echo "Press Ctrl+C to shutdown."

# Start UI in foreground
python3 x69_drone_app/drone_ui.py

# Shutdown
kill $MOCK_PID $API_PID
echo "👋 Shutdown complete."
