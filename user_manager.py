"""
Unified User Management Module
Manages Matrix users with database persistence
"""
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
from database import get_db, User as UserModel
import hashlib


class UserManager:
    def __init__(self):
        pass
        
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

    def create_bot_user(self, db: Session, bot_username: str, bot_password: str):
        """
        Create a bot user specifically for bots
        """
        return self.create_user(db, bot_username, bot_password, user_type="bot")

    def create_regular_user(self, db: Session, username: str, password: str):
        """
        Create a regular user
        """
        return self.create_user(db, username, password, user_type="user")

    def list_users(self, db: Session):
        users = db.query(UserModel).all()
        return [{"id": user.id, "username": user.username, "user_type": user.user_type, 
                 "admin": user.admin, "created_at": user.created_at} for user in users]


user_manager = UserManager()


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


def create_user_router():
    """Create a router for user management endpoints"""
    from fastapi import APIRouter
    
    router = APIRouter()
    
    @router.post("/create_user")
    async def create_user_endpoint(request: CreateUserRequest, db: Session = Depends(get_db)):
        try:
            if request.user_type == "bot":
                result = user_manager.create_bot_user(db, request.username, request.password)
            elif request.user_type == "user":
                result = user_manager.create_regular_user(db, request.username, request.password)
            else:
                raise HTTPException(status_code=400, detail="Invalid user type. Must be 'user' or 'bot'")
            
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error creating user: {str(e)}")

    @router.post("/create_regular_user")
    async def create_regular_user_endpoint(request: CreateRegularUserRequest, db: Session = Depends(get_db)):
        try:
            result = user_manager.create_regular_user(db, request.username, request.password)
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error creating regular user: {str(e)}")

    @router.post("/create_bot_user")
    async def create_bot_user_endpoint(request: CreateBotUserRequest, db: Session = Depends(get_db)):
        try:
            result = user_manager.create_bot_user(db, request.username, request.password)
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error creating bot user: {str(e)}")

    @router.get("/users")
    async def list_users_endpoint(db: Session = Depends(get_db)):
        return user_manager.list_users(db)
    
    return router