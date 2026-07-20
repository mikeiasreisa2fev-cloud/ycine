from flask import Flask, Response, redirect, request
import requests
import re
import base64
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import time

app = Flask(__name__)

# ================= CONFIGURAÇÕES (VERSÃO 25.0) =================
COMMON_HEADERS = {
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 12; SM-G998B Build/SP1A.210812.016)",
    "X-Requested-With": "com.ycineflix.app",
    "Connection": "Keep-Alive"
}

MEGAFLIX_API = "https://app.megafrixapi.com/TV/1.2/"
YCINE_API = "https://ycineflix.tudo30.shop/wp-json/xui-pflix/v1"

# Cache Global (30 minutos para evitar bloqueios)
cache = {"data": None, "time": 0}

# ================= UTILITÁRIOS =================
def decode_b64(data):
    try:
        data = data.replace("\n", "").replace("\r", "").replace(" ", "").strip()
        data += "=" * ((4 - len(data) % 4) % 4)
        return base64.b64decode(data).decode('utf-8')
    except: return "{}"

# ================= MEGAFLIX (BUSCA RÁPIDA) =================
def get_megaflix():
    items = []
    try:
        r = requests.post(f"{MEGAFLIX_API}?page=viewChannels", headers=COMMON_HEADERS, timeout=15)
        matches = re.findall(r'data-data="([^"]+)"', r.text)
        for b64 in matches:
            try:
                d = json.loads(decode_b64(b64))
                cid = d.get("id")
                name = d.get("name") or d.get("titulo")
                if cid and name:
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

# ================= YOUCINE (BUSCA EXAUSTIVA) =================
def get_ycine_all():
    all_items = []
    try:
        # 1. Descobrir total de canais e páginas
        init_res = requests.get(f"{YCINE_API}/channels?per_page=100", headers=COMMON_HEADERS, timeout=10).json()
        meta = init_res.get("data", {}).get("meta", {})
        total_pages = meta.get("total_pages", 1)
        
        # 2. Mapear categorias (para grupos inteligentes)
        cat_res = requests.get(f"{YCINE_API}/channels/categories", headers=COMMON_HEADERS, timeout=10).json()
        cat_map = {str(c["id"]): c["name"] for c in cat_res.get("data", [])}

        def fetch_page(p):
            try:
                url = f"{YCINE_API}/channels?per_page=100&page={p}"
                res = requests.get(url, headers=COMMON_HEADERS, timeout=15).json()
                return res.get("data", {}).get("items", [])
            except: return []

        # 3. Baixar todas as páginas em paralelo (Inteligente)
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_page = {executor.submit(fetch_page, p): p for p in range(1, total_pages + 1)}
            for future in as_completed(future_to_page):
                items = future.result()
                for i in items:
                    # Link Speed CDN - O mais rápido de carregar
                    stream = f"https://speed.megafilmeshd9.com/midia/speed-1/{i['id']}.m3u8"
                    group = cat_map.get(str(i.get("category_id")), "GERAL")
                    all_items.append({
                        "name": f"[YC] {i['name'].upper()}",
                        "url": stream,
                        "logo": i.get("thumbnail") or i.get("stream_icon"),
                        "group": f"YOUCINE | {group.upper()}"
                    })
    except Exception as e:
        print(f"Erro YouCine Total: {e}")
    return all_items

# ================= ROTAS =================
@app.route('/')
def home():
    return "<h1>Servidor M3U V25.0 (Full Catálogo)</h1><p>Sistema Pronto para Tivimate</p>"

@app.route('/playlist.m3u')
def playlist():
    global cache
    now = time.time()
    
    # Se tiver cache de menos de 30 min, entrega o que já está pronto
    if cache["data"] and (now - cache["time"] < 1800):
        return Response(cache["data"], mimetype='text/plain')

    # Cabeçalho da Lista
    m3u = "#EXTM3U\n"
    m3u += '#EXTINF:-1 tvg-id="v25" group-title="-- INFO --",>> LISTA COMPLETA CARREGADA V25 <<\n'
    m3u += 'http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4\n'

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_mf = executor.submit(get_megaflix)
        f_yc = executor.submit(get_ycine_all)
        
        all_items = f_mf.result() + f_yc.result()

    if not all_items:
        # Canal de segurança caso as APIs principais falhem
        m3u += '#EXTINF:-1 tvg-id="offline" group-title="ERRO",SERVIDORES EM MANUTENÇÃO - TENTE LOGO MAIS\n'
        m3u += 'https://shls-globo-rj-prod.akamaized.net/out/v1/f1545648f572421a868494b5952c286a/index.m3u8\n'
    else:
        # Ordenar por grupo para ficar bonito no Tivimate
        all_items.sort(key=lambda x: x['group'])
        for item in all_items:
            tid = item["name"].lower().replace(" ", ".")
            m3u += f'#EXTINF:-1 tvg-id="{tid}" tvg-logo="{item["logo"]}" group-title="{item["group"]}",{item["name"]}\n'
            m3u += f'{item["url"]}\n'
    
    cache["data"] = m3u
    cache["time"] = now
    return Response(m3u, mimetype='text/plain')

@app.route('/play')
def play():
    """Redirecionador para links do MegaFlix."""
    eid = request.args.get('id')
    if not eid: return "Erro", 400
    cid = base64.b64decode(eid).decode()
    try:
        t_url = f"https://app.megafrixapi.com/get_token_channel.php?channel={cid}"
        payload = {"id": 0, "type": "app", "headers": {"User-Agent": "Mozilla/5.0"}}
        res = requests.post(t_url, json=payload, headers=COMMON_HEADERS, timeout=10).json()
        final = res.get("url") or res.get("stream")
        if final: return redirect(final)
    except: pass
    return "Link Off", 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
