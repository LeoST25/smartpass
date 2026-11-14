---
name: qa-performance-audit
description: Checklist de testes automatizados com pytest, auditoria de latência e validação visual via Playwright MCP.
---
# Regras de QA, Testes e Performance

- **Isolamento de Testes:** Todos os testes devem residir em `tests/test_*.py` usando `pytest`. Chamadas externas (OTP, Geocoding) devem ter testes unitários com `unittest.mock` e testes de integração marcados com `@pytest.mark.integration`.
- **Telemetria:** Medir tempo de execução das etapas críticas (geocoding + roteirização + PDF) usando `time.perf_counter()` e registrar no log.
- **Validação Visual:** Sempre que alterar `app.py` ou componentes visuais, subir o Streamlit em background, abrir via MCP `playwright`, executar uma busca de ponta a ponta, capturar screenshot e verificar se há erros no console.
