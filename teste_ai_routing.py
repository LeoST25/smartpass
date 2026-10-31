"""Teste de fumaça do motor de VT com validações independentes do container OTP."""

from src.services.routing import roteirizar_vale_transporte_automatico
from src.services.transit_api import _extrair_itinerario_otp


def main():
    exemplo = _extrair_itinerario_otp({
        "data": {"planConnection": {"edges": [{"node": {"legs": [
            {"mode": "WALK", "distance": 300, "from": {"name": "Casa"}, "to": {"name": "Estação"}, "route": None},
            {"mode": "RAIL", "distance": 24100, "from": {"name": "Estação Carapicuíba"}, "to": {"name": "Luz"}, "route": {"shortName": "8-Diamante", "longName": "Júlio Prestes"}},
        ]}}]}}
    })
    assert exemplo["linhas"][0]["linha"].startswith("Rail 8-Diamante")
    assert exemplo["linhas"][0]["quantidade_dia"] == 2
    assert exemplo["distancia_km"] == 24.4

    resultado = roteirizar_vale_transporte_automatico(
        -23.5228, -46.8355, -23.5505, -46.6333,
        "Carapicuíba, SP", "Avenida Paulista, 1000, São Paulo, SP",
    )
    assert resultado["sucesso"] is True
    assert resultado["detalhes"]
    assert resultado["distancia_km"] > 0
    assert resultado["custo_diario"] > 0
    assert resultado["resumo_trajeto"]
    print("Conversão de resposta OTP e contingência VT validadas:")
    print(f"Fonte: {resultado['fonte']}")
    print(f"Distância: {resultado['distancia_km']} km")
    print(f"Resumo: {resultado['resumo_trajeto']}")
    print(f"Linhas: {resultado['detalhes']}")


if __name__ == "__main__":
    main()
