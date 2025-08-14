import os
import asyncio
import websockets

PORT = int(os.environ.get("PORT", 5000))
clients = set()

async def handler(websocket, path):
    clients.add(websocket)
    try:
        async for message in websocket:
            # Invia il messaggio a tutti gli altri client
            for client in clients:
                if client != websocket:
                    await client.send(message)
    except:
        pass
    finally:
        clients.remove(websocket)

start_server = websockets.serve(handler, "0.0.0.0", PORT)

print(f"Server WebSocket avviato sulla porta {PORT}")
asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()

