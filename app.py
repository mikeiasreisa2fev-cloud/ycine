from flask import Flask, Response, redirect, request
import requests
import re
import base64
import json
from concurrent.futures import ThreadPoolExecutor
import os
import time

app = Flask(__name__)

# ================= CONFIGURAÇÕES (VERSÃO 23.0) =================
# MegaFlix - Fontes
MEGAFLIX_API = "https://app.megafrixapi.com/TV/1.2/"
MEGAFLIX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.91 Mobile Safari/537.36",
    "Referer": "https://megaflix.name/",
    "X-Requested-With": "XMLHttpRequest"
}

# YouCine - Fontes (Mirrors)
YCINE_MIRRORS = [
    "https://ycineflix.tudo30.shop/wp-json/xui-pflix/v1",
    "https://app.pobreflix2.site/wp-json/xui-pflix/v1"
]
YCINE_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Cache Global
cache = {"data": None, "time": 0}

# ================= UTILITÁRIOS =================
def decode_b64(data):
    try:
        data += "=" * ((4 - len(data) % 4) % 4)
        return base64.b64decode(data).decode('utf-8')
    except: return "{}"

# ================= LÓGICA MEGAFLIX =================
def get_megaflix():
    items = []
    try:
        r = requests.post(f"{MEGAFLIX_API}?page=viewChannels", headers=MEGAFLIX_HEADERS, timeout=12)
        matches = re.findall(r'data-data="([^"]+)"', r.text)
        for b64 in matches:
            try:
                d = json.loads(decode_b64(b64))
                cid = d.get("id")
                name = d.get("name") or d.get("titulo")
                if cid and name:
                    eid = base64.b64encode(str(cid).encode()).decode()
                    items.append({
                        "name": f"[MF] {name.strip()}",
                        "url": f"{request.host_url.rstrip('/')}/play?id={eid}",
                        "logo": d.get("background") or d.get("img"),
                        "group": "MEGAFLIX TV"
                    })
            except: continue
    except: pass
    return items

# ================= LÓGICA YOUCINE =================
def get_ycine():
    items = []
    for api_base in YCINE_MIRRORS:
        try:
            # Pega categorias
            c_res = requests.get(f"{api_base}/channels/categories", headers={"User-Agent": YCINE_UA}, timeout=8).json()
            cat_map = {str(c["id"]): c["name"] for c in c_res.get("data", [])}

            # Pega primeira página de canais (100 itens)
            res = requests.get(f"{api_base}/channels?per_page=100", headers={"User-Agent": YCINE_UA}, timeout=10).json()
            raw = res.get("data", {}).get("items", [])
            if not raw: continue # Tenta o próximo mirror se esse falhar

            for i in raw:
                items.append({
                    "name": f"[YC] {i['name']}",
                    "url": f"https://speed.megafilmeshd9.com/midia/speed-1/{i['id']}.m3u8",
                    "logo": i.get("thumbnail") or i.get("stream_icon"),
                    "group": f"YOUCINE | {cat_map.get(str(i.get('category_id')), 'TV').upper()}"
                })
            if items: break # Sucesso, não precisa de outros mirrors
        except: continue
    return items

# ================= ROTAS =================
@app.route('/')
def home():
    return "<h1>Servidor M3U V23.0</h1><p>Status: ONLINE</p>"

@app.route('/playlist.m3u')
def playlist():
    global cache
    if cache["data"] and (time.time() - cache["time"] < 300): # Cache reduzido para 5 min
        return Response(cache["data"], mimetype='text/plain')

    # Canal fixo de teste para saber se o servidor está ativo
    m3u = "#EXTM3U\n"
    m3u += '#EXTINF:-1 tvg-id="status" group-title="-- INFO --",>> SERVIDOR ONLINE V23 <<\n'
    m3u += 'http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4\n'

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_mf = executor.submit(get_megaflix)
        f_yc = executor.submit(get_ycine)
        all_items = f_mf.result() + f_yc.result()

    for item in all_items:
        tid = item["name"].lower().replace(" ", ".")
        m3u += f'#EXTINF:-1 tvg-id="{tid}" tvg-logo="{item["logo"]}" group-title="{item["group"]}",{item["name"]}\n'
        m3u += f'{item["url"]}\n'

    cache["data"] = m3u
    cache["time"] = time.time()
    return Response(m3u, mimetype='text/plain')

@app.route('/play')
def play():
    eid = request.args.get('id')
    if not eid: return "ID Error", 400
    cid = base64.b64decode(eid).decode()
    try:
        t_url = f"https://app.megafrixapi.com/get_token_channel.php?channel={cid}"
        res = requests.post(t_url, json={"id":0,"type":"app","headers":MEGAFLIX_HEADERS}, headers=MEGAFLIX_HEADERS, timeout=10).json()
        final = res.get("url") or res.get("stream")
        if final: return redirect(final)
    except: pass
    return "Stream Offline", 404

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
