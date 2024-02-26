# https_server.py

import argparse
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from ssl import PROTOCOL_TLS_SERVER, SSLContext
import ssl

def main(args):
    #ssl_context = SSLContext(PROTOCOL_TLS_SERVER)
    #ssl_context.load_cert_chain(SelfSignedCertificate(args.host).path)
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(certfile="server.crt", keyfile="ca.key")
    server = HTTPServer((args.host, args.port), SimpleHTTPRequestHandler)
    server.socket = ssl_context.wrap_socket(server.socket, server_side=True)
    webbrowser.open(f"https://{args.host}:{args.port}/")
    server.serve_forever()

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8444)
    return parser.parse_args()

if __name__ == "__main__":
    main(parse_args())
