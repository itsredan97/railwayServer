import socket
import threading

HOST = "0.0.0.0"
PORT = 5000

clients = []

def handle_client(conn, idx):
    while True:
        try:
            msg = conn.recv(4096)
            if not msg:
                break
            # Invia a tutti tranne il mittente
            for i, client in enumerate(clients):
                if i != idx:
                    try:
                        client.send(msg)
                    except:
                        pass
        except:
            break
    conn.close()
    print(f"Client {idx} disconnesso.")

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen(10)
print(f"Server avviato sulla porta {PORT}")

while True:
    conn, addr = server.accept()
    clients.append(conn)
    idx = len(clients) - 1
    print(f"Connesso: {addr}")
    threading.Thread(target=handle_client, args=(conn, idx), daemon=True).start()
