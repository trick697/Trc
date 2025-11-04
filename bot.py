# bot_cc_server.py
# Versión del bot que levanta un servidor HTTP (solo stdlib) y ejecuta el bot.
# Reemplaza TOKEN o define variable de entorno TOKEN en la plataforma.
import os
import urllib.request, urllib.parse, json, time, re
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

# ====== CONFIG ======
TOKEN = os.environ.get("TOKEN", "8449271818:AAGD5rILnYBuCIAefOYHUrPZlqtndC_kO8g")  # mejor: configura TOKEN en las variables de entorno
API = f"https://api.telegram.org/bot{TOKEN}"
GET_UPDATES = API + "/getUpdates"
SEND_MESSAGE = API + "/sendMessage"
SEND_AUDIO = API + "/sendAudio"

# ====== UTIL ======
def http_post(url, data_dict, timeout=30):
    data = urllib.parse.urlencode(data_dict).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()

def safe_read(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode(errors="ignore")

def send_message(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "disable_web_page_preview": "false"}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    try:
        http_post(SEND_MESSAGE, data)
    except Exception as e:
        print("Error send_message:", e)

# ====== ARCHIVE.ORG SEARCH (primera .mp3 pública) ======
def search_archive_for_mp3(query):
    q = urllib.parse.quote_plus(query + " AND mediatype:audio")
    list_url = f"https://archive.org/search.php?query={q}"
    try:
        page = safe_read(list_url)
    except Exception as e:
        print("Error fetching search page:", e)
        return None

    # extrae primeros resultados /details/<id>
    details = re.findall(r'href="(/details/[^"]+)"', page)
    seen = set()
    for d in details:
        if d in seen:
            continue
        seen.add(d)
        details_url = "https://archive.org" + d
        try:
            details_page = safe_read(details_url)
        except Exception:
            continue
        # 1) enlace completo .mp3
        m = re.search(r'href="(https?://[^"]+\.mp3)"', details_page)
        if m:
            return m.group(1)
        # 2) enlace relativo /download/... .mp3
        m2 = re.search(r'href="(/download/[^"]+\.mp3)"', details_page)
        if m2:
            return "https://archive.org" + m2.group(1)
        # 3) intentar candidate /download/<id>/<id>.mp3
        m3 = re.search(r'/details/([^"\s/]+)', d)
        if m3:
            itemid = m3.group(1)
            candidate = f"https://archive.org/download/{itemid}/{itemid}.mp3"
            try:
                req = urllib.request.Request(candidate, method="HEAD", headers={"User-Agent":"Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=7) as r:
                    if r.status == 200:
                        return candidate
            except Exception:
                pass
    return None

# ====== MENÚ SIMPLE ======
def main_menu(chat_id):
    keyboard = {
        "keyboard": [
            ["🔍 Buscar CC (Archive)","ℹ️ Cómo funciona"],
            ["❌ Salir"]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }
    send_message(chat_id, "Elige una opción:", keyboard)

# ====== ESTADOS ======
states = {}

def handle_text(chat_id, text):
    t = text.strip()
    state = states.get(str(chat_id))
    if t == "🔍 Buscar CC (Archive)":
        states[str(chat_id)] = "awaiting_search"
        send_message(chat_id, "Escribe el nombre de la pista o artista que quieres buscar (solo pistas libres):")
        return
    if t == "ℹ️ Cómo funciona":
        send_message(chat_id, ("Busco en archive.org (colección pública/CC) y envio la primera .mp3 directa que encuentre.\n"
                               "Si no hay .mp3 directo, dejo el enlace de búsqueda."))
        return
    if t == "❌ Salir":
        states.pop(str(chat_id), None)
        send_message(chat_id, "Cerrado. Usa 🔍 Buscar CC (Archive) cuando quieras.")
        return

    if state == "awaiting_search":
        query = t
        send_message(chat_id, f"Buscando pistas libres: {query} 🔎")
        mp3url = search_archive_for_mp3(query)
        if mp3url:
            try:
                send_message(chat_id, "Encontrada. Enviando al chat...")
                data = {"chat_id": chat_id, "audio": mp3url}
                http_post(SEND_AUDIO, data)
            except Exception as e:
                print("Error enviando audio:", e)
                send_message(chat_id, "Error enviando el audio. Te dejo el enlace:")
                send_message(chat_id, mp3url)
        else:
            send_message(chat_id, "No encontré .mp3 directo. Te dejo la búsqueda:")
            q = urllib.parse.quote_plus(query)
            search_link = f"https://archive.org/search.php?query={q}+AND+mediatype%3Aaudio"
            send_message(chat_id, search_link)
        states.pop(str(chat_id), None)
        return

    main_menu(chat_id)

# ====== LONG POLLING ======
def get_updates(offset=None, timeout=20):
    url = GET_UPDATES
    if offset:
        url += f"?offset={offset}&timeout={timeout}"
    else:
        url += f"?timeout={timeout}"
    try:
        with urllib.request.urlopen(url, timeout=timeout+5) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print("get_updates error:", e)
        return {"ok": False, "result": []}

def run_bot():
    last_update_id = None
    print("Bot iniciado. Esperando mensajes...")
    while True:
        data = get_updates(offset=last_update_id+1 if last_update_id else None)
        if not data.get("ok"):
            time.sleep(2)
            continue
        for upd in data.get("result", []):
            try:
                last_update_id = max(last_update_id or 0, upd["update_id"])
                if "message" not in upd:
                    continue
                msg = upd["message"]
                chat_id = msg["chat"]["id"]
                text = msg.get("text", "")
                if not text:
                    send_message(chat_id, "Solo manejo texto por ahora.")
                    continue
                handle_text(chat_id, text)
            except Exception as e:
                print("Error procesando update:", e)
        time.sleep(0.5)

# ====== MINI HTTP SERVER (solo stdlib) ======
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            content = b"Bot activo y listo \xf0\x9f\x98\x8e"  # "Bot activo 😎"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(404)
            self.end_headers()

def run_http_server(port=8080):
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    print(f"HTTP server escuchando en puerto {port}")
    server.serve_forever()

# ====== EJECUCIÓN ======
if __name__ == "__main__":
    # arrancar HTTP server en hilo para que la plataforma considere el servicio "vivo"
    port = int(os.environ.get("PORT", "8080"))
    t = threading.Thread(target=run_http_server, args=(port,), daemon=True)
    t.start()
    # ejecutar bot (long polling) en hilo principal
    run_bot()