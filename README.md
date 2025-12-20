# Matrix Bot Manager System

This project implements a complete system with a Matrix server (Synapse), Flowise AI integration, and a bot manager that allows students to create and manage AI-powered Matrix bots.

## Components:
- Matrix Synapse server (handles Matrix protocol)
- Element web client (connects to Synapse server)
- Flowise (creates chatflows with LLMs)
- Bot Manager (web interface to create and manage bots)
- Individual bot instances (each bot runs separately)

## Architecture:
```
Server
├── Synapse Matrix Server (Docker)
├── Flowise AI Service (Docker)
├── Bot Manager (Docker with web interface)
└── Individual Bots (managed by bot manager)
```

## Quick Start with Docker Compose

1. **Update requirements if needed:** If you encounter an error about uvicorn version (like uvicorn==0.35.2 not found), update the requirements.txt file:
```bash
# Change the uvicorn version in requirements.txt from 0.35.2 to 0.36.0
sed -i 's/uvicorn==0.35.2/uvicorn==0.36.0/g' requirements.txt
```

2. **Start the entire system:**
```bash
docker-compose up -d
```

3. **Wait for services to be ready:**
```bash
# Wait until all services show healthy status
docker-compose ps
```

## Alternative Method (Without Docker)

If Docker is not available in your environment, you can run the system manually:

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Run the system simulation script:
   ```bash
   python3 start_system.py
   ```

Note: This method simulates the external services (Synapse and Flowise) and runs only the Bot Manager. For a full setup with Docker, you would need to install Docker and Docker Compose first.

## Student Workflow

### 1. Set up Flowise Chatflow
1. Go to `http://localhost:3000` in your browser
2. Log in with username: `admin`, password: `password`
3. Create a new chatflow with your preferred LLM (you can import the example from `Example_Chatflow.json`)
4. Get the API endpoint URL for your chatflow (typically looks like `http://localhost:3000/api/v1/prediction/[ID]`)

### 2. Set up Matrix Users
1. Open Element web client at `https://app.element.io/`
2. Choose "Edit" for the homeserver
3. Enter your homeserver URL: `http://localhost:8008`
4. Register a new account for yourself
5. Create a second account that will be used for your bot (remember the username and password)

### 3. Use the Bot Manager
1. Go to `http://localhost:8001` in your browser
2. Create a new bot with the following information:
   - Bot ID: a unique identifier for your bot
   - Homeserver URL: `http://localhost:8008`
   - User ID: the bot's Matrix user ID (e.g., `@mybot:localhost`)
   - Password: the bot's password
   - Flowise URL: the API endpoint URL from step 1

### 4. Start and Manage Your Bot
1. After creating the bot, click "Start" to begin running it
2. The bot will connect to Matrix and start responding to messages
3. You can stop the bot anytime using the "Stop" button

## Manual Setup (Alternative to Docker Compose)

If you prefer to set up components individually:

### Synapse Setup
```bash
# Create network
docker network create matrix-network

# Generate Synapse config
docker run -it --rm \
  -v synapse-data:/data \
  -e SYNAPSE_SERVER_NAME=localhost \
  -e SYNAPSE_REPORT_STATS=no \
  matrixdotorg/synapse:latest generate

# Start Synapse server
docker run -d \
  --name synapse \
  --network matrix-network \
  -p 8008:8008 \
  -v synapse-data:/data \
  matrixdotorg/synapse:latest
```

### Flowise Setup
```bash
docker run -d \
  --name flowise \
  --network matrix-network \
  -p 3000:3000 \
  -v flowise-data:/data \
  -e FLOWISE_USERNAME=admin \
  -e FLOWISE_PASSWORD=password \
  flowiseai/flowise:latest
```

### Bot Manager Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot manager
python bot_manager.py
```

### Create Matrix Users
```bash
# Create your user account
docker exec -it synapse register_new_matrix_user http://localhost:8008 -c /data/homeserver.yaml

# Create bot user account
docker exec -it synapse register_new_matrix_user http://localhost:8008 -c /data/homeserver.yaml
```

## Project Structure
- `matrix-bot.py`: Core bot implementation that connects to Matrix and Flowise
- `bot_manager.py`: Web application to create and manage bot instances
- `requirements.txt`: Python dependencies
- `docker-compose.yml`: Docker orchestration file
- `Dockerfile`: Container definition for bot manager
- `Example_Chatflow.json`: Sample Flowise chatflow configuration
- `homeserver.yaml`: Synapse Matrix server configuration file
- `log_config.yaml`: Logging configuration for Synapse

## Troubleshooting

- **Synapse won't start**: Check that port 8008 is available
- **Bot won't connect**: Verify the Matrix credentials and Flowise URL are correct
- **Bot manager can't start bots**: Make sure all dependencies are installed
- **Service health checks failing**: Wait a few minutes for services to initialize

## Resources:
* [Synapse Documentation](https://github.com/matrix-org/synapse)
* [Flowise Documentation](https://github.com/FlowiseAI/Flowise)
* [Matrix Protocol](https://matrix.org/)
