import io
import os
import sys
import time
import traceback
from datetime import datetime

# Garante que `src` seja importável quando executado via `streamlit run src/app.py`
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import requests
import streamlit as st
import pandas as pd

from src.services.benefit_calculator import analisar_viabilidade_clt, parse_salario_brasileiro
from src.services.calendar_engine import calcular_dias_uteis
from src.services.export_formatter import gerar_export_compra, gerar_export_rubrica
from src.services.geocoding import buscar_coordenadas_por_cep_ou_endereco
from src.services.map_generator import gerar_imagem_mapa_rota
from src.services.pdf_generator import gerar_pdf_evidencia
from src.services.routing import (
    calcular_vale_combustivel,
    calcular_vale_transporte,
    roteirizar_com_comparativo,
    roteirizar_vale_transporte_automatico,
)


# -----------------------------------------------------------------------------
# Configuração inicial e estilos
# -----------------------------------------------------------------------------
def _inject_css():
    st.markdown(
        """
        <style>
        /* Reset layout */
        .block-container { padding-top: 1.2rem !important; padding-bottom: 1rem !important; }
        /* Header moderno */
        .smartpass-header {
            background: linear-gradient(135deg, #1E3A8A 0%, #3B82F6 55%, #06B6D4 100%);
            color: white; padding: 1.4rem 1.6rem; border-radius: 16px;
            margin-bottom: 1rem; box-shadow: 0 8px 24px rgba(30,58,138,0.25);
        }
        .smartpass-header h1 { margin: 0; font-size: 1.7rem; font-weight: 800; letter-spacing: -0.02em; }
        .smartpass-header p { margin: 0.25rem 0 0 0; opacity: 0.92; font-size: 0.95rem; }
        /* Cards métricas */
        div[data-testid="stMetric"] {
            background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 14px;
            padding: 12px 14px; box-shadow: 0 2px 8px rgba(15,23,42,0.06);
        }
        div[data-testid="stMetric"] label { font-weight: 600 !important; color: #475569 !important; }
        /* Sidebar form */
        section[data-testid="stSidebar"] { background: #F8FAFC; }
        /* Tabs */
        button[data-baseweb="tab"] { font-weight: 600; }
        /* Expander */
        div[data-testid="stExpander"] { border-radius: 12px; }
        /* Dataframe container */
        </style>
        """,
        unsafe_allow_html=True,
    )


def _init_session():
    now = datetime.now()
    defaults = {
        "resultado": None,
        "resultado_vc": None,
        "resultado_vt": None,
        "coords": None,
        "origem_label": "",
        "destino_label": "",
        "modalidade": "Vale-Transporte",
        "dias_uteis": 22,
        "tarifa": 5.00,
        "valor_km": 1.25,
        "salario_base": 0.0,
        "pdf_buffer": None,
        "ultimo_calculo_em": None,
        "batch_df": None,
        "batch_resultados": None,
        "comparativo": None,
        "rota_selecionada": "economica",
        "escala": "5x2",
        "uf_destino": "SP",
        "municipio_destino": "São Paulo",
        "ano_ref": now.year,
        "mes_ref": now.month,
        "dias_override": None,
        "memoria_calendario": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _estimar_tempo_minutos(distancia_km: float, modalidade: str, baldeacoes: int = 0) -> int:
    """Heurística de tempo para exibir nos cards."""
    try:
        if "Combust" in modalidade:
            # 28 km/h médio urbano
            minutos = (distancia_km / 28.0) * 60
        else:
            # Transporte público ~ 18 km/h + 6 min por baldeação
            minutos = (distancia_km / 18.0) * 60 + baldeacoes * 6
        return max(int(round(minutos)), 5)
    except Exception:
        return 0


def _format_tempo(minutos: int) -> str:
    if minutos <= 0:
        return "—"
    h, m = divmod(minutos, 60)
    if h == 0:
        return f"{m} min"
    return f"{h}h {m}min"


def _verificar_postgres():
    """Checa se PostgreSQL/PostGIS está online."""
    try:
        from src.database.connection import get_db_connection

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.fetchone()
        # Tenta verificar PostGIS
        postgis_ok = False
        postgis_ver = None
        try:
            cur.execute("SELECT PostGIS_Version();")
            row = cur.fetchone()
            if row:
                postgis_ver = row[0]
                postgis_ok = True
        except Exception:
            postgis_ok = False
        cur.close()
        return {"sucesso": True, "postgis": postgis_ok, "versao": postgis_ver}
    except Exception as exc:
        return {"sucesso": False, "erro": str(exc), "postgis": False, "versao": None}


def _verificar_otp():
    """Checa se OTP GraphQL está online."""
    url = os.getenv("OTP_GRAPHQL_URL", "http://localhost:8080/otp/gtfs/v1")
    try:
        # Introspection mínima — qualquer 200 indica serviço ativo
        resp = requests.post(
            url,
            json={"query": "{ __typename }"},
            timeout=5,
        )
        if resp.status_code == 200:
            # Se retornou JSON com data, está online
            try:
                js = resp.json()
                if "data" in js or "errors" in js:
                    return {"sucesso": True, "url": url, "status": resp.status_code}
                return {"sucesso": True, "url": url, "status": resp.status_code}
            except Exception:
                return {"sucesso": True, "url": url, "status": resp.status_code}
        return {"sucesso": False, "url": url, "status": resp.status_code, "erro": f"HTTP {resp.status_code}"}
    except Exception as exc:
        return {"sucesso": False, "url": url, "erro": str(exc)}


def _recalcular_vt_com_parametros(resultado_vt: dict, tarifa: float | None, dias_uteis: int) -> dict:
    """Recalcula custo VT com tarifa override quando informado (compat legada).

    Se tarifa é None ou 0, mantém tarifas oficiais por linha/operadora (catálogo RMSP + GTFS).
    Quando tarifa >0, aplica override RH (convênio) com trilha auditável.
    """
    if not resultado_vt or not resultado_vt.get("sucesso"):
        return resultado_vt
    # Sem override: preserva tarifas oficiais do motor (fare_engine/transit_api)
    if tarifa is None or float(tarifa) <= 0:
        # apenas ajusta mensal pelos dias úteis reais sem sobrescrever tarifa
        if dias_uteis and resultado_vt.get("custo_diario") is not None:
            novo = dict(resultado_vt)
            novo["custo_mensal"] = round(float(resultado_vt["custo_diario"]) * int(dias_uteis), 2)
            novo["dias_uteis"] = int(dias_uteis)
            return novo
        return resultado_vt
    linhas = resultado_vt.get("detalhes") or []
    if not linhas:
        linhas_src = resultado_vt.get("linhas") or [{"linha": "Transporte público", "valor_unitario": float(tarifa), "quantidade_dia": 2}]
    else:
        linhas_src = [{"linha": d.get("linha", "Linha"), "valor_unitario": float(tarifa), "quantidade_dia": d.get("quantidade_dia", 2)} for d in linhas]

    recalc = calcular_vale_transporte(linhas_src)
    recalc["custo_mensal"] = round(recalc["custo_diario"] * dias_uteis, 2)
    novo = {**resultado_vt, **recalc}
    novo["detalhes"] = recalc["detalhes"]
    # trilha auditável do override
    novo["override_tarifa"] = float(tarifa)
    novo["memoria_calculo"] = (resultado_vt.get("memoria_calculo") or []) + [f"Override RH: tarifa unitária R$ {float(tarifa):.2f} aplicada a todos os trechos (convênio)"]
    return novo


def _processar_calculo(origem_txt, destino_txt, modalidade, dias_uteis, tarifa_override, valor_km):
    """Executa geocodificação + roteirização conforme modalidade."""
    # Geocodificação (cacheada)
    res_geo_origem = buscar_coordenadas_por_cep_ou_endereco(origem_txt)
    res_geo_destino = buscar_coordenadas_por_cep_ou_endereco(destino_txt)

    # Validação
    if not res_geo_origem.get("sucesso"):
        return {"sucesso": False, "erro": f"Origem não localizada: {res_geo_origem.get('erro')}"}, None, None, None, None
    if not res_geo_destino.get("sucesso"):
        return {"sucesso": False, "erro": f"Destino não localizado: {res_geo_destino.get('erro')}"}, None, None, None, None

    lat_o, lon_o = res_geo_origem["lat"], res_geo_origem["lon"]
    lat_d, lon_d = res_geo_destino["lat"], res_geo_destino["lon"]
    endereco_origem = res_geo_origem.get("endereco_encontrado", origem_txt)
    endereco_destino = res_geo_destino.get("endereco_encontrado", destino_txt)
    coords = (lat_o, lon_o, lat_d, lon_d)

    resultado_vt = None
    resultado_vc = None
    comparativo = None

    if modalidade in ("Vale-Transporte", "Comparativo Completo"):
        vt_raw = roteirizar_vale_transporte_automatico(lat_o, lon_o, lat_d, lon_d, endereco_origem, endereco_destino)
        # Só recalcula se houver override RH; caso contrário preserva tarifa oficial por linha
        resultado_vt = _recalcular_vt_com_parametros(vt_raw, tarifa_override, dias_uteis)
        # Motor fare_engine: comparativo econômica vs rápida (com integração temporal)
        try:
            comp_raw = roteirizar_com_comparativo(lat_o, lon_o, lat_d, lon_d, dias_uteis=int(dias_uteis))
            if comp_raw.get("sucesso") and comp_raw.get("comparativo"):
                comparativo = comp_raw["comparativo"]
                # Anexa fonte/distância do comparativo ao VT para auditoria
                if comparativo.get("rota_mais_rapida"):
                    resultado_vt["comparativo"] = comparativo
                    resultado_vt["fonte_comparativo"] = comp_raw.get("fonte")
        except Exception:
            comparativo = None

    if modalidade in ("Vale-Combustível", "Comparativo Completo"):
        vc_raw = calcular_vale_combustivel(lat_o, lon_o, lat_d, lon_d, valor_km)
        if vc_raw.get("sucesso"):
            # Para cards: custo diário = ida+volta, mensal = diário * dias
            diario = round(vc_raw["distancia_km"] * valor_km * 2, 2)
            mensal = round(diario * dias_uteis, 2)
            resultado_vc = {
                **vc_raw,
                "custo_diario": diario,
                "custo_mensal": mensal,
                "valor_km": valor_km,
                "origem": endereco_origem,
                "destino": endereco_destino,
            }
        else:
            resultado_vc = vc_raw

    # Resultado consolidado para os cards (prioriza VT se existir)
    if modalidade == "Vale-Transporte":
        principal = resultado_vt
    elif modalidade == "Vale-Combustível":
        principal = resultado_vc
    else:
        # Comparativo: mantém ambos, principal = VT para métricas padrão (usuário verá comparação na tab)
        principal = resultado_vt or resultado_vc

    # Enriquecer com labels e aviso
    return (
        {"sucesso": True, "principal": principal, "vt": resultado_vt, "vc": resultado_vc, "comparativo": comparativo},
        coords,
        endereco_origem,
        endereco_destino,
        (res_geo_origem, res_geo_destino),
    )


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    st.set_page_config(
        page_title="SmartPass — Cálculo de Benefícios",
        page_icon="🚌",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_css()
    _init_session()

    # Header moderno
    st.markdown(
        """
        <div class="smartpass-header">
            <h1>🚌 SmartPass — Cálculo Inteligente de Benefícios</h1>
            <p>Roteirização com OpenTripPlanner (GTFS) + PostGIS &nbsp;•&nbsp; Stateless & LGPD — dados apenas em memória</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ===================== SIDEBAR — Painel de Simulação =====================
    with st.sidebar:
        st.markdown("### 🎛️ Painel de Simulação")
        st.caption("Preencha os dados e clique em **Calcular**. Nenhum dado é gravado — tudo permanece em memória.")

        with st.form("form_simulacao", clear_on_submit=False):
            st.markdown("**Origem e Destino**")
            origem_input = st.text_input(
                "Origem (CEP ou endereço)",
                value=st.session_state.get("origem_label") or "06310-000",
                placeholder="Ex: 06310-000 ou Av. Paulista, 1000",
                help="CEP com 8 dígitos ou endereço completo. Geocodificação via ViaCEP + Nominatim.",
            )
            destino_input = st.text_input(
                "Destino (CEP ou endereço)",
                value=st.session_state.get("destino_label") or "Avenida Paulista, 1000, São Paulo",
                placeholder="Ex: 04538-132 ou Rua Funchal, 418",
            )

            st.markdown("**Modalidade**")
            modalidade_input = st.selectbox(
                "Modalidade",
                options=["Vale-Transporte", "Vale-Combustível", "Comparativo Completo"],
                index=["Vale-Transporte", "Vale-Combustível", "Comparativo Completo"].index(st.session_state.modalidade)
                if st.session_state.modalidade in ["Vale-Transporte", "Vale-Combustível", "Comparativo Completo"]
                else 0,
                help="Comparativo exibe VT e VC lado a lado para decisão de RH.",
            )

            st.markdown("**Parâmetros de Cálculo**")
            # Calendário por escala/município — cálculo exato de dias úteis
            st.markdown("*Calendário — escala e município da unidade*")
            esc_opts = ["5x2", "6x1", "12x36", "Híbrido (3x2)"]
            esc_default = st.session_state.get("escala", "5x2")
            # normaliza label
            if esc_default.lower().replace(" ", "") in ["hibrido(3x2)", "hibrido", "3x2"]:
                esc_default = "Híbrido (3x2)"
            escala_input = st.selectbox(
                "Escala",
                options=esc_opts,
                index=esc_opts.index(esc_default) if esc_default in esc_opts else 0,
                help="5x2 Seg-Sex | 6x1 folga domingo | 12x36 dia 1 trabalhado | Híbrido 3x2 Seg-Qua presenciais. Desconta feriados nacionais (inclui 20/11 Lei 14.759/2023) + municipais Grande SP.",
            )
            c_uf, c_mun = st.columns(2)
            with c_uf:
                uf_opts = ["SP", "RJ", "MG", "Outro"]
                uf_cur = str(st.session_state.get("uf_destino", "SP")).upper()
                if uf_cur not in uf_opts:
                    uf_cur = "SP"
                uf_input = st.selectbox("UF unidade", options=uf_opts, index=uf_opts.index(uf_cur))
            with c_mun:
                mun_opts = ["São Paulo", "Carapicuíba", "Osasco", "Barueri", "Cotia", "Alphaville", "Outro"]
                mun_cur = str(st.session_state.get("municipio_destino", "São Paulo"))
                if mun_cur not in mun_opts:
                    mun_cur = "São Paulo"
                municipio_input = st.selectbox("Município unidade (Grande SP)", options=mun_opts, index=mun_opts.index(mun_cur), help="Municipal: SP 25/01, Carapicuíba 26/03, Osasco 19/02, Barueri 11/03 (Alphaville), Cotia 02/04.")
            c_ano, c_mes = st.columns(2)
            with c_ano:
                ano_input = st.number_input("Ano competência", min_value=2020, max_value=2100, value=int(st.session_state.get("ano_ref", datetime.now().year)), step=1)
            with c_mes:
                mes_input = st.number_input("Mês competência", min_value=1, max_value=12, value=int(st.session_state.get("mes_ref", datetime.now().month)), step=1)
            dias_override_input = st.number_input(
                "Override dias úteis (opcional)",
                min_value=0, max_value=31, value=0, step=1,
                help="0 = cálculo automático por escala/feriados. Informe 1-31 para sobrescrever manualmente (auditoria).",
            )
            # Preview do cálculo (sem cache — puro)
            try:
                _dias_override_preview = int(dias_override_input) if int(dias_override_input) > 0 else None
                _prev = calcular_dias_uteis(int(ano_input), int(mes_input), escala_input, uf_input, municipio_input, dias_override=_dias_override_preview)
                if _prev.get("sucesso"):
                    st.caption(f"📅 Dias úteis calculados: **{int(_prev['dias_uteis'])}** ({int(_prev['dias_brutos'])} brutos - {len(_prev.get('feriados_descontados', []))} feriados) — {escala_input} {int(mes_input):02d}/{int(ano_input)} {uf_input}/{municipio_input}" + (" — override manual" if _prev.get("dias_override_aplicado") else ""))
                else:
                    st.caption(f"⚠️ {_prev.get('erro','Falha no calendário')}")
            except Exception:
                pass
            c1, c2 = st.columns(2)
            with c1:
                dias_input_hidden = st.number_input("Dias úteis (fallback)", min_value=1, max_value=31, value=int(st.session_state.dias_uteis), step=1, help="Usado apenas se calendário falhar. Normalmente use o override acima.")
                dias_input = dias_input_hidden
            with c2:
                st.caption("Tarifa oficial por linha/operadora aplicada automaticamente via catálogo RMSP + GTFS.")
            # Override opcional (avançado) — fora do fluxo obrigatório
            with st.expander("⚙️ Tarifa diferenciada / convênio (opcional)", expanded=False):
                st.caption("Deixe 0 para usar tarifas oficiais por linha (recomendado). Informe valor apenas se o RH tiver convênio/tarifa diferenciada.")
                tarifa_input = st.number_input(
                    "Override tarifa unitária (R$) — 0 = oficial",
                    min_value=0.0,
                    value=float(st.session_state.get("tarifa", 0.0) or 0.0),
                    step=0.10,
                    format="%.2f",
                    help="Quando >0, sobrescreve todas as tarifas oficiais com trilha auditável. 0 mantém catálogo RMSP.",
                )
            valor_km_input = st.number_input(
                "Valor por KM — Vale-Combustível (R$)",
                min_value=0.0,
                value=float(st.session_state.valor_km),
                step=0.05,
                format="%.2f",
                help="Aplicado apenas em VC e Comparativo. Ex: R$ 1,25/km",
            )
            salario_base_input = st.number_input(
                "Salário Base (R$) — opcional (Lei 7.418/85)",
                min_value=0.0,
                value=float(st.session_state.get("salario_base", 0.0)),
                step=100.0,
                format="%.2f",
                help="Se 0 = não informado. Quando preenchido, calcula teto 6% e rateio Empresa vs Colaborador. Dado mantido só em st.session_state (LGPD stateless).",
            )

            st.markdown("")
            submitted = st.form_submit_button("🔍 Calcular Rota e Benefício", width='stretch', type="primary")

        # Ações de limpeza
        if st.button("🧹 Limpar Simulação", width='stretch'):
            for k in ["resultado", "resultado_vt", "resultado_vc", "coords", "pdf_buffer", "batch_df", "batch_resultados", "comparativo", "memoria_calendario"]:
                st.session_state[k] = None
            st.session_state["rota_selecionada"] = "economica"
            st.session_state["ultimo_calculo_em"] = None
            st.session_state["salario_base"] = 0.0
            st.session_state["dias_override"] = None
            st.rerun()

        st.divider()

        # Expander — Simulação em lote (em memória)
        with st.expander("📦 Simulação em Lote (CSV / Excel)", expanded=False):
            st.caption("Faça upload de uma planilha com colunas **origem** e **destino** (e opcionalmente **nome**). Tudo em memória — nada é gravado.")
            arquivo_lote = st.file_uploader(
                "Arraste CSV ou XLSX",
                type=["csv", "xlsx", "xls"],
                label_visibility="collapsed",
            )
            if arquivo_lote is not None:
                try:
                    # Leitura em memória
                    nome_arq = arquivo_lote.name.lower()
                    if nome_arq.endswith(".csv"):
                        # Tenta utf-8 e latin1
                        try:
                            df = pd.read_csv(arquivo_lote)
                        except UnicodeDecodeError:
                            arquivo_lote.seek(0)
                            df = pd.read_csv(arquivo_lote, encoding="latin-1")
                    else:
                        df = pd.read_excel(arquivo_lote)

                    # Normaliza colunas
                    df.columns = [str(c).strip().lower() for c in df.columns]
                    st.session_state.batch_df = df
                    st.success(f"Arquivo carregado: **{len(df)}** colaborador(es).")
                    st.dataframe(df.head(10), width='stretch', height=220)

                    # Botão de processamento em lote (usa mesma lógica de cálculo)
                    if st.button("▶️ Processar Lote (estimativa)", width='stretch'):
                        progresso = st.progress(0)
                        resultados_lote = []
                        for idx, row in df.iterrows():
                            # Detecta colunas origem/destino de forma flexível
                            origem_lote = row.get("origem") or row.get("endereco") or row.get("cep_origem") or row.get("residencia")
                            destino_lote = row.get("destino") or row.get("empresa") or row.get("cep_destino") or row.get("unidade")
                            if pd.isna(origem_lote) or pd.isna(destino_lote):
                                resultados_lote.append({"linha": idx + 1, "origem": str(origem_lote), "destino": str(destino_lote), "erro": "Origem/Destino ausente", "nivel_precisao": "BAIXA", "semaforo": "🔴 Revisar Endereço", "motivo_precisao": "Origem/Destino ausente — revisão obrigatória"})
                                continue
                            # Detecta salario_base opcional (aliases + sanitização BR)
                            salario_raw_lote = None
                            for cand in ["salario_base", "salario", "salario base", "salary", "salario_base_r$"]:
                                if cand in df.columns:
                                    salario_raw_lote = row.get(cand)
                                    break
                            salario_lote = parse_salario_brasileiro(salario_raw_lote) if salario_raw_lote is not None and not pd.isna(salario_raw_lote) else None
                            # Cálculo simplificado: usa VT
                            try:
                                res_geo_o = buscar_coordenadas_por_cep_ou_endereco(str(origem_lote))
                                res_geo_d = buscar_coordenadas_por_cep_ou_endereco(str(destino_lote))
                                if not res_geo_o.get("sucesso") or not res_geo_d.get("sucesso"):
                                    # Geocodificação falhou — marca como BAIXA para revisão
                                    nivel_falha = "BAIXA"
                                    # tenta extrair motivo de quem falhou
                                    motivo_falha = res_geo_o.get("erro") if not res_geo_o.get("sucesso") else res_geo_d.get("erro", "Geocodificação falhou")
                                    resultados_lote.append({"linha": idx + 1, "origem": str(origem_lote), "destino": str(destino_lote), "erro": "Geocodificação falhou", "nivel_precisao": nivel_falha, "semaforo": "🔴 Revisar Endereço", "motivo_precisao": str(motivo_falha)[:180]})
                                    continue
                                # Semáforo: pior nível entre origem e destino (BAIXA > MEDIA > ALTA)
                                _ordem = {"BAIXA": 3, "MEDIA": 2, "ALTA": 1}
                                nivel_o = res_geo_o.get("nivel_precisao", "MEDIA")
                                nivel_d = res_geo_d.get("nivel_precisao", "MEDIA")
                                nivel_lote = nivel_o if _ordem.get(nivel_o, 0) >= _ordem.get(nivel_d, 0) else nivel_d
                                semaforo_lote = res_geo_o.get("semaforo") if nivel_lote == nivel_o else res_geo_d.get("semaforo")
                                # Motivo combinado para auditoria
                                motivo_o = res_geo_o.get("motivo_precisao", "")
                                motivo_d = res_geo_d.get("motivo_precisao", "")
                                motivo_lote = f"Origem: {motivo_o} | Destino: {motivo_d}" if motivo_o or motivo_d else ""
                                vt = roteirizar_vale_transporte_automatico(
                                    res_geo_o["lat"], res_geo_o["lon"], res_geo_d["lat"], res_geo_d["lon"], str(origem_lote), str(destino_lote)
                                )
                                _tarifa_lote = float(tarifa_input) if float(tarifa_input) > 0 else None
                                vt_adj = _recalcular_vt_com_parametros(vt, _tarifa_lote, int(dias_input))
                                custo_m = vt_adj.get("custo_mensal", 0) or 0
                                viab_lote = analisar_viabilidade_clt(float(custo_m), salario_lote)
                                # status em caixa alta conforme ajuste #2
                                if salario_lote is None or salario_lote <= 0:
                                    status_clt = "NAO_INFORMADO"
                                elif viab_lote.get("vt_vantajoso"):
                                    status_clt = "VANTAJOSO"
                                else:
                                    status_clt = "NAO_VANTAJOSO"
                                resultados_lote.append({
                                    "linha": idx + 1,
                                    "origem": str(origem_lote),
                                    "destino": str(destino_lote),
                                    "distancia_km": vt_adj.get("distancia_km"),
                                    "custo_diario": vt_adj.get("custo_diario"),
                                    "custo_mensal": custo_m,
                                    "fonte": vt_adj.get("fonte"),
                                    "teto_6_pct": viab_lote.get("teto_desconto_6_pct", 0.0),
                                    "desconto_colaborador": viab_lote.get("desconto_colaborador", 0.0),
                                    "subsidio_empresa": viab_lote.get("custeio_empresa", 0.0),
                                    "status_viabilidade_clt": status_clt,
                                })
                            except Exception as exc:
                                resultados_lote.append({"linha": idx + 1, "origem": str(origem_lote), "destino": str(destino_lote), "erro": str(exc), "nivel_precisao": "BAIXA", "semaforo": "🔴 Revisar Endereço", "motivo_precisao": str(exc)[:180]})
                            progresso.progress(int(((idx + 1) / len(df)) * 100))

                        st.session_state.batch_resultados = resultados_lote
                        if resultados_lote:
                            df_res = pd.DataFrame(resultados_lote)
                            # Contadores semáforo no topo do resultado do lote
                            n_alta = int((df_res["nivel_precisao"] == "ALTA").sum()) if "nivel_precisao" in df_res.columns else 0
                            n_media = int((df_res["nivel_precisao"] == "MEDIA").sum()) if "nivel_precisao" in df_res.columns else 0
                            n_baixa = int((df_res["nivel_precisao"] == "BAIXA").sum()) if "nivel_precisao" in df_res.columns else 0
                            c1, c2, c3 = st.columns(3)
                            c1.metric("🟢 Exatos", n_alta, help="ALTA — logradouro + número/CEP específico")
                            c2.metric("🟡 Aproximados", n_media, help="MEDIA — apenas logradouro sem número ou bairro")
                            c3.metric("🔴 Para Revisão", n_baixa, help="BAIXA — fallback centro do município / erro de geocodificação")
                            # Filtro rápido visual (não afeta CSV completo)
                            filtrar_revisao = st.checkbox("Mostrar apenas endereços que exigem revisão (🟡/🔴)", value=False, key="filtro_revisao_lote")
                            if filtrar_revisao:
                                df_exib = df_res[df_res["nivel_precisao"].isin(["MEDIA", "BAIXA"])] if "nivel_precisao" in df_res.columns else df_res
                                if df_exib.empty:
                                    st.info("Nenhum endereço com 🟡/🔴 — todos são 🟢 Exatos.")
                                else:
                                    st.dataframe(df_exib, width='stretch', height=260)
                                    st.caption(f"Exibindo {len(df_exib)} de {len(df_res)} — filtro 🟡/🔴 ativo. O CSV abaixo exporta o lote **completo** ({len(df_res)} linhas).")
                            else:
                                st.dataframe(df_res, width='stretch', height=260)
                            # Download em memória — sempre lote completo com nivel_precisao/semaforo/motivo_precisao
                            csv_buf = io.StringIO()
                            df_res.to_csv(csv_buf, index=False)
                            st.download_button(
                                "⬇️ Baixar resultado do lote (CSV completo)",
                                data=csv_buf.getvalue().encode("utf-8"),
                                file_name=f"smartpass_lote_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                                mime="text/csv",
                                width='stretch',
                            )
                            # --- Exportação padronizada para portais de benefícios (BytesIO, LGPD) ---
                            st.markdown("**Exportação padronizada para portais de benefícios (LGPD — CPF mascarado, BytesIO):**")
                            layout_lote = st.radio(
                                "Selecione o layout",
                                options=["Padrão Compra (SPTrans/TOP)", "Rubrica Folha (eSocial/ERP)"],
                                index=0,
                                horizontal=True,
                                key="layout_lote_radio",
                            )
                            # Determina dias úteis para exportação (usa calendário se disponível)
                            try:
                                _ov_lote = int(dias_override_input) if int(dias_override_input) > 0 else None
                                _cal_lote = calcular_dias_uteis(int(ano_input), int(mes_input), escala_input, uf_input, municipio_input, dias_override=_ov_lote)
                                _dias_export = int(_cal_lote["dias_uteis"]) if _cal_lote.get("sucesso") else int(dias_input_hidden)
                            except Exception:
                                _dias_export = int(st.session_state.get("dias_uteis", 22))
                            comp_export = f"{int(mes_input):02d}/{int(ano_input)}"
                            # Monta dados para export_formatter a partir do lote
                            try:
                                export_rows = []
                                for idx_row, row_orig in df.iterrows():
                                    # tenta recuperar custo do resultado correspondente
                                    res_row = resultados_lote[idx_row] if idx_row < len(resultados_lote) else {}
                                    nome_exp = str(row_orig.get("nome") or row_orig.get("colaborador") or f"Colaborador {idx_row+1}").strip()
                                    cpf_exp = str(row_orig.get("cpf") or row_orig.get("documento") or "00000000000").strip()
                                    mat_exp = str(row_orig.get("matricula") or row_orig.get("mat") or str(idx_row+1).zfill(4)).strip()
                                    operadora_exp = str(row_orig.get("operadora") or "SPTrans").strip()
                                    codigo_linha_exp = str(row_orig.get("codigo_linha") or row_orig.get("linha") or "—").strip()
                                    valor_diario_exp = res_row.get("custo_diario", 0) or 0
                                    # normaliza valor_diario para float/str
                                    try:
                                        valor_diario_exp = float(valor_diario_exp)
                                    except Exception:
                                        valor_diario_exp = 0
                                    salario_exp = row_orig.get("salario_base") or row_orig.get("salario") or None
                                    export_rows.append({
                                        "matricula": mat_exp,
                                        "nome": nome_exp,
                                        "cpf": cpf_exp,
                                        "operadora": operadora_exp,
                                        "codigo_linha": codigo_linha_exp,
                                        "valor_diario": valor_diario_exp,
                                        "salario_base": salario_exp,
                                    })
                                df_export_src = pd.DataFrame(export_rows)
                                if layout_lote == "Padrão Compra (SPTrans/TOP)":
                                    exp_res = gerar_export_compra(df_export_src, dias_uteis=int(_dias_export), competencia=comp_export)
                                else:
                                    exp_res = gerar_export_rubrica(df_export_src, dias_uteis=int(_dias_export), competencia=comp_export)
                                if exp_res.get("sucesso"):
                                    st.caption(f"Layout **{layout_lote}** — {len(export_rows)} registros, {_dias_export} dias úteis, competência {comp_export}. CPF mascarado, utf-8-sig, BytesIO.")
                                    for m in exp_res.get("memoria_calculo", [])[:2]:
                                        st.caption(f"• {m}")
                                    st.download_button(
                                        f"⬇️ Baixar {layout_lote} (CSV utf-8-sig, BytesIO)",
                                        data=exp_res["bytesio"].getvalue(),
                                        file_name=exp_res["filename"],
                                        mime="text/csv",
                                        width='stretch',
                                        key="download_lote_export",
                                    )
                                else:
                                    st.warning(f"Falha no export {layout_lote}: {exp_res.get('erro','')}")
                            except Exception as _exc_exp:
                                st.warning(f"Não foi possível gerar export padronizado: {_exc_exp}")
                        progresso.empty()
                except Exception as exc:
                    st.error(f"Falha ao ler arquivo: {exc}")
            else:
                # Modelo para download — gerado em memória
                st.markdown("**Modelo de planilha:**")
                modelo = pd.DataFrame([
                    {"nome": "Maria Silva", "origem": "06310-000", "destino": "Avenida Paulista, 1000, São Paulo", "salario_base": 2500.00},
                    {"nome": "João Souza", "origem": "04538-132", "destino": "Rua Funchal, 418, São Paulo", "salario_base": 3500.00},
                ])
                buf_modelo = io.StringIO()
                modelo.to_csv(buf_modelo, index=False)
                st.download_button(
                    "📄 Baixar modelo CSV",
                    data=buf_modelo.getvalue().encode("utf-8"),
                    file_name="modelo_smartpass_lote.csv",
                    mime="text/csv",
                    width='stretch',
                )
                st.caption("Colunas obrigatórias: **origem**, **destino**. Opcional: **nome**, **salario_base** (ex: 2500.00 ou R$ 2.500,00). Saída inclui **teto_6_pct, desconto_colaborador, subsidio_empresa, status_viabilidade_clt**.")

        st.divider()
        st.caption("🔒 **LGPD / Stateless:** nenhum dado persiste em banco. PDFs e mapas são gerados em `BytesIO` e mantidos apenas em `st.session_state`.")

    # ===================== PROCESSAMENTO DO FORM =====================
    if submitted:
        # Validação rápida
        if not origem_input.strip() or not destino_input.strip():
            st.toast("Informe origem e destino.", icon="⚠️")
            st.error("Preencha origem e destino para calcular.")
        else:
            # Calcula dias úteis por escala/município (com override)
            try:
                _ov = int(dias_override_input) if int(dias_override_input) > 0 else None
            except Exception:
                _ov = None
            try:
                _cal = calcular_dias_uteis(int(ano_input), int(mes_input), escala_input, uf_input, municipio_input, dias_override=_ov)
                if _cal.get("sucesso"):
                    dias_efetivos = int(_cal["dias_uteis"])
                    memoria_cal = _cal.get("memoria_calculo", [])
                else:
                    dias_efetivos = int(dias_input)
                    memoria_cal = [f"Calendário falhou ({_cal.get('erro','')}) — fallback {dias_efetivos} dias."]
                    _cal = {"sucesso": False, "dias_uteis": dias_efetivos, "memoria_calculo": memoria_cal, "justificativa": "Fallback dias úteis."}
            except Exception as _exc:
                dias_efetivos = int(dias_input)
                memoria_cal = [f"Calendário exceção: {_exc} — fallback {dias_efetivos} dias."]
                _cal = {"sucesso": False, "dias_uteis": dias_efetivos, "memoria_calculo": memoria_cal, "justificativa": "Fallback."}
            with st.spinner("🔎 Geocodificando endereços e roteirizando via OTP/OSRM…"):
                try:
                    tarifa_override = float(tarifa_input) if float(tarifa_input) > 0 else None
                    payload, coords, origem_label, destino_label, geos = _processar_calculo(
                        origem_input.strip(),
                        destino_input.strip(),
                        modalidade_input,
                        int(dias_efetivos),
                        tarifa_override,
                        float(valor_km_input),
                    )
                    if not payload.get("sucesso"):
                        st.error(payload.get("erro", "Falha no cálculo."))
                    else:
                        # Persiste tudo em session_state (stateless)
                        st.session_state.resultado = payload["principal"]
                        st.session_state.resultado_vt = payload["vt"]
                        st.session_state.resultado_vc = payload["vc"]
                        st.session_state.comparativo = payload.get("comparativo")
                        st.session_state.rota_selecionada = "economica"
                        st.session_state.coords = coords
                        st.session_state.origem_label = origem_label
                        st.session_state.destino_label = destino_label
                        st.session_state.modalidade = modalidade_input
                        st.session_state.dias_uteis = int(dias_efetivos)
                        st.session_state.escala = str(escala_input)
                        st.session_state.uf_destino = str(uf_input)
                        st.session_state.municipio_destino = str(municipio_input)
                        st.session_state.ano_ref = int(ano_input)
                        st.session_state.mes_ref = int(mes_input)
                        st.session_state.dias_override = _ov
                        st.session_state.memoria_calendario = _cal
                        st.session_state.tarifa = float(tarifa_input)
                        st.session_state.valor_km = float(valor_km_input)
                        st.session_state.salario_base = float(salario_base_input) if salario_base_input is not None else 0.0
                        st.session_state.ultimo_calculo_em = datetime.now()
                        st.session_state.pdf_buffer = None  # invalida PDF anterior
                        # Feedback
                        if payload["principal"] and payload["principal"].get("sucesso") is False:
                            st.error(payload["principal"].get("erro", "Não foi possível calcular."))
                        else:
                            st.toast("Rota calculada com sucesso!", icon="✅")
                except Exception as exc:
                    st.error(f"Erro inesperado no cálculo: {exc}")
                    with st.expander("Detalhes técnicos"):
                        st.code(traceback.format_exc())

    # ===================== ÁREA PRINCIPAL — Dashboard =====================
    # Métricas no topo
    resultado = st.session_state.resultado
    modalidade_atual = st.session_state.modalidade
    dias_uteis_atual = st.session_state.dias_uteis

    if resultado is None:
        st.info("👈 Preencha o **Painel de Simulação** na lateral e clique em **Calcular Rota e Benefício** para ver o dashboard. Nenhuma chamada é feita até o clique (uso de `st.form`).")
        # Exemplo ilustrativo estático
        st.markdown("#### Exemplo de fluxo")
        st.markdown(
            "- **Origem:** Carapicuíba (CEP 06310-000) → **Destino:** Pinheiros (Av. Faria Lima)  \n"
            "- O sistema geocodifica via **ViaCEP → Nominatim**, roteiriza via **OTP (GTFS)** com fallback OSRM e gera **mapa + PDF em memória**."
        )
        # Placeholder cards vazios para layout estável
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Distância Estimada", "—", help="Preenchido após cálculo")
        c2.metric("Tempo de Deslocamento", "—")
        c3.metric("Custo Diário (Ida + Volta)", "—")
        c4.metric(f"Custo Mensal ({dias_uteis_atual} dias)", "—")

        # Tabs vazias mas visíveis para validação visual
        tab_mapa, tab_pdf, tab_status = st.tabs(["🗺️ Mapa & Itinerário", "📄 Relatório PDF", "⚙️ Status da Infraestrutura"])
        with tab_mapa:
            st.caption("O mapa e o itinerário passo a passo aparecerão aqui após o cálculo.")
            st.image("https://via.placeholder.com/900x300?text=Mapa+aparecer%C3%A1+ap%C3%B3s+calcular+a+rota", use_container_width=True)
        with tab_pdf:
            st.caption("O resumo da memória de cálculo e o botão de download do PDF aparecerão aqui.")
        with tab_status:
            st.caption("Indicadores de saúde da infraestrutura em tempo real.")
            # Renderiza status real mesmo sem cálculo
            col_a, col_b = st.columns(2)
            with col_a:
                pg = _verificar_postgres()
                if pg["sucesso"]:
                    st.success(f"**PostgreSQL:** Online ✅  — `PostGIS: {pg['versao'] or 'detectado'}`")
                else:
                    st.error(f"**PostgreSQL:** Offline / Fallback ⚠️ — {pg.get('erro','indisponível')[:120]}")
            with col_b:
                otp = _verificar_otp()
                if otp["sucesso"]:
                    st.success(f"**OpenTripPlanner (OTP):** Online ✅ — `{otp['url']}`")
                else:
                    st.warning(f"**OTP:** Fallback ativo ⚠️ — {otp.get('erro','offline')[:120]}  — usando estimativa de contingência")
            st.info("O cálculo funciona mesmo em modo fallback (estimativa validada manualmente).")
    else:
        # Extrai métricas do resultado principal
        dist = resultado.get("distancia_km", 0)
        # Baldeações para estimar tempo (VT)
        baldeacoes = 0
        if st.session_state.resultado_vt:
            detalhes_vt = st.session_state.resultado_vt.get("detalhes") or []
            baldeacoes = max(len(detalhes_vt) - 1, 0)
        tempo_min = _estimar_tempo_minutos(float(dist or 0), modalidade_atual, baldeacoes)
        custo_diario = resultado.get("custo_diario") if resultado.get("custo_diario") is not None else resultado.get("custo_total", 0)
        # Para VC, custo_total já é uma perna; mas normalizamos para diário em _processar
        # Garante mensal coerente com dias_uteis
        custo_mensal = resultado.get("custo_mensal")
        if custo_mensal is None and custo_diario is not None:
            custo_mensal = round(float(custo_diario) * int(dias_uteis_atual), 2)

        # Cards de métricas
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("📏 Distância Estimada", f"{dist} km" if dist else "—", delta=None)
        m2.metric("⏱️ Tempo de Deslocamento", _format_tempo(tempo_min), help="Estimativa heurística (OTP não expõe duração nesta versão)")
        m3.metric("💰 Custo Diário (Ida + Volta)", f"R$ {float(custo_diario):.2f}" if custo_diario is not None else "—")
        m4.metric(f"🗓️ Custo Mensal ({dias_uteis_atual} dias)", f"R$ {float(custo_mensal):.2f}" if custo_mensal is not None else "—")
        # Memória calendário — trilha auditável de dias úteis por escala/município
        _cal_mem = st.session_state.get("memoria_calendario")
        if _cal_mem and isinstance(_cal_mem, dict):
            escala_show = _cal_mem.get("escala", st.session_state.get("escala", "5x2"))
            uf_show = _cal_mem.get("uf", st.session_state.get("uf_destino", "SP"))
            mun_show = _cal_mem.get("municipio_destino", st.session_state.get("municipio_destino", "—"))
            st.info(f"📅 **Calendário:** Escala **{escala_show}** • **{uf_show}/{mun_show}** • {int(_cal_mem.get('mes',0)):02d}/{int(_cal_mem.get('ano',0))} • **{int(_cal_mem.get('dias_uteis', dias_uteis_atual))} dias úteis** ({int(_cal_mem.get('dias_brutos',0))} brutos - {len(_cal_mem.get('feriados_descontados',[]))} feriados)" + (" — override manual" if _cal_mem.get("dias_override_aplicado") else ""))
            with st.expander("📋 Memória de cálculo — dias úteis por escala/município", expanded=False):
                for linha in _cal_mem.get("memoria_calculo", []):
                    st.caption(f"• {linha}")
                st.caption(_cal_mem.get("justificativa",""))
                if _cal_mem.get("feriados_descontados"):
                    st.markdown("**Feriados descontados no mês:**")
                    for f in _cal_mem.get("feriados_descontados", []):
                        st.caption(f"• {f['data']} — {f['nome']}")
        # Export individual padronizado (suporte ao fluxo individual)
        if st.session_state.resultado_vt or st.session_state.resultado_vc:
            with st.expander("📤 Exportação individual padronizada (BytesIO, LGPD)", expanded=False):
                _layout_ind = st.radio("Layout", options=["Padrão Compra (SPTrans/TOP)", "Rubrica Folha (eSocial/ERP)"], index=0, horizontal=True, key="layout_individual")
                try:
                    _valor_ind = float(st.session_state.resultado_vt.get("custo_diario", 0) if st.session_state.resultado_vt else st.session_state.resultado_vc.get("custo_diario", 0) or 0)
                    _dados_ind = [{"matricula": "0001", "nome": "Colaborador (simulação)", "cpf": "12345678900", "operadora": "SPTrans", "codigo_linha": "—", "valor_diario": _valor_ind, "salario_base": st.session_state.get("salario_base", 0)}]
                    _comp_ind = f"{int(st.session_state.get('mes_ref', datetime.now().month)):02d}/{int(st.session_state.get('ano_ref', datetime.now().year))}"
                    if _layout_ind == "Padrão Compra (SPTrans/TOP)":
                        _exp_ind = gerar_export_compra(_dados_ind, dias_uteis=int(dias_uteis_atual), competencia=_comp_ind)
                    else:
                        _exp_ind = gerar_export_rubrica(_dados_ind, dias_uteis=int(dias_uteis_atual), competencia=_comp_ind)
                    if _exp_ind.get("sucesso"):
                        st.caption(f"{_exp_ind.get('justificativa','')}")
                        st.download_button("⬇️ Baixar export individual (CSV utf-8-sig)", data=_exp_ind["bytesio"].getvalue(), file_name=_exp_ind["filename"], mime="text/csv", width='stretch', key="download_individual_export")
                    else:
                        st.warning(_exp_ind.get("erro","Falha no export individual"))
                except Exception as _e:
                    st.warning(f"Export individual indisponível: {_e}")

        # Aviso de fallback se houver
        if resultado.get("aviso"):
            st.warning(f"ℹ️ {resultado.get('aviso')} — Fonte: **{resultado.get('fonte','—')}**")
        elif resultado.get("fonte"):
            st.caption(f"Fonte da roteirização: **{resultado.get('fonte')}**  •  Atualizado em {st.session_state.ultimo_calculo_em.strftime('%d/%m/%Y %H:%M') if st.session_state.ultimo_calculo_em else ''}")

        # Comparativo Econômica vs Rápida (fare_engine) — seletor e economia mensal
        comparativo = st.session_state.get("comparativo")
        if comparativo and comparativo.get("sucesso") and comparativo.get("rota_mais_rapida"):
            rapida = comparativo["rota_mais_rapida"]
            economica = comparativo.get("rota_mais_economica")
            economia_mensal = comparativo.get("economia_mensal", 0.0)
            # Métrica de economia (reflete no dashboard)
            if economica is None:
                st.warning(f"⚠️ Nenhuma rota elegível para 'Mais Econômica' (limite: ≤1.5 km caminhada e ≤3 baldeações). Exibindo apenas a mais rápida.")
            else:
                # Seletor
                opcoes = ["Mais Econômica", "Mais Rápida"]
                idx_default = 0 if st.session_state.get("rota_selecionada", "economica") == "economica" else 1
                escolha = st.radio(
                    "Comparativo de tarifa — escolha a referência para detalhamento e PDF:",
                    options=opcoes,
                    index=idx_default,
                    horizontal=True,
                    key="radio_comparativo",
                )
                st.session_state.rota_selecionada = "economica" if escolha == "Mais Econômica" else "rapida"
                # Cards comparativos
                col_r, col_e, col_ec = st.columns(3)
                with col_r:
                    st.markdown(
                        f"""
                        <div style="background:#EFF6FF;border:1px solid #DBEAFE;border-radius:12px;padding:12px 14px;">
                        <b>⚡ Mais Rápida</b><br>
                        {rapida.get('duracao_min',0)} min • {rapida.get('distancia_km',0)} km • {rapida.get('baldeacoes',0)} baldeações • {rapida.get('caminhada_km',0)} km caminhada<br>
                        <b>R$ {rapida.get('custo_trecho',0):.2f}</b> / trecho • <b>R$ {rapida.get('custo_diario',0):.2f}</b> /dia • <b>R$ {rapida.get('custo_mensal',0):.2f}</b> /mês
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                with col_e:
                    if economica:
                        st.markdown(
                            f"""
                            <div style="background:#ECFDF5;border:1px solid #A7F3D0;border-radius:12px;padding:12px 14px;">
                            <b>💰 Mais Econômica</b> {"(empate)" if economica.get('indice')==rapida.get('indice') else ""}<br>
                            {economica.get('duracao_min',0)} min • {economica.get('distancia_km',0)} km • {economica.get('baldeacoes',0)} baldeações • {economica.get('caminhada_km',0)} km caminhada<br>
                            <b>R$ {economica.get('custo_trecho',0):.2f}</b> / trecho • <b>R$ {economica.get('custo_diario',0):.2f}</b> /dia • <b>R$ {economica.get('custo_mensal',0):.2f}</b> /mês
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                    else:
                        st.info("Sem rota econômica elegível.")
                with col_ec:
                    st.metric("💸 Economia mensal (vs rápida)", f"R$ {economia_mensal:.2f}", delta=f"-R$ {economia_mensal:.2f}" if economia_mensal>0 else "empate")
                    st.caption(comparativo.get("justificativa",""))
                # Detalhamento tarifário da rota selecionada
                rota_ref = economica if st.session_state.rota_selecionada == "economica" and economica else rapida
                if rota_ref.get("detalhamento_tarifario"):
                    with st.expander("🧾 Detalhamento tarifário — rota selecionada", expanded=True):
                        for linha in rota_ref["detalhamento_tarifario"]:
                            st.markdown(f"- {linha}")
                        # Memória de cálculo
                        if rota_ref.get("memoria_calculo"):
                            st.markdown("**Memória de cálculo (auditoria):**")
                            for m in rota_ref["memoria_calculo"]:
                                st.caption(f"• {m}")
                # Atualiza métricas principais para refletir seleção (sobrescreve custo_diario/mensal do card superior se VT)
                if modalidade_atual in ("Vale-Transporte", "Comparativo Completo") and rota_ref:
                    # Re-renderiza métrica de economia no contexto já exibido via caption abaixo
                    st.caption(f"Exibindo valores da rota **{'Mais Econômica' if st.session_state.rota_selecionada=='economica' and economica else 'Mais Rápida'}** — custo trecho R$ {rota_ref.get('custo_trecho',0):.2f} | diário R$ {rota_ref.get('custo_diario',0):.2f} | mensal R$ {rota_ref.get('custo_mensal',0):.2f}")

        # --- Card/Banner de Viabilidade CLT 6% — reativo ao seletor Rápida/Econômica (ajuste #3) ---
        if modalidade_atual in ("Vale-Transporte", "Comparativo Completo"):
            # custo mensal da opção ativa (economica/rapida) ou fallback do VT
            custo_clt = None
            if comparativo and comparativo.get("sucesso"):
                rapida_c = comparativo.get("rota_mais_rapida") or {}
                economica_c = comparativo.get("rota_mais_economica")
                rota_ativa = economica_c if st.session_state.get("rota_selecionada") == "economica" and economica_c else rapida_c
                custo_clt = rota_ativa.get("custo_mensal")
            if custo_clt is None:
                custo_clt = (st.session_state.resultado_vt or {}).get("custo_mensal") or custo_mensal
            salario_clt = float(st.session_state.get("salario_base", 0.0) or 0.0)
            if salario_clt > 0 and custo_clt is not None:
                try:
                    viab = analisar_viabilidade_clt(float(custo_clt), salario_clt)
                    # banner
                    if viab.get("vt_vantajoso"):
                        st.success(f"✅ **Viabilidade CLT 6% — VT Vantajoso** | {viab.get('recomendacao','')}")
                    else:
                        st.warning(f"⚠️ **Viabilidade CLT 6% — Alerta RH** | {viab.get('recomendacao','')}")
                    c_a, c_b, c_c = st.columns(3)
                    c_a.metric("Teto 6% (salário)", f"R$ {viab.get('teto_desconto_6_pct',0):.2f}", help=f"6% de R$ {salario_clt:.2f}")
                    c_b.metric("Desconto colaborador", f"R$ {viab.get('desconto_colaborador',0):.2f}")
                    c_c.metric("Subsídio empresa", f"R$ {viab.get('custeio_empresa',0):.2f}")
                    with st.expander("📋 Memória CLT — Lei 7.418/85", expanded=False):
                        for linha in viab.get("memoria_calculo", []):
                            st.caption(f"• {linha}")
                        st.caption(viab.get("justificativa",""))
                except Exception:
                    pass
            elif salario_clt == 0 and custo_clt is not None:
                st.info("ℹ️ **Viabilidade CLT 6%:** informe o **Salário Base (R$)** na barra lateral para ver o rateio Empresa vs Colaborador (Lei 7.418/85).")
            # else: sem custo, não exibe

        # Comparativo: resumo rápido quando modo comparativo
        if modalidade_atual == "Comparativo Completo" and st.session_state.resultado_vt and st.session_state.resultado_vc:
            st.markdown("##### 🔀 Comparativo — Resumo")
            cc1, cc2 = st.columns(2)
            vt = st.session_state.resultado_vt
            vc = st.session_state.resultado_vc
            with cc1:
                st.markdown(
                    f"""
                    <div style="background:#EFF6FF;border:1px solid #DBEAFE;border-radius:12px;padding:12px 14px;">
                    <b>🚌 Vale-Transporte</b><br>
                    Distância: <b>{vt.get('distancia_km')} km</b> • Diário: <b>R$ {vt.get('custo_diario',0):.2f}</b> • Mensal ({dias_uteis_atual}d): <b>R$ {vt.get('custo_mensal',0):.2f}</b><br>
                    <span style="color:#475569;font-size:0.85em;">{vt.get('resumo_trajeto','')[:160]}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with cc2:
                st.markdown(
                    f"""
                    <div style="background:#FEF3C7;border:1px solid #FDE68A;border-radius:12px;padding:12px 14px;">
                    <b>🚗 Vale-Combustível</b><br>
                    Distância: <b>{vc.get('distancia_km')} km</b> • Diário (ida+volta): <b>R$ {vc.get('custo_diario',0):.2f}</b> • Mensal ({dias_uteis_atual}d): <b>R$ {vc.get('custo_mensal',0):.2f}</b><br>
                    <span style="color:#475569;font-size:0.85em;">Valor KM: R$ {vc.get('valor_km',0):.2f}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        # Navegação em 3 abas
        tab_mapa, tab_pdf, tab_status = st.tabs(["🗺️ Mapa & Itinerário", "📄 Relatório PDF", "⚙️ Status da Infraestrutura"])

        # ---------------- Aba 1 — Mapa & Itinerário ----------------
        with tab_mapa:
            st.markdown("#### 🗺️ Mapa & Itinerário — largura total")
            coords = st.session_state.coords
            # Mapa estático em largura total
            if coords and len(coords) == 4:
                try:
                    img_buf = gerar_imagem_mapa_rota(*coords)
                    st.image(img_buf, caption=f"Trajeto: {st.session_state.origem_label} → {st.session_state.destino_label}", use_container_width=True)
                except Exception as exc:
                    st.warning(f"Não foi possível renderizar o mapa estático: {exc}")
                    # Fallback: mostra coordenadas
                    st.code(f"Origem: {coords[0]:.5f}, {coords[1]:.5f}  →  Destino: {coords[2]:.5f}, {coords[3]:.5f}")
            else:
                st.info("Coordenadas indisponíveis para renderizar o mapa.")

            st.divider()
            # Detalhamento passo a passo
            if modalidade_atual in ("Vale-Combustível", "Comparativo Completo") and st.session_state.resultado_vc:
                vc = st.session_state.resultado_vc
                if modalidade_atual == "Vale-Combustível":
                    st.markdown("##### 🚗 Detalhamento — Vale-Combustível")
                    st.markdown(f"- **Distância rodoviária (OSRM):** `{vc.get('distancia_km')} km`")
                    st.markdown(f"- **Valor por KM:** `R$ {vc.get('valor_km', st.session_state.valor_km):.2f}`")
                    st.markdown(f"- **Custo diário (ida+volta):** `R$ {vc.get('custo_diario',0):.2f}` → **Mensal ({dias_uteis_atual}d): `R$ {vc.get('custo_mensal',0):.2f}`**")
                    if vc.get("sucesso") is False:
                        st.error(vc.get("erro", "Falha no cálculo VC."))

            if modalidade_atual in ("Vale-Transporte", "Comparativo Completo") and st.session_state.resultado_vt:
                vt = st.session_state.resultado_vt
                st.markdown("##### 🚌 Detalhamento — Vale-Transporte (passo a passo)")
                if vt.get("resumo_trajeto"):
                    st.info(vt["resumo_trajeto"])
                detalhes = vt.get("detalhes") or []
                if detalhes:
                    df_det = pd.DataFrame(detalhes)
                    col_map = {"linha": "Linha / Modal", "codigo_linha": "Código", "operadora": "Operadora", "valor_unitario": "Tarifa (R$)", "quantidade_dia": "Qtd/dia", "subtotal": "Subtotal (R$)", "fonte": "Fonte", "tarifa_confirmada": "Confirmada"}
                    # garante colunas mesmo quando legado
                    for c in ["codigo_linha", "operadora", "fonte", "tarifa_confirmada"]:
                        if c not in df_det.columns:
                            df_det[c] = "—" if c != "tarifa_confirmada" else True
                    # formata confirmada como ícone
                    df_det["tarifa_confirmada"] = df_det["tarifa_confirmada"].map(lambda x: "✅" if x else "⚠️ A confirmar")
                    df_show = df_det.rename(columns=col_map)
                    # ordena colunas na ordem canônica
                    ordem = ["Linha / Modal", "Código", "Operadora", "Tarifa (R$)", "Qtd/dia", "Subtotal (R$)", "Fonte", "Confirmada"]
                    df_show = df_show[[c for c in ordem if c in df_show.columns]]
                    st.dataframe(df_show, width='stretch', hide_index=True)
                    # alertas de tarifas não confirmadas
                    pend = [d for d in detalhes if not d.get("tarifa_confirmada")]
                    if pend:
                        st.warning(f"⚠️ {len(pend)} linha(s) com tarifa estimada — confirmar valor oficial: " + ", ".join([f"{d.get('codigo_linha') or d.get('linha')} ({d.get('operadora')})" for d in pend]))
                    bal = max(len(detalhes) - 1, 0)
                    st.caption(f"**{len(detalhes)}** trecho(s) • **{bal}** baldeação(ões) • Fonte roteirização: **{vt.get('fonte','—')}** • Catálogo: **{vt.get('catalogo_versao') or '—'}**")
                    # Linha de integração destacada
                    if bal > 0:
                        st.markdown(f"🔄 **Integração:** {bal} baldeação(ões) sugerida(s) — valide com o colaborador.")
                else:
                    st.warning("Nenhum trecho de transporte identificado. Verifique a cobertura GTFS ou use a estimativa de contingência.")
                if vt.get("aviso"):
                    st.warning(vt["aviso"])

            # Se comparativo, já mostrou ambos; se VT puro, já acima

        # ---------------- Aba 2 — Relatório PDF ----------------
        with tab_pdf:
            st.markdown("#### 📄 Relatório PDF — Memória de Cálculo")
            # Resumo formatado
            vt = st.session_state.resultado_vt
            vc = st.session_state.resultado_vc
            principal = st.session_state.resultado

            # Bloco origem/destino
            st.markdown(
                f"""
                <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:12px;padding:14px 16px;margin-bottom:12px;">
                <b>Origem:</b> {st.session_state.origem_label}<br>
                <b>Destino:</b> {st.session_state.destino_label}<br>
                <b>Modalidade:</b> {modalidade_atual} &nbsp;•&nbsp; <b>Dias úteis:</b> {dias_uteis_atual} &nbsp;•&nbsp; <b>Tarifa:</b> R$ {st.session_state.tarifa:.2f} &nbsp;•&nbsp; <b>Valor KM:</b> R$ {st.session_state.valor_km:.2f}
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Tabela memória conforme modalidade
            if modalidade_atual == "Vale-Combustível" and vc:
                if vc.get("sucesso"):
                    mem = pd.DataFrame([
                        {"Item": "Distância (OSRM)", "Valor": f"{vc.get('distancia_km')} km"},
                        {"Item": "Valor por KM", "Valor": f"R$ {vc.get('valor_km',0):.2f}"},
                        {"Item": "Custo diário (ida+volta)", "Valor": f"R$ {vc.get('custo_diario',0):.2f}"},
                        {"Item": f"Estimativa mensal ({dias_uteis_atual} dias)", "Valor": f"R$ {vc.get('custo_mensal',0):.2f}"},
                    ])
                    st.table(mem)
                else:
                    st.error(vc.get("erro", "Falha no VC"))
            elif modalidade_atual == "Vale-Transporte" and vt:
                if vt.get("sucesso") is not False:
                    mem_vt = pd.DataFrame(vt.get("detalhes", []))
                    if not mem_vt.empty:
                        mem_vt = mem_vt.rename(columns={"linha": "Linha / Modal", "valor_unitario": "Tarifa (R$)", "quantidade_dia": "Qtd/dia", "subtotal": "Subtotal (R$)"})
                        st.dataframe(mem_vt, width='stretch', hide_index=True)
                    st.markdown(f"**Total diário:** R$ {vt.get('custo_diario',0):.2f}  •  **Mensal ({dias_uteis_atual}d):** R$ {vt.get('custo_mensal',0):.2f}")
                    if vt.get("resumo_trajeto"):
                        st.caption(vt["resumo_trajeto"])
            elif modalidade_atual == "Comparativo Completo":
                col_vt, col_vc = st.columns(2)
                with col_vt:
                    st.markdown("**🚌 Vale-Transporte**")
                    if vt and vt.get("detalhes"):
                        st.dataframe(pd.DataFrame(vt["detalhes"]).rename(columns={"linha":"Linha","valor_unitario":"Tarifa","quantidade_dia":"Qtd","subtotal":"Subtotal"}), width='stretch', hide_index=True)
                    st.markdown(f"Diário: **R$ {vt.get('custo_diario',0):.2f}** • Mensal: **R$ {vt.get('custo_mensal',0):.2f}**" if vt else "—")
                with col_vc:
                    st.markdown("**🚗 Vale-Combustível**")
                    if vc:
                        st.markdown(f"Distância: **{vc.get('distancia_km')} km**  \nDiário: **R$ {vc.get('custo_diario',0):.2f}**  \nMensal: **R$ {vc.get('custo_mensal',0):.2f}**")
            else:
                # Fallback genérico
                st.json(principal)

            st.divider()
            # Geração do PDF em BytesIO (stateless)
            st.markdown("**Gerar evidência auditável (PDF com mapa):**")
            # Prepara dados para pdf_generator (compatível com assinatura existente)
            # O gerador espera dados_candidato, tipo_beneficio, dados_calculo, coords
            dados_candidato = {"nome": "Colaborador (simulação)", "cargo": "—", "centro_custo": "Simulação SmartPass"}
            tipo_pdf = modalidade_atual
            # Escolhe dados_calculo conforme modalidade — inclui comparativo fare_engine quando disponível
            comparativo_pdf = st.session_state.get("comparativo")
            rota_sel = None
            if comparativo_pdf and comparativo_pdf.get("sucesso"):
                sel = st.session_state.get("rota_selecionada", "economica")
                if sel == "economica" and comparativo_pdf.get("rota_mais_economica"):
                    rota_sel = comparativo_pdf["rota_mais_economica"]
                else:
                    rota_sel = comparativo_pdf.get("rota_mais_rapida")

            if modalidade_atual == "Vale-Combustível":
                dados_calc = {
                    "origem": st.session_state.origem_label,
                    "destino": st.session_state.destino_label,
                    "distancia_km": vc.get("distancia_km", 0) if vc else 0,
                    "valor_km": st.session_state.valor_km,
                    "custo_total": vc.get("custo_diario", 0) if vc else 0,
                    "custo_diario": vc.get("custo_diario", 0) if vc else 0,
                    "custo_mensal": vc.get("custo_mensal", 0) if vc else 0,
                }
            elif modalidade_atual == "Vale-Transporte":
                if rota_sel:
                    dados_calc = {
                        "origem": st.session_state.origem_label,
                        "destino": st.session_state.destino_label,
                        "resumo_trajeto": rota_sel.get("resumo_trajeto", vt.get("resumo_trajeto","") if vt else ""),
                        "detalhes": rota_sel.get("detalhes", vt.get("detalhes", []) if vt else []),
                        "detalhamento_tarifario": rota_sel.get("detalhamento_tarifario", []),
                        "memoria_calculo": rota_sel.get("memoria_calculo", []) + (comparativo_pdf.get("memoria_calculo", []) if comparativo_pdf else []),
                        "justificativa": rota_sel.get("justificativa", ""),
                        "comparativo": comparativo_pdf,
                        "custo_diario": rota_sel.get("custo_diario", vt.get("custo_diario",0) if vt else 0),
                        "custo_mensal": rota_sel.get("custo_mensal", vt.get("custo_mensal",0) if vt else 0),
                        "custo_trecho": rota_sel.get("custo_trecho", 0),
                        "distancia_km": rota_sel.get("distancia_km", vt.get("distancia_km",0) if vt else 0),
                        "dias_uteis": dias_uteis_atual,
                    }
                else:
                    dados_calc = {
                        "origem": st.session_state.origem_label,
                        "destino": st.session_state.destino_label,
                        "resumo_trajeto": vt.get("resumo_trajeto", "") if vt else "",
                        "detalhes": vt.get("detalhes", []) if vt else [],
                        "custo_diario": vt.get("custo_diario", 0) if vt else 0,
                        "custo_mensal": vt.get("custo_mensal", 0) if vt else 0,
                        "distancia_km": vt.get("distancia_km", 0) if vt else 0,
                    }
            else:
                # Comparativo: usa rota selecionada + VC no resumo
                if rota_sel:
                    dados_calc = {
                        "origem": st.session_state.origem_label,
                        "destino": st.session_state.destino_label,
                        "resumo_trajeto": (rota_sel.get("resumo_trajeto","") or vt.get("resumo_trajeto","") if vt else "") + (f" | VC: {vc.get('distancia_km')}km, R$ {vc.get('custo_diario',0):.2f}/dia" if vc else ""),
                        "detalhes": rota_sel.get("detalhes", vt.get("detalhes", []) if vt else []),
                        "detalhamento_tarifario": rota_sel.get("detalhamento_tarifario", []),
                        "memoria_calculo": rota_sel.get("memoria_calculo", []) + (comparativo_pdf.get("memoria_calculo", []) if comparativo_pdf else []),
                        "justificativa": comparativo_pdf.get("justificativa", "") if comparativo_pdf else "",
                        "comparativo": comparativo_pdf,
                        "custo_diario": rota_sel.get("custo_diario",0) if rota_sel else (vt.get("custo_diario",0) if vt else 0),
                        "custo_mensal": rota_sel.get("custo_mensal",0) if rota_sel else (vt.get("custo_mensal",0) if vt else 0),
                        "custo_trecho": rota_sel.get("custo_trecho",0) if rota_sel else 0,
                        "distancia_km": rota_sel.get("distancia_km", vt.get("distancia_km",0) if vt else 0),
                        "dias_uteis": dias_uteis_atual,
                    }
                else:
                    dados_calc = {
                        "origem": st.session_state.origem_label,
                        "destino": st.session_state.destino_label,
                        "resumo_trajeto": (vt.get("resumo_trajeto","") if vt else "") + (f" | VC: {vc.get('distancia_km')}km, R$ {vc.get('custo_diario',0):.2f}/dia" if vc else ""),
                        "detalhes": vt.get("detalhes", []) if vt else [],
                        "custo_diario": vt.get("custo_diario",0) if vt else 0,
                        "custo_mensal": vt.get("custo_mensal",0) if vt else 0,
                        "distancia_km": vt.get("distancia_km",0) if vt else 0,
                    }

            # --- Viabilidade CLT para PDF — reativa ao seletor (ajuste #3) ---
            try:
                salario_pdf = float(st.session_state.get("salario_base", 0.0) or 0.0)
                custo_pdf = float(dados_calc.get("custo_mensal", 0) or 0)
                if salario_pdf > 0 and custo_pdf is not None:
                    viab_pdf = analisar_viabilidade_clt(custo_pdf, salario_pdf)
                    dados_calc["viabilidade_clt"] = viab_pdf
                    dados_calc["salario_base"] = salario_pdf
                    # Preview no dashboard antes do PDF
                    st.markdown("##### ⚖️ Rateio CLT 6% — Lei 7.418/85 (prévia do PDF)")
                    if viab_pdf.get("vt_vantajoso"):
                        st.success(viab_pdf.get("recomendacao",""))
                    else:
                        st.warning(viab_pdf.get("recomendacao",""))
                    pc1, pc2, pc3 = st.columns(3)
                    pc1.metric("Teto 6%", f"R$ {viab_pdf.get('teto_desconto_6_pct',0):.2f}")
                    pc2.metric("Desconto colaborador", f"R$ {viab_pdf.get('desconto_colaborador',0):.2f}")
                    pc3.metric("Subsídio empresa", f"R$ {viab_pdf.get('custeio_empresa',0):.2f}")
                    with st.expander("Memória CLT (irá para o PDF)"):
                        for linha in viab_pdf.get("memoria_calculo", []):
                            st.caption(f"• {linha}")
                elif salario_pdf == 0:
                    st.caption("ℹ️ Informe **Salário Base** na barra lateral para incluir o quadro de rateio CLT 6% no PDF.")
            except Exception:
                pass

            # Botão para gerar PDF (mantém em session_state)
            if st.button("📄 Gerar PDF em Memória (BytesIO)", width='stretch'):
                try:
                    with st.spinner("Gerando PDF…"):
                        pdf_buf = gerar_pdf_evidencia(dados_candidato, tipo_pdf, dados_calc, coords=st.session_state.coords)
                        # Normaliza para BytesIO
                        if isinstance(pdf_buf, io.BytesIO):
                            pdf_buf.seek(0)
                            st.session_state.pdf_buffer = pdf_buf
                        else:
                            # Se retornou bytes
                            b = io.BytesIO(pdf_buf if isinstance(pdf_buf, (bytes, bytearray)) else bytes(pdf_buf))
                            b.seek(0)
                            st.session_state.pdf_buffer = b
                    st.success("PDF gerado em memória — pronto para download.")
                except Exception as exc:
                    st.error(f"Falha ao gerar PDF: {exc}")
                    st.code(traceback.format_exc())

            # Botão de download direto (se já gerado)
            if st.session_state.pdf_buffer is not None:
                st.session_state.pdf_buffer.seek(0)
                st.download_button(
                    label="⬇️ Baixar Evidência com Mapa (PDF)",
                    data=st.session_state.pdf_buffer.getvalue(),
                    file_name=f"Evidencia_SmartPass_{modalidade_atual.replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                    mime="application/pdf",
                    width='stretch',
                    type="primary",
                )
            else:
                st.caption("Clique em **Gerar PDF em Memória** para habilitar o download. O arquivo nunca toca disco — todo o fluxo usa `BytesIO` (LGPD/stateless).")

        # ---------------- Aba 3 — Status da Infraestrutura ----------------
        with tab_status:
            st.markdown("#### ⚙️ Status da Infraestrutura — tempo real")
            st.caption("Verificação direta de saúde (sem cache) de PostgreSQL/PostGIS e OpenTripPlanner. Fallback é esperado quando os serviços não estão locais.")

            col_db, col_otp = st.columns(2)

            with col_db:
                st.markdown("**PostgreSQL + PostGIS**")
                pg = _verificar_postgres()
                if pg["sucesso"]:
                    st.success("🟢 **Online** — conexão estabelecida")
                    if pg["postgis"]:
                        st.markdown(f"✅ PostGIS ativo — `{pg['versao'][:60] if pg['versao'] else ''}`")
                    else:
                        st.warning("🟡 PostGIS não detectado — extensão pode estar ausente")
                    st.caption(f"Host: `{os.getenv('DB_HOST','localhost')}:{os.getenv('DB_PORT','5432')}` • DB: `{os.getenv('DB_NAME','smartpass')}`")
                else:
                    st.error("🔴 **Offline / Fallback**")
                    st.markdown(f"Detalhe: `{pg.get('erro','indisponível')[:180]}`")
                    st.info("O app segue operando em modo **fallback** — consultas e rotas usam APIs externas/OSRM sem persistência.")

            with col_otp:
                st.markdown("**OpenTripPlanner (OTP) — GTFS**")
                otp = _verificar_otp()
                if otp["sucesso"]:
                    st.success("🟢 **Online** — GTFS carregado")
                    st.caption(f"Endpoint: `{otp['url']}` • HTTP {otp.get('status',200)}")
                    st.markdown("Roteirização usa **feeds GTFS locais** para linhas reais (ônibus, trem, metrô).")
                else:
                    st.warning("🟡 **Modo Fallback ativo**")
                    st.markdown(f"OTP indisponível: `{otp.get('erro','offline')[:180]}`")
                    st.caption(f"Endpoint tentado: `{otp['url']}`")
                    st.info("Fallback: **estimativa provisória** para validação manual pelo RH (sem GTFS).")

            st.divider()
            # Legenda de indicadores
            st.markdown(
                """
                <div style="display:flex;gap:12px;flex-wrap:wrap;">
                  <span style="background:#DCFCE7;border:1px solid #BBF7D0;padding:6px 10px;border-radius:999px;font-size:0.85em;">🟢 Online</span>
                  <span style="background:#FEF9C3;border:1px solid #FDE68A;padding:6px 10px;border-radius:999px;font-size:0.85em;">🟡 Fallback</span>
                  <span style="background:#FEE2E2;border:1px solid #FECACA;padding:6px 10px;border-radius:999px;font-size:0.85em;">🔴 Offline</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("🔄 Re-verificar agora", width='content'):
                st.rerun()

            # Batch resultados se houver — espelho do lote com semáforo e filtro visual
            if st.session_state.batch_resultados:
                st.divider()
                st.markdown("##### 📦 Resultado do lote (último processamento)")
                try:
                    _df_lote = pd.DataFrame(st.session_state.batch_resultados)
                    if "nivel_precisao" in _df_lote.columns:
                        _n_alta = int((_df_lote["nivel_precisao"] == "ALTA").sum())
                        _n_media = int((_df_lote["nivel_precisao"] == "MEDIA").sum())
                        _n_baixa = int((_df_lote["nivel_precisao"] == "BAIXA").sum())
                        _c1, _c2, _c3 = st.columns(3)
                        _c1.metric("🟢 Exatos", _n_alta)
                        _c2.metric("🟡 Aproximados", _n_media)
                        _c3.metric("🔴 Para Revisão", _n_baixa)
                        _filtrar = st.checkbox("Mostrar apenas endereços que exigem revisão (🟡/🔴)", value=False, key="filtro_revisao_lote_main")
                        if _filtrar:
                            _df_exib = _df_lote[_df_lote["nivel_precisao"].isin(["MEDIA", "BAIXA"])]
                            if _df_exib.empty:
                                st.info("Nenhum endereço com 🟡/🔴 — todos são 🟢 Exatos.")
                            else:
                                st.dataframe(_df_exib, width='stretch')
                                st.caption(f"Exibindo {len(_df_exib)} de {len(_df_lote)} — filtro 🟡/🔴 ativo.")
                        else:
                            st.dataframe(_df_lote, width='stretch')
                    else:
                        st.dataframe(_df_lote, width='stretch')
                except Exception:
                    st.dataframe(pd.DataFrame(st.session_state.batch_resultados), width='stretch')

    # Footer
    st.divider()
    st.caption("SmartPass • Stateless & LGPD • PDFs e mapas em BytesIO • Cache: `@st.cache_data` (geocoding/rotas) e `@st.cache_resource` (DB) • Fallback resiliente para OTP/PostGIS")


if __name__ == "__main__":
    main()
