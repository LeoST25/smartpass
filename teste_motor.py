from src.services.routing import calcular_vale_combustivel, calcular_vale_transporte

# Teste 1: Vale-Combustível (Exemplo: de Carapicuíba para São Paulo - Centro)
origem = (-23.5228, -46.8355)  # Carapicuíba
destino = (-23.5505, -46.6333)  # São Paulo (Centro)
valor_km = 1.25                 # R$ 1,25 por KM contratado

res_vc = calcular_vale_combustivel(origem[0], origem[1], destino[0], destino[1], valor_km)
print("--- Resultado Vale-Combustível ---")
print(res_vc)

# Teste 2: Vale-Transporte
linhas = [
    {"linha": "Linha 022 - Embu", "valor": 5.50, "quantidade_dia": 2},
    {"linha": "Metrô Linha 4", "valor": 5.00, "quantidade_dia": 2}
]

res_vt = calcular_vale_transporte(linhas)
print("\n--- Resultado Vale-Transporte ---")
print(res_vt)