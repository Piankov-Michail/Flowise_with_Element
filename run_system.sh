#!/bin/bash
# Matrix Bot Manager System Control Script

echo "Matrix Bot Manager System Control"
echo "==================================="

show_help() {
    echo "Usage:"
    echo "  $0 [command]"
    echo ""
    echo "Commands:"
    echo "  help     - Show this help message"
    echo "  start    - Start the system (requires Docker)"
    echo "  stop     - Stop the system (requires Docker)"
    echo "  status   - Check system status (requires Docker)"
    echo "  run      - Run bot manager locally without Docker"
    echo "  setup    - Prepare system (fix uvicorn version if needed)"
    echo ""
}

fix_uvicon_version() {
    echo "Checking uvicorn version in requirements.txt..."
    if grep -q "uvicorn==0.35.2" requirements.txt; then
        echo "Found incompatible uvicorn version. Updating to 0.36.0..."
        sed -i 's/uvicorn==0.35.2/uvicorn==0.36.0/g' requirements.txt
        echo "Updated uvicorn version in requirements.txt"
    else
        echo "Uvicorn version appears to be correct."
    fi
}

case "${1:-help}" in
    "help")
        show_help
        ;;
    "setup")
        fix_uvicon_version
        echo "Setup complete!"
        ;;
    "start")
        fix_uvicon_version
        echo "Starting the Matrix Bot Manager system..."
        echo "Make sure Docker and Docker Compose are installed."
        docker-compose up -d
        if [ $? -eq 0 ]; then
            echo ""
            echo "System started successfully!"
            echo "Services:"
            echo "- Bot Manager UI: http://localhost:8001"
            echo "- Synapse Matrix: http://localhost:8008"
            echo "- Flowise: http://localhost:3000"
            echo ""
            echo "To check status: $0 status"
            echo "To stop the system: $0 stop"
        else
            echo "Failed to start the system. Make sure Docker is running."
        fi
        ;;
    "stop")
        echo "Stopping the Matrix Bot Manager system..."
        docker-compose down
        echo "System stopped."
        ;;
    "status")
        echo "Checking system status..."
        docker-compose ps
        ;;
    "run")
        echo "Running bot manager locally (without Docker)..."
        echo "Note: This only runs the bot manager. Synapse and Flowise must be running separately."
        
        # Check if required packages are installed
        python3 -c "import fastapi" 2>/dev/null || { echo "Installing dependencies..."; pip install -r requirements.txt; }
        
        echo "Starting bot manager on http://localhost:8001..."
        python3 -m uvicorn bot_manager:app --host 0.0.0.0 --port 8001
        ;;
    *)
        echo "Unknown command: $1"
        echo ""
        show_help
        ;;
esac