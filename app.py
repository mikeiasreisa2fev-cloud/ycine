from flask import Flask, Response, redirect, request
import requests
import re
import base64
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import time

app = Flask(__name__)

# ================= CONFIGURAÇÕES (VERSÃO 27.0) =================
# User-Agent de Smart TV (Altamente compatível e menos bloqueado)
SMART_TV_UA = "Mozilla/5.0 (Web0S; SmartTV) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.5735.196 Safari/537.36"

# Endpoints das APIs
MEGAFLIX_API = "https://app.megafrixapi.com/TV/1.2/"
YCINE_MIRRORS = [
    "https://ycineflix.tudo30.shop/wp-json/xui-pflix/v1",
    "https://app.pobreflix2.site/wp-json/xui-pflix/v1"
]

# Sistema de Cache Global (Mantém a lista por 15 minutos)
cache = {"data": None, "time": 0}

# ================= UTILITÁRIOS =================
def decode_b64(data):
    """Decodifica strings Base64 limpando caracteres de quebra de linha."""
    try:
        data = data.replace("\n", "").replace("\r", "").replace(" ", "").strip()
        data += "=" * ((4 - len(data) % 4) % 4)
        return base64.b64decode(data).decode('utf-8')
    except: 
        return "{}"

# ================= LÓGICA MEGAFLIX =================
def get_megaflix():
    """Busca todos os canais de TV do MegaFlix."""
    items = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10)",
        "Referer": "https://megaflix.name/",
        "X-Requested-With": "XMLHttpRequest"
    }
    try:
        # Pede a lista de canais via POST
        r = requests.post(f"{MEGAFLIX_API}?page=viewChannels", headers=headers, timeout=15)
        # Captura os dados codificados em Base64 no atributo data-data
        matches = re.findall(r'data-data="([^"]+)"', r.text)
        for b64 in matches:
            try:
                decoded = decode_b64(b64)
                d = json.loads(decoded)
                cid = d.get("id")
                name = d.get("name") or d.get("titulo")
                if cid and name:
                    # Codifica o ID para o redirecionador de token
                    eid = base64.b64encode(str(cid).encode()).decode()
                    items.append({
                        "name": f"[MF] {name.strip().upper()}",
                        "url": f"{request.host_url.rstrip('/')}/play?id={eid}",
                        "logo": d.get("background") or d.get("img"),
                        "group": "MEGAFLIX TV"
                    })
            except: continue
    except: pass
    return items

# ================= LÓGICA YOUCINE (BUSCA PROFUNDA) =================
def fetch_ycine_page(mirror, page):
    """Busca uma página específica da API do YouCine."""
    try:
        url = f"{mirror}/channels?per_page=100&page={page}"
        res = requests.get(url, headers={"User-Agent": SMART_TV_UA}, timeout=10)
        if res.status_code == 200:
            return res.json().get("data", {}).get("items", [])
    except: pass
    return []

def get_ycine_all():
    """Extrai todos os 1.300+ canais do YouCine varrendo todas as páginas."""
    all_channels = []
    # Testa qual mirror está respondendo no momento
    active_mirror = YCINE_MIRRORS[0]
    try:
        test = requests.get(f"{active_mirror}/channels?per_page=1", timeout=5)
        if test.status_code != 200: active_mirror = YCINE_MIRRORS[1]
    except: 
        active_mirror = YCINE_MIRRORS[1]

    # Varre as 14 páginas da API em paralelo para ser rápido
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_ycine_page, active_mirror, p) for p in range(1, 15)]
        for future in as_completed(futures):
            items = future.result()
            for i in items:
                # Gera link direto da CDN Speed (mais estável)
                all_channels.append({
                    "name": f"[YC] {i['name'].upper()}",
                    "url": f"https://speed.megafilmeshd9.com/midia/speed-1/{i['id']}.m3u8",
                    "logo": i.get("thumbnail") or i.get("stream_icon"),
                    "group": f"YOUCINE | {i.get('category_name', 'GERAL').upper()}"
                })
    return all_channels

# ================= ROTAS FLASK =================
@app.route('/')
def home():
    return "<h1>Servidor M3U Ativo (V27.0)</h1><p>Status: ONLINE - 1.400+ Canais</p><a href='/playlist.m3u'>Playlist</a>"

@app.route('/playlist.m3u')
def playlist():
    global cache
    now = time.time()
    
    # Se a lista está no cache (menos de 15 min), entrega ela na hora
    if cache["data"] and (now - cache["time"] < 900):
        return Response(cache["data"], mimetype='text/plain')

    m3u = "#EXTM3U\n"
    m3u += '#EXTINF:-1 tvg-id="status" group-title="-- INFO --",>> LISTA CARREGADA V27 <<\n'
    m3u += 'http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4\n'

    # Busca as duas fontes simultaneamente
    with ThreadPoolExecutor(max_workers=2) as executor:
        f_mf = executor.submit(get_megaflix)
        f_yc = executor.submit(get_ycine_all)
        
        list_mf = f_mf.result()
        list_yc = f_yc.result()
        all_items = list_mf + list_yc

    if not all_items:
        m3u += '#EXTINF:-1 tvg-id="err" group-title="AVISO",ERRO DE CONEXAO COM AS FONTES\n'
        m3u += 'https://shls-globo-rj-prod.akamaized.net/out/v1/f1545648f572421a868494b5952c286a/index.m3u8\n'
    else:
        # Ordena por nome para ficar organizado
        all_items.sort(key=lambda x: x['name'])
        for item in all_items:
            tid = item["name"].lower().replace(" ", ".")
            m3u += f'#EXTINF:-1 tvg-id="{tid}" tvg-logo="{item["logo"]}" group-title="{item["group"]}",{item["name"]}\n'
            m3u += f'{item["url"]}\n'
    
    # Salva no cache para as próximas chamadas serem instantâneas
    cache["data"] = m3u
    cache["time"] = now
    
    return Response(m3u, mimetype='text/plain')

@app.route('/play')
def play():
    """Gera token MegaFlix em tempo real para evitar expiração de links."""
    eid = request.args.get('id')
    if not eid: return "Error", 400
    cid = base64.b64decode(eid).decode()
    try:
        t_url = f"https://app.megafrixapi.com/get_token_channel.php?channel={cid}"
        # Envia o JSON esperado pelo servidor PHP do MegaFlix
        payload = {"id": 0, "type": "app", "headers": {"User-Agent": "Mozilla/5.0"}}
        res = requests.post(t_url, json=payload, headers={"User-Agent": SMART_TV_UA, "Referer": "https://megaflix.name/"}, timeout=10).json()
        final_url = res.get("url") or res.get("stream")
        if final_url: 
            return redirect(final_url)
    except: pass
    return "Offline", 404

if __name__ == "__main__":
    # O Render configura a porta automaticamente
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
