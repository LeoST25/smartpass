# SmartPass — Diretrizes do Projeto e Arquitetura

## Visão Geral
Sistema de cálculo automatizado de rotas de transporte público, geocodificação, análise de benefícios (Vale-Transporte) e geração de relatórios em PDF com mapas interativos.

## Stack Tecnológica
- **Frontend:** Streamlit (Python 3.12+)
- **Backend / Core:** Python (`src/services/*`)
- **Banco de Dados:** PostgreSQL + PostGIS (`src/database/connection.py`)
- **Motor de Roteirização:** OpenTripPlanner (OTP) + dados GTFS + APIs externas de trânsito/geocoding
- **Infraestrutura:** Docker & Docker Compose (`infra/docker-compose.yml`)

## Regras Rígidas de Engenharia
1. **Ponto de Entrada Único:** Consolidar a interface em `src/app.py` (ou `app.py` na raiz) — nunca manter dois arquivos `app.py` concorrentes.
2. **Isolamento de Serviços:** Toda lógica de negócio, chamadas de API e queries SQL devem ficar em `src/services/` e `src/database/`. O arquivo Streamlit deve conter apenas estado de sessão (`st.session_state`), componentes visuais e chamadas aos serviços.
3. **Resiliência e Cache:** Usar `@st.cache_data` para geocodificação e consultas de rotas repetidas, e `@st.cache_resource` para pools de conexão com PostGIS. Sempre implementar fallback e tratamento de timeout nas chamadas ao OTP e APIs externas.
4. **Testes:** Todo script `teste_*.py` deve ser migrado e padronizado para `tests/test_*.py` usando `pytest` com mocks para chamadas de rede.
5. **Segurança:** Nunca hardcodar chaves de API ou senhas de banco. Usar variáveis de ambiente via `.env` e manter `.env.example` sempre sincronizado.