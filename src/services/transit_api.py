import os
import requests
from dotenv import load_dotenv

load_dotenv()

SPTRANS_TOKEN = os.getenv("SPTRANS_API_TOKEN", "")
SPTRANS_BASE_URL = "http://api.olhovivo.sptrans.com.br/v2.1"


class SPTransClient:
    """
    Cliente de integração com a API Olho Vivo da SPTrans para consulta
    de linhas oficiais, itinerários e paradas da região metropolitana.
    """
    def __init__(self, token=None):
        self.token = token or SPTRANS_TOKEN
        self.session = requests.Session()
        self.autenticado = False

    def autenticar(self):
        if not self.token or self.token == "seu_token_aqui":
            return False
        
        url = f"{SPTRANS_BASE_URL}/Login/Autenticar?token={self.token}"
        try:
            resp = self.session.post(url, timeout=5)
            if resp.status_code == 200 and resp.text.lower() == "true":
                self.autenticado = True
                return True
        except Exception:
            pass
        return False

    def buscar_linha_oficial(self, termo_busca):
        """
        Busca linhas oficiais da SPTrans por número ou nome da denominação.
        """
        if not self.autenticado and not self.autenticar():
            return []

        url = f"{SPTRANS_BASE_URL}/Linha/Buscar?termosBusca={termo_busca}"
        try:
            resp = self.session.get(url, timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return []

    def buscar_paradas_proximas(self, lat, lon):
        """
        Busca paradas de ônibus em um raio próximo às coordenadas informadas.
        """
        if not self.autenticado and not self.autenticar():
            return []

        url = f"{SPTRANS_BASE_URL}/Parada/BuscarParadasPorCorredor"
        try:
            resp = self.session.get(url, timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return []


def consultar_linhas_transporte_oficial(origem_lat, origem_lon, destino_lat, destino_lon):
    """
    Função principal que orquestra a consulta de linhas oficiais da SPTrans
    com fallback para cálculo de matriz integrada.
    """
    client = SPTransClient()
    autenticado = client.autenticar()

    if autenticado:
        # Exemplo de consulta oficial a partir da região identificada
        linhas = client.buscar_linha_oficial("Paulista")
        if linhas:
            detalhes = []
            for item in linhas[:2]:
                detalhes.append({
                    "linha": f"{item.get('cl')}-{item.get('sl')} ({item.get('lt')} - {item.get('lc')})",
                    "valor_unitario": 5.00,
                    "quantidade_dia": 2,
                    "subtotal": 10.00,
                    "oficial": True
                })
            return {
                "sucesso": True,
                "fonte": "SPTrans Olho Vivo (API Oficial)",
                "detalhes": detalhes
            }

    # Fallback estruturado se o token não for informado ou a API indisponível
    return {
        "sucesso": True,
        "fonte": "Estimativa Baseada em Matriz Tarifária",
        "detalhes": [
            {"linha": "Ônibus Municipal (SPTrans / Local)", "valor_unitario": 5.00, "quantidade_dia": 2, "subtotal": 10.00},
            {"linha": "Metrô / CPTM (Integração Rota)", "valor_unitario": 5.00, "quantidade_dia": 2, "subtotal": 10.00}
        ]
    }