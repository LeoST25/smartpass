import re

import requests
import streamlit as st


# Mapa de precisão -> semáforo / motivo padrão
_MAPA_SEMAFORO = {
    "ALTA": "🟢 Exato",
    "MEDIA": "🟡 Aproximado",
    "BAIXA": "🔴 Revisar Endereço",
}

_MOTIVOS_PADRAO = {
    "ALTA": "Logradouro + número/CEP específico — coordenada de rua validada",
    "MEDIA": "Apenas logradouro sem número ou bairro — validação recomendada",
    "BAIXA": "CEP geral de município — coordenada centralizada",
}


def _enriquecer_sucesso(res: dict, nivel: str, motivo: str | None = None) -> dict:
    """Adiciona nivel_precisao/semaforo/motivo_precisao ao dicionário de sucesso."""
    motivo_final = motivo or _MOTIVOS_PADRAO.get(nivel, "")
    return {
        **res,
        "nivel_precisao": nivel,
        "semaforo": _MAPA_SEMAFORO.get(nivel, ""),
        "motivo_precisao": motivo_final,
    }


def _classificar_texto_livre(texto_limpo: str) -> tuple[str, str]:
    """
    Heurística para texto livre sem CEP.

    Returns:
        (nivel, motivo)
    """
    tem_numero = bool(re.search(r"\d", texto_limpo))
    if tem_numero:
        return "ALTA", "Endereço com número — geocodificação de logradouro + número"
    # Sem número: verifica se é apenas município/UF (ex: "Carapicuíba, SP")
    partes = [p.strip() for p in texto_limpo.split(",") if p.strip()]
    palavras = texto_limpo.split()
    # BAIXA quando entrada curta sem número e parece apenas cidade/UF
    if not tem_numero and len(partes) <= 2 and len(palavras) <= 3:
        # ex: "Carapicuíba, SP" ou "São Paulo" ou "Carapicuíba"
        return "BAIXA", "Município/UF sem logradouro ou número — coordenada centralizada"
    # Caso contrário: logradouro sem número ou bairro
    return "MEDIA", "Logradouro sem número ou bairro — coordenada aproximada"


@st.cache_data(ttl=3600, show_spinner=False)
def _consultar_nominatim(query, postalcode=None):
    """Consulta o Nominatim com tratamento de timeout e erros padronizado."""
    nominatim_url = "https://nominatim.openstreetmap.org/search"
    headers = {"User-Agent": "SmartPass-Admissao-App/1.0"}

    params = {
        "format": "json",
        "limit": 1,
    }

    if postalcode:
        params["postalcode"] = postalcode
        params["country"] = "Brazil"
    else:
        params["q"] = query

    try:
        response = requests.get(nominatim_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        dados = response.json()
        if dados and len(dados) > 0:
            resultado = dados[0]
            return {
                "sucesso": True,
                "lat": float(resultado["lat"]),
                "lon": float(resultado["lon"]),
                "endereco_encontrado": resultado.get("display_name", query),
            }
    except requests.RequestException as exc:
        return {"sucesso": False, "erro": f"Falha ao consultar Nominatim: {exc}"}
    except (KeyError, TypeError, ValueError) as exc:
        return {"sucesso": False, "erro": f"Resposta inesperada do Nominatim: {exc}"}
    except Exception as exc:
        return {"sucesso": False, "erro": str(exc)}

    return {"sucesso": False, "erro": "Endereço não encontrado no Nominatim."}


@st.cache_data(ttl=3600, show_spinner=False)
def buscar_coordenadas_por_cep_ou_endereco(busca_texto: str) -> dict:
    """
    Busca coordenadas por CEP ou Endereço com múltiplas camadas de fallback e semáforo de confiabilidade.

    Args:
        busca_texto: CEP (8 dígitos) ou endereço livre.

    Returns:
        dict: Em sucesso {"sucesso": True, "lat": float, "lon": float, "endereco_encontrado": str,
              "nivel_precisao": "ALTA"|"MEDIA"|"BAIXA", "semaforo": str, "motivo_precisao": str}
              Em falha {"sucesso": False, "erro": str}
    """
    if not busca_texto or not str(busca_texto).strip():
        return {"sucesso": False, "erro": "Informe um CEP ou endereço válido."}

    texto_limpo = busca_texto.strip()
    apenas_numeros = re.sub(r"\D", "", texto_limpo)

    # É um CEP válido (8 dígitos)
    if len(apenas_numeros) == 8:
        cep_formatado = f"{apenas_numeros[:5]}-{apenas_numeros[5:]}"

        # 1. Tenta via ViaCEP para estruturar o endereço
        _cep_geral_flag = None  # None=ViaCEP não consultado/falhou, True=CEP geral sem logradouro, False=CEP específico
        _cep_geral_cidade = ""
        _cep_geral_uf = ""
        _cep_geral_cep = cep_formatado
        try:
            viacep_url = f"https://viacep.com.br/ws/{apenas_numeros}/json/"
            resp_cep = requests.get(viacep_url, timeout=5)
            resp_cep.raise_for_status()
            dados_cep = resp_cep.json()

            if not dados_cep.get("erro"):
                logradouro = dados_cep.get("logradouro", "").strip()
                bairro = dados_cep.get("bairro", "").strip()
                cidade = dados_cep.get("localidade", "").strip()
                uf = dados_cep.get("uf", "").strip()
                _cep_geral_flag = (logradouro == "")
                _cep_geral_cidade = cidade
                _cep_geral_uf = uf

                # Monta a query apenas com os campos preenchidos
                partes_endereco = [p for p in [logradouro, bairro, cidade, uf, "Brasil"] if p]
                query_endereco = ", ".join(partes_endereco)

                # Tentativa A: Busca pelo endereço completo retornado do ViaCEP
                res = _consultar_nominatim(query_endereco)
                if res.get("sucesso"):
                    # Se logradouro vazio, query_endereco já é município => BAIXA (CEP geral)
                    if not logradouro:
                        motivo = f"CEP geral de município — coordenada centralizada ({cidade}/{uf}) — CEP {cep_formatado} sem logradouro"
                        return _enriquecer_sucesso(res, "BAIXA", motivo)
                    motivo = f"CEP {cep_formatado} — ViaCEP logradouro '{logradouro}' validado no Nominatim"
                    return _enriquecer_sucesso(res, "ALTA", motivo)

                # Tentativa B: Se a rua falhou, busca por Bairro + Cidade + UF
                partes_resumidas = [p for p in [bairro, cidade, uf, "Brasil"] if p]
                if bairro and partes_resumidas:
                    res = _consultar_nominatim(", ".join(partes_resumidas))
                    if res.get("sucesso"):
                        motivo = f"CEP {cep_formatado} — logradouro não localizado, fallback bairro '{bairro}'"
                        return _enriquecer_sucesso(res, "MEDIA", motivo)

                # Tentativa B2: CEP geral sem logradouro — fallback município (ex: 06310-000 Carapicuíba)
                # Evita chamada duplicada quando query_endereco já era município (cache dedup)
                if not logradouro and cidade and uf:
                    query_municipio = f"{cidade}, {uf}, Brasil"
                    if query_municipio != query_endereco:
                        res = _consultar_nominatim(query_municipio)
                        if res.get("sucesso"):
                            motivo = f"CEP geral de município — coordenada centralizada ({cidade}/{uf}) — CEP {cep_formatado} sem logradouro"
                            return _enriquecer_sucesso(res, "BAIXA", motivo)
        except requests.RequestException:
            pass
        except Exception:
            pass

        # Tentativa C: Fallback direto pelo CEP no Nominatim
        res = _consultar_nominatim(None, postalcode=cep_formatado)
        if res.get("sucesso"):
            if _cep_geral_flag is True:
                motivo = f"CEP geral de município — coordenada centralizada ({_cep_geral_cidade}/{_cep_geral_uf}) — CEP {cep_formatado} sem logradouro (fallback postalcode)"
                return _enriquecer_sucesso(res, "BAIXA", motivo)
            motivo = f"CEP {cep_formatado} localizado via postalcode Nominatim sem detalhamento ViaCEP — coordenada aproximada"
            return _enriquecer_sucesso(res, "MEDIA", motivo)

    # 2. Busca genérica por texto livre (se não for CEP ou se o CEP falhar)
    res = _consultar_nominatim(f"{texto_limpo}, Brasil" if "Brasil" not in texto_limpo else texto_limpo)
    if res.get("sucesso"):
        nivel, motivo_base = _classificar_texto_livre(texto_limpo)
        # Enriquece motivo com endereço encontrado para auditoria
        motivo = f"{motivo_base} — '{texto_limpo}' → {res.get('endereco_encontrado','')[:80]}"
        return _enriquecer_sucesso(res, nivel, motivo)

    return {"sucesso": False, "erro": "Endereço ou CEP não localizado no mapa."}
