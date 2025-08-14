import os
import asyncio
import websockets

PORT = int(os.environ.get("PORT", 8080))

# Mappa websocket -> chiave pubblica
clients = {}
client_keys = {}

async def handler(websocket):
    # Aggiunge il client senza chiave inizialmente
    clients[websocket] = None
    print(f"[Sistema] Nuovo client connesso. Client totali: {len(clients)}")

    try:
        async for message in websocket:
            # Se il messaggio è una chiave pubblica
            if message.startswith("-----BEGIN PUBLIC KEY-----"):
                client_keys[websocket] = message
                print(f"[Sistema] Chiave pubblica ricevuta da un client. Client con chiave: {len(client_keys)}")

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
        print(f"[Sistema] Client disconnesso. Client totali: {len(clients)}")

async def main():
    async with websockets.serve(handler, "0.0.0.0", PORT):
        print(f"[Sistema] Server WebSocket avviato sulla porta {PORT}")
        await asyncio.Future()  # Mantiene il server vivo per sempre

if __name__ == "__main__":
    asyncio.run(main())
