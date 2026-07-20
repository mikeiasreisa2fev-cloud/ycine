from flask import Flask, Response, redirect, request
import requests
import re
import base64
import json
from concurrent.futures import ThreadPoolExecutor
import os
import time

app = Flask(__name__)

# ================= CONFIGURAÇÕES (VERSÃO 24.0) =================
# Headers ultra-realistas (Simulando App YouCine/MegaFlix original)
# O User-Agent 'Dalvik' é o que apps Android usam internamente.
COMMON_HEADERS = {
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 12; SM-G998B Build/SP1A.210812.016)",
    "Connection": "Keep-Alive",
    "Accept-Encoding": "gzip",
    "X-Requested-With": "com.ycineflix.app"
}

MEGAFLIX_API = "https://app.megafrixapi.com/TV/1.2/"
YCINE_API = "https://ycineflix.tudo30.shop/wp-json/xui-pflix/v1"

# Cache Global para evitar excesso de requisições e bloqueios
cache = {"data": None, "time": 0}

# ================= UTILITÁRIOS =================
def decode_b64(data):
    """Decodifica Base64 corrigindo preenchimento e quebras de linha."""
    try:
        # Limpa a string de sujeiras que quebram o Base64
        data = data.replace("\n", "").replace("\r", "").replace(" ", "").strip()
        data += "=" * ((4 - len(data) % 4) % 4)
        return base64.b64decode(data).decode('utf-8')
    except: 
        return "{}"

# ================= LÓGICA MEGAFLIX =================
def get_megaflix():
    """Extrai canais do MegaFlix simulando o tráfego do App."""
    items = []
    try:
        # O MegaFlix alterna entre aceitar POST ou GET dependendo do servidor
        r = requests.post(f"{MEGAFLIX_API}?page=viewChannels", headers=COMMON_HEADERS, timeout=15)
        if r.status_code != 200:
            r = requests.get(f"{MEGAFLIX_API}?page=viewChannels", headers=COMMON_HEADERS, timeout=15)
            
        # Captura os dados brutos de cada canal (estão em Base64 dentro de data-data)
        matches = re.findall(r'data-data="([^"]+)"', r.text)
        for b64 in matches:
            try:
                decoded = decode_b64(b64)
                d = json.loads(decoded)
                cid = d.get("id")
                name = d.get("name") or d.get("titulo")
                if cid and name:
                    # Codifica o ID para nossa rota de play
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
    """Busca canais diretamente na API REST oficial do YouCine."""
    items = []
    try:
        # Acesso direto à lista de canais (100 por página)
        res = requests.get(f"{YCINE_API}/channels?per_page=100", headers=COMMON_HEADERS, timeout=15)
        if res.status_code == 200:
            data = res.json().get("data", {}).get("items", [])
            for i in data:
                # Link direto via CDN Speed (Padrão YouCine para Android)
                stream = f"https://speed.megafilmeshd9.com/midia/speed-1/{i['id']}.m3u8"
                items.append({
                    "name": f"[YC] {i['name'].upper()}",
                    "url": stream,
                    "logo": i.get("thumbnail") or i.get("stream_icon"),
                    "group": f"YOUCINE | {i.get('category_name', 'GERAL').upper()}"
                })
    except: pass
    return items

# ================= ROTAS DO SERVIDOR =================
@app.route('/')
def home():
    return "<h1>Servidor M3U Ativo (V24.0)</h1><p>Sistema Online</p><a href='/playlist.m3u'>Gerar M3U</a>"

@app.route('/playlist.m3u')
def playlist():
    global cache
    now = time.time()
    
    # Se a lista foi gerada há menos de 10 minutos, usa o cache para carregar instantâneo
    if cache["data"] and (now - cache["time"] < 600):
        return Response(cache["data"], mimetype='text/plain')

    # Cabeçalho da Lista
    m3u = "#EXTM3U\n"
    m3u += '#EXTINF:-1 tvg-id="info" group-title="-- STATUS --",>> LISTA CARREGADA V24 <<\n'
    m3u += 'http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4\n'

    # Busca MegaFlix e YouCine ao mesmo tempo
    with ThreadPoolExecutor(max_workers=2) as executor:
        f_mf = executor.submit(get_megaflix)
        f_yc = executor.submit(get_ycine)
        
        all_items = []
        try: all_items.extend(f_mf.result(timeout=15))
        except: pass
        try: all_items.extend(f_yc.result(timeout=15))
        except: pass

    # Caso as fontes falhem, adiciona um canal de emergência para a lista não dar erro
    if not all_items:
        m3u += '#EXTINF:-1 tvg-id="aviso" group-title="ERRO",FONTES BLOQUEADAS - TENTE NOVAMENTE EM BREVE\n'
        m3u += 'https://shls-globo-rj-prod.akamaized.net/out/v1/f1545648f572421a868494b5952c286a/index.m3u8\n'
    else:
        for item in all_items:
            tid = item["name"].lower().replace(" ", ".")
            m3u += f'#EXTINF:-1 tvg-id="{tid}" tvg-logo="{item["logo"]}" group-title="{item["group"]}",{item["name"]}\n'
            m3u += f'{item["url"]}\n'
    
    # Salva no cache
    cache["data"] = m3u
    cache["time"] = now
    
    return Response(m3u, mimetype='text/plain')

@app.route('/play')
def play():
    """Gera token MegaFlix em tempo real para o link não expirar."""
    eid = request.args.get('id')
    if not eid: return "Erro", 400
    cid = base64.b64decode(eid).decode()
    try:
        t_url = f"https://app.megafrixapi.com/get_token_channel.php?channel={cid}"
        # Envia o JSON que o servidor MegaFlix espera
        payload = {"id": 0, "type": "app", "headers": {"User-Agent": "Mozilla/5.0"}}
        res = requests.post(t_url, json=payload, headers=COMMON_HEADERS, timeout=10).json()
        
        final_url = res.get("url") or res.get("stream")
        if final_url: 
            return redirect(final_url)
    except: pass
    
    return "Canal Fora do Ar", 404

if __name__ == "__main__":
    # Porta configurada automaticamente pelo Render.com
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
