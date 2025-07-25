import threading
import re
import os
from datetime import datetime, timedelta, UTC
from uuid import uuid4
from flask import Flask, render_template_string, request, make_response, jsonify
from flask_socketio import SocketIO, emit, disconnect
from werkzeug.exceptions import InternalServerError, NotFound

# Lazy import heavy libraries
def get_mongo_client():
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError
    from bson import ObjectId
    return MongoClient, PyMongoError, ObjectId

def get_bleach():
    import bleach
    return bleach

# Configuration
SECRET_KEY = 'your-secret-key'
MONGO_URI = "mongodb+srv://chand37880:19XHvt2unzkoO65E@blog.ymjzol6.mongodb.net/?retryWrites=true&w=majority&appName=blog"
ALLOWED_TAGS = ['b', 'i', 'u', 'strong', 'em']
ALLOWED_ATTRIBUTES = {}
RATE_LIMIT_SECONDS = 1.5

# MongoDB setup
try:
    MongoClient, PyMongoError, ObjectId = get_mongo_client()
    client = MongoClient(MONGO_URI)
    db = client.chatdb
    messages_col = db.messages
    users_col = db.users
except Exception as e:
    print(f"MongoDB connection error: {e}")
    raise

# Global state
clients = set()
clients_lock = threading.Lock()
active_usernames = {}
usernames_lock = threading.Lock()
client_last_seen = {}
client_last_seen_lock = threading.Lock()
typing_users = set()
typing_users_lock = threading.Lock()
rate_limit = {}

# HTML with advanced CSS
HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kurnool City Chat</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
    <style>
        :root {
            --primary: #4caf50;
            --primary-dark: #388e3c;
            --background: #121212;
            --surface: #1e1e1e;
            --text: #e0e0e0;
            --text-secondary: #b0b0b0;
            --error: #f44336;
            --shadow: 0 4px 8px rgba(0,0,0,0.4);
            --border-radius: 8px;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(180deg, #121212, #1e1e1e);
            color: var(--text);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            line-height: 1.5;
        }

        header {
            background: var(--surface);
            padding: clamp(1rem, 2vw, 1.5rem);
            text-align: center;
            font-size: clamp(1.5rem, 3vw, 2rem);
            font-weight: 700;
            color: var(--primary);
            box-shadow: var(--shadow);
            position: sticky;
            top: 0;
            z-index: 10;
        }

        #warning {
            background: rgba(244, 67, 54, 0.1);
            color: var(--error);
            text-align: center;
            padding: clamp(0.5rem, 1vw, 0.75rem);
            font-size: clamp(0.9rem, 1.5vw, 1rem);
            font-weight: 500;
            display: none;
        }

        #warning.show {
            display: block;
        }

        #online-users {
            background: var(--surface);
            padding: clamp(0.75rem, 1.5vw, 1rem);
            color: var(--text-secondary);
            font-size: clamp(0.9rem, 1.5vw, 1rem);
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            justify-content: center;
            align-items: center;
            border-bottom: 1px solid #333;
        }

        #online-users ul {
            list-style: none;
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
        }

        #online-users li {
            background: #2a2a2a;
            padding: clamp(0.3rem, 0.8vw, 0.5rem) clamp(0.6rem, 1.2vw, 0.8rem);
            border-radius: 12px;
            color: var(--primary);
            font-size: clamp(0.8rem, 1.3vw, 0.9rem);
            transition: transform 0.2s ease, opacity 0.3s ease;
        }

        #online-users li:hover {
            transform: scale(1.05);
        }

        #online-users .user-count {
            font-weight: 600;
            color: var(--text);
        }

        #chat {
            flex: 1;
            overflow-y: auto;
            padding: clamp(1rem, 2vw, 1.5rem);
            background: var(--background);
            scroll-behavior: smooth;
            overscroll-behavior: contain;
        }

        .message {
            margin: 0.75rem 0;
            padding: clamp(0.75rem, 1.5vw, 1rem);
            background: var(--surface);
            border-radius: var(--border-radius);
            word-break: break-word;
            box-shadow: var(--shadow);
            border: 1px solid #333;
            animation: slideIn 0.3s ease-out forwards;
            transition: transform 0.2s ease, background 0.2s ease;
        }

        @keyframes slideIn {
            from { transform: translateX(-20px); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }

        .message:hover {
            transform: translateY(-3px);
            background: #2a2a2a;
        }

        .message .user {
            color: var(--primary);
            font-weight: 600;
            margin-right: 0.5rem;
        }

        .message .time {
            color: var(--text-secondary);
            font-size: clamp(0.75rem, 1.2vw, 0.85rem);
            opacity: 0.7;
            display: block;
            text-align: right;
        }

        .date-divider {
            text-align: center;
            color: var(--text-secondary);
            font-size: clamp(0.8rem, 1.3vw, 0.9rem);
            margin: 1rem 0;
            padding: 0.5rem;
            background: rgba(0, 0, 0, 0.2);
            border-radius: var(--border-radius);
        }

        #typing-indicator {
            padding: clamp(0.5rem, 1vw, 0.75rem);
            background: var(--surface);
            color: var(--text-secondary);
            font-style: italic;
            font-size: clamp(0.85rem, 1.3vw, 0.95rem);
            border-top: 1px solid #333;
        }

        form {
            display: flex;
            padding: clamp(0.75rem, 1.5vw, 1rem);
            background: var(--surface);
            gap: clamp(0.5rem, 1vw, 0.75rem);
            box-shadow: var(--shadow);
            position: sticky;
            bottom: 0;
        }

        input[type="text"] {
            padding: clamp(0.75rem, 1.5vw, 1rem);
            font-size: clamp(0.9rem, 1.5vw, 1rem);
            border: 1px solid #333;
            border-radius: var(--border-radius);
            background: #2a2a2a;
            color: var(--text);
            flex: 1;
            transition: border-color 0.2s ease, box-shadow 0.2s ease;
        }

        input[type="text"]:focus {
            border-color: var(--primary);
            box-shadow: 0 0 8px rgba(76, 175, 80, 0.3);
            outline: none;
        }

        #username {
            max-width: clamp(150px, 30vw, 180px);
        }

        #message {
            flex: 2;
        }

        button {
            padding: clamp(0.75rem, 1.5vw, 1rem) clamp(1.5rem, 2.5vw, 2rem);
            background: var(--primary);
            border: none;
            border-radius: var(--border-radius);
            color: #fff;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s ease, transform 0.2s ease;
        }

        button:hover {
            background: var(--primary-dark);
            transform: translateY(-2px);
        }

        button:disabled {
            background: #555;
            cursor: not-allowed;
            transform: none;
        }

        @media (max-width: 600px) {
            form {
                flex-direction: column;
            }
            #username, #message, button {
                width: 100%;
                max-width: none;
            }
            #chat {
                padding: clamp(0.5rem, 1vw, 0.75rem);
            }
        }

        @media (max-width: 400px) {
            .message {
                padding: clamp(0.5rem, 1vw, 0.75rem);
                font-size: clamp(0.85rem, 1.3vw, 0.95rem);
            }
            #online-users li {
                padding: clamp(0.2rem, 0.8vw, 0.3rem) clamp(0.4rem, 1vw, 0.6rem);
                font-size: clamp(0.75rem, 1.2vw, 0.85rem);
            }
        }
    </style>
</head>
<body>
    <header>Kurnool City Chat Room</header>
    <div id="warning" role="alert"></div>
    <div id="online-users" role="status"><span class="user-count"></span><ul></ul></div>
    <div id="chat" role="log" aria-live="polite"></div>
    <div id="typing-indicator" role="status"></div>
    <form id="chat-form" autocomplete="off">
        <input id="username" type="text" placeholder="Your name (max 20 chars)" maxlength="20" required aria-label="Username">
        <input id="message" type="text" placeholder="Type your message (max 200 chars)" maxlength="200" required aria-label="Message">
        <button type="submit">Send</button>
    </form>
    <script>
        const chat = document.getElementById('chat');
        const form = document.getElementById('chat-form');
        const messageInput = document.getElementById('message');
        const usernameInput = document.getElementById('username');
        const warningDiv = document.getElementById('warning');
        const onlineUsersList = document.querySelector('#online-users ul');
        const userCountSpan = document.querySelector('#online-users .user-count');
        const typingIndicator = document.getElementById('typing-indicator');
        let typingTimeout;
        let oldestMessageId = null;
        let isTyping = false;
        let isLoadingMessages = false;
        let isManualScrolling = false;
        let lastScrollTop = 0;

        if (localStorage.getItem('chat_username')) {
            usernameInput.value = localStorage.getItem('chat_username');
        }

        usernameInput.addEventListener('change', () => {
            localStorage.setItem('chat_username', usernameInput.value.trim());
            warningDiv.textContent = '';
            warningDiv.classList.remove('show');
            socket.emit('check_username', { username: usernameInput.value.trim() });
        });

        const socket = io();

        socket.on('connect', () => {
            warningDiv.textContent = '';
            warningDiv.classList.remove('show');
            socket.emit('check_username', { username: usernameInput.value.trim() });
            setInterval(() => socket.emit('heartbeat'), 10000);
        });

        socket.on('disconnect', () => {
            warningDiv.textContent = 'Connection lost, reconnecting...';
            warningDiv.classList.add('show');
        });

        socket.on('message', data => {
            try {
                if (!data || typeof data !== 'object' || !data.type) return;
                if (data.type === 'message' && data.message?._id && data.message.user && data.message.message && data.message.time) {
                    addMessage(data.message);
                    oldestMessageId = oldestMessageId ? (data.message._id < oldestMessageId ? data.message._id : oldestMessageId) : data.message._id;
                    if (!isManualScrolling) chat.scrollTop = chat.scrollHeight;
                } else if (data.type === 'online_users' && Array.isArray(data.users)) {
                    updateOnlineUsers(data.users);
                } else if (data.type === 'typing' && Array.isArray(data.users)) {
                    updateTypingIndicator(data.users);
                }
            } catch (err) {
                console.error('Error processing message:', err);
                warningDiv.textContent = 'Error receiving message. Please refresh.';
                warningDiv.classList.add('show');
            }
        });

        socket.on('username_response', data => {
            if (!data.available) {
                warningDiv.textContent = data.error || 'Username already taken. Please pick another.';
                warningDiv.classList.add('show');
                usernameInput.focus();
            } else {
                warningDiv.textContent = '';
                warningDiv.classList.remove('show');
            }
        });

        socket.on('error', data => {
            warningDiv.textContent = data.error || 'An error occurred.';
            warningDiv.classList.add('show');
        });

        messageInput.addEventListener('input', () => {
            const wasTyping = isTyping;
            isTyping = messageInput.value.trim().length > 0;
            if (wasTyping !== isTyping) socket.emit('typing', { isTyping });
            clearTimeout(typingTimeout);
            typingTimeout = setTimeout(() => {
                if (isTyping) {
                    isTyping = false;
                    socket.emit('typing', { isTyping: false });
                }
            }, 1000);
        });

        function formatDateTime(timestamp) {
            const date = new Date(timestamp);
            const today = new Date();
            const isToday = date.toDateString() === today.toDateString();
            const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            if (isToday) return `Today, ${timeStr}`;
            return `${date.toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: 'numeric' })}, ${timeStr}`;
        }

        function addDateDivider(dateStr) {
            const existingDividers = chat.querySelectorAll('.date-divider');
            const lastDivider = existingDividers[existingDividers.length - 1];
            if (!lastDivider || lastDivider.textContent !== dateStr) {
                const divider = document.createElement('div');
                divider.className = 'date-divider';
                divider.textContent = dateStr;
                chat.appendChild(divider);
            }
        }

        function addMessage(msg, prepend = false) {
            const dateStr = new Date(msg.time).toDateString();
            if (!prepend) addDateDivider(dateStr);
            const p = document.createElement('div');
            p.className = 'message';
            p.dataset.msgid = msg._id;
            p.innerHTML = `<span class="user">${msg.user}</span>: ${msg.message} <span class="time">${formatDateTime(msg.time)}</span>`;
            if (prepend) {
                chat.insertBefore(p, chat.firstChild);
                addDateDivider(dateStr);
            } else {
                chat.appendChild(p);
            }
        }

        function updateOnlineUsers(users) {
            onlineUsersList.innerHTML = '';
            userCountSpan.textContent = `${users.length} online: `;
            users.forEach(user => {
                const li = document.createElement('li');
                li.textContent = user;
                onlineUsersList.appendChild(li);
            });
        }

        function updateTypingIndicator(users) {
            typingIndicator.textContent = users.length === 0 ? '' :
                users.length === 1 ? `${users[0]} is typing...` :
                users.length === 2 ? `${users[0]} and ${users[1]} are typing...` :
                `${users[0]} and ${users.length - 1} others are typing...`;
        }

        async function loadMoreMessages() {
            if (isLoadingMessages) return;
            isLoadingMessages = true;
            try {
                const res = await fetch(`/messages?before=${encodeURIComponent(oldestMessageId || '')}`);
                const messages = await res.json();
                if (messages.length > 0) {
                    const scrollHeightBefore = chat.scrollHeight;
                    const scrollTopBefore = chat.scrollTop;
                    messages.forEach(msg => addMessage(msg, true));
                    if (messages.length < 20) return false;
                    chat.scrollTop = chat.scrollHeight - scrollHeightBefore + scrollTopBefore;
                    oldestMessageId = messages[messages.length - 1]._id;
                    return true;
                }
                return false;
            } catch (err) {
                console.error('Error loading more messages:', err);
                warningDiv.textContent = 'Error loading more messages.';
                warningDiv.classList.add('show');
                return false;
            } finally {
                isLoadingMessages = false;
            }
        }

        chat.addEventListener('scroll', () => {
            if (chat.scrollTop === 0 && !isLoadingMessages) {
                loadMoreMessages();
            }
            isManualScrolling = Math.abs(chat.scrollTop - lastScrollTop) > 10;
            lastScrollTop = chat.scrollTop;
        });

        form.addEventListener('submit', async e => {
            e.preventDefault();
            const user = usernameInput.value.trim();
            const msg = messageInput.value.trim();
            if (!user || !msg) {
                warningDiv.textContent = 'Please enter both username and message.';
                warningDiv.classList.add('show');
                return;
            }

            try {
                const checkRes = await fetch('/check_username', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username: user})
                });
                const checkData = await checkRes.json();
                if (!checkData.available) {
                    warningDiv.textContent = checkData.error || 'Username already taken. Please pick another.';
                    warningDiv.classList.add('show');
                    usernameInput.focus();
                    return;
                }

                socket.emit('send_message', { user, message: msg });
                warningDiv.textContent = '';
                warningDiv.classList.remove('show');
                messageInput.value = '';
                messageInput.focus();
                isManualScrolling = false;
            } catch (err) {
                console.error('Network error:', err);
                warningDiv.textContent = 'Network error. Please try again.';
                warningDiv.classList.add('show');
            }
        });
    </script>
</body>
</html>
"""

# Utility Functions
def sanitize_input(text):
    """Sanitize input and remove problematic characters"""
    if not isinstance(text, str):
        return ''
    text = re.sub(r'[\x00-\x1F\x7F-\x9F"\']', '', text)
    text = text.encode('ascii', 'ignore').decode('ascii')
    bleach = get_bleach()
    return bleach.clean(text, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)

def validate_username(username):
    """Validate username format"""
    return bool(re.match(r'^[a-zA-Z0-9_]{1,20}$', username))

def serialize_mongo_doc(doc):
    """Convert MongoDB document to JSON-serializable format"""
    doc_copy = dict(doc)
    if '_id' in doc_copy:
        doc_copy['_id'] = str(doc_copy['_id'])
    if 'user_id' in doc_copy:
        doc_copy['user_id'] = str(doc_copy['user_id'])
    return doc_copy

# Flask App Setup
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*")

# Error Handlers
@app.errorhandler(NotFound)
def handle_not_found(error):
    if request.path == '/.well-known/appspecific/com.chrome.devtools.json':
        return jsonify({"error": "Not found"}), 404
    app.logger.error(f"Not found: {error}")
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(Exception)
def handle_error(error):
    app.logger.error(f"Unhandled error: {error}")
    return jsonify({"error": "Internal server error"}), 500

# Routes
@app.route("/")
def index():
    try:
        user_id = request.cookies.get("user_id")
        if not user_id:
            user_id = str(uuid4())
            resp = make_response(render_template_string(HTML))
            resp.set_cookie("user_id", user_id, max_age=365*24*60*60, httponly=True, samesite="Lax")
            return resp
        return render_template_string(HTML)
    except Exception as e:
        app.logger.error(f"Error in index: {e}")
        raise InternalServerError()

@app.route("/check_username", methods=["POST"])
def check_username():
    try:
        data = request.json or {}
        username = sanitize_input(data.get("username", "").strip()[:20])
        if not validate_username(username):
            return jsonify({"available": False, "error": "Invalid username format. Use letters, numbers, or underscores (max 20 chars)."})
        with usernames_lock:
            user_id = request.cookies.get("user_id")
            if username in active_usernames.values() and active_usernames.get(user_id) != username:
                return jsonify({"available": False, "error": "Username already taken"})
            return jsonify({"available": True})
    except Exception as e:
        app.logger.error(f"Error in check_username: {e}")
        raise InternalServerError()

@app.route("/messages", methods=["GET"])
def get_messages():
    try:
        before = request.args.get("before")
        query = {}
        if before and before.strip():
            try:
                query = {"_id": {"$lt": ObjectId(before)}}
            except Exception as e:
                app.logger.error(f"Invalid before ID: {before}, Error: {e}")
                return jsonify({"error": "Invalid before parameter"}), 400
        messages = messages_col.find(query).sort("_id", -1).limit(20)
        result = [serialize_mongo_doc(msg) for msg in messages]
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Error in get_messages: {e}")
        raise InternalServerError()

# SocketIO Handlers
@socketio.on('check_username')
def handle_check_username(data):
    try:
        username = sanitize_input(data.get('username', '').strip()[:20])
        user_id = request.cookies.get('user_id')
        if not user_id:
            emit('username_response', {'available': False, 'error': 'Missing user_id cookie'})
            return
        if not validate_username(username):
            emit('username_response', {'available': False, 'error': 'Invalid username format'})
            return
        with usernames_lock:
            if username in active_usernames.values() and active_usernames.get(user_id) != username:
                emit('username_response', {'available': False, 'error': 'Username already taken'})
            else:
                active_usernames[user_id] = username
                for attempt in range(3):
                    try:
                        users_col.update_one(
                            {"user_id": user_id},
                            {"$set": {"username": username, "last_seen": datetime.now(UTC)}},
                            upsert=True
                        )
                        break
                    except PyMongoError as e:
                        if attempt == 2:
                            app.logger.error(f"Failed to update user after retries: {e}")
                            emit('username_response', {'available': False, 'error': 'Server error'})
                            return
                        time.sleep(0.1)
                emit('username_response', {'available': True})
                with clients_lock:
                    socketio.emit('online_users', {'type': 'online_users', 'users': list(set(active_usernames.values()))})
    except Exception as e:
        app.logger.error(f"Error in handle_check_username: {e}")
        emit('username_response', {'available': False, 'error': 'Server error'})

@socketio.on('send_message')
def handle_send_message(data):
    try:
        user_id = request.cookies.get('user_id')
        if not user_id:
            emit('error', {'error': 'Missing user_id cookie'})
            return

        username = sanitize_input(data.get('user', '').strip()[:20])
        message = sanitize_input(data.get('message', '').strip()[:200])
        
        if not validate_username(username) or not message:
            emit('error', {'error': 'Invalid input'})
            return

        import time
        now = time.time()
        last_time = rate_limit.get(user_id, 0)
        if now - last_time < RATE_LIMIT_SECONDS:
            emit('error', {'error': 'Please wait before sending another message'})
            return

        with usernames_lock:
            if username not in active_usernames.values() or active_usernames.get(user_id) == username:
                active_usernames[user_id] = username
                for attempt in range(3):
                    try:
                        users_col.update_one(
                            {"user_id": user_id},
                            {"$set": {"username": username, "last_seen": datetime.now(UTC)}},
                            upsert=True
                        )
                        break
                    except PyMongoError as e:
                        if attempt == 2:
                            app.logger.error(f"Failed to update user after retries: {e}")
                            emit('error', {'error': 'Server error'})
                            return
                        time.sleep(0.1)

        rate_limit[user_id] = now
        message_id = ObjectId()
        
        msg_data = {
            "_id": message_id,
            "user_id": user_id,
            "user": username,
            "message": message,
            "time": int(now * 1000)
        }

        for attempt in range(3):
            try:
                messages_col.insert_one(msg_data)
                break
            except PyMongoError as e:
                if attempt == 2:
                    app.logger.error(f"Failed to insert message after retries: {e}")
                    emit('error', {'error': 'Server error'})
                    return
                time.sleep(0.1)

        with clients_lock:
            socketio.emit('message', {'type': 'message', 'message': serialize_mongo_doc(msg_data)})
            socketio.emit('online_users', {'type': 'online_users', 'users': list(set(active_usernames.values()))})
    except Exception as e:
        app.logger.error(f"Error in handle_send_message: {e}")
        emit('error', {'error': 'Server error'})

@socketio.on('typing')
def handle_typing(data):
    try:
        user_id = request.cookies.get('user_id')
        if not user_id or user_id not in active_usernames:
            return
        username = active_usernames.get(user_id)
        with typing_users_lock:
            if data.get('isTyping', False):
                typing_users.add(username)
            else:
                typing_users.discard(username)
            socketio.emit('typing', {'type': 'typing', 'users': list(typing_users)})
    except Exception as e:
        app.logger.error(f"Error in handle_typing: {e}")

@socketio.on('heartbeat')
def handle_heartbeat():
    try:
        user_id = request.cookies.get('user_id')
        if user_id:
            with client_last_seen_lock:
                client_last_seen[user_id] = datetime.now(UTC)
    except Exception as e:
        app.logger.error(f"Error in handle_heartbeat: {e}")

@socketio.on('connect')
def handle_connect():
    try:
        user_id = request.cookies.get('user_id')
        if user_id:
            with clients_lock:
                clients.add(request.sid)
            with client_last_seen_lock:
                client_last_seen[user_id] = datetime.now(UTC)
    except Exception as e:
        app.logger.error(f"Error in handle_connect: {e}")

@socketio.on('disconnect')
def handle_disconnect():
    try:
        user_id = request.cookies.get('user_id')
        if user_id:
            with clients_lock:
                clients.discard(request.sid)
            with typing_users_lock:
                if user_id in active_usernames:
                    typing_users.discard(active_usernames[user_id])
                    socketio.emit('typing', {'type': 'typing', 'users': list(typing_users)})
    except Exception as e:
        app.logger.error(f"Error in handle_disconnect: {e}")

# Cleanup Task
def cleanup_inactive_users():
    import time
    while True:
        try:
            time.sleep(60)
            with client_last_seen_lock:
                threshold = datetime.now(UTC) - timedelta(seconds=30)
                inactive_ids = [user_id for user_id, last_seen in client_last_seen.items() if last_seen < threshold]
                for user_id in inactive_ids:
                    with usernames_lock:
                        if user_id in active_usernames:
                            username = active_usernames[user_id]
                            del active_usernames[user_id]
                            with typing_users_lock:
                                typing_users.discard(username)
                    del client_last_seen[user_id]
                if inactive_ids:
                    for attempt in range(3):
                        try:
                            users_col.delete_many({"user_id": {"$in": inactive_ids}})
                            break
                        except PyMongoError as e:
                            if attempt == 2:
                                app.logger.error(f"Failed to delete inactive users after retries: {e}")
                            time.sleep(0.1)
                with clients_lock:
                    socketio.emit('online_users', {'type': 'online_users', 'users': list(set(active_usernames.values()))})
                    socketio.emit('typing', {'type': 'typing', 'users': list(typing_users)})
        except Exception as e:
            app.logger.error(f"Error in cleanup_inactive_users: {e}")
            time.sleep(10)

# Start Application
if __name__ == "__main__":
    threading.Thread(target=cleanup_inactive_users, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))  # Use Vercel's PORT env variable
    socketio.run(app, host='0.0.0.0', port=port)
