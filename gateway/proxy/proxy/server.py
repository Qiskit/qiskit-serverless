import socket
import ssl
import headerparser
import threading
import certifi
import gzip
import json
import requests
import logging

HOST = "127.0.0.1"
PORT = 8443


logging.basicConfig(level=logging.DEBUG)


class Flag:
    def __init__(self, request):
        self.request = request
        self.id = None


def process_connection(connection):
    logging.debug("Recieving data")
    data = connection.recv(1024)
    if not data:
        logging.debug("no data")
        return
        logging.debug("data received from client")
    logging.debug("Received: %s", data)
    parser = headerparser.HeaderParser()
    parser.add_field("Host", required=True)
    parser.add_field("X-Qx-Client-Application", required=False)
    parser.add_additional()
    _, headers = data.decode("utf-8").split("\r\n", 1)
    msg = parser.parse(headers)
    host = msg["Host"].split(":", -1)
    logging.debug("Target address: %s", host[0])
    flag = Flag(False)
    if "X-Qx-Client-Application" in msg:
        pos = msg["X-Qx-Client-Application"].find("middleware_job_id")
        if pos != -1:
            flag.id = msg["X-Qx-Client-Application"][
                pos + len("middleware_job_id/") : pos + len("middleware_job_id/") + 36
            ]
            logging.debug("Runtime Job ID: %s", flag.id)

    c_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    c_context.load_verify_locations(certifi.where())
    client_s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client = c_context.wrap_socket(client_s, server_hostname=host[0])

    logging.debug("connecting backend")
    client.connect((host[0], 443))
    logging.debug("connected")
    client.sendall(data)
    logging.debug("data sent to backend")
    t = threading.Thread(
        target=process_from_backend,
        args=(
            client,
            connection,
            flag,
        ),
    )
    t.start()
    t = threading.Thread(
        target=process_from_program,
        args=(
            connection,
            client,
            flag,
        ),
    )
    t.start()
    logging.debug("piping threads created")


def process_from_backend(client, connection, flag):
    parser = headerparser.HeaderParser()
    parser.add_field("Content-Type", required=False)
    parser.add_field("Transfer-Encoding", required=False)
    parser.add_field("Content-Encoding", required=False)
    parser.add_field("Connection", required=False)
    parser.add_additional()
    alldata = b""
    in_header = True

    while True:
        data = client.recv(4096)
        if not data:
            logging.debug("no data")
            break
        logging.debug("data received from backend")
        # logging.debug("Received: %s", data)
        connection.send(data)
        logging.debug("Job requested %s", flag.request)
        if not flag.request:
            continue
        alldata = alldata + data
        if in_header:
            _, headers = alldata.split(b"\x0d\x0a", 1)
            if headers.find(b"\x0d\x0a\x0d\x0a") != -1:
                headers, _ = headers.split(b"\x0d\x0a\x0d\x0a", 1)
            if headers:
                msg = parser.parse(headers.decode("utf-8"))
                logging.debug(
                    "Received header from backend: %s", headers.decode("utf-8")
                )
                in_header = False
                if (
                    not "Content-Encoding" in msg
                    or not msg["Content-Encoding"] == "gzip"
                ):
                    logging.debug("Received: %s", alldata)
        if data.find(b"0\r\n\r\n") != -1:
            logging.debug("end of chunked data received from backend")
            if "Content-Encoding" in msg and msg["Content-Encoding"] == "gzip":
                logging.debug(
                    "Flags: %s",
                    gzip.decompress(
                        alldata.split(b"\r\n\r\n", 2)[1].split(b"\r\n", 2)[1]
                    ),
                )
                if flag.request:
                    jsondata = json.loads(
                        gzip.decompress(
                            alldata.split(b"\r\n\r\n", 2)[1].split(b"\r\n", 2)[1]
                        ).decode("utf-8")
                    )
                    logging.debug("job id: %s", jsondata["id"])
                    logging.debug("middleware job id: %s", flag.id)
                    token = "awesome_token"
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {token}",
                    }
                    logging.debug("Issue add_runtimejob")
                    r = requests.post(
                        f"http://gateway:8000/api/v1/jobs/{flag.id}/add_runtimejob/",
                        headers=headers,
                        json={"runtime_job": jsondata["id"]},
                    )
                    logging.debug("Response: %s", r)
                    flag.request = False
            if not "Connection" in msg or not msg["Connection"] == "keep-alive":
                break
            in_header = True
            alldata = b""
    logging.debug("Receive from backend completed")


def process_from_program(connection, client, flag):
    while True:
        data = connection.recv(1024)
        if not data:
            logging.debug("no data")
            break
        logging.debug("data received from program")
        logging.debug("Received: %s", data)
        client.sendall(data)
        if data.find(b"POST /runtime/jobs") != -1:
            flag.request = True
        logging.debug("Job requested: %s", flag.request)
    logging.debug("receive from program completed")


if __name__ == "__main__":
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(
        certfile="/etc/ray/tls/tls.crt", keyfile="/etc/ray/tls/tls.key"
    )
    context.load_verify_locations(cafile="/etc/ca/tls/ca.crt")
    context.verify_mode = ssl.CERT_NONE

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server = context.wrap_socket(s)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.close()

    server.bind((HOST, PORT))
    server.listen(0)

    while True:
        logging.debug("Waiting for new connection")
        try:
            connection, client_address = server.accept()
        except ssl.SSLError as e:
            print(e)
            continue
        logging.debug("New connection")
        t = threading.Thread(target=process_connection, args=(connection,))
        t.start()
