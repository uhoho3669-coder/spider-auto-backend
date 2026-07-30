from http.server import BaseHTTPRequestHandler
import json
import asyncio
import sys
import os

# Add parent directory to path so we can import grid_ea_alminshar
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from grid_ea_alminshar import run_all_users
except Exception as e:
    run_all_users = None
    print(f"Error loading bot: {e}")

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if run_all_users:
                # Run the grid sync once for all users
                asyncio.run(run_all_users())
                
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok', 'message': 'Grid synced successfully'}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode())
