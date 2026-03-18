# Use a lightweight Python base
FROM python:3.9-slim

# Install system dependencies for OpenCV and networking
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose ports: 7860 (Gradio UI), 8000 (FastAPI), 8888 (Mock UDP Drone)
EXPOSE 7860 8000 8888/udp

# Command to run the entire system
CMD ["python", "run_all.py"]
