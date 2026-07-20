from flask import Flask, Response, redirect, request
import requests
import re
import base64
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import time
import threading

app = Flask(__name__)

# ================= CONFIGURAÇÕES (VERSÃO 30.0 - ULTRA FAST) =================
# User-Agent para compatibilidade e evitar bloqueios
SMART_TV_UA = "Mozilla/5.0 (Web0S; SmartTV) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.5735.196 Safari/537.36"

# Endpoints das APIs
MEGAFLIX_API = "https://app.megafrixapi.com/TV/1.2/"
YCINE_API = "https://ycineflix.tudo30.shop/wp-json/xui-pflix/v1"

# Integração Google Drive
DRIVE_FILE_ID = "11xLQKuz4uicx-SFIr2zLbp9whDSvnXbE"
DRIVE_URL = f"https://drive.google.com/uc?export=download&id={DRIVE_FILE_ID}"

# Banco de Dados em Memória (Para resposta instantânea no Tivimate)
CATALOG_STORE = {
    "main_m3u": "#EXTM3U\n# Carregando canais pela primeira vez...",
    "drive_m3u": "#EXTM3U\n# Carregando drive...",
    "last_update": 0
}

# ================= UTILITÁRIOS =================
def decode_b64(data):
    """Decodifica Base64 de forma segura."""
    try:
        data = data.replace("\n", "").replace("\r", "").replace(" ", "").strip()
        data += "=" * ((4 - len(data) % 4) % 4)
        return base64.b64decode(data).decode('utf-8')
    except: return "{}"

# ================= LÓGICAS DE EXTRAÇÃO =================
def get_megaflix():
    """Extrai canais do MegaFlix."""
    items = []
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://megaflix.name/", "X-Requested-With": "XMLHttpRequest"}
    try:
        r = requests.post(f"{MEGAFLIX_API}?page=viewChannels", headers=headers, timeout=10)
        matches = re.findall(r'data-data="([^"]+)"', r.text)
        for b64 in matches:
            try:
                d = json.loads(decode_b64(b64))
                cid, name = d.get("id"), d.get("name") or d.get("titulo")
                if cid and name:
                    eid = base64.b64encode(str(cid).encode()).decode()
                    items.append({
                        "name": f"[MF] {name.strip().upper()}",
                        "url": f"/play?id={eid}", 
                        "logo": d.get("background") or d.get("img"),
                        "group": "MEGAFLIX TV"
                    })
            except: continue
    except: pass
    return items

def fetch_ycine_page(page):
    """Captura uma página individual do YouCine."""
    try:
        url = f"{YCINE_API}/channels?per_page=100&page={page}"
        res = requests.get(url, headers={"User-Agent": SMART_TV_UA}, timeout=10)
        return res.json().get("data", {}).get("items", []) if res.status_code == 200 else []
    except: return []

def get_ycine_all():
    """Extrai todos os canais do YouCine via CDN Speed."""
    all_channels = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_ycine_page, p) for p in range(1, 15)]
        for future in as_completed(futures):
            for i in future.result():
                all_channels.append({
                    "name": f"[YC] {i['name'].upper()}",
                    "url": f"https://speed.megafilmeshd9.com/midia/speed-1/{i['id']}.m3u8",
                    "logo": i.get("thumbnail") or i.get("stream_icon"),
                    "group": f"YOUCINE | {i.get('category_name', 'GERAL').upper()}"
                })
    return all_channels

def get_drive_channels():
    """Extrai canais da lista do Google Drive."""
    items = []
    try:
        response = requests.get(DRIVE_URL, timeout=15)
        if response.status_code == 200:
            lines = response.text.splitlines()
            current_name, current_logo = None, ""
            for line in lines:
                line = line.strip()
                if line.startswith("#EXTINF"):
                    name_match = re.search(r',(.+)$', line)
                    current_name = name_match.group(1) if name_match else "Drive Canal"
                    logo_match = re.search(r'tvg-logo="([^"]+)"', line)
                    current_logo = logo_match.group(1) if logo_match else ""
                elif line.startswith("http"):
                    if current_name:
                        items.append({"name": current_name.upper(), "url": line, "logo": current_logo, "group": "MINHA LISTA DRIVE"})
                        current_name = None
    except: pass
    return items

# ================= ATUALIZADOR DE BACKGROUND =================
def update_catalogs_task():
    """Tarefa automática: mantém a lista sempre pronta na memória do servidor."""
    while True:
        try:
            # 1. Atualiza Fontes Principais (MF + YC)
            with ThreadPoolExecutor(max_workers=2) as executor:
                f_mf = executor.submit(get_megaflix)
                f_yc = executor.submit(get_ycine_all)
                items = f_mf.result() + f_yc.result()

            if items:
                items.sort(key=lambda x: x['name'])
                m3u = "#EXTM3U\n"
                for item in items:
                    tid = item["name"].lower().replace(" ", ".")
                    m3u += f'#EXTINF:-1 tvg-id="{tid}" tvg-logo="{item["logo"]}" group-title="{item["group"]}",{item["name"]}\n{item["url"]}\n'
                CATALOG_STORE["main_m3u"] = m3u

            # 2. Atualiza Lista do Drive
            drive_items = get_drive_channels()
            if drive_items:
                m3u_dr = "#EXTM3U\n"
                for item in drive_items:
                    m3u_dr += f'#EXTINF:-1 tvg-logo="{item["logo"]}" group-title="{item["group"]}",{item["name"]}\n{item["url"]}\n'
                CATALOG_STORE["drive_m3u"] = m3u_dr
            
            CATALOG_STORE["last_update"] = time.time()
        except: pass
        
        time.sleep(1200) # Trabalha em silêncio a cada 20 minutos

# Inicia o robô de atualização em paralelo com o Flask
threading.Thread(target=update_catalogs_task, daemon=True).start()

# ================= ROTAS FLASK =================
@app.route('/')
def home():
    return "<h1>Servidor M3U Ultra-Fluid Ativo</h1><p>Versão 30.0</p>"

@app.route('/playlist.m3u')
def main_playlist():
    # Resposta instantânea: entrega o que já está na memória
    data = CATALOG_STORE["main_m3u"]
    # Converte links relativos para absolutos dependendo de onde o Render hospedar
    base_url = request.host_url.rstrip('/')
    data = data.replace("\n/play", f"\n{base_url}/play")
    return Response(data, mimetype='text/plain')

@app.route('/drive.m3u')
def drive_playlist():
    return Response(CATALOG_STORE["drive_m3u"], mimetype='text/plain')

@app.route('/play')
def play():
    """Redirecionador em tempo real para links do MegaFlix."""
    eid = request.args.get('id')
    if not eid: return "Error", 400
    cid = base64.b64decode(eid).decode()
    try:
        t_url = f"https://app.megafrixapi.com/get_token_channel.php?channel={cid}"
        payload = {"id":0,"type":"app","headers":{"User-Agent":"Mozilla/5.0"}}
        res = requests.post(t_url, json=payload, headers={"User-Agent": SMART_TV_UA, "Referer": "https://megaflix.name/"}, timeout=10).json()
        final = res.get("url") or res.get("stream")
        if final: return redirect(final)
    except: pass
    return "Offline", 404

if __name__ == "__main__":
    # Render define a porta automaticamente
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
