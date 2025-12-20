# Matrix Orchestration Service Architecture

## Overview
This system provides a unified orchestration service for managing Matrix bots and users with database persistence. The architecture consists of containerized services that work together to provide a complete Matrix bot management solution.

## Components

### 1. Database Layer
- **PostgreSQL**: Containerized database for storing bot and user information
- **SQLAlchemy ORM**: Python ORM for database interactions
- **Models**: 
  - `User` model: Stores user information (username, password, type, admin status)
  - `Bot` model: Stores bot configuration and status information

### 2. Manager Layer
- **Bot Manager** (`bot_manager.py`): Handles bot lifecycle management (create, start, stop, list)
- **User Manager** (`user_manager.py`): Handles Matrix user creation and management
- **Unified Manager** (`unified_manager.py`): Core business logic for both bots and users

### 3. Orchestration Service (`orchestration.py`)
- Main entry point for the application
- Integrates both bot and user managers
- Provides a unified API and web interface
- Handles database connections and migrations

### 4. Web Interface
- Single-page application with tabbed interface
- **Bots Tab**: Create, start, stop, and monitor bots
- **Users Tab**: Create and manage Matrix users
- Real-time status updates

## Containerized Services

### Docker Compose Configuration
The system runs as multiple containerized services:

- **postgres**: PostgreSQL database container
- **synapse**: Matrix homeserver
- **flowise**: AI flow management service
- **bot-manager**: Main orchestration service (this application)

### Database Schema
```sql
-- Users table
id, username, password, user_type, admin, created_at, updated_at

-- Bots table  
id, bot_id, homeserver, user_id, password, flowise_url, status, created_at, updated_at
```

## API Endpoints

### Bot Management
- `POST /create_bot` - Create a new bot
- `POST /start_bot` - Start a bot process
- `POST /stop_bot` - Stop a bot process
- `GET /bots` - List all bots with status

### User Management
- `POST /create_user` - Create a new user
- `GET /users` - List all users

### Web Interface
- `GET /` - Main dashboard with bot and user management tabs

## Features

1. **Database Persistence**: All bot and user information stored in PostgreSQL
2. **Process Management**: Start/stop bot processes with proper cleanup
3. **Web Interface**: User-friendly dashboard with tabbed interface
4. **Containerized Deployment**: All services run in Docker containers
5. **Matrix Integration**: Direct integration with Synapse homeserver
6. **Flowise Integration**: Connects bots to Flowise AI services

## Running the System

```bash
# Start all services
docker-compose up -d

# The orchestration dashboard will be available at http://localhost:8001
```

The system provides a complete solution for managing Matrix bots and users with persistent storage and a user-friendly interface.