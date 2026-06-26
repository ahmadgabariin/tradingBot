import http.server
import socketserver
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()
    def log_message(self, format, *args):
        pass

with socketserver.TCPServer(("", 8080), NoCacheHandler) as httpd:
    httpd.serve_forever()
