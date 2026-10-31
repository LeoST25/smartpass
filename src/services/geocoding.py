import re
import requests

def _consultar_nominatim(query, postalcode=None):
    """Função auxiliar para consultar o Nominatim com tratamento de erros."""
    nominatim_url = "https://nominatim.openstreetmap.org/search"
    headers = {"User-Agent": "SmartPass-Admissao-App/1.0"}
    
    params = {
        "format": "json",
        "limit": 1
    }
    
    if postalcode:
        params["postalcode"] = postalcode
        params["country"] = "Brazil"
    else:
        params["q"] = query

    try:
        response = requests.get(nominatim_url, params=params, headers=headers, timeout=10)
        dados = response.json()
        if dados and len(dados) > 0:
            resultado = dados[0]
            return {
                "sucesso": True,
                "lat": float(resultado["lat"]),
                "lon": float(resultado["lon"]),
                "endereco_encontrado": resultado.get("display_name", query)
            }
    except Exception:
        pass
        
    return {"sucesso": False}


def buscar_coordenadas_por_cep_ou_endereco(busca_texto):
    """
    Busca coordenadas por CEP ou Endereço com múltiplas camadas de fallback.
    """
    texto_limpo = busca_texto.strip()
    apenas_numeros = re.sub(r"\D", "", texto_limpo)
    
    # É um CEP válido (8 dígitos)
    if len(apenas_numeros) == 8:
        cep_formatado = f"{apenas_numeros[:5]}-{apenas_numeros[5:]}"
        
        # 1. Tenta via ViaCEP para estruturar o endereço
        try:
            viacep_url = f"https://viacep.com.br/ws/{apenas_numeros}/json/"
            resp_cep = requests.get(viacep_url, timeout=5)
            dados_cep = resp_cep.json()
            
            if not dados_cep.get("erro"):
                logradouro = dados_cep.get("logradouro", "").strip()
                bairro = dados_cep.get("bairro", "").strip()
                cidade = dados_cep.get("localidade", "").strip()
                uf = dados_cep.get("uf", "").strip()
                
                # Monta a query apenas com os campos preenchidos
                partes_endereco = [p for p in [logradouro, bairro, cidade, uf, "Brasil"] if p]
                query_endereco = ", ".join(partes_endereco)
                
                # Tentativa A: Busca pelo endereço completo retornado do ViaCEP
                res = _consultar_nominatim(query_endereco)
                if res["sucesso"]:
                    return res
                
                # Tentativa B: Se a rua falhou, busca por Bairro + Cidade + UF
                partes_resumidas = [p for p in [bairro, cidade, uf, "Brasil"] if p]
                if partes_resumidas:
                    res = _consultar_nominatim(", ".join(partes_resumidas))
                    if res["sucesso"]:
                        return res
        except Exception:
            pass

        # Tentativa C: Fallback direto pelo CEP no Nominatim
        res = _consultar_nominatim(None, postalcode=cep_formatado)
        if res["sucesso"]:
            return res

    # 2. Busca genérica por texto livre (se não for CEP ou se o CEP falhar)
    res = _consultar_nominatim(f"{texto_limpo}, Brasil" if "Brasil" not in texto_limpo else texto_limpo)
    if res["sucesso"]:
        return res

    return {"sucesso": False, "erro": "Endereço ou CEP não localizado no mapa."}