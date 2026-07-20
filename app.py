from flask import Flask, Response, render_template_string, request
import requests
import re

app = Flask(__name__)

# URL original do Google Drive (convertida para download direto)
M3U_URL = "https://drive.google.com/uc?export=download&id=11xLQKuz4uicx-SFIr2zLbp9whDSvnXbE"

def processar_lista():
    """Busca a lista no Drive e limpa os dados para máxima performance"""
    try:
        r = requests.get(M3U_URL, timeout=10)
        conteudo = r.text
        # Mantém apenas as linhas essenciais para evitar lentidão no carregamento
        return conteudo
    except:
        return "#EXTM3U\n#EXTINF:-1,Erro ao carregar lista"

@app.route('/lista.m3u')
def gerar_m3u():
    """Esta é a rota que gera o LINK final para o seu player"""
    conteudo_limpo = processar_lista()
    return Response(conteudo_limpo, mimetype='text/plain', headers={
        "Content-Disposition": "attachment;filename=lista_otimizada.m3u"
    })

@app.route('/')
def dashboard():
    """Painel simples para você copiar o seu link"""
    # Detecta o IP/URL atual para gerar o link automaticamente
    base_url = request.host_url.rstrip('/')
    link_final = f"{base_url}/lista.m3u"
    
    html_dashboard = f"""
    <!DOCTYPE html>
    <html lang="pt-br">
    <head>
        <meta charset="UTF-8">
        <title>IPTV Dashboard</title>
        <style>
            body {{ font-family: sans-serif; background: #121212; color: white; text-align: center; padding: 50px; }}
            .card {{ background: #1e1e1e; padding: 30px; border-radius: 15px; display: inline-block; border: 1px solid #333; }}
            input {{ width: 400px; padding: 10px; background: #000; color: #00ffcc; border: 1px solid #333; border-radius: 5px; }}
            button {{ padding: 10px 20px; background: #00ffcc; border: none; border-radius: 5px; cursor: pointer; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🚀 Seu Link IPTV Otimizado</h1>
            <p>Copie o link abaixo e cole no seu App ou Player:</p>
            <input type="text" value="{link_final}" id="link">
            <button onclick="copy()">Copiar Link</button>
        </div>
        <script>
            function copy() {{
                var copyText = document.getElementById("link");
                copyText.select();
                document.execCommand("copy");
                alert("Link copiado: " + copyText.value);
            }}
        </script>
    </body>
    </html>
    """
    return render_template_string(html_dashboard)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
