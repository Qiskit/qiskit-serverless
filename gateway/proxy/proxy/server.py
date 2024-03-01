import socket
import ssl
import headerparser
import threading
import certifi
import gzip
import json
import requests

HOST = "127.0.0.1"
PORT = 8443

class Flag:
    def __init__(self, request):
        self.request = request
        self.done = False
        self.id = None

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
    parser.add_field('X-Qx-Client-Application', required=False)
    parser.add_additional()
    _, headers = data.decode('utf-8').split('\r\n', 1)
    msg = parser.parse(headers)
    host = msg["Host"].split(":", -1)
    print(host[0])
    flag = Flag(False)
    if "X-Qx-Client-Application" in msg:
        pos = msg["X-Qx-Client-Application"].find("middleware_job_id")
        if pos != -1:
            flag.id = msg["X-Qx-Client-Application"][pos+len("middleware_job_id/"):pos+len("middleware_job_id/")+36]
            print(flag.id)

    c_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    c_context.load_verify_locations(certifi.where())
    client_s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client = c_context.wrap_socket(client_s, server_hostname=host[0])

    print("connecting backend")
    client.connect((host[0], 443))
    print("connected")
    client.sendall(data)
    print("data sent to backend")
    t = threading.Thread(target=process_from_backend, args=(client, connection, flag, ))
    t.start()
    t = threading.Thread(target=process_from_program, args=(connection, client, flag,  ))
    t.start()
    print("piping threads created")

def process_from_backend(client, connection, flag):
    parser = headerparser.HeaderParser()
    parser.add_field('Content-Type', required=False)
    parser.add_field('Transfer-Encoding', required=False)
    parser.add_field('Content-Encoding', required=False)
    parser.add_field('Connection', required=False)
    parser.add_additional()
    alldata = b''
    in_header = True
    
    while True:
        data = client.recv(4096)
        if not data:
            print("no data")
            break
        print("data received from backend")
        #print(f"Received: {data}")
        connection.send(data)
        print(flag.request)
        if not flag.request or flag.done:
            continue
        alldata = alldata+data
        if in_header :
            _, headers = alldata.split(b'\x0d\x0a', 1)
            if headers.find(b'\x0d\x0a\x0d\x0a') != -1:
                headers, _ = headers.split(b'\x0d\x0a\x0d\x0a', 1)
            if headers:
                msg = parser.parse(headers.decode('utf-8'))
                print(f"Received header from backend: {headers.decode('utf-8')}")
                in_header = False
                if not "Content-Encoding" in msg or not msg["Content-Encoding"] == "gzip":
                    print(f"Received: {alldata}")
        if data.find(b'0\r\n\r\n') != -1:
            print("end of chunked data received from backend")
            # print(alldata)
            if "Content-Encoding" in msg and msg["Content-Encoding"] == "gzip":
                print(gzip.decompress(alldata.split(b'\r\n\r\n',2)[1].split(b'\r\n',2)[1]))
                if flag.request:
                    jsondata = json.loads(gzip.decompress(alldata.split(b'\r\n\r\n',2)[1].split(b'\r\n',2)[1]).decode("utf-8"))
                    print(f"job id: {jsondata['id']}")
                    print(f"middleware job id: {flag.id}")
                    token = "awesome_token"
                    headers =  {"Content-Type":"application/json", "Authorization": f"Bearer {token}"}
                    print("Issue add_runtimejob")
                    r = requests.post(f"http://gateway:8000/api/v1/jobs/{flag.id}/add_runtimejob/", headers = headers, json = {"runtime_job": jsondata['id']})
                    print(r)
                    flag.done = True
            if not "Connection" in msg or not msg["Connection"] == "keep-alive":
                break
            in_header = True
            alldata = b''
    print("receive from backend completed")

def process_from_program(connection, client, flag):
    while True:
        data = connection.recv(1024)
        if not data:
            print("no data")
            break
        print("data received from program")
        print(f"Received: {data}")
        client.sendall(data)
        if flag.done:
            continue
        if data.find(b'POST /runtime/jobs') != -1:
            flag.request = True
        print(flag.request)
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
