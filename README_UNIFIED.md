# Unified Matrix Management System

This project provides a unified orchestration system for managing Matrix bots and users with persistent database storage.

## Architecture

The system includes:

1. **Database Layer**: PostgreSQL database (with SQLite fallback) for storing user and bot information
2. **Unified Manager**: Single manager class that handles both bot and user operations
3. **Orchestration Service**: Main service that coordinates all components
4. **Web Interface**: Single interface with two tabs for managing bots and users

## Components

### Database Models
- `User` model: Stores user information (username, password, type, admin status)
- `Bot` model: Stores bot configuration (ID, homeserver, credentials, status)

### Services
- `UnifiedManager`: Combines functionality from the old bot_manager and user_manager
- `OrchestrationService`: Main service class that manages the entire system
- Web interface with tabs for bot and user management

## Features

- **Unified Management**: Single interface for both bots and users
- **Database Persistence**: All data stored in PostgreSQL (or SQLite)
- **Bot Lifecycle Management**: Create, start, stop bots
- **User Management**: Create Matrix users via API
- **Web Interface**: Two-tab interface for easy management

## API Endpoints

### Bot Management
- `POST /create_bot` - Create a new bot
- `POST /start_bot` - Start a bot
- `POST /stop_bot` - Stop a bot
- `GET /bots` - List all bots

### User Management
- `POST /create_user` - Create a new user
- `GET /users` - List all users

## Setup

The system is designed to run with Docker Compose:

```bash
docker-compose up -d --build
```

The web interface will be available at `http://localhost:8001`

## Database Schema

The system uses two main tables:

**users table**:
- id: Primary key
- username: Unique username
- password: Password (should be hashed in production)
- user_type: 'user' or 'bot'
- admin: Boolean admin status
- created_at: Creation timestamp
- updated_at: Update timestamp

**bots table**:
- id: Primary key
- bot_id: Unique bot identifier
- homeserver: Matrix homeserver URL
- user_id: Bot's user ID
- password: Bot's password
- flowise_url: Flowise API URL
- status: Current status ('created', 'running', 'stopped')
- created_at: Creation timestamp
- updated_at: Update timestamp

## Changes from Original Implementation

1. **Unified Manager**: Combined bot_manager.py and user_manager.py into unified_manager.py
2. **Database Storage**: Added persistent storage using SQLAlchemy
3. **Containerized Database**: Added PostgreSQL container to docker-compose.yml
4. **Single Interface**: Combined both management interfaces into one with tabs
5. **Orchestration Layer**: Added orchestration.py as the main entry point