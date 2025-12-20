"""
Orchestration module for managing Matrix bots and users with database persistence.
This module provides a unified interface for both bot and user management.
"""

import subprocess
import os
import signal
from typing import Dict, Optional
from sqlalchemy.orm import Session
from unified_manager import UnifiedManager
from database import get_db, engine
import uvicorn
from fastapi import FastAPI
import threading
import time


class OrchestrationService:
    def __init__(self):
        self.unified_manager = UnifiedManager()
        self.running = False
        self.app = self._setup_app()
    
    def _setup_app(self):
        """Setup the FastAPI application"""
        from unified_manager import app
        return app
    
    def start_web_server(self, host: str = "0.0.0.0", port: int = 8001):
        """Start the web server for the orchestration service"""
        print(f"Starting orchestration service on {host}:{port}")
        uvicorn.run(self.app, host=host, port=port)
    
    def start_background_services(self):
        """Start any necessary background services"""
        # In a real implementation, you might want to start monitoring services here
        pass
    
    def health_check(self) -> Dict:
        """Check the health of all services"""
        # Check if database is accessible
        try:
            from database import Base
            db_status = "OK"
        except Exception as e:
            db_status = f"Error: {str(e)}"
        
        # Check if Synapse is running
        try:
            result = subprocess.run(["docker", "ps"], capture_output=True, text=True)
            synapse_running = "synapse" in result.stdout
            synapse_status = "Running" if synapse_running else "Not Running"
        except Exception as e:
            synapse_status = f"Error: {str(e)}"
        
        # Check if Flowise is running
        try:
            result = subprocess.run(["docker", "ps"], capture_output=True, text=True)
            flowise_running = "flowise" in result.stdout
            flowise_status = "Running" if flowise_running else "Not Running"
        except Exception as e:
            flowise_status = f"Error: {str(e)}"
        
        return {
            "database": db_status,
            "synapse": synapse_status,
            "flowise": flowise_status,
            "orchestration_service": "Running" if self.running else "Stopped"
        }

    def migrate_database(self):
        """Run any necessary database migrations"""
        # In this simple case, we just ensure tables exist
        from database import Base
        Base.metadata.create_all(bind=engine)
        print("Database migration completed")


# Global instance for the orchestration service
orchestration_service = OrchestrationService()


def main():
    """Main entry point for the orchestration service"""
    print("Initializing Matrix Orchestration Service...")
    
    # Run database migrations
    orchestration_service.migrate_database()
    
    # Start the web server (this will block)
    orchestration_service.start_web_server(host="0.0.0.0", port=8001)


if __name__ == "__main__":
    main()