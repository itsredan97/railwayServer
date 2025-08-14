import os
import asyncio
import websockets

PORT = int(os.environ.get("PORT", 5000))
clients = set()

async def handler(websocket):
    clients.add(websocket)
    try:
        async for message in websocket:
            # Invia il messaggio a tutti gli altri
            for client in clients:
                if client != websocket:
                    await client.send(message)
    except websockets.ConnectionClosed:
        pass
    finally:
        clients.remove(websocket)

async def main():
    async with websockets.serve(handler, "0.0.0.0", PORT):
        print(f" Server WebSocket avviato sulla porta {PORT}")
        await asyncio.Future()  # Mantiene il server vivo per sempre

if __name__ == "__main__":
    asyncio.run(main())

