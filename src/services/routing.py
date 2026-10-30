import os
import requests

def calcular_vale_combustivel(origem_lat, origem_lon, destino_lat, destino_lon, valor_por_km):
    """
    Calcula a distância rodoviária entre origem e destino usando a API pública OSRM 
    e multiplica pelo valor do KM contratado.
    """
    url = f"http://router.project-osrm.org/route/v1/driving/{origem_lon},{origem_lat};{destino_lon},{destino_lat}?overview=false"
    
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data.get("code") == "Ok":
            # OSRM retorna a distância em metros
            distancia_metros = data["routes"][0]["distance"]
            distancia_km = distancia_metros / 1000.0
            
            # Custo total baseado na distância e no valor do KM
            custo_total = distancia_km * valor_por_km
            
            return {
                "sucesso": True,
                "distancia_km": round(distancia_km, 2),
                "custo_total": round(custo_total, 2)
            }
        else:
            return {"sucesso": False, "erro": "Não foi possível calcular a rota de carro."}
            
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


def calcular_vale_transporte(linhas_onibus):
    """
    Recebe uma lista de dicionários contendo as passagens de ônibus diárias
    e retorna o custo diário total e mensal estimado (22 dias úteis).
    Exemplo de linhas_onibus: [{"linha": "022", "valor": 5.20, "quantidade_dia": 2}]
    """
    custo_diario = 0.0
    detalhes = []
    
    for item in linhas_onibus:
        subtotal = item["valor"] * item.get("quantidade_dia", 2)
        custo_diario += subtotal
        detalhes.append({
            "linha": item["linha"],
            "valor_unitario": item["valor"],
            "subtotal": subtotal
        })
        
    dias_uteis = 22
    custo_mensal = custo_diario * dias_uteis
    
    return {
        "custo_diario": round(custo_diario, 2),
        "custo_mensal": round(custo_mensal, 2),
        "detalhes": detalhes
    }