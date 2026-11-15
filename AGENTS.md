# SmartPass — Diretrizes do Projeto e Arquitetura

## Visão Geral
Sistema de cálculo automatizado de rotas de transporte público, geocodificação, análise de benefícios (Vale-Transporte) e geração de relatórios em PDF com mapas interativos.

## Stack Tecnológica
- **Frontend UI:** Streamlit (Python 3.12+) — `src/app.py` (ponto único da UI)
- **API REST:** FastAPI (Python 3.12+) — `src/api/main.py` (entry point: `uvicorn src.api.main:app`)
- **Frontend React/Tailwind:** Futuro consumidor da API REST (React/Tailwind em `frontend/`)
- **Backend / Core:** Python (`src/services/*`) — lógica de negócio isolada, sem dependência de Streamlit
- **Banco de Dados:** PostgreSQL + PostGIS (`src/database/connection.py`)
- **Motor de Roteirização:** OpenTripPlanner (OTP) + dados GTFS + APIs externas de trânsito/geocoding
- **Infraestrutura:** Docker & Docker Compose (`infra/docker-compose.yml`)

## Regras Rígidas de Engenharia
1. **Ponto de Entrada Único UI:** Consolidar a interface Streamlit em `src/app.py` (ou `app.py` na raiz) — nunca manter dois arquivos `app.py` concorrentes. `src/api/main.py` é o entry point da API REST, não da UI.
2. **Isolamento de Serviços:** Toda lógica de negócio, chamadas de API e queries SQL devem ficar em `src/services/` e `src/database/`. O arquivo Streamlit (`src/app.py`) e a API (`src/api/`) contêm apenas estado de sessão / componentes visuais / schemas Pydantic e chamadas aos serviços. **Proibido:** `import streamlit` em `src/services/` ou `src/database/`.
3. **Resiliência e Cache Agnóstico:** Usar `cachetools.TTLCache` com TTLs canônicos (3600s geocoding, 600s routing/OTP/mapa) via `src/services/cache.py` (decorators `@st_cache_data` / `@st_cache_resource` compatíveis com Streamlit). Nunca usar `@st.cache_data` / `@st.cache_resource` diretamente em services/database. Sempre implementar fallback e tratamento de timeout nas chamadas ao OTP e APIs externas.
4. **Testes:** Todo script `teste_*.py` deve ser migrado e padronizado para `tests/test_*.py` usando `pytest` com mocks para chamadas de rede. `tests/test_api.py` cobre endpoints FastAPI via `TestClient`.
5. **Segurança:** Nunca hardcodar chaves de API ou senhas de banco. Usar variáveis de ambiente via `.env` e manter `.env.example` sempre sincronizado.
6. **Fluxo Corporativo Obrigatório (Enterprise Workflow):** Toda entrega DEVE seguir o ciclo `Plan → Build → pytest → @guardian → PR para dev` definido em `.opencode/skills/enterprise-workflow/SKILL.md`. Branching: nunca commitar direto em `dev`, `staging` ou `main`; toda tarefa nasce em `feat/<slug>`, `fix/<slug>` ou `chore/<slug>` a partir de `dev`. Arquitetura & TDD: nova regra nasce primeiro em `src/services/` com docstrings tipadas e testes em `tests/` (feliz/bordas/falhas) antes de plugar em `src/app.py` ou `src/api/routes.py`. Observabilidade & Auditoria: toda decisão de cálculo (tarifa, integração, CLT 6%, precisão geográfica) deve gerar `memoria_calculo`/`justificativa` exibida na UI e no PDF, mantendo zero persistência em disco (LGPD stateless — `BytesIO`/`st.session_state`/`UploadFile` apenas). Template padrão de PR em `.github/pull_request_template.md`; auditoria bloqueante via `@guardian` (`.opencode/agents/guardian.md`) e workflows `.github/workflows/pr-guardian.yml` + `.github/workflows/ci-cd.yml`.