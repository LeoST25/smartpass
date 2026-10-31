import requests

from src.services.transit_api import consultar_linhas_transporte_oficial, estimar_itinerario_fallback


def _distancia_rodoviaria_km(origem_lat, origem_lon, destino_lat, destino_lon, padrao=10.0):
    url = ("http://router.project-osrm.org/route/v1/driving/"
           f"{origem_lon},{origem_lat};{destino_lon},{destino_lat}?overview=false")
    try:
        data = requests.get(url, timeout=10).json()
        if data.get("code") == "Ok":
            return data["routes"][0]["distance"] / 1000.0
    except (requests.RequestException, KeyError, TypeError, ValueError):
        pass
    return padrao


def calcular_vale_combustivel(origem_lat, origem_lon, destino_lat, destino_lon, valor_por_km):
    """Calcula a distância rodoviária via OSRM e aplica o valor do KM."""
    distancia_km = _distancia_rodoviaria_km(origem_lat, origem_lon, destino_lat, destino_lon, None)
    if distancia_km is None:
        return {"sucesso": False, "erro": "Não foi possível calcular a rota."}
    return {"sucesso": True, "distancia_km": round(distancia_km, 2), "custo_total": round(distancia_km * valor_por_km, 2)}


def roteirizar_vale_transporte_automatico(origem_lat, origem_lon, destino_lat, destino_lon, endereco_origem="Origem não informada", endereco_destino="Destino não informado"):
    """Usa OpenTripPlanner como motor principal de VT e estimativa em contingência."""
    distancia_fallback = _distancia_rodoviaria_km(origem_lat, origem_lon, destino_lat, destino_lon)
    resposta = consultar_linhas_transporte_oficial(
        origem_lat, origem_lon, destino_lat, destino_lon, endereco_origem, endereco_destino
    )
    if resposta.get("sucesso"):
        itinerario = resposta
    else:
        itinerario = estimar_itinerario_fallback(distancia_fallback)
        itinerario["fonte"] = resposta.get("fonte", "Estimativa de contingência")
        itinerario["aviso"] = resposta.get("erro", "Serviço de IA indisponível.")

    resultado = calcular_vale_transporte(itinerario["linhas"])
    resultado.update({
        "sucesso": True,
        "distancia_km": itinerario["distancia_km"],
        "resumo_trajeto": itinerario["resumo_trajeto"],
        "fonte": itinerario["fonte"],
    })
    if "aviso" in itinerario:
        resultado["aviso"] = itinerario["aviso"]
    return resultado


def calcular_vale_transporte(linhas_onibus):
    """Soma as passagens diárias e calcula o custo mensal estimado (22 dias úteis)."""
    custo_diario = 0.0
    detalhes = []
    for item in linhas_onibus:
        valor = item.get("valor_unitario", item.get("valor", 0.0))
        quantidade = item.get("quantidade_dia", 2)
        subtotal = valor * quantidade
        custo_diario += subtotal
        detalhes.append({"linha": item["linha"], "valor_unitario": valor, "quantidade_dia": quantidade, "subtotal": subtotal})
    return {"custo_diario": round(custo_diario, 2), "custo_mensal": round(custo_diario * 22, 2), "detalhes": detalhes}
