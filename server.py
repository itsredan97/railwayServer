# securechat_server.py
import os
import asyncio
import websockets
import hashlib
import time
import json
import logging

# ---------- CONFIG ----------
PORT = int(os.environ.get("PORT", 8080))
PING_INTERVAL = 30
PING_TIMEOUT = 30
MESSAGE_CACHE_TIME = 60  # secondi
MESSAGE_CACHE_CLEAN_INTERVAL = 10

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------- STATO SERVER ----------
clients = {}             # websocket -> nickname
nickname_to_ws = {}      # nickname -> websocket
client_keys = {}         # nickname -> pubkey PEM (string)
chat_rooms = {}          # chat_id -> set(nickname)
recent_messages = set()  # set of (msg_hash, timestamp) per dedup

lock = asyncio.Lock()    # protezione semplice per strutture condivise

# ---------- UTIL ----------
async def safe_send(ws, payload):
    """
    Invia in modo robusto (retry limitato). payload è stringa già serializzata (JSON o altro).
    Returns True se inviato, False altrimenti.
    """
    for _ in range(3):
        try:
            await ws.send(payload)
            return True
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            await asyncio.sleep(0.05)
    return False

async def broadcast_to_chat(chat_id, payload, exclude_nick=None):
    """
    Invia payload (string) a tutti i membri della chat chat_id eccetto exclude_nick.
    """
    async with lock:
        members = set(chat_rooms.get(chat_id, set()))
    for nick in members:
        if nick == exclude_nick:
            continue
        ws = nickname_to_ws.get(nick)
        if ws:
            await safe_send(ws, payload)

def hash_message(chat_id, content):
    return hashlib.sha256((chat_id + content).encode()).hexdigest()

async def cleanup_message_cache():
    while True:
        now = time.time()
        to_remove = {m for m in recent_messages if now - m[1] > MESSAGE_CACHE_TIME}
        for m in to_remove:
            recent_messages.discard(m)
        await asyncio.sleep(MESSAGE_CACHE_CLEAN_INTERVAL)

# ---------- GESTIONE CONNESSIONE / DISCONNESSIONE ----------
async def remove_from_all_chats(nickname, notify=True):
    """
    Rimuove nickname da tutte le chat. Se notify==True invia notifica di sistema ai membri della chat.
    """
    async with lock:
        rooms = list(chat_rooms.items())  # snapshot
    for chat_id, members in rooms:
        if nickname in members:
            members.discard(nickname)
            # se rimangono membri, notifica nella chat
            if notify and members:
                msg = {"chat_id": chat_id, "content": f"[Sistema] L'utente {nickname} si è disconnesso!"}
                await broadcast_to_chat(chat_id, json.dumps(msg), exclude_nick=nickname)

async def disconnect_client(ws, notify=True):
    """
    Pulizia alla disconnessione di una websocket.
    """
    nickname = None
    async with lock:
        nickname = clients.pop(ws, None)
        if nickname:
            nickname_to_ws.pop(nickname, None)
            client_keys.pop(nickname, None)

    if nickname:
        logging.info(f"[Sistema] Client {nickname} disconnesso. Client totali: {len(clients)}")
        await remove_from_all_chats(nickname, notify=notify)

# ---------- HANDLER MESSAGGI/COMANDI ----------
async def handle_json_command(nickname, ws, obj):
    """
    Gestisce comandi JSON strutturati come:
      - {"type":"connect", "nickname":"...", "chats":["c1","c2"]}
      - {"type":"create_chat", "chat_id":"..."}
      - {"type":"join_chat", "chat_id":"..."}
      - {"type":"leave_chat", "chat_id":"..."}
      - {"type":"public_key", "pubkey":"PEM..."}
      - {"type":"message", "chat_id":"...", "content":"<latin1 bytes>"}
    """
    t = obj.get("type")
    if t == "connect":
        # aggiungi nickname e iscrivilo alle chat fornite
        chats = obj.get("chats", []) or []
        async with lock:
            for c in chats:
                if c not in chat_rooms:
                    chat_rooms[c] = set()
                chat_rooms[c].add(nickname)

        # invia snapshot di chiavi per le chat a cui è iscritto
        # per ogni chat, inviamo al client le chiavi dei membri già presenti (escluso se stesso)
        for c in chats:
            async with lock:
                members = list(chat_rooms.get(c, set()))
            for m in members:
                if m == nickname:
                    continue
                key = client_keys.get(m)
                if key:
                    key_msg = {"type":"key", "nickname": m, "pubkey": key}
                    await safe_send(ws, json.dumps(key_msg))

        # notifichiamo agli altri membri che è entrato
        for c in chats:
            join_notice = {"chat_id": c, "content": f"[Sistema] L'utente {nickname} si è connesso alla chat {c}!"}
            await broadcast_to_chat(c, json.dumps(join_notice), exclude_nick=nickname)

    elif t == "create_chat":
        chat_id = obj.get("chat_id")
        if not chat_id:
            await safe_send(ws, json.dumps({"type":"error", "message":"create_chat necessita chat_id"}))
            return
        async with lock:
            if chat_id not in chat_rooms:
                chat_rooms[chat_id] = set()
        # opzionale: aggiungiamo il creatore automaticamente (ma client già fa add local)
        async with lock:
            chat_rooms[chat_id].add(nickname)
        await safe_send(ws, json.dumps({"type":"created", "chat_id":chat_id}))

    elif t == "join_chat":
        chat_id = obj.get("chat_id")
        if not chat_id:
            await safe_send(ws, json.dumps({"type":"error", "message":"join_chat necessita chat_id"}))
            return
        async with lock:
            if chat_id not in chat_rooms:
                chat_rooms[chat_id] = set()
            # invitiamo il membro
            chat_rooms[chat_id].add(nickname)

        # notifichiamo i membri esistenti
        join_notice = {"chat_id": chat_id, "content": f"[Sistema] L'utente {nickname} è entrato nella chat."}
        await broadcast_to_chat(chat_id, json.dumps(join_notice), exclude_nick=nickname)

        # inviamo al nuovo membro le chiavi dei membri già presenti
        async with lock:
            members = list(chat_rooms[chat_id])
        for m in members:
            if m == nickname:
                continue
            key = client_keys.get(m)
            if key:
                await safe_send(ws, json.dumps({"type":"key","nickname":m,"pubkey":key}))

    elif t == "leave_chat":
        chat_id = obj.get("chat_id")
        if chat_id:
            async with lock:
                if chat_id in chat_rooms and nickname in chat_rooms[chat_id]:
                    chat_rooms[chat_id].discard(nickname)
            leave_notice = {"chat_id": chat_id, "content": f"[Sistema] L'utente {nickname} ha lasciato la chat."}
            await broadcast_to_chat(chat_id, json.dumps(leave_notice), exclude_nick=nickname)

    elif t == "public_key":
        pem = obj.get("pubkey")
        if not pem:
            return
        async with lock:
            client_keys[nickname] = pem
        # Distribuisci la chiave SOLO ai membri delle chat in comune con nickname.
        async with lock:
            my_chats = [cid for cid, members in chat_rooms.items() if nickname in members]
            # rimuovi duplicati
            my_chats = list(set(my_chats))
        sent_to = set()
        for c in my_chats:
            async with lock:
                members = set(chat_rooms.get(c, set()))
            for m in members:
                if m == nickname:
                    continue
                if m in sent_to:
                    continue
                ws_target = nickname_to_ws.get(m)
                if ws_target:
                    msg = {"type":"key", "nickname": nickname, "pubkey": pem}
                    await safe_send(ws_target, json.dumps(msg))
                    sent_to.add(m)
        # conferma al mittente
        await safe_send(ws, json.dumps({"type":"pubkey_stored", "for": len(sent_to)}))

    elif t == "message":
        chat_id = obj.get("chat_id")
        content = obj.get("content")
        if not chat_id or content is None:
            return
        # dedup
        h = hash_message(chat_id, content)
        now = time.time()
        if h in {m[0] for m in recent_messages}:
            return
        recent_messages.add((h, now))
        # inoltra a membri della chat
        msg = {"chat_id": chat_id, "content": content}
        await broadcast_to_chat(chat_id, json.dumps(msg), exclude_nick=nickname)
    else:
        # Comando non riconosciuto: ignora o logga
        logging.debug(f"[{nickname}] JSON unknown command: {obj}")

# ---------- HANDLER GENERALE ----------
async def handler(websocket, path):
    """
    Protocollo compatibile con:
      - cliente che invia prima nickname (plain string), poi chiave PEM (plain string),
        e poi messaggi JSON di forma {"chat_id":...,"content":...}
      - oppure cliente che manda JSON di tipo connect/join/create/public_key/message
    """
    nickname = None
    try:
        # prima fase: aspettiamo i primi messaggi per stabilire l'identità
        # Il client può inviare:
        #   1) nickname (plain) then PEM (plain)  OR
        #   2) JSON {"type":"connect", "nickname":..., "chats":[...]}
        # Gestire entrambe le modalità.

        # ricevi primo messaggio
        first = await websocket.recv()
        try:
            parsed = json.loads(first)
        except Exception:
            parsed = None

        if isinstance(parsed, dict) and parsed.get("type") == "connect":
            nickname = parsed.get("nickname") or f"user_{int(time.time())}"
            # registra websocket
            async with lock:
                # se nickname già connesso, disconnetti il vecchio
                old = nickname_to_ws.get(nickname)
                if old and old != websocket:
                    try:
                        await safe_send(old, json.dumps({"type":"force_disconnect","message":"Connessione concorrente"}))
                        await remove_from_all_chats(nickname, notify=True)
                        await old.close()
                    except Exception:
                        pass
                clients[websocket] = nickname
                nickname_to_ws[nickname] = websocket
            logging.info(f"[Sistema] Nuovo client (connect JSON): {nickname}. Client totali: {len(clients)}")
            # gestiamo connect (iscrizioni e invio chiavi)
            await handle_json_command(nickname, websocket, parsed)
        else:
            # Modalità legacy: primo messaggio è nickname plain
            nickname = first if isinstance(first, str) and first.strip() else f"user_{int(time.time())}"
            # registra e attendi eventualmente la chiave PEM immediata dopo (non obbligatoria)
            async with lock:
                old = nickname_to_ws.get(nickname)
                if old and old != websocket:
                    try:
                        await safe_send(old, json.dumps({"type":"force_disconnect","message":"Connessione concorrente"}))
                        await remove_from_all_chats(nickname, notify=True)
                        await old.close()
                    except Exception:
                        pass
                clients[websocket] = nickname
                nickname_to_ws[nickname] = websocket
            logging.info(f"[Sistema] Nuovo client (legacy nick): {nickname}. Client totali: {len(clients)}")
            # reinvia snapshot delle chat dell'utente (se presenti) oppure aspetta ulteriori comandi
            # aspettiamo un secondo messaggio (potrebbe essere PEM oppure JSON/other)
            try:
                second = await asyncio.wait_for(websocket.recv(), timeout=1.5)
            except asyncio.TimeoutError:
                second = None

            if isinstance(second, str) and second and second.startswith("-----BEGIN PUBLIC KEY-----"):
                pem = second
                async with lock:
                    client_keys[nickname] = pem
                # Distribuisci la chiave ai membri delle chat di cui è già parte (se ci sono)
                async with lock:
                    my_chats = [cid for cid, members in chat_rooms.items() if nickname in members]
                for c in my_chats:
                    await broadcast_to_chat(c, json.dumps({"type":"key","nickname":nickname,"pubkey":pem}), exclude_nick=nickname)

            else:
                # se second non è PEM, potrebbe essere JSON di comando — gestiamolo se possibile
                if second:
                    try:
                        parsed2 = json.loads(second)
                        await handle_json_command(nickname, websocket, parsed2)
                    except Exception:
                        # ignora
                        pass

        # Notifica locale (solo se vogliamo notifiche globali leggere)
        # (opzionale) : commentata per evitare spam globale
        # for ws_other in list(clients.keys()):
        #     if ws_other != websocket:
        #         await safe_send(ws_other, json.dumps({"type":"notice", "message": f"Utente {nickname} connesso"}))

        # Ora loop principale: ricevi messaggi e gestiscili
        async for message in websocket:
            # se message è testo PEM
            if isinstance(message, str) and message.startswith("-----BEGIN PUBLIC KEY-----"):
                # salva la chiave
                async with lock:
                    client_keys[nickname] = message
                # distribuisci ai membri delle chat comuni
                async with lock:
                    my_chats = [cid for cid, members in chat_rooms.items() if nickname in members]
                for c in my_chats:
                    await broadcast_to_chat(c, json.dumps({"type":"key","nickname":nickname,"pubkey":message}), exclude_nick=nickname)
                continue

            # se è JSON
            try:
                obj = json.loads(message)
                # Se è un envelope message con chat_id & content (messaggi cifrati dal client)
                if "chat_id" in obj and "content" in obj and obj.get("type") is None:
                    # questo è il formato legacy che il client usa per inviare messaggi cifrati:
                    chat_id = obj.get("chat_id")
                    content = obj.get("content")
                    # dedup
                    if not chat_id or content is None:
                        continue
                    h = hash_message(chat_id, content)
                    now = time.time()
                    if h in {m[0] for m in recent_messages}:
                        continue
                    recent_messages.add((h, now))
                    # regista l'utente nella chat se nuovo
                    async with lock:
                        if chat_id not in chat_rooms:
                            chat_rooms[chat_id] = set()
                        chat_rooms[chat_id].add(nickname)
                    # inoltra solo ai membri della chat
                    await broadcast_to_chat(chat_id, json.dumps({"chat_id": chat_id, "content": content}), exclude_nick=nickname)
                    continue
                # altrimenti tratta come comando strutturato
                if isinstance(obj, dict) and "type" in obj:
                    await handle_json_command(nickname, websocket, obj)
                    continue
            except json.JSONDecodeError:
                # non è JSON — ignora o logga
                pass
            except Exception as e:
                logging.exception(f"Errore processing message da {nickname}: {e}")
                continue

            # Se arriva qui: payload non JSON e non PEM -> ignoriamo (protocollo sicuro richiede JSON o PEM)
            logging.debug(f"[{nickname}] Messaggio non riconosciuto/ignorato.")

    except websockets.ConnectionClosed:
        logging.info(f"[Sistema] ConnectionClosed: {nickname}")
    except Exception as e:
        logging.exception(f"[Errore handler] {e}")
    finally:
        await disconnect_client(websocket, notify=True)

# ---------- START SERVER ----------
async def main():
    logging.info(f"[Sistema] Avvio server WebSocket sulla porta {PORT}")
    asyncio.create_task(cleanup_message_cache())
    async with websockets.serve(handler, "0.0.0.0", PORT, ping_interval=PING_INTERVAL, ping_timeout=PING_TIMEOUT):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Server terminato manualmente")
