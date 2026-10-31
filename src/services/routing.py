import os
import requests
from src.services.transit_api import consultar_linhas_transporte_oficial

def calcular_vale_combustivel(origem_lat, origem_lon, destino_lat, destino_lon, valor_por_km):
    """
    Calcula a distância rodoviária via OSRM e aplica o valor do KM.
    """
    url = f"http://router.project-osrm.org/route/v1/driving/{origem_lon},{origem_lat};{destino_lon},{destino_lat}?overview=false"
    
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data.get("code") == "Ok":
            distancia_metros = data["routes"][0]["distance"]
            distancia_km = distancia_metros / 1000.0
            custo_total = distancia_km * valor_por_km
            
            return {
                "sucesso": True,
                "distancia_km": round(distancia_km, 2),
                "custo_total": round(custo_total, 2)
            }
        else:
            return {"sucesso": False, "erro": "Não foi possível calcular a rota."}
            
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


def roteirizar_vale_transporte_automatico(origem_lat, origem_lon, destino_lat, destino_lon):
    """
    Obtém itinerário e linhas oficiais via API de transporte e calcula o custo mensal.
    """
    url = f"http://router.project-osrm.org/route/v1/driving/{origem_lon},{origem_lat};{destino_lon},{destino_lat}?overview=false"
    distancia_km = 10.0
    
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        if data.get("code") == "Ok":
            distancia_km = data["routes"][0]["distance"] / 1000.0
    except Exception:
        pass

    # Consulta a API oficial / matriz de transporte
    res_oficial = consultar_linhas_transporte_oficial(origem_lat, origem_lon, destino_lat, destino_lon)
    linhas = res_oficial.get("detalhes", [])

    res_vt = calcular_vale_transporte(linhas)
    res_vt["distancia_km"] = round(distancia_km, 2)
    res_vt["fonte"] = res_oficial.get("fonte", "Oficial / Estimada")
    res_vt["sucesso"] = True
    
    return res_vt


def calcular_vale_transporte(linhas_onibus):
    """
    Soma as passagens diárias e calcula o custo mensal estimado (22 dias úteis).
    """
    custo_diario = 0.0
    detalhes = []
    
    for item in linhas_onibus:
        subtotal = item.get("valor_unitario", item.get("valor", 0.0)) * item.get("quantidade_dia", 2)
        custo_diario += subtotal
        detalhes.append({
            "linha": item["linha"],
            "valor_unitario": item.get("valor_unitario", item.get("valor", 0.0)),
            "quantidade_dia": item.get("quantidade_dia", 2),
            "subtotal": subtotal
        })
        
    dias_uteis = 22
    custo_mensal = custo_diario * dias_uteis
    
    return {
        "custo_diario": round(custo_diario, 2),
        "custo_mensal": round(custo_mensal, 2),
        "detalhes": detalhes
    }