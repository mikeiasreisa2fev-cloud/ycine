from flask import Flask, Response, redirect, request
import requests
from bs4 import BeautifulSoup
import re
import base64
from concurrent.futures import ThreadPoolExecutor
import os

app = Flask(__name__)

# ================= CONFIGURAÇÕES (VERSÃO 15.0) =================
# Configurações do MegaFlix
MEGAFLIX_API = "https://app.megafrixapi.com/TV/1.2/"
MEGAFLIX_REFERER = "https://megaflix.name/"

# Configurações do YouCine (Fontes espelhadas)
YCINE_SOURCES = [
    "https://ycineflix.tudo30.shop",
    "https://app.pobreflix2.site"
]

# Headers Padrão (Simulando App Android)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": MEGAFLIX_REFERER
}

# ================= UTILITÁRIOS =================
def fix_base64_padding(data):
    """Corrige o preenchimento de strings Base64 se necessário."""
    return data + "=" * ((4 - len(data) % 4) % 4)

def decode_b64(data):
    """Decodifica strings Base64 do sistema MegaFlix/YouCine."""
    try:
        data = fix_base64_padding(data)
        return base64.b64decode(data).decode('utf-8')
    except:
        return data

# ================= LÓGICA MEGAFLIX =================
def get_megaflix_data(endpoint, page=1):
    """Extrai itens do MegaFlix usando a lógica de POST e Base64."""
    results = []
    url = f"{MEGAFLIX_API}?page={endpoint}"
    if page > 1: url += f"&p={page}"
    
    try:
        response = requests.post(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            # Regex baseada no código Smali: getSource('URL_B64', 'DATA_B64')
            matches = re.findall(r"getSource\('([^']+)','([^']+)'\).*?class=\"title\">(.*?)</div>.*?src=\"([^\"]+)\"", response.text, re.DOTALL)
            for url_b64, data_b64, name, thumb in matches:
                results.append({
                    "name": name.strip(),
                    "url": decode_b64(url_b64),
                    "logo": thumb,
                    "group": f"MegaFlix {endpoint.replace('view', '')}"
                })
    except Exception as e:
        print(f"Erro MegaFlix ({endpoint}): {e}")
    return results

# ================= LÓGICA YOUCINE =================
def get_ycine_data(category, page=1):
    """Extrai itens do YouCine via scraping de cartões HTML."""
    results = []
    path = f"/{category}/"
    if page > 1: path += f"page/{page}/"
    
    for base in YCINE_SOURCES:
        try:
            response = requests.get(f"{base}{path}", headers=HEADERS, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                # Busca classes identificadas na análise do app (iptv-card, movie-card)
                cards = soup.find_all(class_=['iptv-card', 'card', 'item', 'movie-card'])
                for card in cards:
                    title_el = card.find(class_=['title', 'name', 'entry-title'])
                    link_el = card.find('a')
                    img_el = card.find('img')
                    
                    if title_el and link_el:
                        results.append({
                            "name": title_el.text.strip(),
                            "url": link_el['href'] if link_el['href'].startswith('http') else base + link_el['href'],
                            "logo": img_el['src'] if img_el else "",
                            "group": f"YouCine {category.capitalize()}"
                        })
                if results: break # Se achou itens, não tenta o próximo espelho
        except: continue
    return results

# ================= ROTAS DO SERVIDOR =================
@app.route('/')
def home():
    return "<h1>Servidor M3U Ativo (V15.0)</h1><p>MegaFlix + YouCine</p><a href='/playlist.m3u'>Link da Playlist</a>"

@app.route('/playlist.m3u')
def generate_m3u():
    m3u = "#EXTM3U\n"
    all_items = []
    
    # Executa as extrações em paralelo para ser super rápido
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = []
        # MegaFlix: Canais + 5 páginas de filmes/series
        futures.append(executor.submit(get_megaflix_data, "viewChannels"))
        for i in range(1, 6):
            futures.append(executor.submit(get_megaflix_data, "viewMovies", i))
            futures.append(executor.submit(get_megaflix_data, "viewSeries", i))
        
        # YouCine: Canais + 5 páginas de filmes/series
        futures.append(executor.submit(get_ycine_data, "canais"))
        for i in range(1, 6):
            futures.append(executor.submit(get_ycine_data, "filmes", i))
            futures.append(executor.submit(get_ycine_data, "series", i))
            
        for f in futures: all_items.extend(f.result())

    # Monta o arquivo M3U
    for item in all_items:
        tid = item["name"].lower().replace(" ", ".")
        # Canais YouCine passam pelo redirecionador para extrair o .m3u8 final
        if "YouCine" in item["group"] and "canais" in item["group"].lower():
            encoded_url = base64.b64encode(item["url"].encode()).decode()
            stream_link = f"{request.host_url.rstrip('/')}/play?u={encoded_url}"
        else:
            stream_link = item["url"]
            
        m3u += f'#EXTINF:-1 tvg-id="{tid}" tvg-logo="{item["logo"]}" group-title="{item["group"]}",{item["name"]}\n'
        m3u += f'{stream_link}\n'
        
    return Response(m3u, mimetype='application/x-mpegurl')

@app.route('/play')
def play_redirect():
    """Extrai o link de vídeo direto (.m3u8) da página do YouCine."""
    encoded_url = request.args.get('u')
    if not encoded_url: return "URL Inválida", 400
    target = base64.b64decode(encoded_url).decode()
    
    try:
        res = requests.get(target, headers=HEADERS, timeout=10)
        # Tenta achar link .m3u8 no script ou iframe
        match = re.search(r'["\'](http[^"\']+\.m3u8[^"\']*)["\']', res.text)
        if match: return redirect(match.group(1))
        
        # Fallback para iframe de player
        iframe = re.search(r'<iframe.*?src=["\']([^"\']+)["\']', res.text)
        if iframe: return redirect(iframe.group(1))
    except: pass
    
    return "Stream não encontrado", 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
