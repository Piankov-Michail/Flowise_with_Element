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


# API Endpoints
app = FastAPI(title="Unified Matrix Manager API")

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