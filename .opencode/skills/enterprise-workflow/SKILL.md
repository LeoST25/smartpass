---
name: enterprise-workflow
description: Fluxo corporativo obrigatório de entrega SmartPass — branching, TDD, observabilidade e auditoria LGPD stateless.
---

# Enterprise Workflow — Ciclo de Vida Obrigatório de Entrega (SmartPass)

> **Skill corporativa canônica.** Toda entrega neste repositório DEVE seguir este fluxo. Desvios são bloqueados pelo `@guardian` (`.opencode/agents/guardian.md`) e pelo CI (`.github/workflows/pr-guardian.yml`, `.github/workflows/ci-cd.yml`). Referência normativa em `AGENTS.md:6`.

## Fluxo obrigatório (Plan → Build → pytest → @guardian → PR)

```
Plan → Build → pytest → @guardian → PR para dev
```

1. **Plan** — Definir escopo, critérios de aceite e impacto LGPD/stateless antes de codar. Registrar decisão em issue/PR description.
2. **Build** — Implementar seguindo as regras abaixo (Branching + Arquitetura & TDD + Observabilidade).
3. **pytest** — Rodar `pytest -v -k "not integration"` localmente; todos os testes novos devem passar com mocks para rede. Falha = bloqueio.
4. **@guardian** — Acionar o agente auditor (`@guardian`) para varredura completa: `AGENTS.md`/`.clinerules`, LGPD stateless (`BytesIO`/`/tmp` apenas), zero segredos (gitleaks), qualidade (`py_compile` + `compileall`). Só avançar se `✅ PASS` em todos os itens 1–4.
5. **PR para dev** — Abrir PR via `gh pr create --base dev` a partir da branch `feat/*`, `fix/*` ou `chore/*`. Nunca fazer push direto em `dev`, `staging` ou `main`.

---

## 1 — Branching (bloqueante)

- **Nunca commitar direto em `dev`, `staging` ou `main`.** Essas branches são protegidas; recebem apenas merges via Pull Request.
- **Toda tarefa nasce a partir de `dev`:**
  ```bash
  git fetch origin dev
  git checkout dev
  git pull origin dev
  git checkout -b feat/<slug>   # nova feature
  # ou
  git checkout -b fix/<slug>    # correção
  git checkout -b chore/<slug>  # infra/docs/workflow
  ```
- **Naming:** `feat/<slug-kebab-case>`, `fix/<slug>`, `chore/<slug>` — slug curto, descritivo (ex.: `chore/enterprise-workflow`, `feat/calculo-clt-6pct`).
- ** commits semânticos:** `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`, `test:` conforme `.clinerules:13`.
- **Sincronização:** Antes do PR, fazer `git fetch origin dev && git rebase origin/dev` (ou merge) para evitar divergência.

> **Verificação @guardian:** `git branch --show-current` deve retornar `feat/*|fix/*|chore/*`; `git diff --name-only origin/dev...HEAD` não pode conter push direto em `dev`/`main`.

---

## 2 — Arquitetura & TDD (bloqueante)

### 2.1 Isolamento de camadas

- **Toda nova regra de negócio nasce em `src/services/`** (ou `src/database/` para queries PostGIS). `src/app.py` contém **apenas** `st.session_state`, componentes visuais e chamadas aos serviços (`AGENTS.md:2`).
- **Proibido:** SQL, `requests.*`, cálculo de tarifa ou geocoding direto em `src/app.py` — extrair para serviço.

### 2.2 Docstrings tipadas

Toda função pública em `src/services/` deve ter:

```python
def calcular_vale_transporte(linhas: list[dict]) -> dict:
    """Calcula VT com regra de integração e CLT 6%.

    Args:
        linhas: Lista de trechos com `linha`, `valor_unitario`, `quantidade_dia`.

    Returns:
        dict: {"sucesso": bool, "custo_diario": float, "custo_mensal": float,
               "detalhes": list, "memoria_calculo": list[str], "justificativa": str}
               Em falha: {"sucesso": False, "erro": str, "memoria_calculo": [...]}
    """
```

- Tipagem obrigatória nos args/return; docstring descreve contrato e dicionário padronizado com chave `"sucesso": True/False` (`.clinerules:9`).
- `try/except` + fallback em toda chamada externa (OTP, Nominatim, ViaCEP, OSRM) com `timeout` explícito (máx. 10s).

### 2.3 TDD — testes primeiro

- **Ordem obrigatória:** `src/services/<novo>.py` → `tests/test_<novo>.py` → só então plugar em `src/app.py`.
- **Cobertura mínima por regra:**

  | Caminho | Exemplo |
  |---------|---------|
  | **Feliz** | tarifa válida, CEP dentro da RMSP, integração Bilhete Único aplicada |
  | **Bordas** | tarifa zero, 0 dias úteis, CEP limite `-24.1/-23.1`, `-47.2/-45.7`, 31 dias |
  | **Falhas** | OTP timeout, geocoding 404, ViaCEP inválido, PostGIS offline |

- **Localização:** `tests/test_*.py` com `pytest` + `unittest.mock` para rede; testes de integração marcados com `@pytest.mark.integration` (`tests/conftest.py`).
- **Execução canônica:** `pytest -v -k "not integration"` deve passar sem erros.

---

## 3 — Observabilidade & Auditoria (LGPD stateless)

### 3.1 Trilha explicável obrigatória

Toda decisão de cálculo deve gerar **trilha auditável** exibida na UI e no PDF:

- **Tarifa aplicada** (unitária, integração temporal Bilhete Único/TOP)
- **Regra CLT 6%** (desconto máximo sobre salário-base, quando aplicável)
- **Nível de precisão geográfica** (`CEP exato` vs `endereço aproximado` vs `fallback estimado` — ver `src/services/geocoding.py`)
- **Fonte da rota** (`OTP GTFS` vs `OSRM` vs `estimativa de contingência`)

**Contrato de retorno (estendido):**

```python
{
  "sucesso": True,
  "custo_diario": 8.80,
  "custo_mensal": 193.60,
  "detalhes": [...],
  "memoria_calculo": [
    "Tarifa SPTrans R$ 5,00 aplicada (1 integração Bilhete Único 3h)",
    "Regra CLT 6%: teto R$ 180,00 sobre salário R$ 3.000,00 — valor devido R$ 180,00",
    "Precisão geográfica: CEP 06310-000 (ViaCEP) → Nominatim lat -23.52, lon -46.84 (alta)",
    "Fonte rota: OTP GTFS (2 trechos, 1 baldeação)"
  ],
  "justificativa": "Cálculo considera integração temporal e teto CLT; geocodificação de alta precisão."
}
```

### 3.2 Exibição e PDF

- **Tela (`src/app.py`):** renderizar `memoria_calculo`/`justificativa` em expander ou tabela na aba `📄 Relatório PDF` / `🗺️ Mapa & Itinerário` antes do botão de download.
- **PDF (`src/services/pdf_generator.py`):** incluir seção **"Memória de Cálculo / Auditoria"** com cada item da trilha; usar `io.BytesIO` exclusivamente — nunca `open(..., "wb")` em disco.

### 3.3 LGPD stateless — zero persistência

- **Proibido:** `open(..., "w")`, `Path.write_text`, `to_csv`/`to_excel` em disco, `pickle.dump`, `plt.savefig("arquivo.png")` fora de `/tmp` ou `BytesIO`.
- **Permitido apenas:** `io.BytesIO`, `io.StringIO`, `/tmp/*`, `st.session_state`.
- **Validação:** workflow `pr-guardian.yml:82` (disk-guard) e script local em `.opencode/agents/guardian.md:62` bloqueiam PR com escrita fora de `/tmp`.

---

## Checklist de entrega (usar no PR)

- [ ] Branch `feat/*|fix/*|chore/*` criada a partir de `dev` — sem commit direto em `dev`/`staging`/`main`
- [ ] Regra em `src/services/` com docstring tipada + `{"sucesso": bool}` + `try/except` + `timeout` + fallback
- [ ] Testes em `tests/test_*.py` cobrindo feliz/bordas/falhas (com mocks) — `pytest -v -k "not integration"` ✅
- [ ] `memoria_calculo`/`justificativa` gerada e exibida na UI e no PDF (via `BytesIO`)
- [ ] Nenhuma escrita em disco fora de `/tmp`; PDF/mapa em `BytesIO`; `.env` não rastreado; zero segredos
- [ ] `@guardian` acionado localmente e CI `pr-guardian.yml` + `ci-cd.yml` verdes
- [ ] PR aberto com template `.github/pull_request_template.md` preenchido, `--base dev`

---

## Referências cruzadas

- `AGENTS.md:6` — Fluxo obrigatório Plan → Build → pytest → @guardian → PR para dev
- `.opencode/agents/guardian.md` — Checklist bloqueante (AGENTS, LGPD, segredos, pytest, `gh pr create`)
- `.github/pull_request_template.md` — Template padrão de PR corporativo
- `.clinerules:9` — Contrato `{"sucesso": True/False}` para `src/services/`
- `.github/workflows/pr-guardian.yml` — Auditoria automatizada (gitleaks, disk-guard, pytest)
- `.github/workflows/ci-cd.yml` — Test & Lint & Build + deploy `staging`/`main`
