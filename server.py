import os
import asyncio
import websockets
import hashlib
import json
import time

PORT = int(os.environ.get("PORT", 8080))

clients = {}             # websocket -> nickname
client_keys = {}         # nickname -> chiave pubblica PEM
nickname_to_ws = {}      # nickname -> websocket attuale
recent_messages = set()
MESSAGE_CACHE_TIME = 60  # secondi per cache duplicati

async def disconnect_client(websocket, notify=True):
    nickname = clients.pop(websocket, None)
    if nickname:
        nickname_to_ws.pop(nickname, None)
        client_keys.pop(nickname, None)
        if notify:
            await broadcast_system(f"L'utente {nickname} si è disconnesso!")
        print(f"[Sistema] Client {nickname} disconnesso. Totali: {len(clients)}")

async def broadcast_system(text):
    data = json.dumps({"type": "system", "text": text})
    await broadcast(data)

async def broadcast(message, exclude_ws=None):
    for client in list(clients.keys()):
        if client != exclude_ws:
            try:
                await client.send(message)
            except:
                continue

async def cleanup_message_cache():
    while True:
        now = time.time()
        to_remove = {m for m in recent_messages if now - m[1] > MESSAGE_CACHE_TIME}
        for m in to_remove:
            recent_messages.discard(m)
        await asyncio.sleep(10)

async def handler(websocket):
    try:
        nickname = await websocket.recv()

        # Disconnette sessione precedente con stesso nickname
        old_ws = nickname_to_ws.get(nickname)
        if old_ws:
            await disconnect_client(old_ws, notify=True)

        clients[websocket] = nickname
        nickname_to_ws[nickname] = websocket

        print(f"[Sistema] {nickname} connesso. Totali: {len(clients)}")
        await broadcast_system(f"L'utente {nickname} si è connesso!")

        # Invia le chiavi pubbliche esistenti al nuovo arrivato
        for other_nick, key in client_keys.items():
            if other_nick != nickname:
                await websocket.send(json.dumps({
                    "type": "pubkey",
                    "nickname": other_nick,
                    "key": key
                }))

        async for raw in websocket:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if data.get("type") == "pubkey":
                # Salva e propaga la chiave pubblica
                key_pem = data["key"]
                client_keys[nickname] = key_pem
                print(f"[Sistema] Chiave aggiornata da {nickname}. Totale: {len(client_keys)}")
                await broadcast(json.dumps({
                    "type": "pubkey",
                    "nickname": nickname,
                    "key": key_pem
                }), exclude_ws=websocket)

            elif data.get("type") == "message":
                msg_hash = hashlib.sha256(data["data"].encode()).hexdigest()
                if msg_hash not in {m[0] for m in recent_messages}:
                    await broadcast(json.dumps({
                        "type": "message",
                        "from": nickname,
                        "data": data["data"]
                    }), exclude_ws=websocket)
                    recent_messages.add((msg_hash, time.time()))

    except websockets.ConnectionClosed:
        pass
    finally:
        await disconnect_client(websocket)

async def main():
    asyncio.create_task(cleanup_message_cache())
    async with websockets.serve(handler, "0.0.0.0", PORT, ping_interval=30, ping_timeout=30):
        print(f"[Sistema] Server WebSocket avviato sulla porta {PORT}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
