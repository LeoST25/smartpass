"""Teste de fumaça do motor de VT com validações independentes de API externa."""

from src.services.routing import roteirizar_vale_transporte_automatico
from src.services.transit_api import _validar_resposta


def main():
    exemplo = _validar_resposta({
        "linhas": [{"linha": "Linha 8-Diamante (CPTM)", "valor_unitario": 5.00, "quantidade_dia": 2}],
        "distancia_km": 24.4,
        "resumo_trajeto": "CPTM Linha 8-Diamante, com integração para o destino.",
    })
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
    print("Roteirização VT validada:")
    print(f"Fonte: {resultado['fonte']}")
    print(f"Distância: {resultado['distancia_km']} km")
    print(f"Resumo: {resultado['resumo_trajeto']}")
    print(f"Linhas: {resultado['detalhes']}")


if __name__ == "__main__":
    main()
