---
name: gis-routing-otp
description: Diretrizes para geocodificação, consultas ao OpenTripPlanner (OTP), dados GTFS e queries espaciais PostGIS no SmartPass.
---
# Regras de Roteirização e GIS (Região Metropolitana de São Paulo)

- **Validação Geográfica:** Antes de consultar o OTP ou salvar coordenadas, valide se `latitude` está entre `-24.1` e `-23.1` e `longitude` entre `-47.2` e `-45.7` (RMSP).
- **Resiliência de API:** Toda requisição HTTP ao OTP ou API de geocoding deve ter `timeout` explícito (máx. 10s), tratamento para `ConnectionError`/`Timeout` e fallback amigável sem quebrar a UI.
- **Regras de Tarifa e Integração:** Separar claramente o cálculo de tarifa unitária (Ônibus Municipal SPTrans, Intermunicipal EMTU, Trilhos CPTM/Metrô) da lógica de integração temporal (Bilhete Único / TOP).
- **Banco Espacial (PostGIS):** Sempre usar SRID `4326` para WGS84 e verificar a existência de índices `GIST` em colunas de geometria (`geom`).
