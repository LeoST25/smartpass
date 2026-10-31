import streamlit as st
from src.services.routing import calcular_vale_combustivel, roteirizar_vale_transporte_automatico
from src.services.geocoding import buscar_coordenadas_por_cep_ou_endereco
from src.services.pdf_generator import gerar_pdf_evidencia

# Configuração da página
st.set_page_config(
    page_title="SmartPass - Cálculo de Benefícios",
    page_icon="🚌",
    layout="wide"
)

st.title("SmartPass 🚌💳")
st.subheader("Painel de Admissão - Vale-Combustível & Vale-Transporte")
st.markdown("---")

# Sidebar - Dados da Admissão
st.sidebar.header("📋 Dados da Admissão")
nome_candidato = st.sidebar.text_input("Nome do Colaborador", value="João da Silva")
cargo = st.sidebar.text_input("Cargo / Função", value="Operador de Logística")
centro_custo = st.sidebar.text_input("Empresa / Centro de Custo", value="Cliente X")

dados_candidato = {
    "nome": nome_candidato,
    "cargo": cargo,
    "centro_custo": centro_custo
}

st.sidebar.markdown("---")
tipo_beneficio = st.sidebar.radio(
    "Selecione o Benefício:",
    ["Vale-Combustível (VC)", "Vale-Transporte (VT)"]
)

# Entrada Unificada de Origem e Destino
st.info("Informe o CEP ou Endereço de Origem e Destino do colaborador para cálculo do itinerário.")
col_o, col_d = st.columns(2)

with col_o:
    st.subheader("Origem (Residência)")
    busca_origem = st.text_input("CEP ou Endereço de Origem", value="06310-000")
    res_geo_origem = buscar_coordenadas_por_cep_ou_endereco(busca_origem) if busca_origem else None
    if res_geo_origem and res_geo_origem.get("sucesso"):
        lat_origem, lon_origem = res_geo_origem["lat"], res_geo_origem["lon"]
        st.caption(f"📍 **Localizado:** {res_geo_origem['endereco_encontrado']}")
    else:
        st.warning("Origem não localizada. Usando coordenadas padrão.")
        lat_origem, lon_origem = -23.5228, -46.8355

with col_d:
    st.subheader("Destino (Empresa/Unidade)")
    busca_destino = st.text_input("CEP ou Endereço de Destino", value="Avenida Paulista, 1000, São Paulo")
    res_geo_destino = buscar_coordenadas_por_cep_ou_endereco(busca_destino) if busca_destino else None
    if res_geo_destino and res_geo_destino.get("sucesso"):
        lat_destino, lon_destino = res_geo_destino["lat"], res_geo_destino["lon"]
        st.caption(f"📍 **Localizado:** {res_geo_destino['endereco_encontrado']}")
    else:
        st.warning("Destino não localizado. Usando coordenadas padrão.")
        lat_destino, lon_destino = -23.5505, -46.6333

coords = (lat_origem, lon_origem, lat_destino, lon_destino)
st.markdown("---")

# Abas de Cálculo
if tipo_beneficio == "Vale-Combustível (VC)":
    st.header("🚗 Cálculo de Vale-Combustível")
    valor_km = st.number_input("Valor do KM Contratado (R$)", value=1.25, step=0.05)
    
    if st.button("Calcular Vale-Combustível", type="primary"):
        res = calcular_vale_combustivel(lat_origem, lon_origem, lat_destino, lon_destino, valor_km)
        if res.get("sucesso"):
            st.success("Cálculo realizado com sucesso!")
            m1, m2 = st.columns(2)
            m1.metric("Distância (KM)", f"{res['distancia_km']} km")
            m2.metric("Custo Estimado (R$)", f"R$ {res['custo_total']:.2f}")

            dados_calculo = {
                "origem": res_geo_origem.get("endereco_encontrado", busca_origem) if res_geo_origem else busca_origem,
                "destino": res_geo_destino.get("endereco_encontrado", busca_destino) if res_geo_destino else busca_destino,
                "distancia_km": res["distancia_km"],
                "valor_km": valor_km,
                "custo_total": res["custo_total"]
            }

            pdf_bytes = gerar_pdf_evidencia(dados_candidato, "Vale-Combustível (VC)", dados_calculo, coords=coords)

            st.download_button(
                label="📄 Baixar Evidência com Mapa (PDF)",
                data=pdf_bytes,
                file_name=f"Evidencia_VC_{nome_candidato.replace(' ', '_')}.pdf",
                mime="application/pdf"
            )

else:
    st.header("🚌 Cálculo Automático de Vale-Transporte")
    
    if st.button("Calcular Itinerário de Vale-Transporte", type="primary"):
        endereco_origem = res_geo_origem.get("endereco_encontrado", busca_origem) if res_geo_origem else busca_origem
        endereco_destino = res_geo_destino.get("endereco_encontrado", busca_destino) if res_geo_destino else busca_destino
        res = roteirizar_vale_transporte_automatico(
            lat_origem, lon_origem, lat_destino, lon_destino, endereco_origem, endereco_destino
        )
        if res.get("sucesso"):
            st.success("Rota de transporte público identificada com sucesso!")
            if res.get("aviso"):
                st.warning(f"Roteirização inteligente indisponível: {res['aviso']}")
            
            m1, m2, m3 = st.columns(3)
            m1.metric("Distância do Trajeto", f"{res['distancia_km']} km")
            m2.metric("Custo Diário Total", f"R$ {res['custo_diario']:.2f}")
            m3.metric("Estimativa Mensal (22 dias)", f"R$ {res['custo_mensal']:.2f}")

            st.subheader("Resumo do trajeto")
            st.write(res["resumo_trajeto"])
            st.caption(f"Fonte da roteirização: {res['fonte']}")

            st.subheader("Linhas e Modais Sugeridos")
            st.table(res["detalhes"])

            dados_pdf = res.copy()
            dados_pdf["origem"] = endereco_origem
            dados_pdf["destino"] = endereco_destino

            pdf_bytes = gerar_pdf_evidencia(dados_candidato, "Vale-Transporte (VT)", dados_pdf, coords=coords)

            st.download_button(
                label="📄 Baixar Evidência com Mapa (PDF)",
                data=pdf_bytes,
                file_name=f"Evidencia_VT_{nome_candidato.replace(' ', '_')}.pdf",
                mime="application/pdf"
            )
