#!/usr/bin/env bash
# setup_local_venv.sh — Setup a fresh venv and run the system locally.

echo "🧹 Cleaning up old environment..."
rm -rf venv_drone

echo "🐍 Creating virtual environment (venv_drone)..."
python3 -m venv venv_drone

echo "📦 Installing dependencies..."
source venv_drone/bin/activate
pip install --upgrade pip
# Using simple requirements
pip install gradio fastapi uvicorn numpy requests opencv-python-headless pydantic

echo "🚀 Starting the system in the background..."

# 1. Start Mock Hardware (background)
python3 drone_mock.py > mock.log 2>&1 &
MOCK_PID=$!

# 2. Start API (background)
python3 drone_api.py > api.log 2>&1 &
API_PID=$!

echo "✨ System is ready. Starting the UI..."
echo "If http://localhost:7860 fails, try http://127.0.0.1:7860"
echo "Press Ctrl+C to stop everything."

# 3. Start UI (foreground)
python3 simple_ui.py

# Cleanup on exit
kill $MOCK_PID $API_PID
echo "👋 Stopped."
