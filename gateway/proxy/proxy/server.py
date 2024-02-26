import socket
import ssl
import headerparser
import threading

HOST = "127.0.0.1"
PORT = 8443

def process_connection(connection):
    while True:
        print("Recieving data")
        data = connection.recv(1024)
        if not data:
            print("no data")
            break
        print(f"Received: {data.decode('utf-8')}")
        print(data)
        parser = headerparser.HeaderParser()
        parser.add_field('Host', required=True)
        parser.add_field('Accept', required=False)
        parser.add_field('User-Agent', required=False)
        parser.add_field('Content-length', required=False)
        parser.add_field('Content-type', required=False)
        _, headers = data.decode('utf-8').split('\r\n', 1)
        msg = parser.parse(headers)
        host = msg["Host"].split(":", -1)
        print(host[0])
        print(host[1])


        c_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        c_context.load_cert_chain(certfile="client.crt", keyfile="ca.key")
        c_context.load_verify_locations(cafile="ca.crt")
    
        client_s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client = c_context.wrap_socket(client_s, server_hostname=HOST)
        client_s.close()

        #client.connect((HOST, 8444))
        if host[0] == HOST and int(host[1]) == PORT:
            client.connect((HOST, 8444))
        else:
            client.connect((host[0], int(host[1])))

        #while True:
        #client.sendall("Hello World!".encode("utf-8"))
        client.sendall(data)
        data = client.recv(4096)
        connection.send(data)
        print(f"Received: {data.decode('utf-8')}")
        break
    print("receive completed")




if __name__ == "__main__":
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile="server.crt", keyfile="ca.key")
    context.load_verify_locations(cafile="ca.crt")
    context.verify_mode = ssl.CERT_NONE

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server = context.wrap_socket(s)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    s.close()
    
    c_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    c_context.verify_mode = ssl.CERT_NONE
    c_context.load_cert_chain(certfile="client.crt", keyfile="ca.key")
    c_context.load_verify_locations(cafile="ca.crt")

    client_s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client = c_context.wrap_socket(client_s, server_hostname=HOST)

    client_s.close()

    server.bind((HOST, PORT))
    server.listen(0)

    while True:
        connection, client_address = server.accept()
        print("new connection")
        t = threading.Thread(target=process_connection, args=(connection, ))
        t.start()

