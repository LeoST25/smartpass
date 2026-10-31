import os
import requests

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
    Calcula a rota e infere a combinação de modais/linhas de transporte público
    com base na distância e nos corredores integrados de transporte.
    """
    # Consulta a distância física do percurso via OSRM
    url = f"http://router.project-osrm.org/route/v1/driving/{origem_lon},{origem_lat};{destino_lon},{destino_lat}?overview=false"
    
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        distancia_km = 10.0
        if data.get("code") == "Ok":
            distancia_km = data["routes"][0]["distance"] / 1000.0

        linhas = []
        # Regra de inferência de trechos baseada na extensão do trajeto
        if distancia_km <= 8.0:
            linhas.append({"linha": "Ônibus Municipal / Local", "valor": 6.70, "quantidade_dia": 2})
        elif distancia_km <= 20.0:
            linhas.append({"linha": "Ônibus Intermunicipal (EMTU / Local)", "valor": 5.65, "quantidade_dia": 2})
            linhas.append({"linha": "Metrô / Trem (CPTM)", "valor": 5.00, "quantidade_dia": 2})
        else:
            linhas.append({"linha": "Ônibus Alimentador", "valor": 6.70, "quantidade_dia": 2})
            linhas.append({"linha": "Trem / Metrô (Linha Troncal)", "valor": 5.00, "quantidade_dia": 2})
            linhas.append({"linha": "Ônibus Intermunicipal Integrado", "valor": 5.65, "quantidade_dia": 2})

        res_vt = calcular_vale_transporte(linhas)
        res_vt["distancia_km"] = round(distancia_km, 2)
        res_vt["sucesso"] = True
        return res_vt

    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


def calcular_vale_transporte(linhas_onibus):
    """
    Soma as passagens diárias e calcula o custo mensal estimado (22 dias úteis).
    """
    custo_diario = 0.0
    detalhes = []
    
    for item in linhas_onibus:
        subtotal = item["valor"] * item.get("quantidade_dia", 2)
        custo_diario += subtotal
        detalhes.append({
            "linha": item["linha"],
            "valor_unitario": item["valor"],
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