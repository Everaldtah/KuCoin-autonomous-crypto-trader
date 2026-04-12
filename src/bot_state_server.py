#!/usr/bin/env python3
"""
Simple HTTP server to expose bot state to the dashboard
Serves bot_state.json to external requests
"""

import json
import http.server
import socketserver
import os
from datetime import datetime

PORT = 8080
STATE_FILE = os.environ.get("DASHBOARD_STATE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "bot_state.json"))

class BotStateHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/bot-state' or self.path == '/bot-state.json':
            try:
                if os.path.exists(STATE_FILE):
                    with open(STATE_FILE, 'r') as f:
                        data = json.load(f)
                    
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')  # Allow CORS
                    self.end_headers()
                    self.wfile.write(json.dumps(data).encode())
                else:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Bot state not found"}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not Found')
    
    def log_message(self, format, *args):
        pass  # Suppress default logging

if __name__ == "__main__":
    print(f"🚀 Bot State Server starting on port {PORT}")
    print(f"📡 Serving: http://0.0.0.0:{PORT}/bot-state")
    
    try:
        with socketserver.TCPServer(("0.0.0.0", PORT), BotStateHandler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Server stopped")
    except Exception as e:
        print(f"❌ Error: {e}")
