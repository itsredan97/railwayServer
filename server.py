import os
import asyncio
import websockets
import hashlib
import time

PORT = int(os.environ.get("PORT", 8080))

clients = {}             # websocket -> nickname
client_keys = {}         # nickname -> chiave pubblica
nickname_to_ws = {}      # nickname -> websocket attuale
recent_messages = set()
MESSAGE_CACHE_TIME = 60  # secondi per mantenere l'ID del messaggio

async def disconnect_client(websocket, notify=True):
    nickname = clients.pop(websocket, None)
    if nickname:
        nickname_to_ws.pop(nickname, None)
        client_keys.pop(nickname, None)
        if notify:
            for client in clients:
                try:
                    await safe_send(client, f"[Sistema] L'utente {nickname} si è disconnesso!")
                except:
                    continue
        print(f"[Sistema] Client {nickname} disconnesso. Client totali: {len(clients)}")

async def cleanup_message_cache():
    """Rimuove vecchi messaggi dal set dei duplicati"""
    while True:
        now = time.time()
        to_remove = {m for m in recent_messages if now - m[1] > MESSAGE_CACHE_TIME}
        for m in to_remove:
            recent_messages.discard(m)
        await asyncio.sleep(10)

async def safe_send(client, message):
    """Invio sicuro con retry su eventuali errori temporanei"""
    for _ in range(3):
        try:
            await client.send(message)
            return True
        except websockets.ConnectionClosed:
            await asyncio.sleep(0.1)
    return False

async def handler(websocket):
    try:
        nickname = await websocket.recv()

        old_ws = nickname_to_ws.get(nickname)
        if old_ws:
            await disconnect_client(old_ws, notify=True)

        clients[websocket] = nickname
        nickname_to_ws[nickname] = websocket
        print(f"[Sistema] Nuovo client connesso: {nickname}. Client totali: {len(clients)}")

        # Notifica tutti gli altri utenti
        for client in clients:
            if client != websocket:
                await safe_send(client, f"[Sistema] L'utente {nickname} si è connesso!")

        async for message in websocket:
            # Chiave pubblica
            if message.startswith("-----BEGIN PUBLIC KEY-----"):
                if client_keys.get(nickname) != message:
                    client_keys[nickname] = message
                    print(f"[Sistema] Chiave pubblica aggiornata da {nickname}. Totale chiavi: {len(client_keys)}")
                    for client in clients:
                        if client != websocket:
                            await safe_send(client, message)
                for other_nick, key in client_keys.items():
                    if other_nick != nickname:
                        await safe_send(websocket, key)
            else:
                # Calcola hash del messaggio per evitare duplicati
                msg_hash = hashlib.sha256(message.encode()).hexdigest()
                if msg_hash not in {m[0] for m in recent_messages}:
                    for client in clients:
                        if client != websocket:
                            await safe_send(client, message)
                    recent_messages.add((msg_hash, time.time()))

    except websockets.ConnectionClosed:
        pass
    except Exception as e:
        print(f"[Errore] {e}")
    finally:
        await disconnect_client(websocket)

async def main():
    asyncio.create_task(cleanup_message_cache())
    async with websockets.serve(
        handler,
        "0.0.0.0",
        PORT,
        ping_interval=30,   # aumenta il ping per stabilità
        ping_timeout=30
    ):
        print(f"[Sistema] Server WebSocket avviato sulla porta {PORT}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())

