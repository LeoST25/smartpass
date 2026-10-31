"""Resolução de itinerários de transporte público para a RMSP."""

import json
import os
from typing import Any

from dotenv import load_dotenv

load_dotenv()

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "linhas": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "linha": {"type": "STRING"},
                    "valor_unitario": {"type": "NUMBER"},
                    "quantidade_dia": {"type": "INTEGER"},
                },
                "required": ["linha", "valor_unitario", "quantidade_dia"],
            },
        },
        "distancia_km": {"type": "NUMBER"},
        "resumo_trajeto": {"type": "STRING"},
    },
    "required": ["linhas", "distancia_km", "resumo_trajeto"],
}


def _montar_prompt(origem_lat, origem_lon, destino_lat, destino_lon, endereco_origem, endereco_destino):
    return f"""
Você é um planejador de transporte público da Região Metropolitana de São Paulo.
Determine um itinerário prático de ida entre os dados abaixo, priorizando linhas
reais de SPTrans, EMTU, CPTM e Metrô. Informe somente embarques tarifados que
compõem o benefício; não invente linhas, integrações ou tarifas. Considere que
quantidade_dia é a quantidade de utilizações de cada modal no dia completo
(ida e volta), normalmente 2 por embarque. Use a melhor estimativa pública de
tarifa vigente e deixe de fora trechos a pé.

Origem: {endereco_origem} ({origem_lat}, {origem_lon})
Destino: {endereco_destino} ({destino_lat}, {destino_lon})

Retorne exclusivamente o JSON no schema solicitado. distancia_km é a extensão
aproximada do percurso de transporte público, em quilômetros. resumo_trajeto
deve ser breve, em português, e indicar os modais e as baldeações.
""".strip()


def _validar_resposta(payload: Any) -> dict[str, Any]:
    """Normaliza e valida o contrato público da resposta do agente."""
    if not isinstance(payload, dict):
        raise ValueError("A resposta do agente não é um objeto JSON.")
    linhas_brutas = payload.get("linhas")
    if not isinstance(linhas_brutas, list) or not linhas_brutas:
        raise ValueError("A resposta não contém linhas de transporte.")

    linhas = []
    for item in linhas_brutas:
        if not isinstance(item, dict):
            raise ValueError("Linha de transporte inválida.")
        linha = str(item.get("linha", "")).strip()
        valor = float(item.get("valor_unitario"))
        quantidade = int(item.get("quantidade_dia"))
        if not linha or not 0 < valor <= 100 or not 0 < quantidade <= 12:
            raise ValueError("Valores de transporte fora dos limites aceitos.")
        linhas.append({"linha": linha, "valor_unitario": round(valor, 2), "quantidade_dia": quantidade})

    distancia = float(payload.get("distancia_km"))
    resumo = str(payload.get("resumo_trajeto", "")).strip()
    if not 0 < distancia <= 500 or not resumo:
        raise ValueError("Distância ou resumo do trajeto inválido.")
    return {"linhas": linhas, "distancia_km": round(distancia, 2), "resumo_trajeto": resumo}


def resolver_itinerario_com_gemini(origem_lat, origem_lon, destino_lat, destino_lon, endereco_origem, endereco_destino):
    """Consulta o Gemini e devolve somente uma resposta validada."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não configurada.")
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError("Dependência google-genai não instalada.") from exc

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=_montar_prompt(origem_lat, origem_lon, destino_lat, destino_lon, endereco_origem, endereco_destino),
        config={"response_mime_type": "application/json", "response_schema": _RESPONSE_SCHEMA, "temperature": 0.1},
    )
    if not response.text:
        raise RuntimeError("Gemini retornou uma resposta vazia.")
    return _validar_resposta(json.loads(response.text))


def estimar_itinerario_fallback(distancia_km: float) -> dict[str, Any]:
    """Mantém o cálculo disponível quando o provedor externo falha."""
    return {
        "linhas": [{"linha": "Estimativa: transporte público urbano (validar com colaborador)", "valor_unitario": 5.00, "quantidade_dia": 2}],
        "distancia_km": round(max(distancia_km, 0.1), 2),
        "resumo_trajeto": "Não foi possível consultar o roteador inteligente. Estimativa provisória para validação manual pelo time de Admissão.",
    }


def consultar_linhas_transporte_oficial(origem_lat, origem_lon, destino_lat, destino_lon, endereco_origem="Origem não informada", endereco_destino="Destino não informado"):
    """Compatibilidade com o serviço anterior, agora priorizando o Gemini."""
    try:
        resultado = resolver_itinerario_com_gemini(origem_lat, origem_lon, destino_lat, destino_lon, endereco_origem, endereco_destino)
        return {"sucesso": True, "fonte": f"Gemini ({GEMINI_MODEL})", **resultado}
    except Exception as exc:  # O cálculo não pode depender de um serviço de IA.
        return {"sucesso": False, "fonte": "Estimativa de contingência", "erro": str(exc), "detalhes": []}
