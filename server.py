import os
import asyncio
import websockets

PORT = int(os.environ.get("PORT", 5000))

clients = set()
client_keys = {}  # mappa websocket -> chiave pubblica

async def handler(websocket):
    clients.add(websocket)
    print(f"[Sistema] Nuovo client connesso. Client totali: {len(clients)}")

    # Invia le chiavi già presenti al nuovo client
    for key_ws, key_data in client_keys.items():
        try:
            await websocket.send(f"[SYSTEM_KEY]{key_data}")
        except:
            pass

    try:
        async for message in websocket:
            if message.startswith("[SYSTEM_KEY]"):
                # Salva la chiave pubblica del client
                key_data = message[len("[SYSTEM_KEY]"):]
                client_keys[websocket] = key_data
                print(f"[Sistema] Chiave pubblica ricevuta. Client con chiave: {len(client_keys)}")
                
                # Invia questa chiave a tutti gli altri client
                for client in clients:
                    if client != websocket:
                        await client.send(message)
            else:
                # Messaggio normale: inoltra a tutti tranne mittente
                for client in clients:
                    if client != websocket:
                        await client.send(message)
    except websockets.ConnectionClosed:
        pass
    finally:
        clients.remove(websocket)
        if websocket in client_keys:
            del client_keys[websocket]
        print(f"[Sistema] Client disconnesso. Client totali: {len(clients)}")

async def main():
    async with websockets.serve(handler, "0.0.0.0", PORT):
        print(f"[Sistema] Server WebSocket avviato sulla porta {PORT}")
        await asyncio.Future()  # Mantiene il server vivo

if __name__ == "__main__":
    asyncio.run(main())
