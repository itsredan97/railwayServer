import os
import asyncio
import websockets
import hashlib
import time
import json

PORT = int(os.environ.get("PORT", 8080))

# websocket -> nickname
clients = {}             
client_keys = {}         
nickname_to_ws = {}      

# chat_id -> set di client
chat_subscriptions = {}  

recent_messages = set()
MESSAGE_CACHE_TIME = 60  

async def disconnect_client(websocket, notify=True):
    nickname = clients.pop(websocket, None)
    if nickname:
        nickname_to_ws.pop(nickname, None)
        client_keys.pop(nickname, None)
        for chat_id in chat_subscriptions:
            chat_subscriptions[chat_id].discard(websocket)
        if notify:
            for client in clients:
                try:
                    await client.send(f"[Sistema] L'utente {nickname} si è disconnesso!")
                except websockets.ConnectionClosed:
                    continue
        print(f"[Sistema] Client {nickname} disconnesso. Totale: {len(clients)}")

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
        old_ws = nickname_to_ws.get(nickname)
        if old_ws:
            await disconnect_client(old_ws, notify=True)

        clients[websocket] = nickname
        nickname_to_ws[nickname] = websocket
        print(f"[Sistema] Nuovo client connesso: {nickname}")

        while True:
            data = await websocket.recv()
            # messaggi strutturati JSON
            try:
                msg_obj = json.loads(data)
            except:
                continue

            chat_id = msg_obj.get("chat_id")
            content = msg_obj.get("content")
            if not chat_id or not content:
                continue

            # gestione chiave pubblica
            if content.startswith("-----BEGIN PUBLIC KEY-----"):
                if client_keys.get(nickname) != content:
                    client_keys[nickname] = content
                    print(f"[Sistema] Chiave pubblica aggiornata da {nickname}")
                # invia chiavi al client
                await websocket.send(json.dumps({"chat_id": chat_id, "content": content}))
                continue

            # Inoltra il messaggio solo ai client iscritti alla chat
            if chat_id not in chat_subscriptions:
                chat_subscriptions[chat_id] = set()
            chat_subscriptions[chat_id].add(websocket)

            msg_hash = hashlib.sha256(content.encode()).hexdigest()
            if msg_hash not in {m[0] for m in recent_messages}:
                for client in chat_subscriptions[chat_id]:
                    if client != websocket:
                        try:
                            await client.send(json.dumps({"chat_id": chat_id, "content": content}))
                        except websockets.ConnectionClosed:
                            continue
                recent_messages.add((msg_hash, time.time()))

    except websockets.ConnectionClosed:
        pass
    finally:
        await disconnect_client(websocket)

async def main():
    asyncio.create_task(cleanup_message_cache())
    async with websockets.serve(handler, "0.0.0.0", PORT, ping_interval=20, ping_timeout=20):
        print(f"[Sistema] Server WebSocket avviato sulla porta {PORT}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())

