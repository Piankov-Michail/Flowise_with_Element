# Matrix Bot Manager System - Complete Guide

## Overview

This project implements a complete system with a Matrix server (Synapse), Flowise AI integration, and a bot manager that allows students to create and manage AI-powered Matrix bots.

The system consists of several components:
- Matrix Synapse server (handles Matrix protocol)
- Element web client (connects to Synapse server)
- Flowise (creates chatflows with LLMs)
- Bot Manager (web interface to create and manage bots)
- Individual bot instances (each bot runs separately)

## Architecture

```
Server
├── Synapse Matrix Server (Docker)
├── Flowise AI Service (Docker)
├── Bot Manager (Docker with web interface)
└── Individual Bots (managed by bot manager)
```

## Complete Student Workflow

### Part 1: System Setup

#### Option A: With Docker (Full Setup)
1. Make sure you have Docker and Docker Compose installed
2. Clone this repository
3. If you encounter uvicorn version issues, update requirements.txt:
   ```bash
   sed -i 's/uvicorn==0.35.2/uvicorn==0.36.0/g' requirements.txt
   ```
4. Start the system: `docker-compose up -d`
5. Wait for all services to be ready: `docker-compose ps`

#### Option B: Without Docker (Bot Manager Only)
1. Install dependencies: `pip install -r requirements.txt`
2. Run the system simulation: `python3 start_system.py`

### Part 2: Flowise Setup

1. Go to `http://localhost:3000` in your browser (if using Docker)
2. Log in with username: `admin`, password: `password`
3. Create a new chatflow with your preferred LLM (you can import the example from `Example_Chatflow.json`)
4. Get the API endpoint URL for your chatflow (typically looks like `http://localhost:3000/api/v1/prediction/[ID]`)

### Part 3: Matrix Setup

1. Open Element web client at `https://app.element.io/`
2. Choose "Edit" for the homeserver
3. Enter your homeserver URL: `http://localhost:8008` (if using Docker setup)
4. Register a new account for yourself
5. Create a second account that will be used for your bot (remember the username and password)

### Part 4: Bot Manager Usage

1. Go to `http://localhost:8001` in your browser
2. Create a new bot with the following information:
   - Bot ID: a unique identifier for your bot
   - Homeserver URL: `http://localhost:8008` (if using Docker setup)
   - User ID: the bot's Matrix user ID (e.g., `@mybot:localhost`)
   - Password: the bot's password
   - Flowise URL: the API endpoint URL from step 2 of Flowise Setup

### Part 5: Running Your Bot

1. After creating the bot, click "Start" to begin running it
2. The bot will connect to Matrix and start responding to messages
3. You can stop the bot anytime using the "Stop" button
4. Monitor the bot's status in the web interface

## Understanding the Code Components

### bot_manager.py
The main web application that provides:
- A FastAPI-based web interface
- Bot creation and management functionality
- Process management for individual bot instances
- Real-time status monitoring

### matrix-bot.py
The core bot implementation that:
- Connects to the Matrix server
- Handles incoming messages
- Communicates with Flowise API for AI responses
- Sends responses back to Matrix

### Docker Configuration
- `docker-compose.yml`: Orchestrates all services
- `Dockerfile`: Defines the bot manager container
- Network configuration for inter-service communication
- `homeserver.yaml`: Synapse Matrix server configuration file
- `log_config.yaml`: Logging configuration for Synapse

## Troubleshooting Common Issues

### Uvicorn Version Error
If you see an error about uvicorn==0.35.2 not being found:
- Update requirements.txt to use uvicorn==0.36.0
- Or install the latest version: `pip install uvicorn`

### Docker Compose Not Found
- Install Docker and Docker Compose
- On Ubuntu/Debian: `sudo apt install docker-compose-plugin`
- On other systems: Follow Docker's official installation guide

### Port Already in Use
- Check if services are already running: `docker ps` or `ps aux | grep python`
- Stop existing services before starting new ones
- Modify ports in docker-compose.yml if needed

### Bot Won't Connect to Matrix
- Verify Matrix credentials are correct
- Check that Synapse server is running and accessible
- Ensure the homeserver URL is properly formatted

### Flowise Connection Issues
- Confirm the Flowise URL is correct
- Test the API endpoint independently
- Check that Flowise service is running

## Extending the System

### Adding New Bot Features
You can enhance the bot functionality by modifying `matrix-bot.py`:
- Add custom commands
- Implement different response strategies
- Integrate with additional APIs

### Scaling the Bot Manager
For production use, consider:
- Adding authentication to the bot manager UI
- Implementing persistent storage for bot configurations
- Adding logging and monitoring features

## Security Considerations

### For Production Deployment
- Use strong passwords for all services
- Configure HTTPS for all web interfaces
- Implement authentication for the bot manager API
- Regularly update dependencies
- Use environment variables for sensitive data

## Resources

- [Synapse Documentation](https://github.com/matrix-org/synapse)
- [Flowise Documentation](https://github.com/FlowiseAI/Flowise)
- [Matrix Protocol](https://matrix.org/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Docker Documentation](https://docs.docker.com/)

## Example Usage Scenario

1. Student creates a chatflow in Flowise that answers questions about programming
2. Student sets up Matrix accounts for themselves and their bot
3. Student configures the bot in the Bot Manager with the Flowise API URL
4. Student starts the bot and tests it by sending messages in Matrix
5. The bot receives messages, sends them to Flowise for processing, and responds appropriately