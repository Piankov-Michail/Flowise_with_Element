#!/usr/bin/env python3
"""
Script to simulate the Matrix Bot Manager system startup
This script demonstrates how the system would work with Docker Compose
"""

import os
import sys
import subprocess
import threading
import time
import signal
import requests
from pathlib import Path


def check_port(port):
    """Check if a port is available"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) != 0


def start_bot_manager():
    """Start the bot manager web service"""
    print("Starting Bot Manager on http://localhost:8001")
    
    # Change to the project directory
    os.chdir('/workspace')
    
    # Start the FastAPI app
    cmd = ["python3", "-m", "uvicorn", "bot_manager:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
    
    try:
        process = subprocess.Popen(cmd)
        return process
    except Exception as e:
        print(f"Error starting bot manager: {e}")
        return None


def simulate_services():
    """Simulate the other services that would run in Docker containers"""
    print("Simulating Synapse server on http://localhost:8008")
    print("Simulating Flowise on http://localhost:3000")
    print("Both services would be started in Docker containers via docker-compose")


def main():
    print("Matrix Bot Manager System Startup Simulation")
    print("=" * 50)
    
    # Check if required ports are available
    if not check_port(8001):
        print("Port 8001 is already in use. Please stop any existing bot manager processes.")
        return
    
    print("Starting services...")
    
    # Simulate external services
    simulate_services()
    
    # Start the bot manager
    bm_process = start_bot_manager()
    
    if bm_process is None:
        print("Failed to start bot manager")
        return
    
    print("\nSystem started successfully!")
    print("- Bot Manager UI: http://localhost:8001")
    print("- Synapse Matrix server: http://localhost:8008 (simulated)")
    print("- Flowise: http://localhost:3000 (simulated)")
    print("\nTo stop the system, press Ctrl+C")
    
    try:
        while True:
            time.sleep(1)
            # Check if the bot manager process is still running
            if bm_process.poll() is not None:
                print("Bot manager process terminated unexpectedly")
                break
    except KeyboardInterrupt:
        print("\nShutting down system...")
        bm_process.terminate()
        try:
            bm_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bm_process.kill()
        print("System stopped.")


if __name__ == "__main__":
    main()