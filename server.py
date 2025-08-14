import os
import asyncio
import websockets

PORT = int(os.environ.get("PORT", 5000))
clients = set()
clients_keys = dict()  # websocket -> public key PEM

async def handler(websocket):
    clients.add(websocket)
    print(f"[Sistema] Nuovo client connesso. Client totali: {len(clients)}")
    try:
        async for message in websocket:
            # Se è una chiave pubblica
            if message.startswith("-----BEGIN PUBLIC KEY-----"):
                clients_keys[websocket] = message
                print(f"[Sistema] Chiave pubblica ricevuta da un client. Client con chiave: {len(clients_keys)}")
                
                # Invia al nuovo client tutte le chiavi già presenti
                for client, key in clients_keys.items():
                    if client != websocket:
                        await websocket.send(key)
            else:
                # Invia il messaggio a tutti gli altri client
                for client in clients:
                    if client != websocket:
                        await client.send(message)
    except websockets.ConnectionClosed:
        print(f"[Sistema] Client disconnesso. Client rimanenti: {len(clients)-1}")
    finally:
        clients.remove(websocket)
        if websocket in clients_keys:
            clients_keys.pop(websocket)
            print(f"[Sistema] Chiave pubblica rimossa. Client con chiave: {len(clients_keys)}")

async def main():
    async with websockets.serve(handler, "0.0.0.0", PORT):
        print(f"[Sistema] Server WebSocket avviato sulla porta {PORT}")
        await asyncio.Future()  # Mantiene il server vivo

if __name__ == "__main__":
    asyncio.run(main())

