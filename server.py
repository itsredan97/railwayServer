import os
import asyncio
import websockets

PORT = int(os.environ.get("PORT", 8080))

# Mappa websocket -> chiave pubblica
clients = {}
client_keys = {}
client_nicknames = {}

async def handler(websocket):
    try:
        # Riceve il nickname dal client
        nickname = await websocket.recv()
        client_nicknames[websocket] = nickname
        clients[websocket] = None
        print(f"[Sistema] Nuovo client connesso: {nickname}. Client totali: {len(clients)}")

        # Notifica tutti gli altri utenti
        for client in clients:
            if client != websocket:
                await client.send(f"[Sistema] L'utente {nickname} si è connesso!")

        async for message in websocket:
            # Se il messaggio è una chiave pubblica
            if message.startswith("-----BEGIN PUBLIC KEY-----"):
                client_keys[websocket] = message
                print(f"[Sistema] Chiave pubblica ricevuta da {nickname}. Client con chiave: {len(client_keys)}")

                # Invia questa chiave a tutti gli altri client
                for client in clients:
                    if client != websocket:
                        await client.send(message)

                # Invia tutte le chiavi già presenti al nuovo client
                for client, key in client_keys.items():
                    if client != websocket and key:
                        await websocket.send(key)

            else:
                # Messaggio normale: inoltra a tutti gli altri client
                for client in clients:
                    if client != websocket:
                        await client.send(message)

    except websockets.ConnectionClosed:
        pass
    finally:
        # Rimuove il client
        clients.pop(websocket, None)
        client_keys.pop(websocket, None)
        nick = client_nicknames.pop(websocket, "Utente sconosciuto")
        print(f"[Sistema] Client {nick} disconnesso. Client totali: {len(clients)}")

        # Notifica la disconnessione agli altri
        for client in clients:
            try:
                await client.send(f"[Sistema] L'utente {nick} si è disconnesso!")
            except:
                pass

async def main():
    async with websockets.serve(handler, "0.0.0.0", PORT):
        print(f"[Sistema] Server WebSocket avviato sulla porta {PORT}")
        await asyncio.Future()  # Mantiene il server vivo

if __name__ == "__main__":
    asyncio.run(main())
