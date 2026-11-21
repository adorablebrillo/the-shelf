#!/usr/bin/env python3
"""Serve the Christmas journey beside a locally served made-up Shelf.

Start the verification skill's server first, then run this file and open
http://127.0.0.1:8812/journey in the task browser. The proxy is local only.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

JOURNEY = Path(__file__).with_name('christmas-scene.html')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/journey':
            data = JOURNEY.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(data)
        else:
            self.forward()

    def do_POST(self):
        self.forward(self.rfile.read(int(self.headers.get('Content-Length', '0'))))

    def forward(self, body=None):
        request = Request('http://127.0.0.1:8811' + self.path, data=body,
                          headers={'Content-Type': self.headers.get('Content-Type', 'application/json')},
                          method=self.command)
        try:
            with urlopen(request) as response:
                self.send_response(response.status)
                self.send_header('Content-Type', response.headers.get('Content-Type', 'application/octet-stream'))
                self.end_headers()
                self.wfile.write(response.read())
        except HTTPError as error:
            self.send_error(error.code)


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', 8812), Handler).serve_forever()
