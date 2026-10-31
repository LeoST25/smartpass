# Dados do OpenTripPlanner

Coloque nesta pasta, antes de iniciar o container, os feeds GTFS compactados e
um extrato OSM da Região Metropolitana de São Paulo:

```text
infra/otp-data/
├── sptrans.zip
├── artesp.zip
└── sao-paulo-latest.osm.pbf
```

- Obtenha o GTFS da SPTrans na área de desenvolvedores, com o cadastro da
  organização.
- Baixe o GTFS da ARTESP no portal de dados abertos.
- Baixe o `.osm.pbf` correspondente à RMSP no Geofabrik ou fonte compatível.

O OTP cria `graph.obj` nesta pasta na primeira execução. Não versione os feeds
nem o grafo, pois eles podem conter muitos dados e devem ser atualizados fora do
código.

Para iniciar o roteador:

```bash
docker compose -f infra/docker-compose.yml up otp
```

O SmartPass consulta `http://localhost:8080/otp/gtfs/v1` por padrão. Para uma
instância remota, configure `OTP_GRAPHQL_URL` no `.env`. A tarifa provisória de
cada embarque pode ser ajustada com `VT_TARIFA_PADRAO`; integrações tarifárias
devem ser revisadas pelo time de People Operations antes do uso em produção.
