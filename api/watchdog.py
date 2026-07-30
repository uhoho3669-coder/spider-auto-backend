from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import os

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            # GitHub repo details
            repo = 'uhoho3669-coder/spider-auto-backend'
            workflow_id = 'bot_loop.yml'
            token = os.environ.get('GITHUB_PAT')
            
            if not token:
                raise Exception("GITHUB_PAT environment variable not found")
                
            # Check for active workflow runs
            url = f'https://api.github.com/repos/{repo}/actions/workflows/{workflow_id}/runs?status=in_progress'
            req = urllib.request.Request(url)
            req.add_header('Authorization', f'token {token}')
            req.add_header('Accept', 'application/vnd.github.v3+json')
            req.add_header('User-Agent', 'Vercel-Watchdog')
            
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                
            total_count = data.get('total_count', 0)
            
            if total_count == 0:
                # No active runs found, trigger the workflow
                trigger_url = f'https://api.github.com/repos/{repo}/actions/workflows/{workflow_id}/dispatches'
                trigger_body = json.dumps({'ref': 'master'}).encode()
                
                trigger_req = urllib.request.Request(trigger_url, data=trigger_body, method='POST')
                trigger_req.add_header('Authorization', f'token {token}')
                trigger_req.add_header('Accept', 'application/vnd.github.v3+json')
                trigger_req.add_header('User-Agent', 'Vercel-Watchdog')
                
                with urllib.request.urlopen(trigger_req, timeout=10) as trigger_resp:
                    if trigger_resp.status == 204:
                        msg = "Workflow was stopped. Successfully triggered a new run."
                    else:
                        msg = f"Failed to trigger workflow. Status: {trigger_resp.status}"
            else:
                msg = f"Workflow is already running ({total_count} active runs). No action needed."
                
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok', 'message': msg}).encode())
            
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'error', 'message': str(e)}).encode())
