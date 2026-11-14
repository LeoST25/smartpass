# Pull Request — SmartPass (template corporativo)

> **Preencha todos os campos. PRs com checklist incompleto são bloqueados pelo `@guardian` (`.opencode/agents/guardian.md`). Fluxo obrigatório: `Plan → Build → pytest → @guardian → PR para dev` (`AGENTS.md:6`, `.opencode/skills/enterprise-workflow/SKILL.md`).**

---

## 1 — Resumo da Entrega

<!-- Descreva em 3–6 linhas: problema, solução, impacto. Inclua link da issue/task se houver. -->

- **Contexto:**
- **Solução:**
- **Impacto / Risco:**

**Branch:** `<!-- feat/<slug> | fix/<slug> | chore/<slug> a partir de dev -->`
**Base:** `dev` <!-- nunca staging/main direto -->

---

## 2 — Tipo de Mudança

<!-- Marque exatamente um. -->

- [ ] `feat:` — Nova funcionalidade / regra de negócio
- [ ] `fix:` — Correção de bug
- [ ] `refactor:` — Refatoração sem mudança de comportamento
- [ ] `chore:` — Infra, CI, docs, workflow
- [ ] `docs:` — Documentação apenas
- [ ] `test:` — Testes apenas

**Escopo principal:** `<!-- ex.: src/services/routing.py, src/app.py, infra/* -->`

---

## 3 — Critérios de Aceite Validados

<!-- Liste critérios do Plan e marque os atendidos. Ex.: “Dado CEP 06310-000, quando calcula VT, então retorna 2 trechos + memória de cálculo”. -->

- [ ] Critério 1:
- [ ] Critério 2:
- [ ] Critério 3:
- [ ] Arquitetura: nova regra em `src/services/` com docstring tipada + `{"sucesso": True/False}` + `try/except` + `timeout` + fallback (antes de plugar em `src/app.py`)
- [ ] Observabilidade: `memoria_calculo`/`justificativa` gerada (tarifa, integração, CLT 6%, precisão geográfica) e exibida na UI + PDF

---

## 4 — Evidências de Testes

### 4.1 pytest (obrigatório)

<!-- Cole saída de `pytest -v -k "not integration"` — deve estar 100% passed. Anexe também quando houver testes de integração (`-k integration`). -->

```bash
pytest -v -k "not integration"
# cole saída completa aqui
```

- [ ] `pytest -v -k "not integration"` ✅ — todos passed
- [ ] Novos testes em `tests/test_*.py` cobrindo **caminho feliz**, **bordas** e **falhas** com `unittest.mock` (sem chamadas reais de rede)
- [ ] Testes de integração separados com `@pytest.mark.integration` (se aplicável)

**Arquivos de teste adicionados/alterados:**
<!-- ex.: tests/test_calculo_clt.py -->

### 4.2 Playwright — Validação Visual (quando há mudança em `src/app.py` ou UI)

<!-- Suba o Streamlit em background, abra via MCP Playwright, execute fluxo ponta a ponta, capture screenshot e verifique console. -->

- [ ] Não se aplica (sem mudança visual) **ou**
- [ ] Streamlit em background + Playwright MCP: fluxo ponta a ponta executado
- [ ] Screenshot anexado (ou link do artefato)
- [ ] Console sem erros (anexar log filtrado)

**Comando de referência:**
```bash
streamlit run src/app.py --server.headless true &
# via MCP playwright: navigate → fill origem/destino → click Calcular → screenshot → check console
```

---

## 5 — Checklist LGPD / Segurança / Qualidade

### LGPD / Stateless (bloqueante — ver `.opencode/agents/guardian.md:56`)

- [ ] Zero persistência de dados de candidato em disco ou banco fora da sessão
- [ ] PDFs e mapas gerados exclusivamente em `io.BytesIO` (nunca `open(..., "wb")` em disco) — `src/services/pdf_generator.py`, `src/services/map_generator.py`
- [ ] Nenhum `open(..., "w")`, `Path.write`, `to_csv`/`to_excel`, `pickle.dump` fora de `/tmp` ou `BytesIO` em `src/services/` e `src/database/` (validado por `pr-guardian.yml:82` disk-guard)
- [ ] Dados mantidos apenas em `st.session_state` / memória; sem `INSERT` de dados pessoais

### Segurança — Zero segredos

- [ ] Nenhum hardcode de credenciais (`DB_*`, `SPTRANS_API_*`, `OTP_*`, `GITHUB_*` etc.) — uso exclusivo de `os.getenv` / `dotenv`
- [ ] `git ls-files | grep "^\.env$"` vazio (`.env` em `.gitignore:4`); `.env.example` sincronizado apenas com placeholders (`changeme`, `seu_valor_aqui`)
- [ ] `gitleaks detect --source . --no-git -v` ou `gitleaks/gitleaks-action@v2` sem achados; verificação de padrões de segredo no diff sem achados
- [ ] Nenhum segredo no título/corpo do PR ou em `opencode.json`

### Qualidade

- [ ] `python -m py_compile src/app.py && python -m compileall src/` sem erros
- [ ] `@st.cache_data` para geocodificação/rotas e `@st.cache_resource` para PostGIS quando aplicável
- [ ] `flake8 --select=E9,F63,F7,F82` sem erros críticos (ou justificativa)

---

## 6 — Auditoria & Rastreabilidade

- [ ] `AGENTS.md` / `.clinerules` respeitados (ponto de entrada único, isolamento de serviços, resiliência)
- [ ] Branch `feat/*|fix/*|chore/*` criada a partir de `dev` — sem commit direto em `dev`/`staging`/`main` (`git branch --show-current` + `git log --oneline origin/dev..HEAD`)
- [ ] Fluxo `Plan → Build → pytest → @guardian → PR para dev` seguido — `@guardian` acionado localmente com relatório `✅ PASS` em todos os itens 1–4

**Relatório @guardian (cole resumo):**
<!-- | # | Item | Status | Evidência | ... | Veredito: APROVADO/REPROVADO | -->

---

## 7 — Notas para Revisão / Deploy

<!-- Observações para revisor, flags, necessidade de migração, variáveis de ambiente novas. -->

-
