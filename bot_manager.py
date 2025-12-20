import asyncio
import json
import os
import subprocess
import signal
from typing import Dict, Optional
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import psutil


class BotManager:
    """Manages bot processes"""
    
    def __init__(self):
        self.bots: Dict[str, dict] = {}  # bot_id -> bot_info
        self.processes: Dict[str, subprocess.Popen] = {}  # bot_id -> process
        
    def create_bot(self, bot_id: str, homeserver: str, user_id: str, password: str, flowise_url: str):
        """Create a new bot instance"""
        if bot_id in self.bots:
            raise ValueError(f"Bot with id {bot_id} already exists")
            
        # Create bot configuration
        bot_config = {
            "bot_id": bot_id,
            "homeserver": homeserver,
            "user_id": user_id,
            "password": password,
            "flowise_url": flowise_url,
            "status": "created"
        }
        
        self.bots[bot_id] = bot_config
        
    def start_bot(self, bot_id: str):
        """Start a bot process"""
        if bot_id not in self.bots:
            raise ValueError(f"Bot with id {bot_id} does not exist")
            
        if bot_id in self.processes:
            # Check if process is still running
            proc = self.processes[bot_id]
            if proc.poll() is None:  # Process is still running
                return
                
        # Create bot-specific script
        bot_script = f"""
import asyncio
from matrix_bot import FlowiseBot

async def main():
    bot = FlowiseBot(
        homeserver="{self.bots[bot_id]['homeserver']}",
        user_id="{self.bots[bot_id]['user_id']}", 
        password="{self.bots[bot_id]['password']}",
        flowise_url="{self.bots[bot_id]['flowise_url']}"
    )
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
"""
        
        # Write bot script to temporary file
        bot_filename = f"/tmp/bot_{bot_id}.py"
        with open(bot_filename, "w") as f:
            f.write(bot_script)
            
        # Start the bot as a subprocess
        process = subprocess.Popen(['python3', bot_filename])
        self.processes[bot_id] = process
        self.bots[bot_id]["status"] = "running"
        
    def stop_bot(self, bot_id: str):
        """Stop a bot process"""
        if bot_id not in self.processes:
            return
            
        proc = self.processes[bot_id]
        if proc.poll() is None:  # Process is still running
            # Terminate the process and its children
            parent = psutil.Process(proc.pid)
            children = parent.children(recursive=True)
            for child in children:
                child.terminate()
            parent.terminate()
            
            # Wait for graceful termination
            try:
                parent.wait(timeout=5)
            except psutil.TimeoutExpired:
                # Force kill if needed
                for child in children:
                    child.kill()
                parent.kill()
                
        del self.processes[bot_id]
        if bot_id in self.bots:
            self.bots[bot_id]["status"] = "stopped"
            
    def list_bots(self):
        """List all bots and their status"""
        # Update status based on process state
        for bot_id in self.bots:
            if bot_id in self.processes:
                proc = self.processes[bot_id]
                if proc.poll() is not None:  # Process has ended
                    self.bots[bot_id]["status"] = "stopped"
                    
        return list(self.bots.values())


# Initialize bot manager
bot_manager = BotManager()

# Create FastAPI app
app = FastAPI(title="Matrix Bot Manager")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models
class CreateBotRequest(BaseModel):
    bot_id: str
    homeserver: str
    user_id: str
    password: str
    flowise_url: str

class StartBotRequest(BaseModel):
    bot_id: str

class StopBotRequest(BaseModel):
    bot_id: str


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main page"""
    html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>Matrix Bot Manager</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; background-color: #f5f5f5; }
        .container { max-width: 800px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #333; text-align: center; }
        form { margin: 20px 0; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }
        label { display: block; margin: 10px 0 5px; font-weight: bold; }
        input[type="text"], input[type="password"], input[type="url"] { width: 100%; padding: 8px; margin-bottom: 10px; border: 1px solid #ccc; border-radius: 4px; }
        button { background-color: #4CAF50; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; margin-right: 10px; }
        button:hover { background-color: #45a049; }
        .stop-btn { background-color: #f44336; }
        .stop-btn:hover { background-color: #da190b; }
        .bot-list { margin-top: 30px; }
        .bot-item { padding: 10px; border: 1px solid #ddd; margin: 10px 0; border-radius: 4px; }
        .status-running { background-color: #dff0d8; border-color: #d6e9c6; }
        .status-stopped { background-color: #f2dede; border-color: #ebccd1; }
        .error { color: red; }
        .success { color: green; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Matrix Bot Manager</h1>
        
        <form id="createBotForm">
            <h2>Create New Bot</h2>
            <label for="botId">Bot ID:</label>
            <input type="text" id="botId" name="botId" required>
            
            <label for="homeserver">Homeserver URL:</label>
            <input type="text" id="homeserver" name="homeserver" value="http://localhost:8008" required>
            
            <label for="userId">User ID:</label>
            <input type="text" id="userId" name="userId" placeholder="@bot:localhost" required>
            
            <label for="password">Password:</label>
            <input type="password" id="password" name="password" required>
            
            <label for="flowiseUrl">Flowise URL:</label>
            <input type="url" id="flowiseUrl" name="flowiseUrl" required>
            
            <button type="submit">Create Bot</button>
        </form>
        
        <div id="message"></div>
        
        <div class="bot-list">
            <h2>Bot List</h2>
            <div id="botsContainer"></div>
        </div>
    </div>

    <script>
        // Load bots on page load
        loadBots();
        
        // Create bot form handler
        document.getElementById('createBotForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const formData = {
                bot_id: document.getElementById('botId').value,
                homeserver: document.getElementById('homeserver').value,
                user_id: document.getElementById('userId').value,
                password: document.getElementById('password').value,
                flowise_url: document.getElementById('flowiseUrl').value
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
                    document.getElementById('message').innerHTML = '<p class="success">Bot created successfully!</p>';
                    document.getElementById('createBotForm').reset();
                    loadBots(); // Refresh bot list
                } else {
                    const error = await response.json();
                    document.getElementById('message').innerHTML = '<p class="error">' + error.detail + '</p>';
                }
            } catch (error) {
                document.getElementById('message').innerHTML = '<p class="error">Error creating bot: ' + error.message + '</p>';
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
                    botDiv.className = 'bot-item';
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
                document.getElementById('message').innerHTML = '<p class="error">Error loading bots: ' + error.message + '</p>';
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
                    document.getElementById('message').innerHTML = '<p class="success">Bot started successfully!</p>';
                    loadBots(); // Refresh bot list
                } else {
                    const error = await response.json();
                    document.getElementById('message').innerHTML = '<p class="error">' + error.detail + '</p>';
                }
            } catch (error) {
                document.getElementById('message').innerHTML = '<p class="error">Error starting bot: ' + error.message + '</p>';
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
                    document.getElementById('message').innerHTML = '<p class="success">Bot stopped successfully!</p>';
                    loadBots(); // Refresh bot list
                } else {
                    const error = await response.json();
                    document.getElementById('message').innerHTML = '<p class="error">' + error.detail + '</p>';
                }
            } catch (error) {
                document.getElementById('message').innerHTML = '<p class="error">Error stopping bot: ' + error.message + '</p>';
            }
        }
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


@app.post("/create_bot")
async def create_bot(request: CreateBotRequest):
    """Create a new bot"""
    try:
        bot_manager.create_bot(
            request.bot_id,
            request.homeserver,
            request.user_id,
            request.password,
            request.flowise_url
        )
        return {"message": f"Bot {request.bot_id} created successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating bot: {str(e)}")


@app.post("/start_bot")
async def start_bot(request: StartBotRequest):
    """Start a bot"""
    try:
        bot_manager.start_bot(request.bot_id)
        return {"message": f"Bot {request.bot_id} started successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting bot: {str(e)}")


@app.post("/stop_bot")
async def stop_bot(request: StopBotRequest):
    """Stop a bot"""
    try:
        bot_manager.stop_bot(request.bot_id)
        return {"message": f"Bot {request.bot_id} stopped successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error stopping bot: {str(e)}")


@app.get("/bots")
async def list_bots():
    """List all bots"""
    return bot_manager.list_bots()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)