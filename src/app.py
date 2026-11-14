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

from src.services.geocoding import buscar_coordenadas_por_cep_ou_endereco
from src.services.map_generator import gerar_imagem_mapa_rota
from src.services.pdf_generator import gerar_pdf_evidencia
from src.services.routing import calcular_vale_combustivel, calcular_vale_transporte, roteirizar_vale_transporte_automatico


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
        "pdf_buffer": None,
        "ultimo_calculo_em": None,
        "batch_df": None,
        "batch_resultados": None,
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


def _recalcular_vt_com_parametros(resultado_vt: dict, tarifa: float, dias_uteis: int) -> dict:
    """Recalcula custo VT com tarifa e dias úteis informados pelo usuário."""
    if not resultado_vt or not resultado_vt.get("sucesso"):
        return resultado_vt
    linhas = resultado_vt.get("detalhes") or []
    # Se não há detalhes (fallback vazio), cria linha única com tarifa
    if not linhas:
        linhas_src = resultado_vt.get("linhas") or [{"linha": "Transporte público", "valor_unitario": tarifa, "quantidade_dia": 2}]
    else:
        linhas_src = [{"linha": d.get("linha", "Linha"), "valor_unitario": tarifa, "quantidade_dia": d.get("quantidade_dia", 2)} for d in linhas]

    recalc = calcular_vale_transporte(linhas_src)
    # Ajusta mensal pelos dias úteis reais
    recalc["custo_mensal"] = round(recalc["custo_diario"] * dias_uteis, 2)
    # Mantém demais campos
    novo = {**resultado_vt, **recalc}
    # Atualiza detalhes com nova tarifa
    novo["detalhes"] = recalc["detalhes"]
    return novo


def _processar_calculo(origem_txt, destino_txt, modalidade, dias_uteis, tarifa, valor_km):
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

    if modalidade in ("Vale-Transporte", "Comparativo Completo"):
        vt_raw = roteirizar_vale_transporte_automatico(lat_o, lon_o, lat_d, lon_d, endereco_origem, endereco_destino)
        # Recalcula com parâmetros do usuário
        resultado_vt = _recalcular_vt_com_parametros(vt_raw, tarifa, dias_uteis)

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
        {"sucesso": True, "principal": principal, "vt": resultado_vt, "vc": resultado_vc},
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
            c1, c2 = st.columns(2)
            with c1:
                dias_input = st.number_input("Dias úteis no mês", min_value=1, max_value=31, value=int(st.session_state.dias_uteis), step=1)
            with c2:
                tarifa_input = st.number_input(
                    "Tarifa unitária / Integração (R$)",
                    min_value=0.0,
                    value=float(st.session_state.tarifa),
                    step=0.10,
                    format="%.2f",
                    help="Usada para recalcular VT quando OTP retorna tarifa padrão.",
                )
            valor_km_input = st.number_input(
                "Valor por KM — Vale-Combustível (R$)",
                min_value=0.0,
                value=float(st.session_state.valor_km),
                step=0.05,
                format="%.2f",
                help="Aplicado apenas em VC e Comparativo. Ex: R$ 1,25/km",
            )

            st.markdown("")
            submitted = st.form_submit_button("🔍 Calcular Rota e Benefício", width='stretch', type="primary")

        # Ações de limpeza
        if st.button("🧹 Limpar Simulação", width='stretch'):
            for k in ["resultado", "resultado_vt", "resultado_vc", "coords", "pdf_buffer", "batch_df", "batch_resultados"]:
                st.session_state[k] = None
            st.session_state["ultimo_calculo_em"] = None
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
                                resultados_lote.append({"linha": idx + 1, "origem": str(origem_lote), "destino": str(destino_lote), "erro": "Origem/Destino ausente"})
                                continue
                            # Cálculo simplificado: usa VT
                            try:
                                res_geo_o = buscar_coordenadas_por_cep_ou_endereco(str(origem_lote))
                                res_geo_d = buscar_coordenadas_por_cep_ou_endereco(str(destino_lote))
                                if not res_geo_o.get("sucesso") or not res_geo_d.get("sucesso"):
                                    resultados_lote.append({"linha": idx + 1, "origem": str(origem_lote), "destino": str(destino_lote), "erro": "Geocodificação falhou"})
                                    continue
                                vt = roteirizar_vale_transporte_automatico(
                                    res_geo_o["lat"], res_geo_o["lon"], res_geo_d["lat"], res_geo_d["lon"], str(origem_lote), str(destino_lote)
                                )
                                vt_adj = _recalcular_vt_com_parametros(vt, float(tarifa_input), int(dias_input))
                                resultados_lote.append({
                                    "linha": idx + 1,
                                    "origem": str(origem_lote),
                                    "destino": str(destino_lote),
                                    "distancia_km": vt_adj.get("distancia_km"),
                                    "custo_diario": vt_adj.get("custo_diario"),
                                    "custo_mensal": vt_adj.get("custo_mensal"),
                                    "fonte": vt_adj.get("fonte"),
                                })
                            except Exception as exc:
                                resultados_lote.append({"linha": idx + 1, "origem": str(origem_lote), "destino": str(destino_lote), "erro": str(exc)})
                            progresso.progress(int(((idx + 1) / len(df)) * 100))

                        st.session_state.batch_resultados = resultados_lote
                        if resultados_lote:
                            df_res = pd.DataFrame(resultados_lote)
                            st.dataframe(df_res, width='stretch', height=260)
                            # Download em memória
                            csv_buf = io.StringIO()
                            df_res.to_csv(csv_buf, index=False)
                            st.download_button(
                                "⬇️ Baixar resultado do lote (CSV)",
                                data=csv_buf.getvalue().encode("utf-8"),
                                file_name=f"smartpass_lote_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                                mime="text/csv",
                                width='stretch',
                            )
                        progresso.empty()
                except Exception as exc:
                    st.error(f"Falha ao ler arquivo: {exc}")
            else:
                # Modelo para download — gerado em memória
                st.markdown("**Modelo de planilha:**")
                modelo = pd.DataFrame([
                    {"nome": "Maria Silva", "origem": "06310-000", "destino": "Avenida Paulista, 1000, São Paulo"},
                    {"nome": "João Souza", "origem": "04538-132", "destino": "Rua Funchal, 418, São Paulo"},
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
                st.caption("Colunas obrigatórias: **origem**, **destino**. Opcional: **nome**.")

        st.divider()
        st.caption("🔒 **LGPD / Stateless:** nenhum dado persiste em banco. PDFs e mapas são gerados em `BytesIO` e mantidos apenas em `st.session_state`.")

    # ===================== PROCESSAMENTO DO FORM =====================
    if submitted:
        # Validação rápida
        if not origem_input.strip() or not destino_input.strip():
            st.toast("Informe origem e destino.", icon="⚠️")
            st.error("Preencha origem e destino para calcular.")
        else:
            with st.spinner("🔎 Geocodificando endereços e roteirizando via OTP/OSRM…"):
                try:
                    payload, coords, origem_label, destino_label, geos = _processar_calculo(
                        origem_input.strip(),
                        destino_input.strip(),
                        modalidade_input,
                        int(dias_input),
                        float(tarifa_input),
                        float(valor_km_input),
                    )
                    if not payload.get("sucesso"):
                        st.error(payload.get("erro", "Falha no cálculo."))
                    else:
                        # Persiste tudo em session_state (stateless)
                        st.session_state.resultado = payload["principal"]
                        st.session_state.resultado_vt = payload["vt"]
                        st.session_state.resultado_vc = payload["vc"]
                        st.session_state.coords = coords
                        st.session_state.origem_label = origem_label
                        st.session_state.destino_label = destino_label
                        st.session_state.modalidade = modalidade_input
                        st.session_state.dias_uteis = int(dias_input)
                        st.session_state.tarifa = float(tarifa_input)
                        st.session_state.valor_km = float(valor_km_input)
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

        # Aviso de fallback se houver
        if resultado.get("aviso"):
            st.warning(f"ℹ️ {resultado.get('aviso')} — Fonte: **{resultado.get('fonte','—')}**")
        elif resultado.get("fonte"):
            st.caption(f"Fonte da roteirização: **{resultado.get('fonte')}**  •  Atualizado em {st.session_state.ultimo_calculo_em.strftime('%d/%m/%Y %H:%M') if st.session_state.ultimo_calculo_em else ''}")

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
                    # Tabela + baldeações
                    df_det = pd.DataFrame(detalhes)
                    # Normaliza colunas para exibição
                    col_map = {"linha": "Linha / Modal", "valor_unitario": "Tarifa (R$)", "quantidade_dia": "Qtd/dia", "subtotal": "Subtotal (R$)"}
                    df_show = df_det.rename(columns=col_map)
                    st.dataframe(df_show, width='stretch', hide_index=True)
                    bal = max(len(detalhes) - 1, 0)
                    st.caption(f"**{len(detalhes)}** trecho(s) • **{bal}** baldeação(ões) • Fonte: **{vt.get('fonte','—')}**")
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
            # Escolhe dados_calculo conforme modalidade
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
                # Comparativo: usa VT como base, anexa VC no resumo
                dados_calc = {
                    "origem": st.session_state.origem_label,
                    "destino": st.session_state.destino_label,
                    "resumo_trajeto": (vt.get("resumo_trajeto","") if vt else "") + (f" | VC: {vc.get('distancia_km')}km, R$ {vc.get('custo_diario',0):.2f}/dia" if vc else ""),
                    "detalhes": vt.get("detalhes", []) if vt else [],
                    "custo_diario": vt.get("custo_diario",0) if vt else 0,
                    "custo_mensal": vt.get("custo_mensal",0) if vt else 0,
                    "distancia_km": vt.get("distancia_km",0) if vt else 0,
                }

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

            # Batch resultados se houver
            if st.session_state.batch_resultados:
                st.divider()
                st.markdown("##### 📦 Resultado do lote (último processamento)")
                st.dataframe(pd.DataFrame(st.session_state.batch_resultados), width='stretch')

    # Footer
    st.divider()
    st.caption("SmartPass • Stateless & LGPD • PDFs e mapas em BytesIO • Cache: `@st.cache_data` (geocoding/rotas) e `@st.cache_resource` (DB) • Fallback resiliente para OTP/PostGIS")


if __name__ == "__main__":
    main()
