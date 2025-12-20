#!/usr/bin/env python3
"""
Orchestrator service for managing Matrix Synapse users and bots
"""

import os
import subprocess
import hashlib
import json
import asyncio
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify, redirect, url_for, session
import psycopg2
from psycopg2.extras import RealDictCursor
import bcrypt

app = Flask(__name__)
app.secret_key = os.getenv('ORCHESTRATOR_WEB_CLIENT_SECRET', 'default_secret_1111111')

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
            return redirect(url_for('index'))
        else:
            return render_template_string(LOGIN_TEMPLATE, error="Invalid password")
    
    return render_template_string(LOGIN_TEMPLATE, error=None)

@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    return redirect(url_for('login'))

@app.route('/api/create_user', methods=['POST'])
def create_user():
    if not session.get('authenticated'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    username = request.form['username']
    password = request.form['password']
    is_admin = request.form.get('is_admin', False)
    
    # Hash the password
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    try:
        # Register user in Synapse
        cmd = [
            'docker', 'exec', '-i', 'synapse', 
            'register_new_matrix_user', 
            'http://localhost:8008', 
            '-c', '/data/homeserver.yaml'
        ]
        
        # Execute the registration command
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Send username, password, and admin status to the process
        stdout, stderr = process.communicate(input=f"{username}\n{password}\n{password}\n{'y' if is_admin else ''}\n")
        
        if process.returncode != 0:
            return jsonify({'error': f'Failed to create user: {stderr}'}), 500
        
        # Store user info in our database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            (username, password_hash)
        )
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True, 'message': f'User {username} created successfully'})
    
    except Exception as e:
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
        password = request.form['password']
        
        # Hash the password
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
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
            
            return jsonify({'success': True, 'message': 'Bot created successfully'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/api/bot/<int:bot_id>/action', methods=['POST'])
def bot_action(bot_id):
    if not session.get('authenticated'):
        return jsonify({'error': 'Not authenticated'}), 401
    
    action = request.form['action']  # start, stop, delete
    provided_password = request.form['password']
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get bot information
    cursor.execute("SELECT * FROM bots WHERE id = %s", (bot_id,))
    bot = cursor.fetchone()
    
    if not bot:
        cursor.close()
        conn.close()
        return jsonify({'error': 'Bot not found'}), 404
    
    # Check if provided password matches bot password or admin password
    admin_password = os.getenv('ORCHESTRATOR_ADMIN_PASSWORD', '1111111')
    is_valid_password = (
        bcrypt.checkpw(provided_password.encode('utf-8'), bot['password_hash'].encode('utf-8')) or
        provided_password == admin_password
    )
    
    if not is_valid_password:
        cursor.close()
        conn.close()
        return jsonify({'error': 'Invalid password'}), 401
    
    try:
        if action == 'start':
            # Start the bot
            start_bot_process(bot_id, bot['bot_user_id'], bot['flowise_url'])
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
        result = {'error': str(e)}, 500
    
    cursor.close()
    conn.close()
    return jsonify(result)

def start_bot_process(bot_id, bot_user_id, flowise_url):
    """Start a bot process"""
    # This would typically involve starting a subprocess that runs the bot
    # For now, we'll just simulate the process
    pass

def stop_bot_process(bot_id):
    """Stop a bot process"""
    # This would typically involve stopping the subprocess
    # For now, we'll just simulate the process
    pass

# HTML Templates
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
                    <input type="text" id="username" name="username" required>
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
                    <input type="text" id="bot_user_id" name="bot_user_id" placeholder="@bot:localhost" required>
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