#!/usr/bin/env python3
"""
Simple HTTP server that receives and logs Asterisk call events.
Run this before making calls. All POSTed events are printed and saved to a log file.
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
from datetime import datetime
import sys
import os

LOG_FILE = os.path.expanduser('~/asterisk-test/results/call_events.log')
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

class EventHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8', errors='replace')
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]

        # Try to parse as JSON, fall back to raw
        try:
            data = json.loads(body)
            display = json.dumps(data, indent=2)
        except json.JSONDecodeError:
            data = body
            display = body

        # Color-coded console output
        event_type = data.get('event', '?') if isinstance(data, dict) else '?'
        colors = {
            'ringing': '\033[93m',    # yellow
            'answered': '\033[92m',   # green
            'hangup': '\033[91m',     # red
            'dial_start': '\033[96m', # cyan
            'dial_result': '\033[95m',# magenta
        }
        color = colors.get(event_type, '\033[0m')
        reset = '\033[0m'

        print(f"\n{color}[{timestamp}] === {event_type.upper()} ==={reset}")
        print(f"{display}")
        print(f"{color}{'='*40}{reset}")

        # Append to log file
        with open(LOG_FILE, 'a') as f:
            f.write(f"[{timestamp}] {json.dumps(data) if isinstance(data, dict) else data}\n")

        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')

    def log_message(self, format, *args):
        # Suppress default access logs
        pass

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    print(f"Event receiver listening on http://127.0.0.1:{port}")
    print(f"Logging to {LOG_FILE}")
    print(f"Waiting for call events...\n")
    server = HTTPServer(('127.0.0.1', port), EventHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
