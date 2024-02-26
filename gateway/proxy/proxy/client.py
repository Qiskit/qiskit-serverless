# use curl instead of this 
# curl https://127.0.0.1:8443/ca.crt -s --cacert ca.crt -v
#
import socket
import ssl
import time

HOST = "127.0.0.1"
PORT = 8443

if __name__ == "__main__":
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_cert_chain(certfile="client.crt", keyfile="ca.key")
    context.load_verify_locations(cafile="ca.crt")
    
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client = context.wrap_socket(s, server_hostname=HOST)
    s.close()

    client.connect((HOST, PORT))

    #while True:
    client.sendall("Hello World!".encode("utf-8"))
    #    time.sleep(1)
    client.close()
