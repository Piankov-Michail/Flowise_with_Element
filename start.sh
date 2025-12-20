#!/bin/bash

echo "Starting Matrix Synapse Orchestrator services..."

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo "Error: docker-compose is not installed or not in PATH"
    exit 1
fi

# Start the services
docker-compose up -d

echo ""
echo "Services started successfully!"
echo ""
echo "Access the services:"
echo "- Synapse (Matrix server): http://localhost:8008"
echo "- Orchestrator (Web UI): http://localhost:8001 (default password: 1111111)"
echo ""
echo "To stop the services, run: docker-compose down"