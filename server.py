"""
Server WebSocket ottimizzato per chat.
Miglioramenti implementati:
- recent_messages: dict per lookup efficiente e cleanup semplice
- safe_send con controllo websocket.closed e rimozione client non raggiungibili
- broadcast parallelo con asyncio.gather e rimozione dei client morti
- lock per modifiche sicure alle strutture condivise
- gestione elegante di nickname duplicati (sostituzione della connessione precedente)
- logging con timestamp
- limitazione max_size per messaggi grandi
- graceful shutdown
"""

import os
import asyncio
import websockets
import hashlib
import time
from datetime import datetime

PORT = int(os.environ.get("PORT", 8080))
MESSAGE_CACHE_TIME = 60  # secondi per mantenere l'ID del messaggio
MAX_MSG_SIZE = 2 ** 20  # 1 MB

# Strutture condivise
clients = {}             # websocket -> nickname
client_keys = {}         # nickname -> chiave pubblica
nickname_to_ws = {}      # nickname -> websocket attuale
recent_messages = {}     # msg_hash -> timestamp

# Lock per proteggere le strutture condivise
state_lock = asyncio.Lock()


def log(msg: str):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")


async def remove_client(ws, notify=True):
    """Rimuove il client dalle strutture condivise in modo sicuro."""
    async with state_lock:
        nickname = clients.pop(ws, None)
        if nickname:
            # rimuovi mapping nickname -> ws solo se punta a questo ws
            if nickname_to_ws.get(nickname) is ws:
                nickname_to_ws.pop(nickname, None)
            # non rimuoviamo la chiave pubblica automaticamente (si potrebbe volerla conservare)

    if nickname:
        log(f"Client {nickname} rimosso. Client totali: {len(clients)}")
        if notify:
            await broadcast(f"[Sistema] L'utente {nickname} si è disconnesso!", exclude_ws=None)


async def safe_send(client, message):
    """Invio sicuro: ritorna True se inviato, False altrimenti."""
    try:
        if client.closed:
            return False
        await client.send(message)
        return True
    except websockets.ConnectionClosed:
        return False
    except Exception as e:
        # altri errori non dovrebbero far crashare il server
        log(f"[safe_send] Errore invio a client: {e}")
        return False


async def broadcast(message, exclude_ws=None):
    """Invia message a tutti i client connessi (escludendo exclude_ws). Rimuove i client morti."""
    async with state_lock:
        targets = [ws for ws in clients.keys() if ws != exclude_ws]

    if not targets:
        return

    # parallelizza gli invii
    send_coros = [safe_send(ws, message) for ws in targets]
    results = await asyncio.gather(*send_coros, return_exceptions=True)

    # rimuove i client che hanno fallito
    failed = []
    for ws, res in zip(targets, results):
        if isinstance(res, Exception) or res is False:
            failed.append(ws)

    for ws in failed:
        # non notifica (notify=False) poiché il broadcast già copriva l'evento
        await remove_client(ws, notify=False)


async def cleanup_message_cache_task():
    """Task che periodicamente pulisce recent_messages"""
    while True:
        now = time.time()
        async with state_lock:
            # rimuovi gli hash più vecchi di MESSAGE_CACHE_TIME
            keys_to_delete = [h for h, t in recent_messages.items() if now - t > MESSAGE_CACHE_TIME]
            for k in keys_to_delete:
                recent_messages.pop(k, None)
        await asyncio.sleep(10)


async def handler(websocket, path):
    nickname = None
    try:
        # ricevi il nickname come primo messaggio (compatibile col client esistente)
        nickname = await websocket.recv()
        if not isinstance(nickname, str) or not nickname.strip():
            await websocket.send("[Sistema] Nickname non valido. Connessione chiusa.")
            await websocket.close()
            return
        nickname = nickname.strip()

        # Se esisteva un vecchio websocket per questo nickname, lo sostituiamo
        async with state_lock:
            old_ws = nickname_to_ws.get(nickname)
            if old_ws and old_ws is not websocket:
                # informiamo che il vecchio utente viene disconnesso
                try:
                    await old_ws.send("[Sistema] Una nuova connessione ha preso il tuo nickname. Verrai disconnesso.")
                except Exception:
                    pass
                await remove_client(old_ws, notify=True)

            # registra il nuovo client
            clients[websocket] = nickname
            nickname_to_ws[nickname] = websocket

        log(f"Nuovo client connesso: {nickname}. Client totali: {len(clients)}")

        # invia tutte le chiavi pubbliche esistenti al nuovo client (utile per crittografia lato client)
        async with state_lock:
            for other_nick, key in client_keys.items():
                if other_nick != nickname:
                    try:
                        await websocket.send(key)
                    except Exception:
                        # non bloccare la connessione se il send fallisce
                        pass

        # notifica gli altri
        await broadcast(f"[Sistema] L'utente {nickname} si è connesso!", exclude_ws=websocket)

        async for message in websocket:
            # protezione da messaggi troppo grandi (websockets può gestirla con max_size ma controllo aggiuntivo non fa male)
            if isinstance(message, str) and len(message) > MAX_MSG_SIZE:
                await websocket.send("[Sistema] Messaggio troppo grande.")
                continue

            # gestione chiave pubblica
            if message.startswith("-----BEGIN PUBLIC KEY-----"):
                async with state_lock:
                    old_key = client_keys.get(nickname)
                    if old_key != message:
                        client_keys[nickname] = message
                        log(f"Chiave pubblica aggiornata da {nickname}. Totale chiavi: {len(client_keys)}")
                        # broadcast della nuova chiave a tutti gli altri
                        await broadcast(message, exclude_ws=websocket)
                # poi invia tutte le chiavi esistenti (già fatto alla connessione, ma nel caso aggiorniamo)
                async with state_lock:
                    for other_nick, key in client_keys.items():
                        if other_nick != nickname:
                            try:
                                await websocket.send(key)
                            except Exception:
                                pass
                continue

            # messaggi normali: check duplicati tramite hash
            msg_hash = hashlib.sha256(message.encode()).hexdigest()
            now = time.time()
            send_this = False
            async with state_lock:
                if msg_hash not in recent_messages:
                    recent_messages[msg_hash] = now
                    send_this = True

            if send_this:
                await broadcast(message, exclude_ws=websocket)
            # altrimenti ignoriamo il duplicato

    except websockets.ConnectionClosed:
        log(f"Connessione chiusa: {nickname}")
    except Exception as e:
        log(f"[Errore handler] {e}")
    finally:
        # rimuovi il client (se presente)
        if websocket.open:
            try:
                await websocket.close()
            except Exception:
                pass
        await remove_client(websocket, notify=True)


async def main():
    # avvia task di pulizia
    cleanup_task = asyncio.create_task(cleanup_message_cache_task())

    server = await websockets.serve(
        handler,
        "0.0.0.0",
        PORT,
        ping_interval=30,
        ping_timeout=30,
        max_size=MAX_MSG_SIZE,
    )

    log(f"Server WebSocket avviato sulla porta {PORT}")

    try:
        await server.wait_closed()
    except asyncio.CancelledError:
        pass
    finally:
        cleanup_task.cancel()
        log("Server arrestato")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("[Sistema] Arresto manuale del server.")
    except Exception as e:
        log(f"[Sistema] Errore critico: {e}")

