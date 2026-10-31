import io
import requests
import matplotlib
matplotlib.use('Agg') # Backend sem interface gráfica para servidores
import matplotlib.pyplot as plt

def gerar_imagem_mapa_rota(origem_lat, origem_lon, destino_lat, destino_lon):
    """
    Busca os pontos da rota via OSRM/API e desenha um mapa estático com a rota,
    ponto de origem (verde) e destino (vermelho) em formato PNG para o PDF.
    """
    # Consulta a rota geométrica no OSRM
    url = f"http://router.project-osrm.org/route/v1/driving/{origem_lon},{origem_lat};{destino_lon},{destino_lat}?overview=full&geometries=geojson"
    
    lats = [origem_lat, destino_lat]
    lons = [origem_lon, destino_lon]
    
    try:
        resp = requests.get(url, timeout=5)
        data = resp.json()
        if data.get("code") == "Ok":
            coords = data["routes"][0]["geometry"]["coordinates"]
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
    except Exception:
        pass

    # Cria a figura Matplotlib
    fig, ax = plt.subplots(figsize=(7, 3.5), dpi=150)
    
    # Plota a linha da rota
    ax.plot(lons, lats, color='#1E3A8A', linewidth=3, label='Trajeto Sugerido')
    
    # Plota marcadores de Origem e Destino
    ax.scatter([origem_lon], [origem_lat], color='#16A34A', s=120, zorder=5, label='Origem (Residência)')
    ax.scatter([destino_lon], [destino_lat], color='#DC2626', s=120, zorder=5, label='Destino (Empresa)')
    
    # Ajustes estéticos e margens do gráfico
    ax.set_title("Evidência Cartográfica do Trajeto", fontsize=10, fontweight='bold', color='#1E3A8A', pad=10)
    ax.set_xlabel("Longitude", fontsize=8)
    ax.set_ylabel("Latitude", fontsize=8)
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.legend(loc='upper right', fontsize=8)
    
    # Converte o gráfico para buffer PNG em memória
    img_buffer = io.BytesIO()
    plt.tight_layout()
    plt.savefig(img_buffer, format='png', bbox_inches='tight')
    plt.close(fig)
    img_buffer.seek(0)
    
    return img_buffer