from flask import Flask, Response, redirect, request, stream_with_context
import requests
import re
import os
import time
import threading

app = Flask(__name__)

# Configuração da lista do Google Drive
DRIVE_FILE_ID = "11xLQKuz4uicx-SFIr2zLbp9whDSvnXbE"
# Link com parâmetros para forçar download direto e contornar confirmações do Drive
DRIVE_URL = f"https://docs.google.com/uc?export=download&confirm=t&id={DRIVE_FILE_ID}"

CATALOG_STORE = {
    "drive_m3u": "#EXTM3U\n# Carregando drive...",
    "last_update": 0
}

def get_drive_channels():
    """Extrai canais da lista do Google Drive de forma otimizada."""
    items = []
    try:
        # User-Agent simulando navegador para evitar bloqueios e limites de requisição
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(DRIVE_URL, headers=headers, timeout=20)
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
                        items.append({
                            "name": current_name.upper(), 
                            "url": line, 
                            "logo": current_logo, 
                            "group": "MINHA LISTA DRIVE"
                        })
                    current_name = None
    except Exception as e:
        print(f"Erro ao buscar canais: {e}")
    return items

def update_catalogs_task():
    """Mantém a lista atualizada em cache na memória para resposta instantânea."""
    while True:
        try:
            drive_items = get_drive_channels()
            if drive_items:
                m3u_dr = "#EXTM3U\n"
                host_url = request.url_root if 'request' in globals() else ""
                
                for item in drive_items:
                    # O segredo da fluidez: a URL do canal aponta para o proxy do seu próprio servidor
                    # Passamos a URL real codificada em Base64 ou URL segura para evitar quebras
                    import urllib.parse
                    encoded_url = urllib.parse.quote_plus(item["url"])
                    
                    # Rota interna que vai gerenciar o fluxo do canal
                    proxy_url = f"/stream?url={encoded_url}"
                    
                    m3u_dr += f'#EXTINF:-1 tvg-logo="{item["logo"]}" group-title="{item["group"]}",{item["name"]}\n{proxy_url}\n'
                
                CATALOG_STORE["drive_m3u"] = m3u_dr
                CATALOG_STORE["last_update"] = time.time()
        except Exception as e:
            print(f"Erro na tarefa de atualização: {e}")
        time.sleep(1200)

# Inicia a atualização em segundo plano imediatamente
threading.Thread(target=update_catalogs_task, daemon=True).start()

@app.route('/')
def home():
    return "<h1>Servidor M3U Otimizado Ativo</h1>"

@app.route('/drive.m3u')
def drive_playlist():
    # Modifica os links gerados para usar o domínio atual de forma dinâmica
    host = request.host_url
    playlist = CATALOG_STORE["drive_m3u"].replace("/stream?url=", f"{host}stream?url=")
    return Response(playlist, mimetype='text/plain')

@app.route('/stream')
def stream_proxy():
    """Proxy de streaming com buffer em pedaços (chunks) para eliminar travamentos."""
    target_url = request.args.get('url')
    if not target_url:
        return "URL do canal ausente", 400

    import urllib.parse
    target_url = urllib.parse.unquote_plus(target_url)

    def generate():
        headers = {"User-Agent": "Mozilla/5.0"}
        # stream=True faz o download em tempo real sem carregar o vídeo inteiro na memória do servidor
        with requests.get(target_url, headers=headers, stream=True, timeout=15) as r:
            # Transmite blocos de 16KB por vez para manter a reprodução contínua e fluida
            for chunk in r.iter_content(chunk_size=16384):
                if chunk:
                    yield chunk

    try:
        return Response(stream_with_context(generate()), content_type="video/mp2t")
    except Exception as e:
        return f"Erro na transmissão: {e}", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
