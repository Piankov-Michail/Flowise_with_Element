import asyncio
import json
import os
import subprocess
import signal
from typing import Dict, Optional
from fastapi import FastAPI, HTTPException, Request, Depends
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import psutil
from sqlalchemy.orm import Session
from database import get_db, User as UserModel, Bot as BotModel
import hashlib

class UnifiedManager:
    def __init__(self):
        self.processes: Dict[str, subprocess.Popen] = {}
        
    def create_user(self, db: Session, username: str, password: str, user_type: str = "user"):
        """
        Create a new Matrix user using the register_new_matrix_user command
        """
        try:
            # Hash the password in a real application
            # hashed_password = hashlib.sha256(password.encode()).hexdigest()
            
            # Prepare the docker command to create the user
            cmd = [
                "docker", "exec", "-i", "synapse", 
                "register_new_matrix_user", 
                "http://localhost:8008", 
                "-c", "/data/homeserver.yaml"
            ]
            
            # Execute the command with input
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Provide inputs: username, password, password confirmation, admin choice
            input_data = f"{username}\n{password}\n{password}\n"
            # For now, we're not making anyone admin through this command
            input_data += "\n"   # Just Enter for non-admin
            
            stdout, stderr = process.communicate(input=input_data)
            
            if process.returncode != 0:
                raise Exception(f"Failed to create user: {stderr}")
            
            # Store user info in database
            db_user = UserModel(
                username=username,
                password=password,  # In real app, store hashed password
                user_type=user_type,
                admin=False  # We're not creating admins through this method
            )
            db.add(db_user)
            db.commit()
            db.refresh(db_user)
            
            return {"message": f"User {username} created successfully", "user_info": {
                "id": db_user.id,
                "username": db_user.username,
                "user_type": db_user.user_type,
                "admin": db_user.admin
            }}
            
        except Exception as e:
            raise Exception(f"Error creating user: {str(e)}")

    def create_bot(self, db: Session, bot_id: str, homeserver: str, user_id: str, password: str, flowise_url: str):
        if db.query(BotModel).filter(BotModel.bot_id == bot_id).first():
            raise ValueError(f"Bot with id {bot_id} already exists")

        bot_config = BotModel(
            bot_id=bot_id,
            homeserver=homeserver,
            user_id=user_id,
            password=password,
            flowise_url=flowise_url,
            status="created"
        )
        
        db.add(bot_config)
        db.commit()
        db.refresh(bot_config)
        
        return {"message": f"Bot {bot_id} created successfully"}

    def start_bot(self, db: Session, bot_id: str):
        bot_record = db.query(BotModel).filter(BotModel.bot_id == bot_id).first()
        if not bot_record:
            raise ValueError(f"Bot with id {bot_id} does not exist")
            
        if bot_id in self.processes:
            proc = self.processes[bot_id]
            if proc.poll() is None:
                return
                
        bot_script = f"""
            import asyncio
            from matrix_bot import FlowiseBot

            async def main():
                bot = FlowiseBot(
                    homeserver="{bot_record.homeserver}",
                    user_id="{bot_record.user_id}", 
                    password="{bot_record.password}",
                    flowise_url="{bot_record.flowise_url}"
                )
                await bot.run()

            if __name__ == "__main__":
                asyncio.run(main())
            """

        bot_filename = f"/tmp/bot_{bot_id}.py"
        with open(bot_filename, "w") as f:
            f.write(bot_script)

        process = subprocess.Popen(['python3', bot_filename])
        self.processes[bot_id] = process
        
        # Update status in database
        bot_record.status = "running"
        db.commit()

    def stop_bot(self, db: Session, bot_id: str):
        if bot_id not in self.processes:
            return
            
        proc = self.processes[bot_id]
        if proc.poll() is None:
            parent = psutil.Process(proc.pid)
            children = parent.children(recursive=True)
            for child in children:
                child.terminate()
            parent.terminate()

            try:
                parent.wait(timeout=5)
            except psutil.TimeoutExpired:
                for child in children:
                    child.kill()
                parent.kill()
                
        del self.processes[bot_id]
        
        # Update status in database
        bot_record = db.query(BotModel).filter(BotModel.bot_id == bot_id).first()
        if bot_record:
            bot_record.status = "stopped"
            db.commit()

    def list_bots(self, db: Session):
        # Update statuses based on process state
        bots = db.query(BotModel).all()
        for bot in bots:
            if bot.bot_id in self.processes:
                proc = self.processes[bot.bot_id]
                if proc.poll() is not None:
                    bot.status = "stopped"
                    db.commit()
                    
        return [{"id": bot.id, "bot_id": bot.bot_id, "homeserver": bot.homeserver, 
                 "user_id": bot.user_id, "flowise_url": bot.flowise_url, "status": bot.status,
                 "created_at": bot.created_at} for bot in bots]

    def list_users(self, db: Session):
        users = db.query(UserModel).all()
        return [{"id": user.id, "username": user.username, "user_type": user.user_type, 
                 "admin": user.admin, "created_at": user.created_at} for user in users]


unified_manager = UnifiedManager()

app = FastAPI(title="Unified Matrix Manager")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateUserRequest(BaseModel):
    username: str
    password: str
    user_type: str  # 'user' or 'bot'


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
    html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>Unified Matrix Manager</title>
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
        <h1>Unified Matrix Manager</h1>
        
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


@app.post("/create_user")
async def create_user(request: CreateUserRequest, db: Session = Depends(get_db)):
    try:
        result = unified_manager.create_user(
            db,
            request.username,
            request.password,
            request.user_type
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating user: {str(e)}")


@app.post("/create_bot")
async def create_bot(request: CreateBotRequest, db: Session = Depends(get_db)):
    try:
        result = unified_manager.create_bot(
            db,
            request.bot_id,
            request.homeserver,
            request.user_id,
            request.password,
            request.flowise_url
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating bot: {str(e)}")


@app.post("/start_bot")
async def start_bot(request: StartBotRequest, db: Session = Depends(get_db)):
    try:
        unified_manager.start_bot(db, request.bot_id)
        return {"message": f"Bot {request.bot_id} started successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting bot: {str(e)}")


@app.post("/stop_bot")
async def stop_bot(request: StopBotRequest, db: Session = Depends(get_db)):
    try:
        unified_manager.stop_bot(db, request.bot_id)
        return {"message": f"Bot {request.bot_id} stopped successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error stopping bot: {str(e)}")


@app.get("/bots")
async def list_bots(db: Session = Depends(get_db)):
    return unified_manager.list_bots(db)


@app.get("/users")
async def list_users(db: Session = Depends(get_db)):
    return unified_manager.list_users(db)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)