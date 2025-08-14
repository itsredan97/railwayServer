import os
import asyncio
import websockets

PORT = int(os.environ.get("PORT", 8080))

# Map websocket -> nickname
clients = {}       # websocket -> nickname
client_keys = {}   # nickname -> chiave pubblica
nickname_to_ws = {}  # nickname -> websocket attuale

async def disconnect_client(websocket, notify=True):
    """Rimuove un client e notifica gli altri utenti"""
    nickname = clients.pop(websocket, None)
    if nickname:
        nickname_to_ws.pop(nickname, None)
        if notify:
            for client in clients:
                try:
                    await client.send(f"[Sistema] L'utente {nickname} si è disconnesso!")
                except websockets.ConnectionClosed:
                    continue
        print(f"[Sistema] Client {nickname} disconnesso. Client totali: {len(clients)}")

async def handler(websocket):
    try:
        # Riceve il nickname
        nickname = await websocket.recv()

        # Se nickname già connesso, disconnetti il vecchio websocket
        old_ws = nickname_to_ws.get(nickname)
        if old_ws:
            await disconnect_client(old_ws, notify=True)

        # Aggiungi nuovo client
        clients[websocket] = nickname
        nickname_to_ws[nickname] = websocket
        print(f"[Sistema] Nuovo client connesso: {nickname}. Client totali: {len(clients)}")

        # Notifica tutti gli altri utenti
        for client in clients:
            if client != websocket:
                try:
                    await client.send(f"[Sistema] L'utente {nickname} si è connesso!")
                except websockets.ConnectionClosed:
                    continue

        async for message in websocket:
            # Chiave pubblica
            if message.startswith("-----BEGIN PUBLIC KEY-----"):
                client_keys[nickname] = message
                print(f"[Sistema] Chiave pubblica ricevuta da {nickname}. Totale chiavi: {len(client_keys)}")

                # Invia la chiave pubblica appena ricevuta a tutti gli altri
                for client in clients:
                    if client != websocket:
                        try:
                            await client.send(message)
                        except websockets.ConnectionClosed:
                            continue

                # Invia tutte le chiavi esistenti al nuovo client
                for other_nick, key in client_keys.items():
                    if other_nick != nickname:
                        try:
                            await websocket.send(key)
                        except websockets.ConnectionClosed:
                            continue

            else:
                # Messaggio normale: inoltra a tutti gli altri client
                for client in clients:
                    if client != websocket:
                        try:
                            await client.send(message)
                        except websockets.ConnectionClosed:
                            continue

    except websockets.ConnectionClosed:
        pass
    except Exception as e:
        print(f"[Errore] {e}")
    finally:
        await disconnect_client(websocket)

async def main():
    async with websockets.serve(
        handler, 
        "0.0.0.0", 
        PORT, 
        ping_interval=20,   # invia ping ogni 20 secondi
        ping_timeout=20     # timeout se non riceve pong
    ):
        print(f"[Sistema] Server WebSocket avviato sulla porta {PORT}")
        await asyncio.Future()  # Mantiene il server vivo

if __name__ == "__main__":
    asyncio.run(main())
