import os
import asyncio
import websockets

PORT = int(os.environ.get("PORT", 8080))

# Map websocket -> chiave pubblica e nickname
clients = {}           # websocket -> nickname
client_keys = {}       # nickname -> chiave pubblica

async def disconnect_client(websocket):
    """Rimuove un client e notifica gli altri utenti"""
    nickname = clients.pop(websocket, None)
    if nickname:
        client_keys.pop(nickname, None)
        print(f"[Sistema] Client {nickname} disconnesso. Client totali: {len(clients)}")
        for client in clients:
            try:
                await client.send(f"[Sistema] L'utente {nickname} si è disconnesso!")
            except:
                pass

async def handler(websocket):
    try:
        # Riceve il nickname
        nickname = await websocket.recv()

        # Se nickname già connesso, disconnetti il vecchio websocket
        for ws, nick in list(clients.items()):
            if nick == nickname:
                await disconnect_client(ws)

        # Aggiungi nuovo client
        clients[websocket] = nickname
        print(f"[Sistema] Nuovo client connesso: {nickname}. Client totali: {len(clients)}")

        # Notifica tutti gli altri utenti
        for client in clients:
            if client != websocket:
                await client.send(f"[Sistema] L'utente {nickname} si è connesso!")

        async for message in websocket:
            # Chiave pubblica
            if message.startswith("-----BEGIN PUBLIC KEY-----"):
                client_keys[nickname] = message
                print(f"[Sistema] Chiave pubblica ricevuta da {nickname}. Totale chiavi: {len(client_keys)}")

                # Invia la chiave pubblica appena ricevuta a tutti gli altri
                for client in clients:
                    if client != websocket:
                        await client.send(message)

                # Invia tutte le chiavi esistenti al nuovo client
                for other_nick, key in client_keys.items():
                    if other_nick != nickname:
                        await websocket.send(key)
            else:
                # Messaggio normale: inoltra a tutti gli altri client
                for client in clients:
                    if client != websocket:
                        await client.send(message)

    except websockets.ConnectionClosed:
        pass
    finally:
        await disconnect_client(websocket)

async def main():
    async with websockets.serve(handler, "0.0.0.0", PORT):
        print(f"[Sistema] Server WebSocket avviato sulla porta {PORT}")
        await asyncio.Future()  # Mantiene il server vivo

if __name__ == "__main__":
    asyncio.run(main())
