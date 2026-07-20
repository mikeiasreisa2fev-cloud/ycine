from flask import Flask, jsonify, Response
import requests
import re

app = Flask(__name__)

# URL da lista M3U no Google Drive
M3U_URL = "https://drive.google.com/uc?export=download&id=11xLQKuz4uicx-SFIr2zLbp9whDSvnXbE"

def parse_m3u(content):
    channels = []
    # Regex para extrair logo, grupo e nome
    pattern = re.compile(r'#EXTINF:-1.*?tvg-logo="(.*?)".*?group-title="(.*?)",(.*)\n(http.*)', re.MULTILINE)
    matches = pattern.findall(content)
    
    for match in matches:
        logo, category, name, url = match
        channels.append({
            "name": name.strip(),
            "logo": logo.strip(),
            "category": category.strip() or "Geral", # "General" mudado para "Geral"
            "url": url.strip()
        })
    return channels

@app.route('/api/canais', methods=['GET']) # Rota traduzida
def get_channels():
    try:
        response = requests.get(M3U_URL, timeout=15)
        response.raise_for_status()
        channels = parse_m3u(response.text)
        
        categories = {}
        for channel in channels:
            cat = channel['category']
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(channel)
        
        result = []
        for cat_name, chs in categories.items():
            result.append({
                "name": cat_name,
                "channels": chs
            })
            
        return jsonify(result)
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

@app.route('/')
def index():
    return "Servidor Proxy IPTV Ativo. Use a rota /api/canais para obter os dados."

if __name__ == '__main__':
    print("Iniciando servidor IPTV na porta 5000...")
    app.run(host='0.0.0.0', port=5000, debug=True)
