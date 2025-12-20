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


class UserManager:
    def __init__(self):
        self.users: Dict[str, dict] = {}
        
    def create_user(self, username: str, password: str, admin: bool = False):
        """
        Create a new Matrix user using the register_new_matrix_user command
        """
        try:
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
            if admin:
                input_data += "y\n"  # Yes for admin
            else:
                input_data += "\n"   # Just Enter for non-admin
            
            stdout, stderr = process.communicate(input=input_data)
            
            if process.returncode != 0:
                raise Exception(f"Failed to create user: {stderr}")
            
            # Store user info
            user_info = {
                "username": username,
                "admin": admin,
                "status": "created"
            }
            
            self.users[username] = user_info
            return {"message": f"User {username} created successfully", "user_info": user_info}
            
        except Exception as e:
            raise Exception(f"Error creating user: {str(e)}")

    def create_bot_user(self, bot_username: str, bot_password: str):
        """
        Create a bot user specifically for bots
        """
        return self.create_user(bot_username, bot_password, admin=False)

    def create_regular_user(self, username: str, password: str):
        """
        Create a regular user
        """
        return self.create_user(username, password, admin=False)

    def list_users(self):
        return list(self.users.values())


user_manager = UserManager()

app = FastAPI(title="Matrix User Manager")

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


class CreateRegularUserRequest(BaseModel):
    username: str
    password: str


class CreateBotUserRequest(BaseModel):
    username: str
    password: str


@app.get("/", response_class=HTMLResponse)
async def root():
    html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>Matrix User Manager</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; background-color: #f5f5f5; }
        .container { max-width: 800px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #333; text-align: center; }
        form { margin: 20px 0; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }
        label { display: block; margin: 10px 0 5px; font-weight: bold; }
        input[type="text"], input[type="password"], select { width: 100%; padding: 8px; margin-bottom: 10px; border: 1px solid #ccc; border-radius: 4px; }
        button { background-color: #4CAF50; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; margin-right: 10px; }
        button:hover { background-color: #45a049; }
        .user-list { margin-top: 30px; }
        .user-item { padding: 10px; border: 1px solid #ddd; margin: 10px 0; border-radius: 4px; }
        .status-created { background-color: #dff0d8; border-color: #d6e9c6; }
        .error { color: red; }
        .success { color: green; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Matrix User Manager</h1>
        
        <form id="createUserForm">
            <h2>Create New User</h2>
            <label for="username">Username:</label>
            <input type="text" id="username" name="username" placeholder="@username:localhost" required>
            
            <label for="password">Password:</label>
            <input type="password" id="password" name="password" required>
            
            <label for="userType">User Type:</label>
            <select id="userType" name="userType" required>
                <option value="user">Regular User</option>
                <option value="bot">Bot User</option>
            </select>
            
            <button type="submit">Create User</button>
        </form>
        
        <div id="message"></div>
        
        <div class="user-list">
            <h2>User List</h2>
            <div id="usersContainer"></div>
        </div>
    </div>

    <script>
        // Load users on page load
        loadUsers();
        
        // Create user form handler
        document.getElementById('createUserForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const formData = {
                username: document.getElementById('username').value,
                password: document.getElementById('password').value,
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
                    document.getElementById('message').innerHTML = '<p class="success">' + result.message + '</p>';
                    document.getElementById('createUserForm').reset();
                    loadUsers(); // Refresh user list
                } else {
                    const error = await response.json();
                    document.getElementById('message').innerHTML = '<p class="error">' + error.detail + '</p>';
                }
            } catch (error) {
                document.getElementById('message').innerHTML = '<p class="error">Error creating user: ' + error.message + '</p>';
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
                    userDiv.className = 'user-item status-created';
                    
                    userDiv.innerHTML = `
                        <strong>${user.username}</strong> 
                        <span>Type: ${user.admin ? 'Admin' : 'Regular'}</span><br>
                        <small>Status: ${user.status}</small>
                    `;
                    container.appendChild(userDiv);
                });
            } catch (error) {
                document.getElementById('message').innerHTML = '<p class="error">Error loading users: ' + error.message + '</p>';
            }
        }
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


@app.post("/create_user")
async def create_user(request: CreateUserRequest):
    try:
        if request.user_type == "bot":
            result = user_manager.create_bot_user(request.username, request.password)
        elif request.user_type == "user":
            result = user_manager.create_regular_user(request.username, request.password)
        else:
            raise HTTPException(status_code=400, detail="Invalid user type. Must be 'user' or 'bot'")
        
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating user: {str(e)}")


@app.post("/create_regular_user")
async def create_regular_user(request: CreateRegularUserRequest):
    try:
        result = user_manager.create_regular_user(request.username, request.password)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating regular user: {str(e)}")


@app.post("/create_bot_user")
async def create_bot_user(request: CreateBotUserRequest):
    try:
        result = user_manager.create_bot_user(request.username, request.password)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating bot user: {str(e)}")


@app.get("/users")
async def list_users():
    return user_manager.list_users()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)