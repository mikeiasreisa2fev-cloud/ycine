from flask import Flask, Response, redirect, request
import requests
import re
import base64
from concurrent.futures import ThreadPoolExecutor
import os

app = Flask(__name__)

# ================= CONFIGURAÇÕES (VERSÃO 16.0) =================
# MegaFlix - Configurações extraídas do App
MEGAFLIX_API = "https://app.megafrixapi.com/TV/1.2/"
MEGAFLIX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
    "Referer": "https://megaflix.name/",
    "X-Requested-With": "XMLHttpRequest"
}

# YouCine - API REST oficial identificada na análise
YCINE_API_BASE = "https://ycineflix.tudo30.shop/wp-json/xui-pflix/v1"
YCINE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ================= UTILITÁRIOS =================
def decode_b64(data):
    """Decodifica strings Base64 do sistema MegaFlix."""
    try:
        # Corrige padding se necessário
        data += "=" * ((4 - len(data) % 4) % 4)
        return base64.b64decode(data).decode('utf-8')
    except:
        return data

# ================= LÓGICA MEGAFLIX =================
def fetch_megaflix_page(endpoint, page=1):
    """Extrai itens do MegaFlix usando POST e Base64."""
    items = []
    url = f"{MEGAFLIX_API}?page={endpoint}"
    if page > 1: url += f"&p={page}"
    try:
        response = requests.post(url, headers=MEGAFLIX_HEADERS, timeout=10)
        if response.status_code == 200:
            # Regex para capturar os dados codificados nos cartões do MegaFlix
            matches = re.findall(r"getSource\('([^']+)','([^']+)'\).*?class=\"title\">(.*?)</div>.*?src=\"([^\"]+)\"", response.text, re.DOTALL)
            for url_b64, data_b64, name, thumb in matches:
                items.append({
                    "name": name.strip(),
                    "url": decode_b64(url_b64),
                    "logo": thumb,
                    "group": f"MegaFlix {endpoint.replace('view', '')}"
                })
    except Exception as e:
        print(f"Erro MegaFlix ({endpoint}): {e}")
    return items

def get_megaflix_catalog():
    """Carrega o catálogo do MegaFlix em paralelo."""
    all_content = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_megaflix_page, "viewChannels")]
        # Carrega 3 páginas de filmes e séries para performance
        for i in range(1, 4):
            futures.append(executor.submit(fetch_megaflix_page, "viewMovies", i))
            futures.append(executor.submit(fetch_megaflix_page, "viewSeries", i))
        for f in futures: all_content.extend(f.result())
    return all_content

# ================= LÓGICA YOUCINE (REST API) =================
def get_ycine_stream(item_id, type="channels"):
    """Busca o link .m3u8 real de um canal YouCine via API."""
    try:
        url = f"{YCINE_API_BASE}/{type}/{item_id}/stream"
        res = requests.get(url, headers=YCINE_HEADERS, timeout=10).json()
        # O YouCine retorna o link direto no campo 'free_url'
        return res.get("data", {}).get("free_url") or res.get("data", {}).get("stream_url")
    except:
        return None

def fetch_ycine_category_map(type="channels"):
    """Cria um dicionário de IDs para Nomes de categorias do YouCine."""
    try:
        url = f"{YCINE_API_BASE}/{type}/categories"
        res = requests.get(url, headers=YCINE_HEADERS, timeout=10).json()
        return {str(cat["id"]): cat["name"] for cat in res.get("data", [])}
    except:
        return {}

def get_ycine_catalog():
    """Extrai canais do YouCine usando a API REST de alto desempenho."""
    items = []
    try:
        # 1. Obtém nomes das categorias
        cat_map = fetch_ycine_category_map("channels")
        
        # 2. Busca lista de canais (100 principais)
        list_url = f"{YCINE_API_BASE}/channels?per_page=100"
        response = requests.get(list_url, headers=YCINE_HEADERS, timeout=10).json()
        raw_items = response.get("data", {}).get("items", [])
        
        # 3. Resolve os links de stream em paralelo
        with ThreadPoolExecutor(max_workers=15) as executor:
            def process_item(item):
                stream = get_ycine_stream(item["id"], "channels")
                if stream:
                    cat_name = cat_map.get(str(item.get("category_id")), "YouCine TV")
                    return {
                        "name": item["name"],
                        "url": stream,
                        "logo": item.get("thumbnail") or item.get("logo"),
                        "group": f"YouCine | {cat_name}"
                    }
                return None

            results = executor.map(process_item, raw_items)
            items = [r for r in results if r]
            
    except Exception as e:
        print(f"YouCine Error: {e}")
    return items

# ================= ROTAS DO SERVIDOR =================
@app.route('/')
def index():
    return "<h1>M3U Server V16.0</h1><p>Status: ONLINE</p><a href='/playlist.m3u'>Gerar Playlist</a>"

@app.route('/playlist.m3u')
def playlist():
    m3u = "#EXTM3U\n"
    
    # Processa MegaFlix e YouCine simultaneamente
    with ThreadPoolExecutor(max_workers=2) as executor:
        f_mega = executor.submit(get_megaflix_catalog)
        f_ycine = executor.submit(get_ycine_catalog)
        
        all_items = f_mega.result() + f_ycine.result()

    # Gera as linhas do M3U para o Tivimate
    for item in all_items:
        # Cria um ID amigável para o guia de programação (EPG)
        tid = item["name"].lower().replace(" ", ".")
        m3u += f'#EXTINF:-1 tvg-id="{tid}" tvg-logo="{item["logo"]}" group-title="{item["group"]}",{item["name"]}\n'
        m3u += f'{item["url"]}\n'
        
    return Response(m3u, mimetype='application/x-mpegurl')

if __name__ == "__main__":
    # Render configura a porta via variável de ambiente
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
