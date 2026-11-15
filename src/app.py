import io
import os
import sys
from datetime import datetime

# Garante que `src` seja importável quando executado via `streamlit run src/app.py`
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st
import pandas as pd

from src.services.benefit_calculator import analisar_viabilidade_clt, parse_salario_brasileiro
from src.services.calendar_engine import calcular_dias_uteis
from src.services.export_formatter import gerar_export_compra, gerar_export_rubrica
from src.services.geocoding import buscar_coordenadas_por_cep_ou_endereco, sugerir_enderecos
from src.services.map_generator import gerar_imagem_mapa_rota
from src.services.pdf_generator import gerar_pdf_evidencia
from src.services.routing import (
    calcular_vale_combustivel,
    calcular_vale_transporte,
    roteirizar_com_comparativo,
    roteirizar_vale_transporte_automatico,
)

try:
    from streamlit_searchbox import st_searchbox

    _SEARCHBOX_DISPONIVEL = True
except Exception:  # pragma: no cover - fallback defensivo de ambiente
    st_searchbox = None
    _SEARCHBOX_DISPONIVEL = False



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
        "origem_selecionada": None,
        "destino_selecionada": None,
        "origem_texto": "",
        "destino_texto": "",
        "origem_numero": "",
        "destino_numero": "",
        "modalidade": "Vale-Transporte",
        "dias_uteis": 22,
        "tarifa": 0.0,
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
        "geo_auditoria": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _buscar_sugestoes_endereco(termo: str) -> list[tuple[str, dict]]:
    """Search function do ``st_searchbox``: retorna ``(label_exibicao, candidato)``.

    Args:
        termo: Texto digitado pelo usuário (mínimo 3 caracteres).

    Returns:
        list[tuple[str, dict]]: Sugestões geocodificadas na RMSP; ``[]`` em falha.
    """
    try:
        sugestoes = sugerir_enderecos(termo, limite=5)
    except Exception:
        return []
    return [(item["label_exibicao"], item) for item in sugestoes]


def _render_endereco_autocomplete(chave: str, label: str, default: str) -> str:
    """Renderiza autocomplete de endereço com fallback nativo e preview de precisão.

    Args:
        chave: Identificador do campo (``"origem"``/``"destino"``).
        label: Rótulo exibido no componente.
        default: Texto inicial quando não há seleção em ``st.session_state``.

    Returns:
        str: Texto efetivo (label + número condicional) usado na geocodificação.
    """
    estado = st.session_state.get(f"{chave}_selecionada") or {}
    texto_atual = estado.get("label_exibicao") or st.session_state.get(f"{chave}_texto") or default

    if _SEARCHBOX_DISPONIVEL:
        escolha = st_searchbox(
            _buscar_sugestoes_endereco,
            label=label,
            placeholder="Ex: 06310-000 ou Av. Paulista, 1000",
            default=estado or texto_atual,
            default_options=[(estado["label_exibicao"], estado)] if estado.get("label_exibicao") else None,
            default_use_searchterm=True,
            clear_on_submit=False,
            key=f"searchbox_{chave}",
            rerun_scope="app",
        )
        if isinstance(escolha, dict) and escolha.get("label_exibicao"):
            if escolha.get("label_exibicao") != estado.get("label_exibicao"):
                st.session_state[f"{chave}_numero"] = ""
            estado = escolha
            st.session_state[f"{chave}_selecionada"] = escolha
            texto_atual = escolha["label_exibicao"]
            st.session_state[f"{chave}_texto"] = texto_atual
        elif isinstance(escolha, str) and escolha.strip():
            texto_atual = escolha.strip()
            st.session_state[f"{chave}_texto"] = texto_atual
            if texto_atual != (estado.get("label_exibicao") or ""):
                st.session_state[f"{chave}_selecionada"] = {}
                estado = {}
    else:
        texto_atual = st.text_input(
            label,
            value=texto_atual,
            placeholder="Ex: 06310-000 ou Av. Paulista, 1000",
            key=f"txt_{chave}",
            help="Autocomplete indisponível — digite o CEP/endereço e escolha uma sugestão.",
        )
        st.session_state[f"{chave}_texto"] = texto_atual
        if len(str(texto_atual).strip()) >= 3:
            opcoes = _buscar_sugestoes_endereco(texto_atual)
            if opcoes:
                rotulos = ["— selecionar sugestão —"] + [rotulo for rotulo, _ in opcoes]
                escolha = st.selectbox("Sugestões encontradas", rotulos, key=f"sel_{chave}")
                if escolha != rotulos[0]:
                    estado = opcoes[rotulos.index(escolha) - 1][1]
                    st.session_state[f"{chave}_selecionada"] = estado
                    texto_atual = estado["label_exibicao"]

    numero_atual = st.session_state.get(f"{chave}_numero", "")
    if estado and not estado.get("numero") and estado.get("nivel_precisao") in ("ALTA", "MEDIA"):
        numero_atual = st.text_input(
            "Número (opcional — refina a precisão)",
            value=numero_atual,
            key=f"numero_{chave}",
            placeholder="Ex: 1500",
        )
        st.session_state[f"{chave}_numero"] = numero_atual
    elif estado and estado.get("numero"):
        numero_atual = str(estado["numero"])

    texto_final = str(texto_atual or "")
    if numero_atual and str(numero_atual).strip() and str(numero_atual).strip() not in texto_final:
        texto_final = f"{texto_final}, {str(numero_atual).strip()}"

    preview = estado
    if numero_atual and estado and str(numero_atual) != str(estado.get("numero") or ""):
        refinado = sugerir_enderecos(texto_final, limite=1)
        preview = refinado[0] if refinado else estado

    if preview:
        rotulo_precisao = {
            "ALTA": "Endereço exato",
            "MEDIA": "Endereço aproximado",
            "BAIXA": "Localização aproximada",
        }.get(str(preview.get("nivel_precisao", "")).upper(), "")
        linha_endereco = f"{preview.get('semaforo', '')} {preview.get('label_exibicao', '')}".strip()
        if rotulo_precisao:
            icone = str(preview.get("semaforo", "")).split(" ")[0].strip()
            linha_endereco = f"{icone} {preview.get('label_exibicao', '')}".strip() + f" · {rotulo_precisao}"
        st.caption(linha_endereco)

    return texto_final


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


def _df_lote_para_exibicao(df: pd.DataFrame) -> pd.DataFrame:
    """Traduz colunas técnicas do lote para rótulos de negócio (exibição apenas)."""
    exibicao = df.copy()
    if "fonte" in exibicao.columns:
        exibicao["fonte"] = exibicao["fonte"].map(
            lambda valor: "Rota oficial" if str(valor).startswith("OpenTripPlanner") else "Estimativa"
        )
    if "nivel_precisao" in exibicao.columns:
        exibicao["nivel_precisao"] = exibicao["nivel_precisao"].map(
            {"ALTA": "Exato", "MEDIA": "Aproximado", "BAIXA": "Para revisão"}
        ).fillna(exibicao["nivel_precisao"])
    return exibicao


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
        return {"sucesso": False, "erro": "Não foi possível localizar o endereço de origem. Revise o CEP ou o endereço informado."}, None, None, None, None
    if not res_geo_destino.get("sucesso"):
        return {"sucesso": False, "erro": "Não foi possível localizar o endereço de destino. Revise o CEP ou o endereço informado."}, None, None, None, None

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

    # Header
    st.markdown(
        """
        <div class="smartpass-header">
            <h1>🚌 SmartPass — Gestão Inteligente de Vale-Transporte</h1>
            <p>Roteirização oficial e cálculo de benefícios para admissão e folha</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ===================== SIDEBAR — Painel de Simulação =====================
    with st.sidebar:
        st.markdown("### 🎛️ Painel de Simulação")

        st.markdown("**Origem e Destino**")
        origem_input = _render_endereco_autocomplete("origem", "Origem (CEP ou endereço)", "06310-000")
        destino_input = _render_endereco_autocomplete(
            "destino", "Destino (CEP ou endereço)", "Avenida Paulista, 1000, São Paulo"
        )

        with st.form("form_simulacao", clear_on_submit=False):
            st.markdown("**Modalidade**")
            modalidade_input = st.selectbox(
                "Modalidade",
                options=["Vale-Transporte", "Vale-Combustível", "Comparativo Completo"],
                index=["Vale-Transporte", "Vale-Combustível", "Comparativo Completo"].index(st.session_state.modalidade)
                if st.session_state.modalidade in ["Vale-Transporte", "Vale-Combustível", "Comparativo Completo"]
                else 0,
                help="Comparativo exibe VT e VC lado a lado para decisão de RH.",
            )

            with st.expander("⚙️ Parâmetros Avançados (Escala, Salário CLT e Convênio)", expanded=False):
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
                    help="Define quais dias são trabalhados no mês. Feriados nacionais e municipais são descontados automaticamente.",
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
                    municipio_input = st.selectbox("Município unidade (Grande SP)", options=mun_opts, index=mun_opts.index(mun_cur), help="Feriados municipais da unidade.")
                c_ano, c_mes = st.columns(2)
                with c_ano:
                    ano_input = st.number_input("Ano competência", min_value=2020, max_value=2100, value=int(st.session_state.get("ano_ref", datetime.now().year)), step=1)
                with c_mes:
                    mes_input = st.number_input("Mês competência", min_value=1, max_value=12, value=int(st.session_state.get("mes_ref", datetime.now().month)), step=1)
                dias_override_input = st.number_input(
                    "Override dias úteis (opcional)",
                    min_value=0, max_value=31, value=0, step=1,
                    help="0 = cálculo automático por escala/feriados. Informe 1-31 para sobrescrever manualmente.",
                )
                # Preview do cálculo (sem cache — puro)
                try:
                    _dias_override_preview = int(dias_override_input) if int(dias_override_input) > 0 else None
                    _prev = calcular_dias_uteis(int(ano_input), int(mes_input), escala_input, uf_input, municipio_input, dias_override=_dias_override_preview)
                    if _prev.get("sucesso"):
                        st.caption(f"📅 Dias úteis calculados: **{int(_prev['dias_uteis'])}** ({int(_prev['dias_brutos'])} brutos - {len(_prev.get('feriados_descontados', []))} feriados) — {escala_input} {int(mes_input):02d}/{int(ano_input)} {uf_input}/{municipio_input}" + (" — override manual" if _prev.get("dias_override_aplicado") else ""))
                    else:
                        st.caption("Não foi possível calcular os dias úteis automaticamente.")
                except Exception:
                    pass
                c1, c2 = st.columns(2)
                with c1:
                    dias_input_hidden = st.number_input("Dias úteis (manual)", min_value=1, max_value=31, value=int(st.session_state.dias_uteis), step=1, help="Usado apenas se o calendário falhar.")
                    dias_input = dias_input_hidden
                with c2:
                    st.caption("Tarifa oficial por linha aplicada automaticamente quando o override é 0.")
                tarifa_input = st.number_input(
                    "Override tarifa unitária (R$) — 0 = oficial",
                    min_value=0.0,
                    value=float(st.session_state.get("tarifa", 0.0) or 0.0),
                    step=0.10,
                    format="%.2f",
                    help="Deixe 0,00 para usar a tarifa oficial da linha. Informe um valor apenas para convênio/tarifa diferenciada.",
                )
                valor_km_input = st.number_input(
                    "Valor por KM — Vale-Combustível (R$)",
                    min_value=0.0,
                    value=float(st.session_state.valor_km),
                    step=0.05,
                    format="%.2f",
                    help="Aplicado apenas em Vale-Combustível e Comparativo.",
                )
                salario_base_input = st.number_input(
                    "Salário Base (R$) — opcional (Lei 7.418/85)",
                    min_value=0.0,
                    value=float(st.session_state.get("salario_base", 0.0)),
                    step=100.0,
                    format="%.2f",
                    help="Se 0 = não informado. Quando preenchido, calcula o teto de 6% e o rateio Empresa vs Colaborador.",
                )

            st.markdown("")
            submitted = st.form_submit_button("🔍 Calcular Rota e Benefício", width='stretch', type="primary")

        # Ações de limpeza
        if st.button("🧹 Limpar Simulação", width='stretch'):
            for k in ["resultado", "resultado_vt", "resultado_vc", "coords", "pdf_buffer", "batch_df", "batch_resultados", "comparativo", "memoria_calendario", "geo_auditoria", "origem_selecionada", "destino_selecionada"]:
                st.session_state[k] = None
            for k in ["origem_texto", "destino_texto", "origem_numero", "destino_numero"]:
                st.session_state[k] = ""
            st.session_state["rota_selecionada"] = "economica"
            st.session_state["ultimo_calculo_em"] = None
            st.session_state["salario_base"] = 0.0
            st.session_state["tarifa"] = 0.0
            st.session_state["valor_km"] = 1.25
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
                            c1.metric("🟢 Exatos", n_alta, help="Endereço com logradouro e número/CEP específico")
                            c2.metric("🟡 Aproximados", n_media, help="Apenas logradouro, sem número, ou bairro")
                            c3.metric("🔴 Para Revisão", n_baixa, help="Localização aproximada ou endereço não localizado")
                            # Filtro rápido visual (não afeta CSV completo)
                            filtrar_revisao = st.checkbox("Mostrar apenas endereços que exigem revisão (🟡/🔴)", value=False, key="filtro_revisao_lote")
                            # Exibição em linguagem de negócio (CSV mantém a trilha técnica completa)
                            if filtrar_revisao:
                                df_exib = df_res[df_res["nivel_precisao"].isin(["MEDIA", "BAIXA"])] if "nivel_precisao" in df_res.columns else df_res
                                if df_exib.empty:
                                    st.info("Nenhum endereço com 🟡/🔴 — todos são 🟢 Exatos.")
                                else:
                                    st.dataframe(_df_lote_para_exibicao(df_exib), width='stretch', height=260)
                                    st.caption(f"Exibindo {len(df_exib)} de {len(df_res)} — filtro 🟡/🔴 ativo. O CSV abaixo exporta o lote **completo** ({len(df_res)} linhas).")
                            else:
                                st.dataframe(_df_lote_para_exibicao(df_res), width='stretch', height=260)
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
                            # --- Exportação padronizada para portais de benefícios (CPF mascarado) ---
                            st.markdown("**Exportação para portais de benefícios (CPF mascarado):**")
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
                                    st.caption(f"Layout **{layout_lote}** — {len(export_rows)} registros, {_dias_export} dias úteis, competência {comp_export}. CPF protegido.")
                                    for m in exp_res.get("memoria_calculo", [])[:2]:
                                        st.caption(f"• {m}")
                                    st.download_button(
                                        f"⬇️ Baixar {layout_lote} (CSV)",
                                        data=exp_res["bytesio"].getvalue(),
                                        file_name=exp_res["filename"],
                                        mime="text/csv",
                                        width='stretch',
                                        key="download_lote_export",
                                    )
                                else:
                                    st.warning(f"Não foi possível gerar a exportação no layout {layout_lote}.")
                            except Exception:
                                st.warning("Não foi possível gerar a exportação padronizada para este lote.")
                        progresso.empty()
                except Exception:
                    st.error("Não foi possível ler o arquivo. Use CSV ou Excel com as colunas origem e destino.")
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
                    memoria_cal = [f"Não foi possível calcular os feriados — usando {dias_efetivos} dias úteis informados manualmente."]
                    _cal = {"sucesso": False, "dias_uteis": dias_efetivos, "memoria_calculo": memoria_cal, "justificativa": "Fallback dias úteis."}
            except Exception:
                dias_efetivos = int(dias_input)
                memoria_cal = [f"Não foi possível calcular os feriados — usando {dias_efetivos} dias úteis informados manualmente."]
                _cal = {"sucesso": False, "dias_uteis": dias_efetivos, "memoria_calculo": memoria_cal, "justificativa": "Fallback."}
            with st.spinner("🔎 Localizando endereços e calculando a rota…"):
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
                        st.error(payload.get("erro", "Não foi possível concluir o cálculo."))
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
                        st.session_state.geo_auditoria = [
                            f"Precisão geográfica ({rotulo}): {geo.get('nivel_precisao', '—')} — "
                            f"fonte {geo.get('fonte', '—')} — "
                            f"{geo.get('label_exibicao') or geo.get('endereco_encontrado') or '—'}"
                            for rotulo, geo in (("origem", geos[0]), ("destino", geos[1]))
                            if isinstance(geo, dict)
                        ]
                        st.session_state.tarifa = float(tarifa_input)
                        st.session_state.valor_km = float(valor_km_input)
                        st.session_state.salario_base = float(salario_base_input) if salario_base_input is not None else 0.0
                        st.session_state.ultimo_calculo_em = datetime.now()
                        st.session_state.pdf_buffer = None  # invalida PDF anterior
                        # Feedback
                        if payload["principal"] and payload["principal"].get("sucesso") is False:
                            st.error("Não foi possível concluir o cálculo. Revise os dados informados.")
                        else:
                            st.toast("Rota calculada com sucesso!", icon="✅")
                except Exception:
                    st.error("Não foi possível concluir o cálculo. Tente novamente em instantes.")

    # ===================== ÁREA PRINCIPAL — Dashboard =====================
    # Métricas no topo
    resultado = st.session_state.resultado
    modalidade_atual = st.session_state.modalidade
    dias_uteis_atual = st.session_state.dias_uteis

    if resultado is None:
        st.info("👈 Preencha **Origem** e **Destino** no painel lateral e clique em **Calcular Rota e Benefício**.")
        # Placeholder cards vazios para layout estável
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Distância Estimada", "—", help="Preenchido após cálculo")
        c2.metric("Tempo de Deslocamento", "—")
        c3.metric("Custo Diário (Ida + Volta)", "—")
        c4.metric(f"Custo Mensal ({dias_uteis_atual} dias)", "—")
        st.caption("O mapa, o itinerário e o relatório em PDF aparecerão aqui após o cálculo.")
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
        m2.metric("⏱️ Tempo de Deslocamento", _format_tempo(tempo_min), help="Tempo estimado de deslocamento porta a porta.")
        m3.metric("💰 Custo Diário (Ida + Volta)", f"R$ {float(custo_diario):.2f}" if custo_diario is not None else "—")
        m4.metric(f"🗓️ Custo Mensal ({dias_uteis_atual} dias)", f"R$ {float(custo_mensal):.2f}" if custo_mensal is not None else "—")

        # Aviso único quando a rota oficial não pôde ser obtida (estimativa provisória)
        if resultado.get("aviso"):
            st.warning(resultado["aviso"])

        # --- Viabilidade CLT 6% — exibida apenas quando o salário base é informado ---
        comparativo = st.session_state.get("comparativo")
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

        # Navegação em 2 abas
        tab_mapa, tab_pdf = st.tabs(["🗺️ Itinerário Detalhado", "📄 Relatório PDF"])

        # ---------------- Aba 1 — Itinerário Detalhado ----------------
        with tab_mapa:
            st.markdown("#### Itinerário Detalhado")
            coords = st.session_state.coords
            # Mapa estático em largura total
            if coords and len(coords) == 4:
                try:
                    img_buf = gerar_imagem_mapa_rota(*coords)
                    st.image(img_buf, caption=f"Trajeto: {st.session_state.origem_label} → {st.session_state.destino_label}", width="stretch")
                except Exception:
                    st.warning("Não foi possível exibir o mapa deste trajeto.")
            else:
                st.info("Mapa indisponível para este trajeto.")

            st.divider()
            # Detalhamento passo a passo
            if modalidade_atual in ("Vale-Combustível", "Comparativo Completo") and st.session_state.resultado_vc:
                vc = st.session_state.resultado_vc
                if modalidade_atual == "Vale-Combustível":
                    st.markdown("##### 🚗 Detalhamento — Vale-Combustível")
                    st.markdown(f"- **Distância do trajeto:** {vc.get('distancia_km')} km")
                    st.markdown(f"- **Valor por KM:** R$ {vc.get('valor_km', st.session_state.valor_km):.2f}")
                    st.markdown(f"- **Custo diário (ida+volta):** R$ {vc.get('custo_diario',0):.2f} → **Mensal ({dias_uteis_atual}d): R$ {vc.get('custo_mensal',0):.2f}**")

            if modalidade_atual in ("Vale-Transporte", "Comparativo Completo") and st.session_state.resultado_vt:
                vt = st.session_state.resultado_vt
                st.markdown("##### 🚌 Detalhamento — Vale-Transporte (passo a passo)")
                if vt.get("resumo_trajeto"):
                    st.info(vt["resumo_trajeto"])
                detalhes = vt.get("detalhes") or []
                if detalhes:
                    df_det = pd.DataFrame(detalhes)
                    col_map = {"linha": "Linha / Modal", "codigo_linha": "Código", "operadora": "Operadora", "valor_unitario": "Tarifa (R$)", "quantidade_dia": "Qtd/dia", "subtotal": "Subtotal (R$)", "tarifa_confirmada": "Tarifa"}
                    # garante colunas mesmo quando legado
                    for c in ["codigo_linha", "operadora", "tarifa_confirmada"]:
                        if c not in df_det.columns:
                            df_det[c] = "—" if c != "tarifa_confirmada" else True
                    # formata confirmada como ícone
                    df_det["tarifa_confirmada"] = df_det["tarifa_confirmada"].map(lambda x: "✅ Oficial" if x else "⚠️ A confirmar")
                    df_show = df_det.rename(columns=col_map)
                    # ordena colunas na ordem canônica
                    ordem = ["Linha / Modal", "Código", "Operadora", "Tarifa (R$)", "Qtd/dia", "Subtotal (R$)", "Tarifa"]
                    df_show = df_show[[c for c in ordem if c in df_show.columns]]
                    st.dataframe(df_show, width='stretch', hide_index=True)
                    # alertas de tarifas não confirmadas
                    pend = [d for d in detalhes if not d.get("tarifa_confirmada")]
                    if pend:
                        st.warning(f"⚠️ {len(pend)} linha(s) com tarifa a confirmar — valide com o colaborador.")
                    bal = max(len(detalhes) - 1, 0)
                    fonte_rota = "Rota oficial" if str(vt.get("fonte", "")).startswith("OpenTripPlanner") else "Estimativa provisória"
                    st.caption(f"**{len(detalhes)}** trecho(s) • **{bal}** baldeação(ões) • {fonte_rota}")
                    # Linha de integração destacada
                    if bal > 0:
                        st.markdown(f"🔄 **Integração:** {bal} baldeação(ões) sugerida(s) — valide com o colaborador.")
                else:
                    st.warning("Nenhum trecho de transporte identificado para este trajeto.")

            # Alternativas de rota (mais rápida x mais econômica) — auditoria tarifária
            if (
                modalidade_atual in ("Vale-Transporte", "Comparativo Completo")
                and comparativo
                and comparativo.get("sucesso")
                and comparativo.get("rota_mais_rapida")
            ):
                rapida = comparativo["rota_mais_rapida"]
                economica = comparativo.get("rota_mais_economica")
                if economica:
                    st.divider()
                    st.markdown("##### 🔀 Alternativas de rota")
                    opcoes = ["Mais econômica", "Mais rápida"]
                    idx_default = 0 if st.session_state.get("rota_selecionada", "economica") == "economica" else 1
                    escolha = st.radio(
                        "Rota de referência para o relatório",
                        options=opcoes,
                        index=idx_default,
                        horizontal=True,
                        key="radio_comparativo",
                        label_visibility="collapsed",
                    )
                    st.session_state.rota_selecionada = "economica" if escolha == "Mais econômica" else "rapida"
                    rota_ref = economica if st.session_state.rota_selecionada == "economica" else rapida
                    st.caption(
                        f"{rota_ref.get('duracao_min', 0)} min • {rota_ref.get('distancia_km', 0)} km • "
                        f"{rota_ref.get('baldeacoes', 0)} baldeação(ões) • {rota_ref.get('caminhada_km', 0)} km a pé"
                    )
                    c_dia, c_mes, c_eco = st.columns(3)
                    c_dia.metric("Custo diário (ida + volta)", f"R$ {rota_ref.get('custo_diario', 0):.2f}")
                    c_mes.metric(f"Custo mensal ({dias_uteis_atual} dias)", f"R$ {rota_ref.get('custo_mensal', 0):.2f}")
                    c_eco.metric("Economia mensal (vs. mais rápida)", f"R$ {comparativo.get('economia_mensal', 0.0):.2f}")
                    if rota_ref.get("detalhamento_tarifario") or rota_ref.get("memoria_calculo"):
                        with st.expander("🧾 Memória de cálculo da tarifa", expanded=False):
                            for linha in rota_ref.get("detalhamento_tarifario", []):
                                st.markdown(f"- {linha}")
                            for memoria_item in rota_ref.get("memoria_calculo", []):
                                st.caption(f"• {memoria_item}")

            # Memória de cálculo dos dias úteis (escala, feriados e município)
            _cal_mem = st.session_state.get("memoria_calendario")
            if isinstance(_cal_mem, dict) and _cal_mem.get("dias_uteis") is not None:
                st.divider()
                with st.expander("📋 Memória de cálculo — dias úteis", expanded=False):
                    n_feriados = len(_cal_mem.get("feriados_descontados", []) or [])
                    st.caption(
                        f"Escala {_cal_mem.get('escala', '—')} • "
                        f"{_cal_mem.get('uf', '—')}/{_cal_mem.get('municipio_destino', '—')} • "
                        f"{int(_cal_mem.get('mes', 0) or 0):02d}/{int(_cal_mem.get('ano', 0) or 0)} • "
                        f"{int(_cal_mem.get('dias_uteis', dias_uteis_atual))} dias úteis "
                        f"({int(_cal_mem.get('dias_brutos', 0) or 0)} brutos - {n_feriados} feriados)"
                    )
                    for linha_cal in _cal_mem.get("memoria_calculo", []) or []:
                        st.caption(f"• {linha_cal}")
                    if _cal_mem.get("justificativa"):
                        st.caption(_cal_mem["justificativa"])

        # ---------------- Aba 2 — Relatório PDF ----------------
        with tab_pdf:
            st.markdown("#### 📄 Relatório PDF")
            # Resumo formatado
            vt = st.session_state.resultado_vt
            vc = st.session_state.resultado_vc

            # Bloco origem/destino
            st.markdown(
                f"""
                <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:12px;padding:14px 16px;margin-bottom:12px;">
                <b>Origem:</b> {st.session_state.origem_label}<br>
                <b>Destino:</b> {st.session_state.destino_label}<br>
                <b>Modalidade:</b> {modalidade_atual} &nbsp;•&nbsp; <b>Dias úteis:</b> {dias_uteis_atual}
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Tabela memória conforme modalidade
            if modalidade_atual == "Vale-Combustível" and vc:
                if vc.get("sucesso"):
                    mem = pd.DataFrame([
                        {"Item": "Distância do trajeto", "Valor": f"{vc.get('distancia_km')} km"},
                        {"Item": "Valor por KM", "Valor": f"R$ {vc.get('valor_km',0):.2f}"},
                        {"Item": "Custo diário (ida+volta)", "Valor": f"R$ {vc.get('custo_diario',0):.2f}"},
                        {"Item": f"Estimativa mensal ({dias_uteis_atual} dias)", "Valor": f"R$ {vc.get('custo_mensal',0):.2f}"},
                    ])
                    st.table(mem)
                else:
                    st.error("Não foi possível calcular o Vale-Combustível para este trajeto.")
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
                st.info("Não há dados suficientes para montar o relatório. Refaça o cálculo.")

            st.divider()
            # Geração do PDF (em memória)
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
                        "detalhamento_tarifario": vt.get("detalhamento_tarifario", []) if vt else [],
                        "memoria_calculo": (vt.get("memoria_calculo", []) if vt else []),
                        "justificativa": vt.get("justificativa", "") if vt else "",
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

            # --- Trilha auditável comum ao PDF: calendário e precisão geográfica ---
            _memoria_auditoria = list(dados_calc.get("memoria_calculo") or [])
            _cal_pdf = st.session_state.get("memoria_calendario")
            if isinstance(_cal_pdf, dict) and _cal_pdf.get("dias_uteis") is not None:
                _memoria_auditoria.append(
                    f"Calendário: escala {_cal_pdf.get('escala', '—')} • "
                    f"{_cal_pdf.get('uf', '—')}/{_cal_pdf.get('municipio_destino', '—')} • "
                    f"{int(_cal_pdf.get('mes', 0) or 0):02d}/{int(_cal_pdf.get('ano', 0) or 0)} • "
                    f"{int(_cal_pdf.get('dias_uteis', dias_uteis_atual))} dias úteis "
                    f"({int(_cal_pdf.get('dias_brutos', 0) or 0)} brutos - "
                    f"{len(_cal_pdf.get('feriados_descontados', []) or [])} feriados)"
                )
                _memoria_auditoria.extend(_cal_pdf.get("memoria_calculo", []) or [])
                if _cal_pdf.get("justificativa"):
                    _memoria_auditoria.append(_cal_pdf["justificativa"])
            _memoria_auditoria.extend(st.session_state.get("geo_auditoria") or [])
            if _memoria_auditoria:
                dados_calc["memoria_calculo"] = _memoria_auditoria

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
            except Exception:
                pass

            # Botão para gerar PDF (mantém em session_state)
            if st.button("📄 Gerar PDF", width='stretch'):
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
                    st.success("PDF gerado — pronto para download.")
                except Exception:
                    st.error("Não foi possível gerar o PDF. Tente novamente em instantes.")

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
                st.caption("Clique em **Gerar PDF** para habilitar o download.")

            # Exportação individual para portais de benefícios (mantida na aba de relatório)
            if st.session_state.resultado_vt or st.session_state.resultado_vc:
                st.divider()
                with st.expander("📤 Exportação individual para portais", expanded=False):
                    _layout_ind = st.radio(
                        "Layout de exportação",
                        options=["Padrão Compra (SPTrans/TOP)", "Rubrica Folha (eSocial/ERP)"],
                        index=0,
                        horizontal=True,
                        key="layout_individual",
                    )
                    try:
                        _valor_ind = float(
                            st.session_state.resultado_vt.get("custo_diario", 0)
                            if st.session_state.resultado_vt
                            else (st.session_state.resultado_vc or {}).get("custo_diario", 0) or 0
                        )
                        _dados_ind = [{
                            "matricula": "0001",
                            "nome": "Colaborador (simulação)",
                            "cpf": "12345678900",
                            "operadora": "SPTrans",
                            "codigo_linha": "—",
                            "valor_diario": _valor_ind,
                            "salario_base": st.session_state.get("salario_base", 0),
                        }]
                        _comp_ind = f"{int(st.session_state.get('mes_ref', datetime.now().month)):02d}/{int(st.session_state.get('ano_ref', datetime.now().year))}"
                        if _layout_ind == "Padrão Compra (SPTrans/TOP)":
                            _exp_ind = gerar_export_compra(_dados_ind, dias_uteis=int(dias_uteis_atual), competencia=_comp_ind)
                        else:
                            _exp_ind = gerar_export_rubrica(_dados_ind, dias_uteis=int(dias_uteis_atual), competencia=_comp_ind)
                        if _exp_ind.get("sucesso"):
                            st.caption(_exp_ind.get("justificativa", ""))
                            st.download_button(
                                "⬇️ Baixar exportação individual (CSV)",
                                data=_exp_ind["bytesio"].getvalue(),
                                file_name=_exp_ind["filename"],
                                mime="text/csv",
                                width='stretch',
                                key="download_individual_export",
                            )
                        else:
                            st.warning("Não foi possível gerar a exportação individual.")
                    except Exception:
                        st.warning("Exportação individual indisponível para esta simulação.")


if __name__ == "__main__":
    main()
