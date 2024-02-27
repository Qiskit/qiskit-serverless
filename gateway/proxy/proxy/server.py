import socket
import ssl
import headerparser
import threading
import certifi

HOST = "127.0.0.1"
PORT = 8443

def process_connection(connection):
    print("Recieving data")
    data = connection.recv(1024)
    if not data:
        print("no data")
        return
        print("data received from client")
    print(f"Received: {data}")
    parser = headerparser.HeaderParser()
    parser.add_field('Host', required=True)
    parser.add_field('Accept', required=False)
    parser.add_field('User-Agent', required=False)
    parser.add_field('Content-length', required=False)
    parser.add_field('Content-type', required=False)
    parser.add_field('Accept-Encoding')
    parser.add_field('Connection')
    parser.add_field('X-Qx-Client-Application')
    parser.add_field('X-Access-Token')
    _, headers = data.decode('utf-8').split('\r\n', 1)
    msg = parser.parse(headers)
    host = msg["Host"].split(":", -1)
    print(host[0])

    c_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    c_context.load_verify_locations(certifi.where())
    client_s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client = c_context.wrap_socket(client_s, server_hostname=host[0])

    print("connecting backend")
    client.connect((host[0], 443))
    print("connected")
    client.sendall(data)
    print("data sent to backend")
    t = threading.Thread(target=process_from_backend, args=(client, connection, ))
    t.start()
    t = threading.Thread(target=process_from_program, args=(connection, client, ))
    t.start()
    print("piping threads created")

def process_from_backend(client, connection):
    while True:
        data = client.recv(4096)
        if not data:
            print("no data")
            break
        print("data received from backend")
        print(f"Received: {data}")
        connection.send(data)
    print("receive from backend completed")

def process_from_program(connection, client):
    while True:
        data = connection.recv(1024)
        if not data:
            print("no data")
            break
        print("data received from program")
        print(f"Received: {data}")
        client.sendall(data)
    print("receive from program completed")

if __name__ == "__main__":
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile="/etc/ray/tls/tls.crt", keyfile="/etc/ray/tls/tls.key")
    context.load_verify_locations(cafile="/etc/ca/tls/ca.crt")
    context.verify_mode = ssl.CERT_NONE

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server = context.wrap_socket(s)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.close()
    
    server.bind((HOST, PORT))
    server.listen(0)

    while True:
        print("waiting for new connection")
        connection, client_address = server.accept()
        print("new connection")
        t = threading.Thread(target=process_connection, args=(connection, ))
        t.start()

