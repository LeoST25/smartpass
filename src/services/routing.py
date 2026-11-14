import requests
import streamlit as st

from src.services.transit_api import (
    consultar_linhas_transporte_oficial,
    consultar_todos_itinerarios_oficial,
    estimar_itinerario_fallback,
)


@st.cache_data(ttl=600, show_spinner=False)
def _distancia_rodoviaria_km(origem_lat, origem_lon, destino_lat, destino_lon, padrao=10.0):
    url = (
        "http://router.project-osrm.org/route/v1/driving/"
        f"{origem_lon},{origem_lat};{destino_lon},{destino_lat}?overview=false"
    )
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
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
    return {
        "sucesso": True,
        "distancia_km": round(distancia_km, 2),
        "custo_total": round(distancia_km * valor_por_km, 2),
    }


def roteirizar_vale_transporte_automatico(
    origem_lat, origem_lon, destino_lat, destino_lon, endereco_origem="Origem não informada", endereco_destino="Destino não informado"
):
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
        itinerario["aviso"] = resposta.get("erro", "Serviço de roteirização indisponível.")

    resultado = calcular_vale_transporte(itinerario["linhas"])
    resultado.update(
        {
            "sucesso": True,
            "distancia_km": itinerario["distancia_km"],
            "resumo_trajeto": itinerario["resumo_trajeto"],
            "fonte": itinerario["fonte"],
        }
    )
    if "aviso" in itinerario:
        resultado["aviso"] = itinerario["aviso"]
    return resultado


def calcular_vale_transporte(linhas_onibus):
    """Soma as passagens diárias e calcula o custo mensal estimado (22 dias úteis).

    Mantido para compatibilidade; novo motor de tarifa com integração temporal
    está em ``src.services.fare_engine.calcular_custo_com_integracao``.
    """
    custo_diario = 0.0
    detalhes = []
    for item in linhas_onibus:
        valor = item.get("valor_unitario", item.get("valor", 0.0))
        quantidade = item.get("quantidade_dia", 2)
        subtotal = valor * quantidade
        custo_diario += subtotal
        detalhes.append(
            {"linha": item["linha"], "valor_unitario": valor, "quantidade_dia": quantidade, "subtotal": subtotal}
        )
    return {"custo_diario": round(custo_diario, 2), "custo_mensal": round(custo_diario * 22, 2), "detalhes": detalhes}


def roteirizar_com_comparativo(
    origem_lat: float,
    origem_lon: float,
    destino_lat: float,
    destino_lon: float,
    dias_uteis: int = 22,
    config=None,
):
    """Roteiriza via OTP e retorna comparativo econômica vs rápida com integração BU/TOP.

    Args:
        origem_lat: Latitude origem (validada RMSP -24.1..-23.1).
        origem_lon: Longitude origem (-47.2..-45.7).
        destino_lat: Latitude destino.
        destino_lon: Longitude destino.
        dias_uteis: Dias úteis para cálculo mensal.
        config: FareConfig/dict para tarifas (ver fare_engine.FareConfig).

    Returns:
        dict: {"sucesso": bool, "comparativo": {...}, "fallback": bool, "fonte": str, ...}
              Em sucesso ``comparativo`` contém ``rota_mais_rapida`` e
              ``rota_mais_economica`` (None só quando nenhuma elegível).
    """
    try:
        from src.services.fare_engine import comparar_rotas

        distancia_fallback = _distancia_rodoviaria_km(origem_lat, origem_lon, destino_lat, destino_lon)
        resp = consultar_todos_itinerarios_oficial(origem_lat, origem_lon, destino_lat, destino_lon)

        if resp.get("sucesso") and resp.get("itinerarios"):
            itinerarios = resp["itinerarios"]
            comparativo = comparar_rotas(itinerarios, dias_uteis=dias_uteis, config=config)
            if comparativo.get("sucesso"):
                # enriquece com fonte/distância principal (usa rápida como referência)
                rapida = comparativo.get("rota_mais_rapida") or {}
                return {
                    "sucesso": True,
                    "comparativo": comparativo,
                    "fonte": resp.get("fonte", "OpenTripPlanner (GTFS local)"),
                    "distancia_km": rapida.get("distancia_km", itinerarios[0].get("distancia_km", 0)),
                    "resumo_trajeto": rapida.get("resumo_trajeto", ""),
                }
            # falha no comparativo mas tem itinerários: retorna fallback com primeiro
            itinerario = itinerarios[0]
            fb = estimar_itinerario_fallback(distancia_fallback)
            return {
                "sucesso": True,
                "comparativo": comparativo,
                "fonte": resp.get("fonte", "OpenTripPlanner (GTFS local)"),
                "distancia_km": itinerario.get("distancia_km", 0),
                "resumo_trajeto": itinerario.get("resumo_trajeto", ""),
                "aviso": comparativo.get("erro", ""),
            }

        # OTP offline ou sem itinerários: fallback estimado
        itinerario = estimar_itinerario_fallback(distancia_fallback)
        # tenta comparar mesmo com fallback único para gerar estrutura
        try:
            from src.services.fare_engine import calcular_custo_com_integracao

            # converte fallback linhas em legs sintéticos para fare_engine
            legs_fb = [{"linha": l["linha"], "mode": "BUS", "route": {"shortName": l["linha"]}, "distance": 1000} for l in itinerario["linhas"]]
            custo_fb = calcular_custo_com_integracao(legs_fb, dias_uteis=dias_uteis, config=config)
            comparativo_fb = {
                "sucesso": True,
                "rota_mais_rapida": {
                    "legs": legs_fb,
                    "distancia_km": itinerario["distancia_km"],
                    "duracao_min": 30,
                    "caminhada_km": 0.3,
                    "baldeacoes": 0,
                    "resumo_trajeto": itinerario["resumo_trajeto"],
                    **custo_fb,
                },
                "rota_mais_economica": None,
                "economia_mensal": 0.0,
                "memoria_calculo": custo_fb.get("memoria_calculo", []) + ["Fallback: OTP offline — estimativa provisória sem GTFS."],
                "justificativa": "OTP offline — comparativo indisponível, estimativa aplicada.",
            }
            # fallback single não tem econômica elegível viável? Mantém None para sinalizar modo contingência
        except Exception:
            comparativo_fb = {
                "sucesso": False,
                "rota_mais_rapida": None,
                "rota_mais_economica": None,
                "economia_mensal": 0.0,
                "memoria_calculo": ["OTP offline — estimativa de contingência sem integração."],
                "justificativa": "OTP offline.",
                "erro": resp.get("erro", "Serviço de roteirização indisponível."),
            }

        return {
            "sucesso": True,
            "comparativo": comparativo_fb,
            "fonte": resp.get("fonte", "Estimativa de contingência"),
            "distancia_km": itinerario["distancia_km"],
            "resumo_trajeto": itinerario["resumo_trajeto"],
            "aviso": resp.get("erro", "Serviço de roteirização indisponível."),
            "fallback": True,
        }
    except Exception as exc:
        return {
            "sucesso": False,
            "erro": str(exc),
            "comparativo": None,
            "fonte": "Estimativa de contingência",
        }
