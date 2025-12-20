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
from fastapi.middleware.cors import CORSMiddleware
import threading
import time


class OrchestrationService:
    def __init__(self):
        self.unified_manager = UnifiedManager()
        self.running = False
        self.app = self._setup_app()
    
    def _setup_app(self):
        """Setup the FastAPI application"""
        app = FastAPI(title="Matrix Orchestration Service")
        
        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Import and include routers from bot and user managers
        from bot_manager import create_bot_router
        from user_manager import create_user_router
        
        bot_router = create_bot_router()
        user_router = create_user_router()
        
        app.include_router(bot_router, prefix="/bots", tags=["bots"])
        app.include_router(user_router, prefix="/users", tags=["users"])
        
        # Include bot and user management routes
        from bot_manager import create_bot_router
        from user_manager import create_user_router
        
        bot_router = create_bot_router()
        user_router = create_user_router()
        
        app.include_router(bot_router, prefix="", tags=["bots"])
        app.include_router(user_router, prefix="", tags=["users"])
        
        # Add the main unified manager endpoints (including the UI)
        from bot_manager import bot_manager
        from user_manager import user_manager
        from database import get_db, Bot as BotModel, User as UserModel
        from fastapi import Depends
        from fastapi.responses import HTMLResponse
        from unified_manager import unified_manager
        
        # Main UI endpoint with tabs for bots and users
        @app.get("/", response_class=HTMLResponse)
        async def root():
            html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>Matrix Orchestration Dashboard</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; background-color: #f5f5f5; }
        .container { max-width: 1000px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #333; text-align: center; }
        .tabs { margin-bottom: 20px; }
        .tab-button { background-color: #ddd; border: none; padding: 10px 20px; cursor: pointer; margin-right: 5px; border-radius: 5px 5px 0 0; }
        .tab-button.active { background-color: #4CAF50; color: white; }
        .tab-content { display: none; padding: 20px; border: 1px solid #ddd; border-top: none; }
        .tab-content.active { display: block; }
        form { margin: 20px 0; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }
        label { display: block; margin: 10px 0 5px; font-weight: bold; }
        input[type="text"], input[type="password"], input[type="url"], select { width: 100%; padding: 8px; margin-bottom: 10px; border: 1px solid #ccc; border-radius: 4px; }
        button { background-color: #4CAF50; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; margin-right: 10px; }
        button:hover { background-color: #45a049; }
        .stop-btn { background-color: #f44336; }
        .stop-btn:hover { background-color: #da190b; }
        .bot-list, .user-list { margin-top: 30px; }
        .item { padding: 10px; border: 1px solid #ddd; margin: 10px 0; border-radius: 4px; }
        .status-running { background-color: #dff0d8; border-color: #d6e9c6; }
        .status-stopped { background-color: #f2dede; border-color: #ebccd1; }
        .error { color: red; }
        .success { color: green; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Matrix Orchestration Dashboard</h1>
        
        <div class="tabs">
            <button class="tab-button active" onclick="openTab('bots')">Manage Bots</button>
            <button class="tab-button" onclick="openTab('users')">Manage Users</button>
        </div>

        <!-- Bots Tab -->
        <div id="bots" class="tab-content active">
            <form id="createBotForm">
                <h2>Create New Bot</h2>
                <label for="botId">Bot ID:</label>
                <input type="text" id="botId" name="botId" required>
                
                <label for="botHomeserver">Homeserver URL:</label>
                <input type="text" id="botHomeserver" name="botHomeserver" value="http://localhost:8008" required>
                
                <label for="botUserId">User ID:</label>
                <input type="text" id="botUserId" name="botUserId" placeholder="@bot:localhost" required>
                
                <label for="botPassword">Password:</label>
                <input type="password" id="botPassword" name="botPassword" required>
                
                <label for="botFlowiseUrl">Flowise URL:</label>
                <input type="url" id="botFlowiseUrl" name="botFlowiseUrl" required>
                
                <button type="submit">Create Bot</button>
            </form>
            
            <div id="botMessage"></div>
            
            <div class="bot-list">
                <h2>Bot List</h2>
                <div id="botsContainer"></div>
            </div>
        </div>

        <!-- Users Tab -->
        <div id="users" class="tab-content">
            <form id="createUserForm">
                <h2>Create New User</h2>
                <label for="username">Username:</label>
                <input type="text" id="username" name="username" placeholder="@username:localhost" required>
                
                <label for="userPassword">Password:</label>
                <input type="password" id="userPassword" name="userPassword" required>
                
                <label for="userType">User Type:</label>
                <select id="userType" name="userType" required>
                    <option value="user">Regular User</option>
                    <option value="bot">Bot User</option>
                </select>
                
                <button type="submit">Create User</button>
            </form>
            
            <div id="userMessage"></div>
            
            <div class="user-list">
                <h2>User List</h2>
                <div id="usersContainer"></div>
            </div>
        </div>
    </div>

    <script>
        // Tab switching functionality
        function openTab(tabName) {
            // Hide all tab contents
            var tabContents = document.getElementsByClassName("tab-content");
            for (var i = 0; i < tabContents.length; i++) {
                tabContents[i].classList.remove("active");
            }
            
            // Remove active class from all tab buttons
            var tabButtons = document.getElementsByClassName("tab-button");
            for (var i = 0; i < tabButtons.length; i++) {
                tabButtons[i].classList.remove("active");
            }
            
            // Show selected tab content and mark button as active
            document.getElementById(tabName).classList.add("active");
            event.currentTarget.classList.add("active");
            
            // Reload content when switching tabs
            if (tabName === 'bots') {
                loadBots();
            } else if (tabName === 'users') {
                loadUsers();
            }
        }
        
        // Bot management functions
        document.getElementById('createBotForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const formData = {
                bot_id: document.getElementById('botId').value,
                homeserver: document.getElementById('botHomeserver').value,
                user_id: document.getElementById('botUserId').value,
                password: document.getElementById('botPassword').value,
                flowise_url: document.getElementById('botFlowiseUrl').value
            };
            
            try {
                const response = await fetch('/create_bot', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(formData)
                });
                
                if (response.ok) {
                    document.getElementById('botMessage').innerHTML = '<p class="success">Bot created successfully!</p>';
                    document.getElementById('createBotForm').reset();
                    loadBots(); // Refresh bot list
                } else {
                    const error = await response.json();
                    document.getElementById('botMessage').innerHTML = '<p class="error">' + error.detail + '</p>';
                }
            } catch (error) {
                document.getElementById('botMessage').innerHTML = '<p class="error">Error creating bot: ' + error.message + '</p>';
            }
        });
        
        async function loadBots() {
            try {
                const response = await fetch('/bots');
                const bots = await response.json();
                
                const container = document.getElementById('botsContainer');
                container.innerHTML = '';
                
                if (bots.length === 0) {
                    container.innerHTML = '<p>No bots created yet.</p>';
                    return;
                }
                
                bots.forEach(bot => {
                    const botDiv = document.createElement('div');
                    botDiv.className = 'item';
                    if (bot.status === 'running') {
                        botDiv.classList.add('status-running');
                    } else {
                        botDiv.classList.add('status-stopped');
                    }
                    
                    botDiv.innerHTML = `
                        <strong>${bot.bot_id}</strong> 
                        <span>Status: ${bot.status}</span><br>
                        <small>User: ${bot.user_id}</small><br>
                        <small>Flowise: ${bot.flowise_url.substring(0, 50)}...</small><br>
                        <button onclick="startBot('${bot.bot_id}')">Start</button>
                        <button class="stop-btn" onclick="stopBot('${bot.bot_id}')">Stop</button>
                    `;
                    container.appendChild(botDiv);
                });
            } catch (error) {
                document.getElementById('botMessage').innerHTML = '<p class="error">Error loading bots: ' + error.message + '</p>';
            }
        }
        
        async function startBot(botId) {
            try {
                const response = await fetch('/start_bot', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({bot_id: botId})
                });
                
                if (response.ok) {
                    document.getElementById('botMessage').innerHTML = '<p class="success">Bot started successfully!</p>';
                    loadBots(); // Refresh bot list
                } else {
                    const error = await response.json();
                    document.getElementById('botMessage').innerHTML = '<p class="error">' + error.detail + '</p>';
                }
            } catch (error) {
                document.getElementById('botMessage').innerHTML = '<p class="error">Error starting bot: ' + error.message + '</p>';
            }
        }
        
        async function stopBot(botId) {
            try {
                const response = await fetch('/stop_bot', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({bot_id: botId})
                });
                
                if (response.ok) {
                    document.getElementById('botMessage').innerHTML = '<p class="success">Bot stopped successfully!</p>';
                    loadBots(); // Refresh bot list
                } else {
                    const error = await response.json();
                    document.getElementById('botMessage').innerHTML = '<p class="error">' + error.detail + '</p>';
                }
            } catch (error) {
                document.getElementById('botMessage').innerHTML = '<p class="error">Error stopping bot: ' + error.message + '</p>';
            }
        }
        
        // User management functions
        document.getElementById('createUserForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const formData = {
                username: document.getElementById('username').value,
                password: document.getElementById('userPassword').value,
                user_type: document.getElementById('userType').value
            };
            
            try {
                const response = await fetch('/create_user', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(formData)
                });
                
                if (response.ok) {
                    const result = await response.json();
                    document.getElementById('userMessage').innerHTML = '<p class="success">' + result.message + '</p>';
                    document.getElementById('createUserForm').reset();
                    loadUsers(); // Refresh user list
                } else {
                    const error = await response.json();
                    document.getElementById('userMessage').innerHTML = '<p class="error">' + error.detail + '</p>';
                }
            } catch (error) {
                document.getElementById('userMessage').innerHTML = '<p class="error">Error creating user: ' + error.message + '</p>';
            }
        });
        
        async function loadUsers() {
            try {
                const response = await fetch('/users');
                const users = await response.json();
                
                const container = document.getElementById('usersContainer');
                container.innerHTML = '';
                
                if (users.length === 0) {
                    container.innerHTML = '<p>No users created yet.</p>';
                    return;
                }
                
                users.forEach(user => {
                    const userDiv = document.createElement('div');
                    userDiv.className = 'item';
                    
                    userDiv.innerHTML = `
                        <strong>${user.username}</strong> 
                        <span>Type: ${user.user_type}</span><br>
                        <small>Admin: ${user.admin ? 'Yes' : 'No'}</small><br>
                        <small>Created: ${new Date(user.created_at).toLocaleString()}</small>
                    `;
                    container.appendChild(userDiv);
                });
            } catch (error) {
                document.getElementById('userMessage').innerHTML = '<p class="error">Error loading users: ' + error.message + '</p>';
            }
        }
    </script>
</body>
</html>
            """
            return HTMLResponse(content=html_content)
        
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