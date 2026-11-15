"""Geocodificação multi-camada e autocomplete de endereços para a RMSP.

Camadas (com fallback e timeout explícito):
1. ViaCEP (estruturação de CEP) → BrasilAPI (fallback de CEP)
2. Photon (autocomplete com bbox/foco RMSP)
3. Nominatim estruturado (logradouro/cidade/UF ou CEP, limitado à RMSP)
4. Google Geocoding (opcional, apenas se ``GOOGLE_MAPS_API_KEY`` estiver definida)

LGPD/stateless: nenhuma coordenada ou endereço é persistido; apenas retorno em memória
(``list[dict]``) consumido pela UI e pelo ``st.session_state``.
"""

import os
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

# Limites geográficos da Região Metropolitana de São Paulo (WGS84)
_RMSP_LAT_MIN = -24.1
_RMSP_LAT_MAX = -23.1
_RMSP_LON_MIN = -47.2
_RMSP_LON_MAX = -45.7
# Formato aceito pelo Photon: minLon,minLat,maxLon,maxLat
_RMSP_BBOX = f"{_RMSP_LON_MIN},{_RMSP_LAT_MIN},{_RMSP_LON_MAX},{_RMSP_LAT_MAX}"
# Foco (centro de São Paulo) para desempate de homônimos no Photon
_RMSP_FOCO = (-23.5505, -46.6333)

_PHOTON_URL = "https://photon.komoot.io/api/"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_VIACEP_URL = "https://viacep.com.br/ws/{cep}/json/"
_BRASILAPI_URL = "https://brasilapi.com.br/api/cep/v2/{cep}"
_GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

_TIMEOUT_PADRAO = 3
_HEADERS_NOMINATIM = {"User-Agent": "SmartPass-Admissao-App/1.0"}


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

    Args:
        texto_limpo: Texto informado pelo usuário (sem número explícito).

    Returns:
        tuple[str, str]: (nivel, motivo) com nivel em ALTA/MEDIA/BAIXA.
    """
    tem_numero = bool(re.search(r"\d", texto_limpo))
    if tem_numero:
        return "ALTA", "Endereço com número — geocodificação de logradouro + número"
    partes = [p.strip() for p in texto_limpo.split(",") if p.strip()]
    palavras = texto_limpo.split()
    if not tem_numero and len(partes) <= 2 and len(palavras) <= 3:
        return "BAIXA", "Município/UF sem logradouro ou número — coordenada centralizada"
    return "MEDIA", "Logradouro sem número ou bairro — coordenada aproximada"


def _parse_termo(termo: str) -> dict:
    """Extrai CEP (8 dígitos) e número opcional de um termo de busca.

    Args:
        termo: CEP e/ou endereço digitado (ex.: ``"06320-290, 1500"``).

    Returns:
        dict: ``{"texto_original", "texto", "cep", "numero"}``; ``cep`` com 8 dígitos
              apenas e ``numero`` como string quando identificado.
    """
    texto = str(termo or "").strip()
    cep = None
    numero = None
    resto = texto

    match_cep = re.search(r"\b(\d{5})-?(\d{3})\b", texto)
    if match_cep:
        cep = f"{match_cep.group(1)}{match_cep.group(2)}"
        resto = (texto[: match_cep.start()] + " " + texto[match_cep.end() :]).strip(" ,-")

    if resto and re.fullmatch(r"\d{1,5}", resto.strip(" ,-")):
        numero = resto.strip(" ,-")
        resto = ""
    else:
        match_numero = re.search(r"(?:,\s*|\bn[ºo°.]?\s*)(\d{1,5})(?=\s*(?:,|$))", resto, re.IGNORECASE)
        if match_numero:
            numero = match_numero.group(1)
            resto = (resto[: match_numero.start()] + resto[match_numero.end() :]).strip(" ,-")

    return {
        "texto_original": texto,
        "texto": resto.strip(),
        "cep": cep,
        "numero": numero,
    }


def _dentro_rmsp(lat, lon) -> bool:
    """Indica se a coordenada está dentro do bbox da RMSP (-24.1/-23.1, -47.2/-45.7)."""
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return False
    return _RMSP_LAT_MIN <= lat_f <= _RMSP_LAT_MAX and _RMSP_LON_MIN <= lon_f <= _RMSP_LON_MAX


def _montar_label(
    logradouro: str = "",
    numero: str = "",
    bairro: str = "",
    cidade: str = "",
    uf: str = "",
    cep: str = "",
) -> str:
    """Monta label de exibição priorizando logradouro + número."""
    logradouro = str(logradouro or "").strip()
    numero = str(numero or "").strip()
    bairro = str(bairro or "").strip()
    cidade = str(cidade or "").strip()
    uf = str(uf or "").strip()
    cep = str(cep or "").strip()

    if numero and numero in logradouro.split():
        numero = ""
    via = ", ".join(p for p in [logradouro, numero] if p)
    partes = [via] if via else ([cidade] if cidade else [])
    if bairro and bairro != cidade:
        partes.append(bairro)
    local = " - ".join(p for p in [cidade, uf] if p)
    if local and local not in partes:
        partes.append(local)
    label = ", ".join(p for p in partes if p)
    if cep:
        label = f"{label} — CEP {cep}" if label else f"CEP {cep}"
    return label or "Endereço sem rótulo"


def _normalizar_label(props: dict) -> str:
    """Normaliza o label de uma feature do Photon priorizando o housenumber."""
    props = props or {}
    logradouro = props.get("street") or props.get("name") or ""
    numero = str(props.get("housenumber") or "")
    bairro = props.get("district") or props.get("locality") or ""
    cidade = props.get("city") or props.get("town") or props.get("village") or ""
    uf = props.get("state") or ""
    cep = props.get("postcode") or ""
    return _montar_label(logradouro, numero, bairro, cidade, uf, cep)


def _candidato(
    label_exibicao: str,
    lat,
    lon,
    *,
    cep: str = "",
    logradouro: str = "",
    numero: str = "",
    bairro: str = "",
    cidade: str = "",
    uf: str = "",
    nivel: str = "MEDIA",
    fonte: str = "",
    motivo: str = "",
) -> dict:
    """Cria um candidato padronizado de geocodificação (sem persistência)."""
    return {
        "label_exibicao": label_exibicao,
        "lat": float(lat),
        "lon": float(lon),
        "cep": str(cep or ""),
        "logradouro": str(logradouro or ""),
        "numero": str(numero or ""),
        "bairro": str(bairro or ""),
        "cidade": str(cidade or ""),
        "uf": str(uf or ""),
        "nivel_precisao": nivel,
        "semaforo": _MAPA_SEMAFORO.get(nivel, ""),
        "fonte": fonte,
        "motivo_precisao": motivo or _MOTIVOS_PADRAO.get(nivel, ""),
    }


@st.cache_data(ttl=3600, show_spinner=False)
def _consultar_viacep(cep: str) -> dict:
    """Consulta o ViaCEP e retorna os campos estruturados do CEP.

    Args:
        cep: CEP com 8 dígitos (sem máscara).

    Returns:
        dict: ``{"sucesso": True, "cep", "logradouro", "bairro", "cidade", "uf"}``
              ou ``{"sucesso": False, "erro": str}``.
    """
    try:
        response = requests.get(
            _VIACEP_URL.format(cep=cep),
            timeout=_TIMEOUT_PADRAO,
        )
        response.raise_for_status()
        dados = response.json()
        if not isinstance(dados, dict) or dados.get("erro"):
            return {"sucesso": False, "erro": "CEP não encontrado no ViaCEP."}
        return {
            "sucesso": True,
            "cep": str(dados.get("cep") or "").strip(),
            "logradouro": str(dados.get("logradouro") or "").strip(),
            "bairro": str(dados.get("bairro") or "").strip(),
            "cidade": str(dados.get("localidade") or "").strip(),
            "uf": str(dados.get("uf") or "").strip(),
        }
    except requests.RequestException as exc:
        return {"sucesso": False, "erro": f"Falha ao consultar ViaCEP: {exc}"}
    except (KeyError, TypeError, ValueError) as exc:
        return {"sucesso": False, "erro": f"Resposta inesperada do ViaCEP: {exc}"}
    except Exception as exc:
        return {"sucesso": False, "erro": str(exc)}


@st.cache_data(ttl=3600, show_spinner=False)
def _consultar_brasilapi(cep: str) -> dict:
    """Consulta a BrasilAPI (fallback do ViaCEP) com coordenadas quando disponíveis.

    Args:
        cep: CEP com 8 dígitos (sem máscara).

    Returns:
        dict: ``{"sucesso": True, "cep", "logradouro", "bairro", "cidade", "uf",
              "lat"|None, "lon"|None}`` ou ``{"sucesso": False, "erro": str}``.
    """
    try:
        response = requests.get(
            _BRASILAPI_URL.format(cep=cep),
            timeout=_TIMEOUT_PADRAO,
        )
        response.raise_for_status()
        dados = response.json()
        if not isinstance(dados, dict) or not dados.get("cep"):
            return {"sucesso": False, "erro": "CEP não encontrado na BrasilAPI."}
        coordenadas = ((dados.get("location") or {}).get("coordinates") or {})
        lat = coordenadas.get("latitude")
        lon = coordenadas.get("longitude")
        return {
            "sucesso": True,
            "cep": str(dados.get("cep") or "").strip(),
            "logradouro": str(dados.get("street") or "").strip(),
            "bairro": str(dados.get("neighborhood") or "").strip(),
            "cidade": str(dados.get("city") or "").strip(),
            "uf": str(dados.get("state") or "").strip(),
            "lat": lat,
            "lon": lon,
        }
    except requests.RequestException as exc:
        return {"sucesso": False, "erro": f"Falha ao consultar BrasilAPI: {exc}"}
    except (KeyError, TypeError, ValueError) as exc:
        return {"sucesso": False, "erro": f"Resposta inesperada da BrasilAPI: {exc}"}
    except Exception as exc:
        return {"sucesso": False, "erro": str(exc)}


@st.cache_data(ttl=3600, show_spinner=False)
def _consultar_photon(termo: str, limite: int = 5) -> list[dict]:
    """Consulta o Photon com bbox/foco RMSP e prioriza logradouro + número.

    Args:
        termo: Texto livre (logradouro, bairro, CEP ou referência).
        limite: Quantidade máxima de sugestões.

    Returns:
        list[dict]: Candidatos padronizados (``fonte="photon"``), já filtrados pela RMSP.
    """
    params = {
        "q": termo,
        "limit": int(limite),
        "bbox": _RMSP_BBOX,
        "lat": _RMSP_FOCO[0],
        "lon": _RMSP_FOCO[1],
    }
    try:
        response = requests.get(_PHOTON_URL, params=params, timeout=_TIMEOUT_PADRAO)
        response.raise_for_status()
        dados = response.json()
        features = dados.get("features", []) if isinstance(dados, dict) else []
        candidatos: list[dict] = []
        for feature in features:
            props = feature.get("properties") or {}
            coords = (feature.get("geometry") or {}).get("coordinates") or []
            if len(coords) < 2:
                continue
            lon, lat = coords[0], coords[1]
            if not _dentro_rmsp(lat, lon):
                continue
            numero = str(props.get("housenumber") or "").strip()
            label = _normalizar_label(props)
            if numero:
                nivel = "ALTA"
                motivo = f"Photon: logradouro + número {numero} — coordenada de rua"
            else:
                nivel, motivo = _classificar_texto_livre(label or termo)
                motivo = f"Photon: {motivo}"
            candidatos.append(
                _candidato(
                    label,
                    lat,
                    lon,
                    cep=props.get("postcode") or "",
                    logradouro=props.get("street") or props.get("name") or "",
                    numero=numero,
                    bairro=props.get("district") or props.get("locality") or "",
                    cidade=props.get("city") or props.get("town") or "",
                    uf=props.get("state") or "",
                    nivel=nivel,
                    fonte="photon",
                    motivo=motivo,
                )
            )
        return candidatos[: int(limite)]
    except requests.RequestException:
        return []
    except (KeyError, TypeError, ValueError, AttributeError):
        return []
    except Exception:
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def _consultar_nominatim_estruturado(
    texto: str = "",
    *,
    street: str = "",
    city: str = "",
    state: str = "",
    postalcode: str = "",
    limite: int = 5,
) -> list[dict]:
    """Consulta o Nominatim (texto ou estrutura) limitada à RMSP.

    Args:
        texto: Query livre (``q``) quando informada.
        street: Logradouro para busca estruturada.
        city: Cidade para busca estruturada.
        state: UF para busca estruturada.
        postalcode: CEP para busca estruturada/fallback.
        limite: Quantidade máxima de resultados (aplicada também no request).

    Returns:
        list[dict]: Candidatos padronizados (``fonte="nominatim"``) dentro da RMSP.
    """
    params = {
        "format": "json",
        "addressdetails": 1,
        "limit": int(limite),
        "countrycodes": "br",
        "bounded": 1,
        "viewbox": f"{_RMSP_LON_MIN},{_RMSP_LAT_MAX},{_RMSP_LON_MAX},{_RMSP_LAT_MIN}",
    }
    if texto:
        params["q"] = texto
    else:
        if street:
            params["street"] = street
        if city:
            params["city"] = city
        if state:
            params["state"] = state
    if postalcode:
        params["postalcode"] = postalcode

    try:
        response = requests.get(
            _NOMINATIM_URL,
            params=params,
            headers=_HEADERS_NOMINATIM,
            timeout=_TIMEOUT_PADRAO,
        )
        response.raise_for_status()
        dados = response.json()
        if not isinstance(dados, list):
            return []
        candidatos: list[dict] = []
        for item in dados:
            try:
                lat = float(item["lat"])
                lon = float(item["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if not _dentro_rmsp(lat, lon):
                continue
            endereco = item.get("address") or {}
            logradouro = endereco.get("road") or endereco.get("pedestrian") or street or ""
            numero = str(endereco.get("house_number") or "").strip()
            bairro = endereco.get("suburb") or endereco.get("neighbourhood") or ""
            cidade = endereco.get("city") or endereco.get("town") or endereco.get("village") or city or ""
            uf = endereco.get("state_code") or endereco.get("state") or state or ""
            cep = endereco.get("postcode") or postalcode or ""
            label = _montar_label(logradouro, numero, bairro, cidade, uf, cep)
            if not logradouro and item.get("display_name"):
                label = str(item["display_name"])
            if numero:
                nivel = "ALTA"
                motivo = f"Nominatim: logradouro + número {numero} — coordenada de rua"
            else:
                nivel, motivo = _classificar_texto_livre(texto or label)
                motivo = f"Nominatim: {motivo}"
            candidatos.append(
                _candidato(
                    label,
                    lat,
                    lon,
                    cep=cep,
                    logradouro=logradouro,
                    numero=numero,
                    bairro=bairro,
                    cidade=cidade,
                    uf=uf,
                    nivel=nivel,
                    fonte="nominatim",
                    motivo=motivo,
                )
            )
        return candidatos[: int(limite)]
    except requests.RequestException:
        return []
    except (KeyError, TypeError, ValueError, AttributeError):
        return []
    except Exception:
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def _consultar_google(termo: str, limite: int = 5) -> list[dict]:
    """Consulta o Google Geocoding apenas quando ``GOOGLE_MAPS_API_KEY`` está definida.

    Args:
        termo: Texto livre do endereço.
        limite: Quantidade máxima de sugestões.

    Returns:
        list[dict]: Candidatos padronizados (``fonte="google"``) dentro da RMSP.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key or not termo:
        return []
    params = {
        "address": termo,
        "key": api_key,
        "region": "br",
        "bounds": f"{_RMSP_LAT_MIN},{_RMSP_LON_MIN}|{_RMSP_LAT_MAX},{_RMSP_LON_MAX}",
        "language": "pt-BR",
    }
    try:
        response = requests.get(_GOOGLE_GEOCODE_URL, params=params, timeout=_TIMEOUT_PADRAO)
        response.raise_for_status()
        dados = response.json()
        if not isinstance(dados, dict) or dados.get("status") not in ("OK", "ZERO_RESULTS"):
            return []
        candidatos: list[dict] = []
        for item in (dados.get("results") or [])[: int(limite)]:
            local = (item.get("geometry") or {}).get("location") or {}
            lat, lon = local.get("lat"), local.get("lng")
            if not _dentro_rmsp(lat, lon):
                continue
            componentes = {
                comp.get("type"): comp.get("long_name", "")
                for comp in item.get("address_components") or []
            }
            logradouro = componentes.get("route", "")
            numero = componentes.get("street_number", "")
            bairro = componentes.get("sublocality_level_1") or componentes.get("sublocality") or ""
            cidade = componentes.get("administrative_area_level_2") or componentes.get("locality") or ""
            uf = componentes.get("administrative_area_level_1", "")
            cep = componentes.get("postal_code", "")
            label = item.get("formatted_address") or _montar_label(logradouro, numero, bairro, cidade, uf, cep)
            nivel = "ALTA" if numero else _classificar_texto_livre(termo)[0]
            candidatos.append(
                _candidato(
                    label,
                    lat,
                    lon,
                    cep=cep,
                    logradouro=logradouro,
                    numero=numero,
                    bairro=bairro,
                    cidade=cidade,
                    uf=uf,
                    nivel=nivel,
                    fonte="google",
                    motivo="Google Geocoding: endereço validado" if numero else "Google Geocoding: coordenada aproximada",
                )
            )
        return candidatos
    except requests.RequestException:
        return []
    except (KeyError, TypeError, ValueError, AttributeError):
        return []
    except Exception:
        return []


def _deduplicar(candidatos: list[dict], limite: int) -> list[dict]:
    """Remove duplicatas por proximidade de lat/lon preservando a ordem de prioridade."""
    vistos: set[tuple[float, float]] = set()
    unicos: list[dict] = []
    for candidato in candidatos:
        chave = (round(float(candidato["lat"]), 4), round(float(candidato["lon"]), 4))
        if chave in vistos:
            continue
        vistos.add(chave)
        unicos.append(candidato)
    return unicos[: max(1, int(limite))]


@st.cache_data(ttl=3600, show_spinner=False)
def sugerir_enderecos(termo: str, limite: int = 5) -> list[dict]:
    """Sugere endereços na RMSP com pipeline CEP → Photon/Nominatim → Google.

    Args:
        termo: CEP (8 dígitos) e/ou endereço digitado; mínimo de 3 caracteres.
        limite: Quantidade máxima de sugestões (default 5).

    Returns:
        list[dict]: Cada item contém ``label_exibicao``, ``lat``, ``lon``, ``cep``,
        ``logradouro``, ``numero``, ``bairro``, ``cidade``, ``uf``,
        ``nivel_precisao``, ``semaforo``, ``fonte`` e ``motivo_precisao``.
        Retorna ``[]`` quando o termo é curto ou nenhuma camada localiza o endereço.
    """
    if not termo or len(str(termo).strip()) < 3:
        return []

    limite = max(1, min(int(limite or 5), 10))
    info = _parse_termo(termo)
    numero = info["numero"] or ""
    candidatos: list[dict] = []

    if info["cep"]:
        cep_digitos = info["cep"]
        cep_formatado = f"{cep_digitos[:5]}-{cep_digitos[5:]}"
        base = _consultar_viacep(cep_digitos)
        fonte_base = "viacep"
        if not base.get("sucesso"):
            base = _consultar_brasilapi(cep_digitos)
            fonte_base = "brasilapi"

        if base.get("sucesso"):
            logradouro = base.get("logradouro", "")
            bairro = base.get("bairro", "")
            cidade = base.get("cidade", "")
            uf = base.get("uf", "")
            numero_final = numero or str(base.get("numero") or "")
            label_estruturado = _montar_label(logradouro, numero_final, bairro, cidade, uf, cep_formatado)

            lat_base, lon_base = base.get("lat"), base.get("lon")
            if lat_base is not None and lon_base is not None and _dentro_rmsp(lat_base, lon_base):
                nivel = "ALTA" if logradouro else "BAIXA"
                motivo = (
                    f"CEP {cep_formatado} — {fonte_base} logradouro '{logradouro}'"
                    if logradouro
                    else f"CEP geral de município — coordenada centralizada ({cidade}/{uf})"
                )
                candidatos.append(
                    _candidato(
                        label_estruturado,
                        lat_base,
                        lon_base,
                        cep=cep_formatado,
                        logradouro=logradouro,
                        numero=numero_final,
                        bairro=bairro,
                        cidade=cidade,
                        uf=uf,
                        nivel=nivel,
                        fonte=fonte_base,
                        motivo=motivo,
                    )
                )

            if not candidatos and logradouro:
                geos = _consultar_nominatim_estruturado(
                    street=logradouro,
                    city=cidade,
                    state=uf,
                    postalcode=cep_formatado,
                    limite=limite,
                )
                for geo in geos:
                    candidatos.append(
                        {
                            **geo,
                            "label_exibicao": label_estruturado,
                            "cep": cep_formatado,
                            "logradouro": logradouro,
                            "numero": numero_final,
                            "bairro": bairro or geo.get("bairro", ""),
                            "cidade": cidade or geo.get("cidade", ""),
                            "uf": uf or geo.get("uf", ""),
                            "nivel_precisao": "ALTA",
                            "semaforo": _MAPA_SEMAFORO["ALTA"],
                            "fonte": geo.get("fonte", "nominatim"),
                            "motivo_precisao": f"CEP {cep_formatado} — {geo.get('fonte', 'nominatim')} logradouro '{logradouro}' validado",
                        }
                    )

                if not candidatos:
                    for geo in _consultar_photon(f"{logradouro}, {cidade}, {uf}", limite):
                        candidatos.append(
                            {
                                **geo,
                                "label_exibicao": label_estruturado,
                                "cep": cep_formatado,
                                "logradouro": logradouro,
                                "numero": numero_final,
                                "bairro": bairro or geo.get("bairro", ""),
                                "cidade": cidade or geo.get("cidade", ""),
                                "uf": uf or geo.get("uf", ""),
                                "nivel_precisao": "ALTA",
                                "semaforo": _MAPA_SEMAFORO["ALTA"],
                                "motivo_precisao": f"CEP {cep_formatado} — Photon logradouro '{logradouro}' validado",
                            }
                        )

                if not candidatos and bairro and cidade:
                    for geo in _consultar_nominatim_estruturado(
                        texto=f"{bairro}, {cidade}, {uf}, Brasil", limite=limite
                    ):
                        candidatos.append(
                            {
                                **geo,
                                "label_exibicao": label_estruturado,
                                "cep": cep_formatado,
                                "logradouro": logradouro,
                                "numero": numero_final,
                                "bairro": bairro,
                                "cidade": cidade,
                                "uf": uf,
                                "nivel_precisao": "MEDIA",
                                "semaforo": _MAPA_SEMAFORO["MEDIA"],
                                "motivo_precisao": f"CEP {cep_formatado} — logradouro não localizado, fallback bairro '{bairro}'",
                            }
                        )

            if not candidatos and not logradouro and cidade and uf:
                for geo in _consultar_nominatim_estruturado(texto=f"{cidade}, {uf}, Brasil", limite=limite):
                    candidatos.append(
                        {
                            **geo,
                            "label_exibicao": label_estruturado,
                            "cep": cep_formatado,
                            "nivel_precisao": "BAIXA",
                            "semaforo": _MAPA_SEMAFORO["BAIXA"],
                            "motivo_precisao": f"CEP geral de município — coordenada centralizada ({cidade}/{uf}) — CEP {cep_formatado} sem logradouro",
                        }
                    )

            if not candidatos:
                nivel_fallback = "MEDIA" if logradouro else "BAIXA"
                for geo in _consultar_nominatim_estruturado(postalcode=cep_formatado, limite=limite):
                    candidatos.append(
                        {
                            **geo,
                            "label_exibicao": label_estruturado,
                            "cep": cep_formatado,
                            "logradouro": logradouro,
                            "numero": numero_final,
                            "bairro": bairro or geo.get("bairro", ""),
                            "cidade": cidade or geo.get("cidade", ""),
                            "uf": uf or geo.get("uf", ""),
                            "nivel_precisao": nivel_fallback,
                            "semaforo": _MAPA_SEMAFORO[nivel_fallback],
                            "motivo_precisao": (
                                f"CEP {cep_formatado} localizado via postalcode Nominatim"
                                + (" sem detalhamento ViaCEP — coordenada aproximada" if logradouro else " — CEP geral")
                            ),
                        }
                    )
        else:
            for geo in _consultar_nominatim_estruturado(postalcode=cep_formatado, limite=limite):
                candidatos.append(
                    {
                        **geo,
                        "label_exibicao": f"CEP {cep_formatado}",
                        "cep": cep_formatado,
                        "nivel_precisao": "BAIXA",
                        "semaforo": _MAPA_SEMAFORO["BAIXA"],
                        "motivo_precisao": f"CEP {cep_formatado} — fallback postalcode (ViaCEP/BrasilAPI indisponíveis)",
                    }
                )
    else:
        texto_busca = termo.strip()
        candidatos.extend(_consultar_photon(texto_busca, limite))
        if len(candidatos) < limite:
            for geo in _consultar_nominatim_estruturado(texto=texto_busca, limite=limite):
                if numero and not geo.get("numero"):
                    label = _montar_label(
                        geo.get("logradouro") or texto_busca,
                        numero,
                        geo.get("bairro", ""),
                        geo.get("cidade", ""),
                        geo.get("uf", ""),
                        geo.get("cep", ""),
                    )
                    geo = {
                        **geo,
                        "label_exibicao": label,
                        "numero": numero,
                        "nivel_precisao": "ALTA",
                        "semaforo": _MAPA_SEMAFORO["ALTA"],
                    }
                candidatos.append(geo)
        if len(candidatos) < limite:
            candidatos.extend(_consultar_google(texto_busca, limite))

    return _deduplicar(candidatos, limite)


@st.cache_data(ttl=3600, show_spinner=False)
def buscar_coordenadas_por_cep_ou_endereco(busca_texto: str) -> dict:
    """Fachada legada (lote/UI) sobre ``sugerir_enderecos`` com o melhor resultado.

    Args:
        busca_texto: CEP (8 dígitos) ou endereço livre.

    Returns:
        dict: Em sucesso ``{"sucesso": True, "lat": float, "lon": float,
        "endereco_encontrado": str, "nivel_precisao": "ALTA"|"MEDIA"|"BAIXA",
        "semaforo": str, "motivo_precisao": str, "fonte": str}``.
        Em falha ``{"sucesso": False, "erro": str}``.
    """
    if not busca_texto or not str(busca_texto).strip():
        return {"sucesso": False, "erro": "Informe um CEP ou endereço válido."}

    try:
        sugestoes = sugerir_enderecos(str(busca_texto).strip(), 1)
    except Exception as exc:
        return {"sucesso": False, "erro": f"Falha na geocodificação: {exc}"}

    if not sugestoes:
        return {"sucesso": False, "erro": "Endereço ou CEP não localizado no mapa."}

    melhor = sugestoes[0]
    return {
        "sucesso": True,
        "lat": melhor["lat"],
        "lon": melhor["lon"],
        "endereco_encontrado": melhor["label_exibicao"],
        "nivel_precisao": melhor["nivel_precisao"],
        "semaforo": melhor["semaforo"],
        "motivo_precisao": melhor["motivo_precisao"],
        "fonte": melhor["fonte"],
        "cep": melhor.get("cep", ""),
    }
