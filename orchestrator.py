#!/usr/bin/env python3
"""
Orchestrator service for managing Matrix Synapse users and bots
"""

import os
import signal
import threading
import subprocess
import hashlib
import json
import asyncio
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session
import psycopg2
from psycopg2.extras import RealDictCursor
import bcrypt
import docker
import sys
import logging

# Глобальный словарь для хранения запущенных процессов
running_bots = {}

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv('ORCHESTRATOR_WEB_CLIENT_SECRET', 'default_secret_1111111')

# Initialize Docker client
try:
    docker_client = docker.from_env()
    logger.info("Docker client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Docker client: {e}")
    docker_client = None

# Database connection
def get_db_connection():
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'postgres'),
        database=os.getenv('DB_NAME', 'orchestrator'),
        user=os.getenv('DB_USER', 'orchestrator_user'),
        password=os.getenv('DB_PASSWORD', 'orchestrator_pass')
    )
    return conn

# Initialize database tables
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create bots table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bots (
            id SERIAL PRIMARY KEY,
            bot_user_id VARCHAR(255) UNIQUE NOT NULL,
            flowise_url TEXT NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            status VARCHAR(20) DEFAULT 'stopped',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create processes table to track running bots
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_processes (
            id SERIAL PRIMARY KEY,
            bot_id INTEGER REFERENCES bots(id),
            process_id INTEGER,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    cursor.close()
    conn.close()
    logger.info("Database initialized")

@app.route('/')
def index():
    if not session.get('authenticated'):
        return redirect(url_for('login'))
    return render_template_string(HTML_TEMPLATE)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form['password']
        admin_password = os.getenv('ORCHESTRATOR_WEB_CLIENT_SECRET', '1111111')
        
        if password == admin_password:
            session['authenticated'] = True
            logger.info("User logged in successfully")
            return redirect(url_for('index'))
        else:
            logger.warning("Failed login attempt")
            return render_template_string(LOGIN_TEMPLATE, error="Invalid password")
    
    return render_template_string(LOGIN_TEMPLATE, error=None)

@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    logger.info("User logged out")
    return redirect(url_for('login'))

def register_matrix_user_simple(username, password, is_admin=False):
    """Simplified method to register a new user in Synapse"""
    try:
        if docker_client is None:
            return False, "Docker client not available"
        
        logger.info(f"Attempting to register user: {username}, admin: {is_admin}")
        
        # Get synapse container
        try:
            container = docker_client.containers.get('synapse')
        except docker.errors.NotFound:
            return False, "Synapse container not found. Is it running?"
        
        # Extract localpart from username (remove @ and :localhost)
        localpart = username
        if localpart.startswith('@'):
            localpart = localpart[1:]
        if localpart.endswith(':localhost'):
            localpart = localpart[:-len(':localhost')]
        
        logger.info(f"Localpart: {localpart}")
        
        # Build the docker exec command with non-interactive arguments
        cmd = [
            'docker', 'exec', '-i', 'synapse',
            'register_new_matrix_user',
            'http://localhost:8008',
            '-c', '/data/homeserver.yaml',
            '--user', localpart,
            '--password', password,
            '--no-admin'
        ]
        
        if is_admin:
            # Replace --no-admin with --admin
            cmd = [
                'docker', 'exec', '-i', 'synapse',
                'register_new_matrix_user',
                'http://localhost:8008',
                '-c', '/data/homeserver.yaml',
                '--user', localpart,
                '--password', password,
                '--admin'
            ]
        
        logger.info(f"Executing command: {' '.join(cmd)}")
        
        # Run the command
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate()
        
        logger.info(f"Command stdout: {stdout}")
        logger.info(f"Command stderr: {stderr}")
        logger.info(f"Command return code: {process.returncode}")
        
        if process.returncode == 0:
            return True, "User created successfully"
        else:
            # Check for specific error messages
            if "already exists" in stderr.lower() or "already exists" in stdout.lower():
                return True, "User already exists in Synapse"
            return False, f"Registration failed: {stdout} {stderr}"
            
    except Exception as e:
        logger.error(f"Error in register_matrix_user_simple: {e}", exc_info=True)
        return False, f"Unexpected error: {str(e)}"

@app.route('/api/create_user', methods=['POST'])
def create_user():
    if not session.get('authenticated'):
        logger.warning("Unauthorized access attempt to create_user")
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = request.form['username']
    password = request.form['password']
    is_admin = request.form.get('is_admin') == 'on'
    
    logger.info(f"Creating user: {username}, admin: {is_admin}")
    
    # Validate username
    if not username:
        return jsonify({'error': 'Username is required'}), 400
    
    # Format username
    if not username.startswith('@'):
        username = '@' + username
    if not username.endswith(':localhost'):
        username = username + ':localhost'
    
    # Check password length
    if len(password) < 3:
        return jsonify({'error': 'Password must be at least 3 characters'}), 400
    
    # Hash the password for our database
    try:
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    except Exception as e:
        logger.error(f"Error hashing password: {e}")
        return jsonify({'error': 'Error processing password'}), 500
    
    try:
        # Register user in Synapse
        success, message = register_matrix_user_simple(username, password, is_admin)
        
        if not success:
            # Check if it's just that user already exists
            if "already exists" not in message.lower():
                logger.error(f"Failed to create user in Synapse: {message}")
                return jsonify({'error': f'Failed to create user: {message}'}), 500
            else:
                logger.info(f"User already exists in Synapse: {message}")
        
        # Store user info in our database
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                (username, password_hash)
            )
            conn.commit()
            logger.info(f"User {username} saved to database")
        except psycopg2.IntegrityError as e:
            # User already exists in our DB
            conn.rollback()
            logger.info(f"User {username} already exists in database: {e}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Error saving user to database: {e}")
            # Don't fail if database save fails, just log it
        
        cursor.close()
        conn.close()
        
        logger.info(f"User {username} created successfully")
        return jsonify({'success': True, 'message': f'User {username} created successfully'})
    
    except Exception as e:
        logger.error(f"Error in create_user: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/bots', methods=['GET', 'POST'])
def manage_bots():
    if not session.get('authenticated'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    if request.method == 'GET':
        # Get all bots
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM bots ORDER BY created_at DESC")
        bots = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(bots)
    
    elif request.method == 'POST':
        # Create a new bot
        bot_user_id = request.form['bot_user_id']
        flowise_url = request.form['flowise_url']
        password = request.form['bot_password']
        
        logger.info(f"Creating bot: {bot_user_id}")
        
        # Validate bot_user_id format
        if not bot_user_id:
            return jsonify({'error': 'Bot user ID is required'}), 400
        
        if not bot_user_id.startswith('@'):
            bot_user_id = '@' + bot_user_id
        if not bot_user_id.endswith(':localhost'):
            bot_user_id = bot_user_id + ':localhost'
        
        # Hash the password
        try:
            password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        except Exception as e:
            logger.error(f"Error hashing bot password: {e}")
            return jsonify({'error': 'Error processing password'}), 500
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO bots (bot_user_id, flowise_url, password_hash) VALUES (%s, %s, %s)",
                (bot_user_id, flowise_url, password_hash)
            )
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info(f"Bot {bot_user_id} created successfully")
            return jsonify({'success': True, 'message': 'Bot created successfully'})
        except Exception as e:
            logger.error(f"Error creating bot in database: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

@app.route('/api/bot/<int:bot_id>/action', methods=['POST'])
def bot_action(bot_id):
    if not session.get('authenticated'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    action = request.form['action']  # start, stop, delete
    provided_password = request.form['password']
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get bot information including password
    cursor.execute("SELECT * FROM bots WHERE id = %s", (bot_id,))
    bot = cursor.fetchone()
    
    if not bot:
        cursor.close()
        conn.close()
        return jsonify({'error': 'Bot not found'}), 404
    
    # Check if provided password matches bot password or admin password
    admin_password = os.getenv('ORCHESTRATOR_ADMIN_PASSWORD', '1111111')
    
    try:
        is_valid_password = bcrypt.checkpw(provided_password.encode('utf-8'), bot['password_hash'].encode('utf-8'))
    except:
        is_valid_password = False

    if not is_valid_password and provided_password != admin_password:
        cursor.close()
        conn.close()
        return jsonify({'error': 'Invalid password'}), 401
    
    try:
        if action == 'start':
            # Get the actual bot password from the database
            # We need to verify it matches the provided password
            if not is_valid_password:
                # If admin password was used, we need to get bot password differently
                # For now, use provided password (which is admin password)
                bot_password = provided_password
            else:
                # The provided password is the bot's password
                bot_password = provided_password
            
            # Start the bot with the actual password
            start_bot_process(bot_id, bot['bot_user_id'], bot['flowise_url'], bot_password)
            cursor.execute("UPDATE bots SET status = 'running' WHERE id = %s", (bot_id,))
            conn.commit()
            result = {'success': True, 'message': 'Bot started successfully'}
            
        elif action == 'stop':
            # Stop the bot
            stop_bot_process(bot_id)
            cursor.execute("UPDATE bots SET status = 'stopped' WHERE id = %s", (bot_id,))
            conn.commit()
            result = {'success': True, 'message': 'Bot stopped successfully'}
            
        elif action == 'delete':
            # Stop the bot if running and delete
            stop_bot_process(bot_id)
            cursor.execute("DELETE FROM bots WHERE id = %s", (bot_id,))
            cursor.execute("DELETE FROM bot_processes WHERE bot_id = %s", (bot_id,))
            conn.commit()
            result = {'success': True, 'message': 'Bot deleted successfully'}
        else:
            result = {'error': 'Invalid action'}, 400
            
    except Exception as e:
        logger.error(f"Error performing bot action {action}: {e}", exc_info=True)
        result = {'error': str(e)}, 500
    
    cursor.close()
    conn.close()
    return jsonify(result)

def start_bot_process(bot_id, bot_user_id, flowise_url, password):
    """Start a bot process using the existing matrix-bot.py script"""
    try:
        logger.info(f"Starting bot {bot_id} ({bot_user_id}) with Flowise URL: {flowise_url}")
        
        # Ensure the bot script exists
        bot_script_path = "/app/matrix-bot.py"
        if not os.path.exists(bot_script_path):
            logger.error(f"Bot script not found at {bot_script_path}")
            raise FileNotFoundError(f"Bot script not found at {bot_script_path}")
        
        # Extract localpart from bot_user_id for logging
        localpart = bot_user_id
        if localpart.startswith('@'):
            localpart = localpart[1:]
        if localpart.endswith(':localhost'):
            localpart = localpart[:-len(':localhost')]
        
        # Create environment variables for the bot
        env = os.environ.copy()
        env.update({
            'BOT_HOMESERVER': 'http://synapse:8008',
            'BOT_USER_ID': bot_user_id,
            'BOT_PASSWORD': password,
            'BOT_FLOWISE_URL': flowise_url,
            'BOT_ID': str(bot_id)
        })
        
        # Create log directory if it doesn't exist
        log_dir = "/app/bot_logs"
        os.makedirs(log_dir, exist_ok=True)
        
        # Log file for this bot
        log_file = f"{log_dir}/bot_{bot_id}.log"
        
        # Start the bot process
        with open(log_file, 'a') as log_f:
            process = subprocess.Popen(
                [
                    sys.executable, 
                    bot_script_path,
                    '--homeserver', 'http://synapse:8008',
                    '--user', bot_user_id,
                    '--password', password,
                    '--flowise-url', flowise_url
                ],
                stdout=log_f,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                preexec_fn=os.setsid  # Create new process group
            )
        
        # Store process info
        running_bots[bot_id] = {
            'process': process,
            'bot_user_id': bot_user_id,
            'log_file': log_file,
            'started_at': datetime.now()
        }
        
        # Store in database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO bot_processes (bot_id, process_id) VALUES (%s, %s)",
            (bot_id, process.pid)
        )
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"✅ Bot {bot_id} started with PID: {process.pid}, Log: {log_file}")
        
        # Start a thread to monitor the process
        monitor_thread = threading.Thread(
            target=monitor_bot_process,
            args=(bot_id, process, log_file),
            daemon=True
        )
        monitor_thread.start()
        
    except Exception as e:
        logger.error(f"❌ Error starting bot {bot_id}: {e}", exc_info=True)
        raise

def stop_bot_process(bot_id):
    """Stop a bot process"""
    try:
        logger.info(f"Stopping bot {bot_id}")
        
        if bot_id in running_bots:
            process_info = running_bots[bot_id]
            process = process_info['process']
            
            # Kill the entire process group
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                process.wait(timeout=5)
                logger.info(f"✅ Bot {bot_id} (PID: {process.pid}) terminated gracefully")
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                logger.info(f"⚠️ Bot {bot_id} (PID: {process.pid}) killed forcefully")
            except ProcessLookupError:
                logger.warning(f"Bot {bot_id} process already terminated")
            
            # Remove from running bots
            del running_bots[bot_id]
            
            # Update database
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM bot_processes WHERE bot_id = %s",
                (bot_id,)
            )
            conn.commit()
            cursor.close()
            conn.close()
            
        else:
            # Try to kill by PID from database
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT process_id FROM bot_processes WHERE bot_id = %s",
                (bot_id,)
            )
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if result:
                pid = result[0]
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                    logger.info(f"✅ Killed bot {bot_id} process group {pid}")
                except ProcessLookupError:
                    logger.warning(f"Process {pid} for bot {bot_id} not found")
                except Exception as e:
                    logger.error(f"Error killing process {pid}: {e}")
            
    except Exception as e:
        logger.error(f"❌ Error stopping bot {bot_id}: {e}", exc_info=True)
        raise

def monitor_bot_process(bot_id, process, log_file):
    """Monitor a bot process and update status if it dies"""
    try:
        process.wait()
        exit_code = process.returncode
        logger.info(f"Bot {bot_id} process terminated with code: {exit_code}")
        
        # Log termination
        with open(log_file, 'a') as f:
            f.write(f"\n[{datetime.now()}] Bot process terminated with exit code: {exit_code}\n")
        
        # Update status in database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE bots SET status = 'stopped' WHERE id = %s",
            (bot_id,)
        )
        conn.commit()
        cursor.close()
        conn.close()
        
        # Clean up if still in running_bots
        if bot_id in running_bots:
            del running_bots[bot_id]
            
    except Exception as e:
        logger.error(f"Error monitoring bot {bot_id}: {e}")

@app.route('/api/bot/<int:bot_id>/logs')
def get_bot_logs(bot_id):
    if not session.get('authenticated'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    log_file = f"/app/bot_logs/bot_{bot_id}.log"
    try:
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                logs = f.read()
            return jsonify({'success': True, 'logs': logs})
        else:
            return jsonify({'success': False, 'error': 'Log file not found'})
    except Exception as e:
        logger.error(f"Error reading logs for bot {bot_id}: {e}")
        return jsonify({'success': False, 'error': str(e)})

# HTML Templates (same as before)
LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Orchestrator Login</title>
    <style>
        body { font-family: Arial, sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background-color: #f0f0f0; }
        .login-container { background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); width: 300px; }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; }
        input[type="password"] { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px; }
        button { width: 100%; padding: 10px; background-color: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }
        button:hover { background-color: #0056b3; }
        .error { color: red; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="login-container">
        <h2>Login to Orchestrator</h2>
        <form method="post">
            <div class="form-group">
                <label for="password">Password:</label>
                <input type="password" id="password" name="password" required>
            </div>
            <button type="submit">Login</button>
        </form>
        {% if error %}
            <div class="error">{{ error }}</div>
        {% endif %}
    </div>
</body>
</html>
'''

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Matrix Orchestrator</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
        .container { max-width: 1000px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .tabs { display: flex; margin-bottom: 20px; }
        .tab { padding: 10px 20px; cursor: pointer; background: #e9ecef; border: 1px solid #ddd; border-bottom: none; border-radius: 4px 4px 0 0; margin-right: 5px; }
        .tab.active { background: #007bff; color: white; }
        .tab-content { display: none; padding: 20px; border: 1px solid #ddd; border-radius: 0 4px 4px 4px; }
        .tab-content.active { display: block; }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; font-weight: bold; }
        input, textarea { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }
        button { padding: 10px 15px; background-color: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }
        button:hover { background-color: #0056b3; }
        .btn-danger { background-color: #dc3545; }
        .btn-danger:hover { background-color: #c82333; }
        .btn-success { background-color: #28a745; }
        .btn-success:hover { background-color: #218838; }
        .bot-item { border: 1px solid #ddd; padding: 15px; margin-bottom: 10px; border-radius: 4px; }
        .bot-actions { margin-top: 10px; }
        .bot-status { display: inline-block; padding: 3px 8px; border-radius: 4px; color: white; font-size: 12px; }
        .status-running { background-color: #28a745; }
        .status-stopped { background-color: #dc3545; }
        .notification { padding: 10px; margin: 10px 0; border-radius: 4px; display: none; }
        .notification.success { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .notification.error { background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Matrix Orchestrator</h1>
        <div style="float: right;">
            <a href="{{ url_for('logout') }}">Logout</a>
        </div>
        
        <div class="tabs">
            <div class="tab active" onclick="showTab('users')">Create User</div>
            <div class="tab" onclick="showTab('bots')">Manage Bots</div>
        </div>
        
        <div class="notification" id="notification"></div>
        
        <!-- Create User Tab -->
        <div id="users" class="tab-content active">
            <h2>Create New User</h2>
            <form id="userForm">
                <div class="form-group">
                    <label for="username">Username:</label>
                    <input type="text" id="username" name="username" required placeholder="username (without @ and :localhost)">
                </div>
                <div class="form-group">
                    <label for="password">Password:</label>
                    <input type="password" id="password" name="password" required>
                </div>
                <div class="form-group">
                    <label for="confirm_password">Confirm Password:</label>
                    <input type="password" id="confirm_password" name="confirm_password" required>
                </div>
                <div class="form-group">
                    <label>
                        <input type="checkbox" id="is_admin" name="is_admin"> Admin User
                    </label>
                </div>
                <button type="submit">Create User</button>
            </form>
        </div>
        
        <!-- Manage Bots Tab -->
        <div id="bots" class="tab-content">
            <h2>Manage Bots</h2>
            <form id="botForm">
                <div class="form-group">
                    <label for="bot_user_id">Bot User ID:</label>
                    <input type="text" id="bot_user_id" name="bot_user_id" placeholder="botname (without @ and :localhost)" required>
                </div>
                <div class="form-group">
                    <label for="flowise_url">Flowise URL:</label>
                    <input type="text" id="flowise_url" name="flowise_url" placeholder="http://flowise:3000/api/v1/prediction/..." required>
                </div>
                <div class="form-group">
                    <label for="bot_password">Bot Password:</label>
                    <input type="password" id="bot_password" name="bot_password" required>
                </div>
                <button type="submit">Create Bot</button>
            </form>
            
            <h3>Existing Bots</h3>
            <div id="botsList"></div>
        </div>
    </div>

    <script>
        // Tab switching functionality
        function showTab(tabName) {
            // Hide all tab contents
            const tabContents = document.querySelectorAll('.tab-content');
            tabContents.forEach(content => content.classList.remove('active'));
            
            // Remove active class from all tabs
            const tabs = document.querySelectorAll('.tab');
            tabs.forEach(tab => tab.classList.remove('active'));
            
            // Show selected tab content
            document.getElementById(tabName).classList.add('active');
            
            // Make selected tab active
            event.target.classList.add('active');
            
            // Load bots if switching to bots tab
            if(tabName === 'bots') {
                loadBots();
            }
        }
        
        // Show notification
        function showNotification(message, isError = false) {
            const notification = document.getElementById('notification');
            notification.textContent = message;
            notification.className = `notification ${isError ? 'error' : 'success'}`;
            notification.style.display = 'block';
            
            setTimeout(() => {
                notification.style.display = 'none';
            }, 5000);
        }
        
        // Handle user form submission
        document.getElementById('userForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const formData = new FormData(this);
            
            // Check if passwords match
            if(formData.get('password') !== formData.get('confirm_password')) {
                showNotification('Passwords do not match!', true);
                return;
            }
            
            try {
                const response = await fetch('/api/create_user', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if(response.ok) {
                    showNotification(result.message || 'User created successfully!');
                    document.getElementById('userForm').reset();
                } else {
                    showNotification(result.error || 'Error creating user', true);
                }
            } catch(error) {
                showNotification('Network error occurred', true);
            }
        });
        
        // Handle bot form submission
        document.getElementById('botForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const formData = new FormData(this);
            
            try {
                const response = await fetch('/api/bots', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if(response.ok) {
                    showNotification(result.message || 'Bot created successfully!');
                    document.getElementById('botForm').reset();
                    loadBots(); // Reload the bots list
                } else {
                    showNotification(result.error || 'Error creating bot', true);
                }
            } catch(error) {
                showNotification('Network error occurred', true);
            }
        });
        
        // Load and display bots
        async function loadBots() {
            try {
                const response = await fetch('/api/bots');
                const bots = await response.json();
                
                const botsList = document.getElementById('botsList');
                
                if(bots.length === 0) {
                    botsList.innerHTML = '<p>No bots created yet.</p>';
                    return;
                }
                
                let html = '';
                bots.forEach(bot => {
                    const statusClass = bot.status === 'running' ? 'status-running' : 'status-stopped';
                    const statusText = bot.status.charAt(0).toUpperCase() + bot.status.slice(1);
                    
                    html += `
                        <div class="bot-item">
                            <div><strong>${bot.bot_user_id}</strong></div>
                            <div>URL: ${bot.flowise_url}</div>
                            <div>Status: <span class="bot-status ${statusClass}">${statusText}</span></div>
                            <div class="bot-actions">
                                <input type="password" id="pass_${bot.id}" placeholder="Enter password" style="width: 200px; margin-right: 10px;">
                                <button class="btn-success" onclick="performBotAction(${bot.id}, 'start')">Start</button>
                                <button class="btn-danger" onclick="performBotAction(${bot.id}, 'stop')">Stop</button>
                                <button class="btn-danger" onclick="deleteBot(${bot.id})">Delete</button>
                            </div>
                        </div>
                    `;
                });
                
                botsList.innerHTML = html;
            } catch(error) {
                showNotification('Error loading bots', true);
            }
        }
        
        // Perform bot action (start/stop)
        async function performBotAction(botId, action) {
            const passwordInput = document.getElementById(`pass_${botId}`);
            const password = passwordInput.value;
            
            if(!password) {
                showNotification('Please enter password', true);
                return;
            }
            
            const formData = new FormData();
            formData.append('action', action);
            formData.append('password', password);
            
            try {
                const response = await fetch(`/api/bot/${botId}/action`, {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if(response.ok) {
                    showNotification(result.message || `Bot ${action}ed successfully!`);
                    loadBots(); // Reload the bots list
                } else {
                    showNotification(result.error || `Error ${action}ing bot`, true);
                }
            } catch(error) {
                showNotification('Network error occurred', true);
            }
        }
        
        // Delete bot
        async function deleteBot(botId) {
            const passwordInput = document.getElementById(`pass_${botId}`);
            const password = passwordInput.value;
            
            if(!password) {
                showNotification('Please enter password', true);
                return;
            }
            
            const formData = new FormData();
            formData.append('action', 'delete');
            formData.append('password', password);
            
            if(confirm('Are you sure you want to delete this bot?')) {
                try {
                    const response = await fetch(`/api/bot/${botId}/action`, {
                        method: 'POST',
                        body: formData
                    });
                    
                    const result = await response.json();
                    
                    if(response.ok) {
                        showNotification(result.message || 'Bot deleted successfully!');
                        loadBots(); // Reload the bots list
                    } else {
                        showNotification(result.error || 'Error deleting bot', true);
                    }
                } catch(error) {
                    showNotification('Network error occurred', true);
                }
            }
        }
        
        // Load bots when page loads if we're on the bots tab
        window.onload = function() {
            if(document.querySelector('#bots').classList.contains('active')) {
                loadBots();
            }
        };
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    # Initialize the database
    init_db()
    
    # Run the Flask app
    app.run(host='0.0.0.0', port=8001, debug=True)