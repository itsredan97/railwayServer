import os
import asyncio
import websockets

PORT = int(os.environ.get("PORT", 5000))
clients = set()
clients_keys = dict()  # websocket -> public key PEM

async def handler(websocket):
    clients.add(websocket)
    try:
        async for message in websocket:
            # Se è una chiave pubblica
            if message.startswith("-----BEGIN PUBLIC KEY-----"):
                clients_keys[websocket] = message
                # Invia questa chiave al nuovo client per tutti gli altri già connessi
                for client, key in clients_keys.items():
                    if client != websocket:
                        await websocket.send(key)
            else:
                # Invia il messaggio a tutti gli altri client
                for client in clients:
                    if client != websocket:
                        await client.send(message)
    except websockets.ConnectionClosed:
        pass
    finally:
        clients.remove(websocket)
        clients_keys.pop(websocket, None)

async def main():
    async with websockets.serve(handler, "0.0.0.0", PORT):
        print(f" Server WebSocket avviato sulla porta {PORT}")
        await asyncio.Future()  # Mantiene il server vivo

if __name__ == "__main__":
    asyncio.run(main())
