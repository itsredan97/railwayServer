"""
Server WebSocket compatibile con il client SecureChat migliorato.
Protocollo JSON usato:
- Autenticazione in ingresso: {"type":"auth","token":...,"nickname":...}
- Public key inviata dal client: {"type":"public_key","key": "-----BEGIN..."}
  -> il server salva e ritrasmette a tutti gli altri: {"type":"public_key","from":nickname,"key":...}
- Chat: {"type":"chat","content":"<base64 ciphertext>"}
  -> il server inoltra: {"type":"chat","from":nickname,"content":"<base64>"}

Il server include protezioni base: deduplicazione messaggi, gestione disconnessioni e logging.
"""

import os
import asyncio
import websockets
import json
import hashlib
import time
from datetime import datetime

PORT = int(os.environ.get("PORT", 8080))
MESSAGE_CACHE_TIME = 60
MAX_MSG_SIZE = 2 ** 20
AUTH_TOKEN = os.environ.get("SECURECHAT_TOKEN", "secure_token_123")

# Shared state
clients = {}          # websocket -> nickname
nickname_to_ws = {}   # nickname -> websocket
client_keys = {}      # nickname -> pem string
recent_messages = {}  # msg_hash -> timestamp
state_lock = asyncio.Lock()


def log(msg: str):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")


async def disconnect_client(ws):
    async with state_lock:
        nick = clients.pop(ws, None)
        if nick:
            if nickname_to_ws.get(nick) is ws:
                nickname_to_ws.pop(nick, None)
            client_keys.pop(nick, None)
    if nick:
        log(f"[INFO] {nick} disconnected")
        # notify others
        payload = json.dumps({"type": "system", "message": f"L'utente {nick} si è disconnesso!"})
        await broadcast(payload, exclude_ws=None)


async def safe_send(ws, payload):
    try:
        if ws.closed:
            return False
        await ws.send(payload)
        return True
    except Exception:
        return False


async def broadcast(payload, exclude_ws=None):
    async with state_lock:
        targets = [w for w in clients.keys() if w != exclude_ws]
    if not targets:
        return
    tasks = [safe_send(w, payload) for w in targets]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # cleanup failed
    for w, r in zip(targets, results):
        if isinstance(r, Exception) or r is False:
            await disconnect_client(w)


async def authenticate(ws):
    try:
        raw = await ws.recv()
        data = json.loads(raw)
        if data.get("type") == "auth" and data.get("token") == AUTH_TOKEN:
            nick = data.get("nickname")
            return nick
        else:
            await ws.send(json.dumps({"type": "error", "message": "Unauthorized"}))
            return None
    except Exception:
        return None


async def cleanup_task():
    while True:
        now = time.time()
        async with state_lock:
            keys = [k for k, t in recent_messages.items() if now - t > MESSAGE_CACHE_TIME]
            for k in keys:
                recent_messages.pop(k, None)
        await asyncio.sleep(10)


async def handle_client(ws):
    nick = await authenticate(ws)
    if not nick:
        try:
            await ws.close()
        except:
            pass
        return

    async with state_lock:
        clients[ws] = nick
        nickname_to_ws[nick] = ws
    log(f"[INFO] {nick} connected")

    # send existing public keys to the newly connected client
    async with state_lock:
        for other, key in client_keys.items():
            if other != nick:
                try:
                    await ws.send(json.dumps({"type": "public_key", "from": other, "key": key}))
                except Exception:
                    pass
    # notify others
    await broadcast(json.dumps({"type": "system", "message": f"L'utente {nick} si è connesso!"}), exclude_ws=ws)

    try:
        async for raw in ws:
            # protect from non-JSON or too large
            if isinstance(raw, (bytes, bytearray)):
                try:
                    raw = raw.decode()
                except Exception:
                    continue
            if not isinstance(raw, str):
                continue
            if len(raw) > MAX_MSG_SIZE:
                await ws.send(json.dumps({"type": "error", "message": "Message too large"}))
                continue

            try:
                msg = json.loads(raw)
            except Exception:
                # ignore non-json
                continue

            mtype = msg.get("type")

            if mtype == "public_key":
                key_pem = msg.get("key")
                if not key_pem:
                    continue
                async with state_lock:
                    client_keys[nick] = key_pem
                # broadcast to others that this user published/updated key
                payload = json.dumps({"type": "public_key", "from": nick, "key": key_pem})
                await broadcast(payload, exclude_ws=ws)
                continue

            if mtype == "chat":
                content = msg.get("content", "")
                if not isinstance(content, str):
                    continue
                # deduplicate via hash
                msg_id = hashlib.sha256(content.encode()).hexdigest()
                now = time.time()
                async with state_lock:
                    if msg_id in recent_messages:
                        continue
                    recent_messages[msg_id] = now
                # broadcast chat
                payload = json.dumps({"type": "chat", "from": nick, "content": content})
                await broadcast(payload, exclude_ws=ws)
                continue

            # unknown type -> ignore or reply
            await ws.send(json.dumps({"type": "error", "message": "Unknown message type"}))

    except websockets.ConnectionClosed:
        log(f"[INFO] Connection closed: {nick}")
    except Exception as e:
        log(f"[ERROR] handler {e}")
    finally:
        await disconnect_client(ws)


async def main():
    cleanup = asyncio.create_task(cleanup_task())
    async with websockets.serve(handle_client, "0.0.0.0", PORT):
        log(f"[INFO] WebSocket server running on port {PORT}")
        await asyncio.Future()
    cleanup.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("[INFO] Server stopped")
