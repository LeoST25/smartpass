"""Motor de tarifa com integração temporal Bilhete Único / TOP para RMSP.

Regras implementadas (parametrizáveis via .env e catálogo oficial):
- Bilhete Único SPTrans: até 4 embarques em ônibus municipais dentro de 3h pagam 1 tarifa cheia.
- Integração Ônibus SPTrans + Trilho (Metrô/CPTM) aplica teto VT_TARIFA_INTEGRACAO_ONIBUS_TRILHO.
- Cadeia Ônibus -> Trilho -> Ônibus dentro da mesma janela mantém o teto (segundo ônibus gratuito).
- EMTU intermunicipal preserva tarifa própria (por linha/operadora via tarifas_rmsp.json) e aplica desconto quando integrado ao trilho (TOP).
- Fallback transparente: linha não catalogada usa tarifa base da operadora com tarifa_confirmada=False e alerta em memória_calculo.
- Prioridade de tarifa: GTFS fare_attributes (cents) > linha exata no JSON > agency match no JSON > tarifa base por tipo (env).

Contrato de retorno sempre contém chave "sucesso": True/False (.clinerules).
Cálculo base é por trecho (1 sentido); diário = trecho*2; mensal = diário*dias_uteis.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(float(os.getenv(key, str(default))))
    except (TypeError, ValueError):
        return default


@dataclass
class FareConfig:
    """Configuração de tarifas e janelas — 100% via .env com defaults RMSP vigentes."""

    tarifa_onibus_sptrans: float = field(default_factory=lambda: _env_float("VT_TARIFA_ONIBUS_SPTRANS", _env_float("VT_TARIFA_PADRAO", 4.40)))
    tarifa_trilho: float = field(default_factory=lambda: _env_float("VT_TARIFA_TRILHO", _env_float("VT_TARIFA_TRILHO_CPTM_METRO", 5.00)))
    tarifa_integracao_onibus_trilho: float = field(default_factory=lambda: _env_float("VT_TARIFA_INTEGRACAO_ONIBUS_TRILHO", 9.20))
    tarifa_emtu: float = field(default_factory=lambda: _env_float("VT_TARIFA_EMTU", _env_float("VT_TARIFA_INTERMUNICIPAL", 6.80)))
    desconto_emtu_trilho: float = field(default_factory=lambda: _env_float("VT_DESCONTO_INTEGRACAO_EMTU_TRILHO", _env_float("VT_DESCONTO_TOP", 0.50)))
    janela_minutos: int = field(default_factory=lambda: _env_int("VT_JANELA_BU_MINUTOS", 180))
    max_embarques_bu: int = field(default_factory=lambda: _env_int("VT_MAX_EMBARQUES_BU", 4))
    max_caminhada_km: float = field(default_factory=lambda: _env_float("VT_MAX_CAMINHADA_ECONOMICA_KM", 1.5))
    max_baldeacoes: int = field(default_factory=lambda: _env_int("VT_MAX_BALDEACOES_ECONOMICA", 3))
    tarifa_padrao: float = field(default_factory=lambda: _env_float("VT_TARIFA_PADRAO", 5.00))
    intervalo_embarque_min: int = field(default_factory=lambda: _env_int("VT_INTERVALO_EMBARQUE_MIN", 5))


# ---------------------------------------------------------------------------
# Catálogo oficial RMSP — src/data/tarifas_rmsp.json
# ---------------------------------------------------------------------------
_CATALOGO_CACHE: dict | None = None
_CATALOGO_PATH_CACHE: str | None = None


def _normalizar_txt(s: str) -> str:
    return (s or "").strip().lower()


def _carregar_catalogo(caminho: str | Path | None = None) -> dict:
    """Carrega catálogo JSON versionado; retorna dict vazio se ausente (fallback env)."""
    global _CATALOGO_CACHE, _CATALOGO_PATH_CACHE
    env_path = os.getenv("VT_TARIFAS_RMSP_JSON", "src/data/tarifas_rmsp.json")
    path = Path(caminho or env_path)
    # resolve relativo à raiz do projeto
    if not path.is_absolute():
        # tenta a partir de cwd e a partir de src/
        candidates = [Path.cwd() / path, Path(__file__).resolve().parents[2] / path, Path(__file__).resolve().parents[2] / "src" / "data" / "tarifas_rmsp.json"]
        found = None
        for c in candidates:
            if c.exists():
                found = c
                break
        if found is None:
            return {}
        path = found
    path_str = str(path.resolve())
    if _CATALOGO_CACHE is not None and _CATALOGO_PATH_CACHE == path_str:
        return _CATALOGO_CACHE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _CATALOGO_CACHE = data
        _CATALOGO_PATH_CACHE = path_str
        return data
    except Exception:
        return {}


def carregar_catalogo_tarifas(caminho: str | Path | None = None) -> dict:
    """API pública para carregar catálogo oficial (LGPD stateless, read-only)."""
    return _carregar_catalogo(caminho)


def _codigo_linha_leg(leg: dict) -> str:
    rota = leg.get("route") or {}
    for k in ("shortName", "gtfsId", "longName"):
        v = (rota.get(k) or "").strip()
        if v:
            if ":" in v and k == "gtfsId":
                v = v.split(":")[-1].strip()
            return v
    # fallback para codigo_linha já enriquecido
    return (leg.get("codigo_linha") or leg.get("linha") or "").strip()


def _agencia_leg(leg: dict) -> dict:
    rota = leg.get("route") or {}
    agency = rota.get("agency") or leg.get("agency") or {}
    return {"gtfsId": (agency.get("gtfsId") or "").strip(), "name": (agency.get("name") or "").strip()}


def resolver_tarifa_por_leg(leg: dict, config: FareConfig | dict | None = None, catalogo: dict | None = None) -> dict:
    """Resolve tarifa oficial de uma perna com prioridade GTFS > JSON linha > agency > base.

    Args:
        leg: dict com mode/route/agency/codigo_linha/fare_cents opcional.
        config: FareConfig ou dict para tarifas base.
        catalogo: dict do JSON (se None, carrega do disco).

    Returns:
        dict: {"valor": float, "fonte": str, "tarifa_confirmada": bool, "operadora": str, "codigo_linha": str, "tipo": str}
    """
    cfg = _resolve_config(config)
    cat = catalogo if catalogo is not None else _carregar_catalogo()
    codigo = _codigo_linha_leg(leg)
    codigo_norm = _normalizar_txt(codigo)
    codigo_upper = codigo.strip().upper()
    agencia = _agencia_leg(leg)
    agencia_txt = f"{agencia.get('gtfsId','')} {agencia.get('name','')}".strip()
    agencia_norm = _normalizar_txt(agencia_txt)
    tipo_inferido = _classificar_leg(leg)
    versao = cat.get("versao", "env")

    # 1) GTFS fare_attributes — cents quando grafo expõe fare
    fare_cents = leg.get("fare_cents")
    if fare_cents is None:
        # também pode vir como fare.regular.cents em mocks
        fare = leg.get("fare") or {}
        if isinstance(fare, dict):
            reg = fare.get("regular") or {}
            if isinstance(reg, dict) and "cents" in reg:
                try:
                    fare_cents = int(reg["cents"])
                except Exception:
                    fare_cents = None
    if fare_cents is not None:
        try:
            valor = round(int(fare_cents) / 100, 2)
            operadora = agencia.get("name") or tipo_inferido
            return {"valor": valor, "fonte": "GTFS Oficial (fare_attributes)", "tarifa_confirmada": True, "operadora": operadora, "codigo_linha": codigo, "tipo": tipo_inferido}
        except Exception:
            pass

    # 2) Match exato por linha no JSON (shortName/gtfsId)
    linhas_cat = cat.get("linhas") or {}
    # normaliza chaves para upper
    linhas_norm = {str(k).strip().upper(): v for k, v in linhas_cat.items()}
    match_linha = None
    if codigo_upper and codigo_upper in linhas_norm:
        match_linha = linhas_norm[codigo_upper]
    elif codigo_norm and any(_normalizar_txt(k) == codigo_norm for k in linhas_cat):
        # fallback lower
        for k, v in linhas_cat.items():
            if _normalizar_txt(k) == codigo_norm:
                match_linha = v
                break
    if match_linha:
        try:
            valor = round(float(match_linha.get("tarifa")), 2)
            operadora = match_linha.get("operadora") or agencia.get("name") or tipo_inferido
            tipo = match_linha.get("tipo") or tipo_inferido
            return {"valor": valor, "fonte": f"Tabela Vigente RMSP {versao} — linha {codigo}", "tarifa_confirmada": True, "operadora": operadora, "codigo_linha": codigo, "tipo": tipo}
        except Exception:
            pass

    # 3) Match por agência no JSON (substring)
    agencias_cat = cat.get("agencias") or {}
    for _key, adata in agencias_cat.items():
        matches = adata.get("match") or []
        for m in matches:
            if _normalizar_txt(m) and _normalizar_txt(m) in agencia_norm:
                try:
                    valor = round(float(adata.get("tarifa")), 2)
                    operadora = adata.get("operadora") or agencia.get("name") or tipo_inferido
                    tipo = adata.get("tipo") or tipo_inferido
                    # EMTU genérico sem linha exata é estimativa (tarifa varia por linha)
                    confirmada = True
                    fonte = f"Tabela Vigente RMSP {versao} — operadora {operadora}"
                    if tipo == "EMTU" and codigo_upper not in {str(k).strip().upper() for k in linhas_cat}:
                        confirmada = False
                        fonte = f"Tarifa base {operadora} R$ {valor:.2f} — linha {codigo or '—'} não catalogada (estimativa provisória)"
                    return {"valor": valor, "fonte": fonte, "tarifa_confirmada": confirmada, "operadora": operadora, "codigo_linha": codigo, "tipo": tipo}
                except Exception:
                    continue

    # 4) Fallback por tipo (tarifa base env) — não confirmada, sinaliza estimativa
    if tipo_inferido == "SPTRANS_ONIBUS":
        valor = round(cfg.tarifa_onibus_sptrans, 2)
        operadora = agencia.get("name") or "SPTrans (estimativa)"
        fonte = f"Tarifa base SPTrans R$ {valor:.2f} — linha não catalogada (estimativa provisória)"
        return {"valor": valor, "fonte": fonte, "tarifa_confirmada": False, "operadora": operadora, "codigo_linha": codigo, "tipo": tipo_inferido}
    if tipo_inferido == "TRILHO":
        valor = round(cfg.tarifa_trilho, 2)
        operadora = agencia.get("name") or "Trilho (estimativa)"
        fonte = f"Tarifa base Trilho R$ {valor:.2f} — linha não catalogada (estimativa provisória)"
        return {"valor": valor, "fonte": fonte, "tarifa_confirmada": False, "operadora": operadora, "codigo_linha": codigo, "tipo": tipo_inferido}
    if tipo_inferido == "EMTU":
        valor = round(cfg.tarifa_emtu, 2)
        operadora = agencia.get("name") or "EMTU (estimativa)"
        fonte = f"Tarifa base EMTU R$ {valor:.2f} — linha não catalogada (estimativa provisória)"
        return {"valor": valor, "fonte": fonte, "tarifa_confirmada": False, "operadora": operadora, "codigo_linha": codigo, "tipo": tipo_inferido}
    # OUTRO
    try:
        v = leg.get("valor_unitario") or leg.get("valor")
        if v is not None:
            valor = round(float(v), 2)
            return {"valor": valor, "fonte": "Valor informado na perna", "tarifa_confirmada": False, "operadora": agencia.get("name") or tipo_inferido, "codigo_linha": codigo, "tipo": tipo_inferido}
    except Exception:
        pass
    valor = round(cfg.tarifa_padrao, 2)
    return {"valor": valor, "fonte": f"Tarifa padrão R$ {valor:.2f} — tipo OUTRO (estimativa)", "tarifa_confirmada": False, "operadora": agencia.get("name") or tipo_inferido, "codigo_linha": codigo, "tipo": tipo_inferido}


def _resolve_config(config: FareConfig | dict | None) -> FareConfig:
    """Normaliza config dict/FareConfig/None para FareConfig."""
    if config is None:
        return FareConfig()
    if isinstance(config, FareConfig):
        return config
    if isinstance(config, dict):
        base = FareConfig()
        # permite override parcial via dict
        for k, v in config.items():
            if hasattr(base, k):
                setattr(base, k, type(getattr(base, k))(v) if v is not None else getattr(base, k))
            # aliases comuns
            alias = {
                "tarifa_onibus": "tarifa_onibus_sptrans",
                "tarifa_integracao": "tarifa_integracao_onibus_trilho",
                "janela": "janela_minutos",
            }
            if k in alias and hasattr(base, alias[k]):
                setattr(base, alias[k], type(getattr(base, alias[k]))(v))
        return base
    return FareConfig()


def _nome_leg(leg: dict, idx: int) -> str:
    """Extrai nome legível para detalhamento."""
    if leg.get("linha"):
        return str(leg["linha"])
    rota = leg.get("route") or {}
    curto = (rota.get("shortName") or "").strip()
    longo = (rota.get("longName") or "").strip()
    modo = (leg.get("mode") or "TRANSPORTE").replace("_", " ").title()
    if curto and longo:
        return f"{modo} {curto} — {longo}"
    if curto or longo:
        return f"{modo} {curto or longo}".strip()
    return f"{modo} Trecho {idx+1}"


def _classificar_leg(leg: dict) -> str:
    """Classifica perna em SPTRANS_ONIBUS | TRILHO | EMTU | OUTRO — agency tem precedência."""
    linha = str(leg.get("linha", "")).upper()
    modo = str(leg.get("mode", "")).upper()
    rota = leg.get("route") or {}
    agency = rota.get("agency") or leg.get("agency") or {}
    agencia_txt = f"{agency.get('gtfsId','')} {agency.get('name','')}".upper()
    curto = str(rota.get("shortName", "")).upper()
    longo = str(rota.get("longName", "")).upper()
    codigo = str(leg.get("codigo_linha", "")).upper()
    combinado = " ".join([linha, curto, longo, codigo, modo, agencia_txt])

    # Agency tem precedência absoluta (evita BUS genérico quebrar EMTU)
    if any(x in agencia_txt for x in ["EMTU", "INTERMUNICIPAL"]):
        return "EMTU"
    if any(x in agencia_txt for x in ["METRO", "METRÔ", "CPTM", "VIAQUATRO", "VIAMOBILIDADE", "TREM"]):
        return "TRILHO"
    if "EMTU" in combinado or "INTERMUNICIPAL" in combinado or "TOP" in combinado:
        return "EMTU"
    if modo == "BUS" or "ONIBUS" in combinado or "ÔNBUS" in combinado:
        if modo == "BUS":
            # se agency já classificou, mantém; senão BUS = SPTrans por padrão (EMTU já filtrado)
            return "SPTRANS_ONIBUS"
        if "BUS" in modo:
            return "SPTRANS_ONIBUS"
    if modo in ("RAIL", "SUBWAY", "TRAM") or any(x in combinado for x in ["METRO", "METRÔ", "CPTM", "TREM", "RAIL", "SUBWAY"]):
        return "TRILHO"
    if any(x in linha for x in ["METRÔ", "METRO", "CPTM", "L4", "L1", "L2", "L3"]):
        return "TRILHO"
    if "392" in linha or "ONIBUS" in linha or "ÔNBUS" in linha:
        return "SPTRANS_ONIBUS"
    return "OUTRO"


def _duracao_leg(leg: dict) -> int:
    """Retorna duração estimada da perna em minutos."""
    for k in ("duracao_min", "duration_min", "tempo_min", "duration", "duracao"):
        v = leg.get(k)
        if v is not None:
            try:
                return max(int(round(float(v))), 1)
            except Exception:
                pass
    try:
        dist_km = float(leg.get("distance") or 0) / 1000
        if dist_km > 0:
            return max(int(round((dist_km / 18.0) * 60)), 2)
    except Exception:
        pass
    return 10


def _intervalo_leg(leg: dict, cfg: FareConfig) -> int:
    """Intervalo entre pernas; permite override por leg."""
    v = leg.get("intervalo_min") or leg.get("intervalo") or leg.get("gap_min")
    if v is not None:
        try:
            return max(int(round(float(v))), 0)
        except Exception:
            pass
    return cfg.intervalo_embarque_min


def calcular_custo_com_integracao(
    legs: list[dict],
    dias_uteis: int = 22,
    config: FareConfig | dict | None = None,
) -> dict:
    """Calcula custo com integração temporal BU/TOP usando tarifa oficial por leg.

    Cada leg é tarifado via resolver_tarifa_por_leg (GTFS > JSON > base). Integração BU/TOP
    aplica teto/desconto sobre os valores oficiais.

    O cálculo base é de **1 sentido** (custo_trecho). Derivados:
    ``custo_diario = custo_trecho * 2`` (ida e volta) e
    ``custo_mensal = custo_diario * dias_uteis``.

    Args:
        legs: Lista de pernas na ordem do trajeto. Cada item deve conter
            ao menos ``linha`` ou ``mode``/``route``. Opcional:
            ``inicio_min``, ``duracao_min``, ``distance``, ``intervalo_min``,
            ``agency``, ``codigo_linha``, ``fare_cents``.
        dias_uteis: Dias úteis no mês para cálculo mensal.
        config: FareConfig ou dict parcial para override de tarifas/janela.

    Returns:
        dict: Em sucesso ``{"sucesso": True, "custo_trecho": float,
            "custo_diario": float, "custo_mensal": float,
            "detalhamento_tarifario": list[str], "detalhes": list[dict],
            "memoria_calculo": list[str], "justificativa": str}``.
            Cada detalhe contém ``operadora, codigo_linha, fonte, tarifa_confirmada``.
            Em falha ``{"sucesso": False, "erro": str, "memoria_calculo": [...]}``.
    """
    try:
        cfg = _resolve_config(config)
        catalogo = _carregar_catalogo()
        if not isinstance(dias_uteis, int) or dias_uteis < 1:
            dias_uteis = 22
        if dias_uteis > 31:
            dias_uteis = 31

        if legs is None or not isinstance(legs, list) or len(legs) == 0:
            return {
                "sucesso": False,
                "erro": "Nenhuma perna de transporte informada para cálculo de tarifa.",
                "memoria_calculo": ["Falha: lista de pernas vazia — OTP possivelmente offline. Aplicar estimativa de contingência."],
                "justificativa": "Sem itinerário válido não é possível aplicar regras de integração.",
            }

        # filtra WALK se houver
        legs_transito = [l for l in legs if l.get("mode", "").upper() != "WALK" and l.get("route") is not None or l.get("linha")]
        if not legs_transito:
            legs_transito = [l for l in legs if _classificar_leg(l) != "OUTRO" or l.get("linha")]
        if not legs_transito:
            legs_transito = legs

        # Resolve tarifa oficial por leg antes do cálculo de integração
        tarifas_resolvidas = [resolver_tarifa_por_leg(l, config=cfg, catalogo=catalogo) for l in legs_transito]

        custo_trecho = 0.0
        detalhamento: list[str] = []
        detalhes: list[dict] = []
        memoria: list[str] = []
        alertas: list[str] = []

        janela_inicio_min: int | None = None
        janela_embarques = 0
        janela_custo_pago = 0.0
        janela_tipos: list[str] = []
        elapsed = 0

        tem_inicio_explicito = any("inicio_min" in l for l in legs_transito)

        for idx, leg in enumerate(legs_transito):
            nome = _nome_leg(leg, idx)
            tarifa_info = tarifas_resolvidas[idx]
            tipo = tarifa_info.get("tipo") or _classificar_leg(leg)
            tarifa_base = tarifa_info["valor"]
            operadora = tarifa_info["operadora"]
            fonte = tarifa_info["fonte"]
            confirmada = tarifa_info["tarifa_confirmada"]
            codigo = tarifa_info["codigo_linha"]

            if not confirmada:
                alertas.append(f"Linha {codigo or nome} — tarifa não catalogada, estimativa R$ {tarifa_base:.2f} ({operadora})")

            if idx == 0:
                if tem_inicio_explicito:
                    try:
                        elapsed = int(float(leg.get("inicio_min", 0)))
                    except Exception:
                        elapsed = 0
                else:
                    elapsed = 0
            else:
                prev = legs_transito[idx - 1]
                if tem_inicio_explicito:
                    try:
                        elapsed = int(float(leg.get("inicio_min", elapsed + _duracao_leg(prev) + _intervalo_leg(prev, cfg))))
                    except Exception:
                        elapsed = elapsed + _duracao_leg(prev) + _intervalo_leg(prev, cfg)
                else:
                    elapsed = elapsed + _duracao_leg(prev) + _intervalo_leg(prev, cfg)

            dentro_janela = False
            if janela_inicio_min is not None:
                tempo_na_janela = elapsed - janela_inicio_min
                if tempo_na_janela <= cfg.janela_minutos and janela_embarques < cfg.max_embarques_bu:
                    dentro_janela = True
                else:
                    memoria.append(
                        f"Janela BU encerrada antes do trecho {idx+1}: {tempo_na_janela}min desde início (limite {cfg.janela_minutos}min) ou {janela_embarques} embarques (limite {cfg.max_embarques_bu}). Nova janela iniciada."
                    )
                    janela_inicio_min = None
                    janela_embarques = 0
                    janela_custo_pago = 0.0
                    janela_tipos = []
                    dentro_janela = False

            custo_leg = 0.0
            sufixo_fonte = f" [{fonte}]"
            status_icon = "✅" if confirmada else "⚠️"

            if tipo == "SPTRANS_ONIBUS":
                if not dentro_janela:
                    custo_leg = round(tarifa_base, 2)
                    janela_inicio_min = elapsed
                    janela_embarques = 1
                    janela_custo_pago = custo_leg
                    janela_tipos = [tipo]
                    detalhamento.append(f"Trecho {idx+1}: {nome} ({operadora} {codigo}) — R$ {custo_leg:.2f} (Tarifa cheia){sufixo_fonte} {status_icon}")
                    mem_extra = "" if confirmada else " — ⚠️ tarifa a confirmar (estimativa)"
                    memoria.append(f"Trecho {idx+1} ({nome}): ônibus SPTrans {operadora} tarifa cheia R$ {custo_leg:.2f} — janela BU iniciada em {elapsed}min. Fonte: {fonte}.{mem_extra}")
                else:
                    has_sptrans = "SPTRANS_ONIBUS" in janela_tipos
                    has_trilho = "TRILHO" in janela_tipos
                    if not has_sptrans:
                        if has_trilho:
                            complemento = round(cfg.tarifa_integracao_onibus_trilho - janela_custo_pago, 2)
                            if complemento < 0:
                                complemento = 0.0
                            if complemento > tarifa_base:
                                complemento = round(tarifa_base, 2)
                            custo_leg = complemento
                            if custo_leg == 0:
                                detalhamento.append(f"Trecho {idx+1}: {nome} ({operadora} {codigo}) — R$ 0,00 (Gratuidade BU — teto integração R$ {cfg.tarifa_integracao_onibus_trilho:.2f} já atingido){sufixo_fonte} {status_icon}")
                                memoria.append(f"Trecho {idx+1} ({nome}): ônibus SPTrans {operadora} gratuito — teto integração já atingido (trilho prévio). Fonte: {fonte}.")
                            else:
                                detalhamento.append(f"Trecho {idx+1}: {nome} ({operadora} {codigo}) — R$ {custo_leg:.2f} (Integração BU — complemento até R$ {cfg.tarifa_integracao_onibus_trilho:.2f}){sufixo_fonte} {status_icon}")
                                memoria.append(f"Trecho {idx+1} ({nome}): ônibus SPTrans {operadora} com integração BU — complemento R$ {custo_leg:.2f} até teto R$ {cfg.tarifa_integracao_onibus_trilho:.2f} (trilho prévio). Fonte: {fonte}.")
                        else:
                            custo_leg = round(tarifa_base, 2)
                            detalhamento.append(f"Trecho {idx+1}: {nome} ({operadora} {codigo}) — R$ {custo_leg:.2f} (Tarifa cheia — sem integração com {janela_tipos[-1] if janela_tipos else 'janela'} na janela){sufixo_fonte} {status_icon}")
                            memoria.append(f"Trecho {idx+1} ({nome}): ônibus SPTrans {operadora} tarifa cheia R$ {custo_leg:.2f} — janela sem ônibus SPTrans prévio (iniciada com {janela_tipos}), sem gratuidade BU. Fonte: {fonte}.")
                        janela_embarques += 1
                        janela_custo_pago += custo_leg
                        janela_tipos.append(tipo)
                    elif janela_custo_pago >= cfg.tarifa_integracao_onibus_trilho - 1e-9:
                        custo_leg = 0.0
                        detalhamento.append(f"Trecho {idx+1}: {nome} ({operadora} {codigo}) — R$ 0,00 (Gratuidade BU — teto integração R$ {cfg.tarifa_integracao_onibus_trilho:.2f} já atingido){sufixo_fonte} {status_icon}")
                        memoria.append(f"Trecho {idx+1} ({nome}): ônibus SPTrans {operadora} gratuito — janela BU com integração já no teto R$ {cfg.tarifa_integracao_onibus_trilho:.2f}. Fonte: {fonte}.")
                        janela_embarques += 1
                        janela_tipos.append(tipo)
                    else:
                        custo_leg = 0.0
                        detalhamento.append(f"Trecho {idx+1}: {nome} ({operadora} {codigo}) — R$ 0,00 (Gratuidade BU — {janela_embarques+1}º embarque em <3h){sufixo_fonte} {status_icon}")
                        memoria.append(f"Trecho {idx+1} ({nome}): ônibus SPTrans {operadora} gratuito — {janela_embarques+1}º embarque dentro da janela de {cfg.janela_minutos}min (Bilhete Único até {cfg.max_embarques_bu} embarques). Fonte: {fonte}.")
                        janela_embarques += 1
                        janela_tipos.append(tipo)

            elif tipo == "TRILHO":
                if not dentro_janela:
                    custo_leg = round(tarifa_base, 2)
                    janela_inicio_min = elapsed
                    janela_embarques = 1
                    janela_custo_pago = custo_leg
                    janela_tipos = [tipo]
                    detalhamento.append(f"Trecho {idx+1}: {nome} ({operadora} {codigo}) — R$ {custo_leg:.2f} (Tarifa trilho cheia){sufixo_fonte} {status_icon}")
                    mem_extra = "" if confirmada else " — ⚠️ tarifa a confirmar"
                    memoria.append(f"Trecho {idx+1} ({nome}): trilho {operadora} tarifa cheia R$ {custo_leg:.2f} — nova janela. Fonte: {fonte}.{mem_extra}")
                else:
                    has_onibus = "SPTRANS_ONIBUS" in janela_tipos
                    has_emtu = "EMTU" in janela_tipos
                    if has_onibus:
                        complemento = round(cfg.tarifa_integracao_onibus_trilho - janela_custo_pago, 2)
                        if complemento < 0:
                            complemento = 0.0
                        if complemento > tarifa_base:
                            complemento = round(tarifa_base, 2)
                        custo_leg = complemento
                        if custo_leg == 0:
                            detalhamento.append(f"Trecho {idx+1}: {nome} ({operadora} {codigo}) — R$ 0,00 (Gratuidade BU — teto integração já atingido){sufixo_fonte} {status_icon}")
                            memoria.append(f"Trecho {idx+1} ({nome}): trilho {operadora} gratuito — teto integração R$ {cfg.tarifa_integracao_onibus_trilho:.2f} já atingido na janela. Fonte: {fonte}.")
                        else:
                            detalhamento.append(f"Trecho {idx+1}: {nome} ({operadora} {codigo}) — R$ {custo_leg:.2f} (Integração BU — complemento até R$ {cfg.tarifa_integracao_onibus_trilho:.2f}){sufixo_fonte} {status_icon}")
                            memoria.append(f"Trecho {idx+1} ({nome}): trilho {operadora} com integração BU — complemento R$ {custo_leg:.2f} para teto R$ {cfg.tarifa_integracao_onibus_trilho:.2f} (ônibus prévio na janela). Fonte: {fonte}.")
                        janela_custo_pago += custo_leg
                        janela_embarques += 1
                        janela_tipos.append(tipo)
                    elif has_emtu:
                        custo_leg = round(max(tarifa_base - cfg.desconto_emtu_trilho, 0), 2)
                        detalhamento.append(f"Trecho {idx+1}: {nome} ({operadora} {codigo}) — R$ {custo_leg:.2f} (Integração TOP/EMTU — desconto R$ {cfg.desconto_emtu_trilho:.2f}){sufixo_fonte} {status_icon}")
                        memoria.append(f"Trecho {idx+1} ({nome}): trilho {operadora} com integração TOP/EMTU — tarifa R$ {tarifa_base:.2f} - desconto R$ {cfg.desconto_emtu_trilho:.2f} = R$ {custo_leg:.2f}. Fonte: {fonte}.")
                        janela_custo_pago += custo_leg
                        janela_embarques += 1
                        janela_tipos.append(tipo)
                    else:
                        custo_leg = round(tarifa_base, 2)
                        detalhamento.append(f"Trecho {idx+1}: {nome} ({operadora} {codigo}) — R$ {custo_leg:.2f} (Tarifa trilho cheia — sem integração ônibus na janela){sufixo_fonte} {status_icon}")
                        memoria.append(f"Trecho {idx+1} ({nome}): trilho {operadora} tarifa cheia R$ {custo_leg:.2f} — janela sem ônibus SPTrans prévio, sem integração. Fonte: {fonte}.")
                        janela_custo_pago += custo_leg
                        janela_embarques += 1
                        janela_tipos.append(tipo)

            elif tipo == "EMTU":
                if not dentro_janela:
                    custo_leg = round(tarifa_base, 2)
                    janela_inicio_min = elapsed
                    janela_embarques = 1
                    janela_custo_pago = custo_leg
                    janela_tipos = [tipo]
                    detalhamento.append(f"Trecho {idx+1}: {nome} ({operadora} {codigo}) — R$ {custo_leg:.2f} (Tarifa EMTU cheia){sufixo_fonte} {status_icon}")
                    mem_extra = "" if confirmada else " — ⚠️ confirmar tarifa oficial da linha"
                    memoria.append(f"Trecho {idx+1} ({nome}): EMTU {operadora} tarifa cheia R$ {custo_leg:.2f} — nova janela. Fonte: {fonte}.{mem_extra}")
                else:
                    has_trilho = "TRILHO" in janela_tipos
                    if has_trilho:
                        custo_leg = round(max(tarifa_base - cfg.desconto_emtu_trilho, 0), 2)
                        detalhamento.append(f"Trecho {idx+1}: {nome} ({operadora} {codigo}) — R$ {custo_leg:.2f} (Integração TOP/EMTU — desconto R$ {cfg.desconto_emtu_trilho:.2f}){sufixo_fonte} {status_icon}")
                        memoria.append(f"Trecho {idx+1} ({nome}): EMTU {operadora} com integração TOP — R$ {tarifa_base:.2f} - R$ {cfg.desconto_emtu_trilho:.2f} = R$ {custo_leg:.2f} (trilho prévio na janela). Fonte: {fonte}.")
                        janela_custo_pago += custo_leg
                        janela_embarques += 1
                        janela_tipos.append(tipo)
                    else:
                        custo_leg = round(tarifa_base, 2)
                        detalhamento.append(f"Trecho {idx+1}: {nome} ({operadora} {codigo}) — R$ {custo_leg:.2f} (Tarifa EMTU — sem integração trilho na janela){sufixo_fonte} {status_icon}")
                        memoria.append(f"Trecho {idx+1} ({nome}): EMTU {operadora} tarifa cheia R$ {custo_leg:.2f} — sem trilho na janela, sem desconto TOP. Fonte: {fonte}.")
                        janela_custo_pago += custo_leg
                        janela_embarques += 1
                        janela_tipos.append(tipo)
            else:  # OUTRO
                custo_leg = round(tarifa_base, 2)
                if not dentro_janela:
                    janela_inicio_min = elapsed
                    janela_embarques = 1
                    janela_custo_pago = custo_leg
                    janela_tipos = [tipo]
                else:
                    janela_custo_pago += custo_leg
                    janela_embarques += 1
                    janela_tipos.append(tipo)
                detalhamento.append(f"Trecho {idx+1}: {nome} ({operadora} {codigo}) — R$ {custo_leg:.2f} (Tarifa cheia){sufixo_fonte} {status_icon}")
                memoria.append(f"Trecho {idx+1} ({nome}): tarifa cheia R$ {custo_leg:.2f} (tipo OUTRO). Fonte: {fonte}.")

            custo_trecho += custo_leg
            detalhes.append(
                {
                    "linha": nome,
                    "codigo_linha": codigo,
                    "operadora": operadora,
                    "valor_unitario": round(custo_leg, 2),
                    "valor_base": round(tarifa_base, 2),
                    "quantidade_dia": 2,
                    "subtotal": round(custo_leg * 2, 2),
                    "tipo": tipo,
                    "fonte": fonte,
                    "tarifa_confirmada": confirmada,
                }
            )

        custo_trecho = round(custo_trecho, 2)
        custo_diario = round(custo_trecho * 2, 2)
        custo_mensal = round(custo_diario * dias_uteis, 2)

        # alerta de tarifas não confirmadas no topo da memória
        if alertas:
            memoria.insert(0, f"⚠️ Atenção: {len(alertas)} linha(s) com tarifa estimada (não catalogada): " + "; ".join(alertas) + ". Confirmar valor oficial junto à operadora/ARTESP.")

        memoria.insert(
            0,
            f"Cálculo por trecho (1 sentido): R$ {custo_trecho:.2f} | Diário (ida+volta x2): R$ {custo_diario:.2f} | Mensal ({dias_uteis}d): R$ {custo_mensal:.2f}. Janela BU {cfg.janela_minutos}min / {cfg.max_embarques_bu} embarques; teto integração ônibus+trilho R$ {cfg.tarifa_integracao_onibus_trilho:.2f}. Catálogo RMSP {catalogo.get('versao','—')} ({catalogo.get('fonte','—')[:60]})",
        )
        justificativa = (
            f"Custo por trecho R$ {custo_trecho:.2f} com regras Bilhete Único ({cfg.janela_minutos}min/{cfg.max_embarques_bu} embarques) "
            f"e integração ônibus-trilho teto R$ {cfg.tarifa_integracao_onibus_trilho:.2f}; "
            f"EMTU preservada com desconto TOP R$ {cfg.desconto_emtu_trilho:.2f} quando integrada ao trilho. "
            f"Diário x2 e mensal x{dias_uteis}. {f'{len(alertas)} tarifa(s) estimada(s) — confirmar.' if alertas else 'Tarifas oficiais por linha/operadora aplicadas.'}"
        )

        return {
            "sucesso": True,
            "custo_trecho": custo_trecho,
            "custo_diario": custo_diario,
            "custo_mensal": custo_mensal,
            "detalhamento_tarifario": detalhamento,
            "detalhes": detalhes,
            "memoria_calculo": memoria,
            "justificativa": justificativa,
            "dias_uteis": dias_uteis,
            "alertas_tarifa": alertas,
            "catalogo_versao": catalogo.get("versao"),
        }

    except Exception as exc:
        return {
            "sucesso": False,
            "erro": str(exc),
            "memoria_calculo": [f"Falha no cálculo de tarifa: {exc}"],
            "justificativa": "Erro inesperado ao aplicar regras de integração.",
        }


def comparar_rotas(
    itinerarios: list[dict],
    dias_uteis: int = 22,
    config: FareConfig | dict | None = None,
) -> dict:
    """Compara itinerários e retorna rota mais rápida e mais econômica.

    Filtra a econômica por ``caminhada_total_km <= 1.5`` e ``baldeações <= 3``
    (parametrizáveis via .env). Se a mais rápida já for a mais barata elegível,
    ``rota_mais_economica`` replica a rápida com ``economia_mensal = 0``.
    Só retorna ``rota_mais_economica = None`` quando **nenhuma** rota respeita
    os limites de economicidade.

    Args:
        itinerarios: Lista de itinerários, cada um com ``legs`` (lista),
            ``duracao_total_min`` ou ``duracao_min`` ou ``tempo_min``,
            ``caminhada_km``/``caminhada_total_km``/``walk_distance``,
            ``baldeacoes``/``num_baldeacoes``, ``distancia_km``, ``resumo_trajeto``.
        dias_uteis: Dias úteis para cálculo mensal.
        config: FareConfig/dict para tarifas e limites.

    Returns:
        dict: ``{"sucesso": bool, "rota_mais_rapida": dict|None,
            "rota_mais_economica": dict|None, "economia_mensal": float,
            "memoria_calculo": list[str], "justificativa": str}``
            Em falha (sem itinerários ou OTP offline) ``{"sucesso": False, ...}``.
    """
    try:
        cfg = _resolve_config(config)
        if not isinstance(dias_uteis, int) or dias_uteis < 1:
            dias_uteis = 22
        if dias_uteis > 31:
            dias_uteis = 31

        if not itinerarios or not isinstance(itinerarios, list) or len(itinerarios) == 0:
            return {
                "sucesso": False,
                "erro": "Nenhum itinerário disponível para comparação (OTP possivelmente offline).",
                "memoria_calculo": ["Comparação indisponível: lista de itinerários vazia — usar estimativa de contingência."],
                "justificativa": "Sem itinerários não é possível comparar economicidade.",
                "rota_mais_rapida": None,
                "rota_mais_economica": None,
                "economia_mensal": 0.0,
            }

        avaliados: list[dict] = []
        for idx, itin in enumerate(itinerarios):
            legs = itin.get("legs") or itin.get("linhas") or []
            caminhada = itin.get("caminhada_km")
            if caminhada is None:
                caminhada = itin.get("caminhada_total_km", itin.get("walk_km", itin.get("walk_distance_km", 0)))
                if caminhada is None and "legs" in itin:
                    try:
                        caminhada = sum(float(l.get("distance") or 0) for l in itin.get("legs", []) if str(l.get("mode", "")).upper() == "WALK") / 1000
                    except Exception:
                        caminhada = 0
            try:
                caminhada = float(caminhada or 0)
            except Exception:
                caminhada = 0.0

            baldeacoes = itin.get("baldeacoes")
            if baldeacoes is None:
                baldeacoes = itin.get("num_baldeacoes", itin.get("baldeacoes_total", itin.get("transfers", 0)))
            try:
                baldeacoes = int(baldeacoes or 0)
            except Exception:
                baldeacoes = max(len([l for l in legs if l.get("route")]) - 1, 0)

            duracao = itin.get("duracao_total_min")
            if duracao is None:
                duracao = itin.get("duracao_min", itin.get("tempo_min", itin.get("duration_min", itin.get("duracao", 0))))
            try:
                duracao = int(round(float(duracao or 0)))
            except Exception:
                duracao = 0
            if duracao == 0 and legs:
                duracao = sum(_duracao_leg(l) for l in legs)

            distancia = itin.get("distancia_km", itin.get("distancia", 0))
            try:
                distancia = round(float(distancia or 0), 2)
            except Exception:
                distancia = 0.0

            res_custo = calcular_custo_com_integracao(legs, dias_uteis=dias_uteis, config=cfg)
            if not res_custo.get("sucesso"):
                res_custo = {
                    "sucesso": True,
                    "custo_trecho": round(len([l for l in legs if l.get("route") or l.get("linha")]) * cfg.tarifa_padrao, 2),
                    "custo_diario": 0,
                    "custo_mensal": 0,
                    "detalhamento_tarifario": [f"Trecho {i+1}: {_nome_leg(l, i)} — R$ {cfg.tarifa_padrao:.2f} (Estimativa)" for i, l in enumerate(legs)],
                    "detalhes": [],
                    "memoria_calculo": [f"Itinerário {idx+1}: fallback tarifa padrão R$ {cfg.tarifa_padrao:.2f} por trecho."],
                    "justificativa": "Fallback sem integração.",
                }
                res_custo["custo_diario"] = round(res_custo["custo_trecho"] * 2, 2)
                res_custo["custo_mensal"] = round(res_custo["custo_diario"] * dias_uteis, 2)

            avaliados.append(
                {
                    "indice": idx,
                    "legs": legs,
                    "distancia_km": distancia,
                    "duracao_min": duracao,
                    "caminhada_km": round(caminhada, 2),
                    "baldeacoes": baldeacoes,
                    "resumo_trajeto": itin.get("resumo_trajeto", itin.get("resumo", "")),
                    "fonte": itin.get("fonte", "OTP"),
                    **res_custo,
                }
            )

        rota_mais_rapida = min(avaliados, key=lambda x: (x["duracao_min"] if x["duracao_min"] > 0 else 9999, x["custo_trecho"]))

        elegiveis = [a for a in avaliados if a["caminhada_km"] <= cfg.max_caminhada_km + 1e-9 and a["baldeacoes"] <= cfg.max_baldeacoes]

        memoria_comp: list[str] = []
        memoria_comp.append(
            f"Comparativo com {len(avaliados)} itinerário(s); filtro econômica: caminhada <= {cfg.max_caminhada_km} km e baldeações <= {cfg.max_baldeacoes}."
        )
        for a in avaliados:
            eleg = "elegível" if a in elegiveis else "inelegível"
            memoria_comp.append(
                f"Itinerário {a['indice']+1}: {a['duracao_min']}min, {a['caminhada_km']}km caminhada, {a['baldeacoes']} baldeações, custo trecho R$ {a['custo_trecho']:.2f} — {eleg}."
            )

        if not elegiveis:
            justificativa = (
                f"Nenhuma rota respeita os limites de economicidade (caminhada <= {cfg.max_caminhada_km} km, baldeações <= {cfg.max_baldeacoes}); "
                f"rota mais rápida mantida como referência sem opção econômica."
            )
            return {
                "sucesso": True,
                "rota_mais_rapida": rota_mais_rapida,
                "rota_mais_economica": None,
                "economia_mensal": 0.0,
                "memoria_calculo": memoria_comp + [justificativa],
                "justificativa": justificativa,
            }

        rota_mais_economica = min(elegiveis, key=lambda x: (x["custo_trecho"], x["duracao_min"]))

        if rota_mais_rapida in elegiveis and rota_mais_rapida["custo_trecho"] <= rota_mais_economica["custo_trecho"] + 1e-9:
            if rota_mais_rapida["indice"] == rota_mais_economica["indice"] or abs(rota_mais_rapida["custo_trecho"] - rota_mais_economica["custo_trecho"]) < 1e-9:
                rota_mais_economica = rota_mais_rapida
                economia = 0.0
                justificativa = "Rota mais rápida já é a mais econômica elegível — economia mensal R$ 0,00."
                memoria_comp.append(justificativa)
                return {
                    "sucesso": True,
                    "rota_mais_rapida": rota_mais_rapida,
                    "rota_mais_economica": rota_mais_economica,
                    "economia_mensal": round(economia, 2),
                    "memoria_calculo": memoria_comp,
                    "justificativa": justificativa,
                }

        economia = round(rota_mais_rapida.get("custo_mensal", 0) - rota_mais_economica.get("custo_mensal", 0), 2)
        if economia < 0:
            economia = 0.0
        justificativa = (
            f"Rota econômica (R$ {rota_mais_economica['custo_trecho']:.2f}/trecho) vs rápida (R$ {rota_mais_rapida['custo_trecho']:.2f}/trecho); "
            f"economia mensal R$ {economia:.2f} em {dias_uteis} dias."
        )
        memoria_comp.append(justificativa)

        return {
            "sucesso": True,
            "rota_mais_rapida": rota_mais_rapida,
            "rota_mais_economica": rota_mais_economica,
            "economia_mensal": economia,
            "memoria_calculo": memoria_comp,
            "justificativa": justificativa,
        }

    except Exception as exc:
        return {
            "sucesso": False,
            "erro": str(exc),
            "memoria_calculo": [f"Falha na comparação de rotas: {exc}"],
            "justificativa": "Erro inesperado ao comparar rotas.",
            "rota_mais_rapida": None,
            "rota_mais_economica": None,
            "economia_mensal": 0.0,
        }
