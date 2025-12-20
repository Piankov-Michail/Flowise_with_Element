# Unified Matrix Management System

This project provides a unified orchestration system for managing Matrix bots and users with persistent database storage.

## Overview

The system provides:
- A containerized database (PostgreSQL) for storing information about users and bots
- Unified management of both bots and users through a single interface
- A web interface with two tabs: one for bot management and one for user management
- Persistent storage using SQLAlchemy ORM

## Architecture

- `orchestration.py`: Main orchestration service
- `unified_manager.py`: Combined bot and user management
- `database.py`: Database models and setup
- `docker-compose.yml`: Container orchestration with PostgreSQL, Synapse, Flowise, and the bot manager

## Features

- Create, start, and stop Matrix bots
- Create Matrix users
- Persistent storage of bot and user information
- Web interface with separate tabs for bot and user management
- Process management for running bots

## Setup

```bash
docker-compose up -d --build
```

The web interface will be available at `http://localhost:8001`

