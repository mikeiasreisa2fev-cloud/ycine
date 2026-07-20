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

# Configuração da lista do Google Drive
DRIVE_FILE_ID = "11xLQKuz4uicx-SFIr2zLbp9whDSvnXbE"
DRIVE_URL = f"https://drive.google.com/uc?export=download&id={DRIVE_FILE_ID}"

CATALOG_STORE = {
    "drive_m3u": "#EXTM3U\n# Carregando drive...",
    "last_update": 0
}

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
    except:
        pass
    return items

def update_catalogs_task():
    """Mantém a lista atualizada em memória a cada 20 minutos."""
    while True:
        try:
            drive_items = get_drive_channels()
            if drive_items:
                m3u_dr = "#EXTM3U\n"
                for item in drive_items:
                    m3u_dr += f'#EXTINF:-1 tvg-logo="{item["logo"]}" group-title="{item["group"]}",{item["name"]}\n{item["url"]}\n'
                CATALOG_STORE["drive_m3u"] = m3u_dr
                CATALOG_STORE["last_update"] = time.time()
        except:
            pass
        time.sleep(1200)

# Inicia a atualização em segundo plano
threading.Thread(target=update_catalogs_task, daemon=True).start()

@app.route('/')
def home():
    return "<h1>Servidor M3U Ativo</h1>"

@app.route('/drive.m3u')
def drive_playlist():
    return Response(CATALOG_STORE["drive_m3u"], mimetype='text/plain')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
