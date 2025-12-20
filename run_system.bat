@echo off
REM Matrix Bot Manager System Control Script for Windows

echo Matrix Bot Manager System Control
echo ===================================

if "%1"=="help" goto help
if "%1"=="start" goto start
if "%1"=="stop" goto stop
if "%1"=="status" goto status
if "%1"=="run" goto run
if "%1"=="" goto help

echo Unknown command: %1
goto help

:help
echo Usage:
echo   %0 [command]
echo.
echo Commands:
echo   help     - Show this help message
echo   start    - Start the system (requires Docker)
echo   stop     - Stop the system (requires Docker)
echo   status   - Check system status (requires Docker)
echo   run      - Run bot manager locally without Docker
echo.
goto end

:start
echo Starting the Matrix Bot Manager system...
echo Make sure Docker and Docker Compose are installed.
docker-compose up -d
if %errorlevel% == 0 (
  echo.
  echo System started successfully!
  echo Services:
  echo - Bot Manager UI: http://localhost:8001
  echo - Synapse Matrix: http://localhost:8008
  echo - Flowise: http://localhost:3000
  echo.
  echo To check status: %0 status
  echo To stop the system: %0 stop
) else (
  echo Failed to start the system. Make sure Docker is running.
)
goto end

:stop
echo Stopping the Matrix Bot Manager system...
docker-compose down
echo System stopped.
goto end

:status
echo Checking system status...
docker-compose ps
goto end

:run
echo Running bot manager locally ^(without Docker^)...
echo Note: This only runs the bot manager. Synapse and Flowise must be running separately.
echo Installing dependencies if needed...
pip install -r requirements.txt
echo Starting bot manager on http://localhost:8001...
python -m uvicorn bot_manager:app --host 0.0.0.0 --port 8001
goto end

:end