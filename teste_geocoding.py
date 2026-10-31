from src.services.geocoding import buscar_coordenadas_por_cep_ou_endereco

# Subtitua pelo seu CEP para testar
seu_cep = "06326-000" # Exemplo

resultado = buscar_coordenadas_por_cep_ou_endereco(seu_cep)
print(f"--- Resultado do CEP {seu_cep} ---")
print(resultado)