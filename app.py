from flask import Flask, Response, redirect, request
import requests
import re
import base64
import json
from concurrent.futures import ThreadPoolExecutor
import os

app = Flask(__name__)

# ================= CONFIGURAÇÕES (VERSÃO 20.0) =================
# MegaFlix
MEGAFLIX_API = "https://app.megafrixapi.com/TV/1.2/"
MEGAFLIX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
    "Referer": "https://megaflix.name/",
    "X-Requested-With": "XMLHttpRequest"
}

# YouCine (REST API)
YCINE_API_BASE = "https://ycineflix.tudo30.shop/wp-json/xui-pflix/v1"
YCINE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ================= UTILITÁRIOS =================
def decode_b64(data):
    try:
        data += "=" * ((4 - len(data) % 4) % 4)
        return base64.b64decode(data).decode('utf-8')
    except: return data

# ================= LÓGICA MEGAFLIX =================
def get_megaflix_channels():
    """Extrai todos os canais de TV disponíveis no MegaFlix."""
    items = []
    try:
        # Pede a lista de canais via POST (padrão do App)
        response = requests.post(f"{MEGAFLIX_API}?page=viewChannels", headers=MEGAFLIX_HEADERS, timeout=15)
        if response.status_code == 200:
            # Captura blocos JSON codificados em Base64 dentro do HTML
            matches = re.findall(r'data-data="([^"]+)"', response.text)
            for b64_json in matches:
                try:
                    data = json.loads(decode_b64(b64_json))
                    item_id = data.get("id")
                    name = data.get("name") or data.get("titulo")
                    thumb = data.get("background") or data.get("img")

                    if item_id and name:
                        encoded_id = base64.b64encode(str(item_id).encode()).decode()
                        # Rota interna /play para gerar o token do MegaFlix sob demanda
                        play_url = f"{request.host_url.rstrip('/')}/play?t=m_live&id={encoded_id}"

                        items.append({
                            "name": name.strip(),
                            "url": play_url,
                            "logo": thumb,
                            "group": "MegaFlix | Canais"
                        })
                except: continue
    except Exception as e:
        print(f"Erro MegaFlix: {e}")
    return items

# ================= LÓGICA YOUCINE =================
def fetch_ycine_category_map():
    """Obtém o mapeamento de IDs para nomes de categorias (Globo, Esportes, etc)."""
    try:
        url = f"{YCINE_API_BASE}/channels/categories"
        res = requests.get(url, headers=YCINE_HEADERS, timeout=10).json()
        return {str(cat["id"]): cat["name"] for cat in res.get("data", [])}
    except: return {}

def get_ycine_channels():
    """Busca exaustivamente todos os canais de TV do YouCine (múltiplas páginas)."""
    all_channels = []
    cat_map = fetch_ycine_category_map()

    def fetch_page(p):
        try:
            # per_page=100 é o limite máximo por requisição
            url = f"{YCINE_API_BASE}/channels?per_page=100&page={p}"
            res = requests.get(url, headers=YCINE_HEADERS, timeout=15).json()
            items = res.get("data", {}).get("items", [])
            return items
        except: return []

    # Varre as primeiras 8 páginas (até 800 canais) em paralelo
    with ThreadPoolExecutor(max_workers=8) as executor:
        pages_data = executor.map(fetch_page, range(1, 9))
        for items in pages_data:
            for item in items:
                # Link direto via Speed CDN identificado na análise do tráfego do App
                stream_url = f"https://speed.megafilmeshd9.com/midia/speed-1/{item['id']}.m3u8"
                cat_name = cat_map.get(str(item.get("category_id")), "TV")

                all_channels.append({
                    "name": item["name"],
                    "url": stream_url,
                    "logo": item.get("thumbnail") or item.get("logo"),
                    "group": f"YouCine | {cat_name}"
                })
    return all_channels

# ================= ROTAS DO SERVIDOR =================
@app.route('/')
def index():
    return "<h1>Servidor M3U Canais TV V20.0</h1><p>MegaFlix + YouCine Integrados</p><a href='/playlist.m3u'>Acessar Playlist</a>"

@app.route('/playlist.m3u')
def playlist():
    m3u = "#EXTM3U\n"

    # Busca dados das duas fontes em paralelo
    with ThreadPoolExecutor(max_workers=2) as executor:
        f_mega = executor.submit(get_megaflix_channels)
        f_ycine = executor.submit(get_ycine_channels)

        all_items = f_mega.result() + f_ycine.result()

    for item in all_items:
        # Gera ID para o guia de programação (EPG)
        tid = item["name"].lower().replace(" ", ".")
        m3u += f'#EXTINF:-1 tvg-id="{tid}" tvg-logo="{item["logo"]}" group-title="{item["group"]}",{item["name"]}\n'
        m3u += f'{item["url"]}\n'

    return Response(m3u, mimetype='application/x-mpegurl')

@app.route('/play')
def play_redirect():
    """Gera o link de streaming final para o MegaFlix em tempo real."""
    t = request.args.get('t')
    encoded_id = request.args.get('id')
    if not encoded_id: return "ID ausente", 400
    item_id = base64.b64decode(encoded_id).decode()

    try:
        if t == "m_live":
            # O MegaFlix exige um token gerado via PHP para liberar o link .m3u8
            token_url = f"https://app.megafrixapi.com/get_token_channel.php?channel={item_id}"
            payload = {"id": 0, "type": "app", "headers": MEGAFLIX_HEADERS}
            res = requests.post(token_url, json=payload, headers=MEGAFLIX_HEADERS, timeout=10).json()

            final_url = res.get("url") or res.get("stream")
            if final_url: return redirect(final_url)
    except: pass

    return "Canal temporariamente fora do ar", 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
