---
name: pdf-map-reporting
description: Padrões para renderização de mapas leves e geração de relatórios PDF de Vale-Transporte sem bloquear o Streamlit.
---
# Regras de Mapas e Geração de PDF

- **Performance Visual:** Evitar renderizar milhares de pontos vetoriais pesados no Folium/PyDeck. Simplificar polilinhas de rotas quando necessário para manter o carregamento abaixo de 2 segundos.
- **Estrutura do Relatório PDF:** Todo PDF gerado em `pdf_generator.py` deve conter: cabeçalho com identificação da consulta, origem/destino geocodificados, tabela resumo (tarifa por trecho, total diário ida/volta, total mensal para 22 dias úteis) e itinerário passo a passo.
- **Memória:** Gerar arquivos PDF em buffer de memória (`io.BytesIO`) em vez de gravar arquivos temporários soltos na raiz do projeto.
