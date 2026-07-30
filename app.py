from flask import Flask
import threading
import asyncio
import os

app = Flask(__name__)

# Import your EA bot
from grid_ea_alminshar import main as run_bot

def start_bot():
    print("Starting AlMinshar EA Background Thread...")
    asyncio.run(run_bot())

@app.route('/')
def health_check():
    return "AlMinshar Grid EA is running continuously.", 200

if __name__ == "__main__":
    # Start bot in a background thread so it doesn't block Flask
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
    
    # Cloud Run expects the app to listen on port 8080 or the PORT env var
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
