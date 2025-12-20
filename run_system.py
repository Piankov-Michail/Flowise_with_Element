#!/usr/bin/env python3
"""
Script to run the Matrix Bot Manager system
"""

import subprocess
import sys
import os
import time
import signal
from typing import List

def check_docker():
    """Check if Docker is available"""
    try:
        result = subprocess.run(['docker', '--version'], capture_output=True, text=True)
        if result.returncode != 0:
            print("❌ Docker is not installed or not accessible")
            return False
        print("✅ Docker is available")
        return True
    except FileNotFoundError:
        print("❌ Docker is not installed or not in PATH")
        return False

def check_docker_compose():
    """Check if Docker Compose is available"""
    try:
        result = subprocess.run(['docker-compose', '--version'], capture_output=True, text=True)
        if result.returncode != 0:
            print("❌ Docker Compose is not available")
            return False
        print("✅ Docker Compose is available")
        return True
    except FileNotFoundError:
        print("❌ Docker Compose is not installed or not in PATH")
        return False

def start_system():
    """Start the entire system using docker-compose"""
    print("🚀 Starting Matrix Bot Manager system...")
    
    try:
        # Start all services in detached mode
        process = subprocess.run([
            'docker-compose', 'up', '-d'
        ], check=True, capture_output=True, text=True)
        
        print("✅ System started successfully!")
        print("📊 Services status:")
        subprocess.run(['docker-compose', 'ps'])
        
        print("\n📋 Access the services at:")
        print("   • Synapse (Matrix server): http://localhost:8008")
        print("   • Flowise (AI chatflow): http://localhost:3000 (admin/password)")
        print("   • Bot Manager: http://localhost:8001")
        print("\n💡 Follow the instructions in README.md to set up your bots!")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Error starting system: {e}")
        print(f"Output: {e.output if hasattr(e, 'output') else 'N/A'}")
        return False
    
    return True

def stop_system():
    """Stop the entire system"""
    print("🛑 Stopping Matrix Bot Manager system...")
    
    try:
        subprocess.run(['docker-compose', 'down'], check=True)
        print("✅ System stopped successfully!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error stopping system: {e}")
        return False
    
    return True

def main():
    if len(sys.argv) < 2:
        print("Usage: python run_system.py [start|stop|status]")
        print("  start  - Start the Matrix Bot Manager system")
        print("  stop   - Stop the Matrix Bot Manager system")
        print("  status - Show status of all services")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == 'start':
        if not check_docker() or not check_docker_compose():
            print("Please install Docker and Docker Compose before running this system.")
            sys.exit(1)
        
        start_system()
        
    elif command == 'stop':
        stop_system()
        
    elif command == 'status':
        try:
            print("📊 Services status:")
            subprocess.run(['docker-compose', 'ps'])
        except FileNotFoundError:
            print("❌ Docker Compose is not available")
            
    else:
        print(f"Unknown command: {command}")
        print("Usage: python run_system.py [start|stop|status]")
        sys.exit(1)

if __name__ == "__main__":
    main()