import streamlit as st
from src.services.routing import calcular_vale_combustivel, calcular_vale_transporte

# Configuração da página
st.set_page_config(
    page_title="SmartPass - Cálculo de Benefícios",
    page_icon="🚌",
    layout="wide"
)

st.title("SmartPass 🚌💳")
st.subheader("Painel de Admissão - Vale-Combustível & Vale-Transporte")
st.markdown("---")

# Sidebar - Dados do Candidato / Processo
st.sidebar.header("📋 Dados da Admissão")
nome_candidato = st.sidebar.text_input("Nome do Colaborador", placeholder="Ex: João da Silva")
cargo = st.sidebar.text_input("Cargo / Função", placeholder="Ex: Operador de Logística")
centro_custo = st.sidebar.text_input("Empresa / Centro de Custo", placeholder="Ex: Cliente X")

st.sidebar.markdown("---")
tipo_beneficio = st.sidebar.radio(
    "Selecione o Benefício:",
    ["Vale-Combustível (VC)", "Vale-Transporte (VT)"]
)

# Conteúdo Principal
if tipo_beneficio == "Vale-Combustível (VC)":
    st.header("🚗 Cálculo de Vale-Combustível")
    st.info("Insira as coordenadas ou os pontos para obter a distância rodoviária exata e o custo.")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Origem (Residência)")
        lat_origem = st.number_input("Latitude Origem", value=-23.5228, format="%.6f")
        lon_origem = st.number_input("Longitude Origem", value=-46.8355, format="%.6f")
        
    with col2:
        st.subheader("Destino (Empresa/Unidade)")
        lat_destino = st.number_input("Latitude Destino", value=-23.5505, format="%.6f")
        lon_destino = st.number_input("Longitude Destino", value=-46.6333, format="%.6f")
        
    valor_km = st.number_input("Valor do KM Contratado (R$)", value=1.25, step=0.05)
    
    if st.button("Calcular Vale-Combustível", type="primary"):
        res = calcular_vale_combustivel(lat_origem, lon_origem, lat_destino, lon_destino, valor_km)
        
        if res.get("sucesso"):
            st.success("Cálculo realizado com sucesso!")
            m1, m2 = st.columns(2)
            m1.metric("Distância (KM)", f"{res['distancia_km']} km")
            m2.metric("Custo Estimado (R$)", f"R$ {res['custo_total']:.2f}")
        else:
            st.error(f"Erro no cálculo: {res.get('erro')}")

else:
    st.header("🚌 Cálculo de Vale-Transporte")
    st.info("Informe os dados do itinerário e valores das passagens diárias.")
    
    # Simulação simples de entrada de linhas
    num_linhas = st.number_input("Quantidade de linhas/modais utilizados (Ida e Volta)", min_value=1, max_value=6, value=2)
    
    linhas = []
    for i in range(int(num_linhas)):
        st.markdown(f"**Linha {i+1}**")
        c1, c2, c3 = st.columns([3, 2, 2])
        nome_linha = c1.text_input(f"Nome da Linha/Modal", value=f"Linha {i+1}", key=f"linha_{i}")
        valor_tarifa = c2.number_input(f"Valor da Tarifa (R$)", value=5.00, key=f"valor_{i}")
        qtd_dia = c3.number_input(f"Viagens/Dia", value=2, key=f"qtd_{i}")
        
        linhas.append({"linha": nome_linha, "valor": valor_tarifa, "quantidade_dia": qtd_dia})
        
    if st.button("Calcular Vale-Transporte", type="primary"):
        res = calcular_vale_transporte(linhas)
        st.success("Cálculo realizado com sucesso!")
        
        m1, m2 = st.columns(2)
        m1.metric("Custo Diário Total", f"R$ {res['custo_diario']:.2f}")
        m2.metric("Custo Mensal Estimado (22 dias)", f"R$ {res['custo_mensal']:.2f}")
        
        st.subheader("Detalhamento por Linha")
        st.table(res["detalhes"])