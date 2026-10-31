from src.services.transit_api import consultar_linhas_transporte_oficial

# Teste das coordenadas (Carapicuíba -> Av. Paulista)
origem_lat, origem_lon = -23.5228, -46.8355
destino_lat, destino_lon = -23.5505, -46.6333

resultado = consultar_linhas_transporte_oficial(origem_lat, origem_lon, destino_lat, destino_lon)
print("--- Resultado da Consulta Oficial / Fallback ---")
print(resultado)