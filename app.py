from flask import Flask, Response, redirect, request
import requests
import re
import base64
import json
from concurrent.futures import ThreadPoolExecutor
import os
import time

app = Flask(__name__)

# ================= CONFIGURAÇÕES (VERSÃO 26.0) =================
# User-Agent de Navegador Real (Evita bloqueios de nuvem como Cloudflare)
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Endpoints das fontes
MEGAFLIX_API = "https://app.megafrixapi.com/TV/1.2/"
YCINE_MIRRORS = [
    "https://ycineflix.tudo30.shop/wp-json/xui-pflix/v1",
    "https://app.pobreflix2.site/wp-json/xui-pflix/v1"
]

# Sistema de Cache para performance
cache = {"data": None, "time": 0}

# ================= UTILITÁRIOS =================
def decode_b64(data):
    """Decodifica strings Base64 limpando caracteres inválidos."""
    try:
        data = data.replace("\n", "").replace("\r", "").replace(" ", "").strip()
        data += "=" * ((4 - len(data) % 4) % 4)
        return base64.b64decode(data).decode('utf-8')
    except: 
        return "{}"

# ================= LÓGICA MEGAFLIX =================
def get_megaflix():
    """Extrai canais do MegaFlix simulando o aplicativo original."""
    items = []
    headers = {
        "User-Agent": BROWSER_UA,
        "Referer": "https://megaflix.name/",
        "X-Requested-With": "XMLHttpRequest"
    }
    try:
        # Tenta POST (padrão) e fallback para GET se falhar
        r = requests.post(f"{MEGAFLIX_API}?page=viewChannels", headers=headers, timeout=15)
        if r.status_code != 200:
            r = requests.get(f"{MEGAFLIX_API}?page=viewChannels", headers=headers, timeout=15)
            
        # Captura os canais codificados no HTML
        matches = re.findall(r'data-data="([^"]+)"', r.text)
        for b64 in matches:
            try:
                d = json.loads(decode_b64(b64))
                cid = d.get("id")
                name = d.get("name") or d.get("titulo")
                if cid and name:
                    # Codifica o ID para o redirecionador de play
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

# ================= LÓGICA YOUCINE =================
def get_ycine():
    """Busca canais nas APIs do YouCine usando sistema de espelhos (mirrors)."""
    items = []
    headers = {"User-Agent": BROWSER_UA}
    
    for base in YCINE_MIRRORS:
        try:
            # Obtém a lista de canais via API REST
            res = requests.get(f"{base}/channels?per_page=100", headers=headers, timeout=12)
            if res.status_code == 200:
                raw_data = res.json().get("data", {}).get("items", [])
                for i in raw_data:
                    # Link direto da CDN Speed (Alta velocidade)
                    items.append({
                        "name": f"[YC] {i['name'].upper()}",
                        "url": f"https://speed.megafilmeshd9.com/midia/speed-1/{i['id']}.m3u8",
                        "logo": i.get("thumbnail") or i.get("stream_icon"),
                        "group": f"YOUCINE | {i.get('category_name', 'GERAL').upper()}"
                    })
                if items: break # Se obteve sucesso em um mirror, ignora os outros
        except: continue
    return items

# ================= ROTAS FLASK =================
@app.route('/')
def home():
    return "<h1>Servidor M3U Ativo (V26.0)</h1><p>Status: ONLINE</p><a href='/playlist.m3u'>Playlist</a>"

@app.route('/playlist.m3u')
def playlist():
    global cache
    now = time.time()
    
    # Retorna cache se gerado há menos de 10 minutos
    if cache["data"] and (now - cache["time"] < 600):
        return Response(cache["data"], mimetype='text/plain')

    m3u = "#EXTM3U\n"
    m3u += '#EXTINF:-1 tvg-id="status" group-title="-- INFO --",>> LISTA CARREGADA V26 <<\n'
    m3u += 'http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4\n'

    # Processamento paralelo das fontes
    with ThreadPoolExecutor(max_workers=2) as executor:
        f_mf = executor.submit(get_megaflix)
        f_yc = executor.submit(get_ycine)
        
        all_items = []
        try: all_items.extend(f_mf.result(timeout=15))
        except: pass
        try: all_items.extend(f_yc.result(timeout=15))
        except: pass

    if not all_items:
        # Aviso visível caso as fontes principais estejam bloqueadas
        m3u += '#EXTINF:-1 tvg-id="err" group-title="AVISO",FONTES BLOQUEADAS - TENTE NOVAMENTE EM ALGUNS MINUTOS\n'
        m3u += 'https://shls-globo-rj-prod.akamaized.net/out/v1/f1545648f572421a868494b5952c286a/index.m3u8\n'
    else:
        # Constrói as linhas do M3U
        for item in all_items:
            tid = item["name"].lower().replace(" ", ".")
            m3u += f'#EXTINF:-1 tvg-id="{tid}" tvg-logo="{item["logo"]}" group-title="{item["group"]}",{item["name"]}\n'
            m3u += f'{item["url"]}\n'
    
    # Atualiza cache
    cache["data"] = m3u
    cache["time"] = now
    
    return Response(m3u, mimetype='text/plain')

@app.route('/play')
def play():
    """Redirecionador de Token para MegaFlix."""
    eid = request.args.get('id')
    if not eid: return "ID Error", 400
    cid = base64.b64decode(eid).decode()
    try:
        t_url = f"https://app.megafrixapi.com/get_token_channel.php?channel={cid}"
        payload = {"id": 0, "type": "app", "headers": {"User-Agent": "Mozilla/5.0"}}
        res = requests.post(t_url, json=payload, headers={"User-Agent": BROWSER_UA, "Referer": "https://megaflix.name/"}, timeout=10).json()
        final = res.get("url") or res.get("stream")
        if final: 
            return redirect(final)
    except: pass
    return "Offline", 404

if __name__ == "__main__":
    # Porta padrão para o Render.com
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
