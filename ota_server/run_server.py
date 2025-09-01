from http.server import HTTPServer, SimpleHTTPRequestHandler

SECRET_TOKEN = "wU^vftkBgipMlYO#PkF%!bFE4F@61y8Z"

class AuthHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        auth = self.headers.get("Authorization")
        if auth == f"Bearer {SECRET_TOKEN}":
            super().do_GET()
        else:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"Forbidden: Invalid token")

PORT = 8788
httpd = HTTPServer(("", PORT), AuthHandler)
print(f"Serving on port {PORT}")
httpd.serve_forever()