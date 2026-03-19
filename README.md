# Planejamento do aplicativo de traçado viário com OSM + DEM

Este repositório inicia um plano prático para construir um aplicativo que analisa dados geoespaciais e propõe o **melhor traçado viário**, incluindo decisão de **pontes** versus **desvios**.

## 1) Por onde começar

A melhor primeira etapa é **Dados e Terreno**.

Sem uma boa base de dados (rede viária, hidrografia, uso do solo e elevação), a lógica de custo não terá confiança. Primeiro construímos a superfície de custo; depois aplicamos os algoritmos de rota.

## 2) Arquitetura recomendada (MVP)

- **Entrada de dados**
  - OSM: vias, rios, corpos d'água, edificações, áreas protegidas.
  - DEM: SRTM, Copernicus DEM ou ALOS.
- **Pré-processamento GIS**
  - Reprojeção para CRS métrico local.
  - Derivação de declividade e curvatura do terreno.
  - Raster de custo (célula = custo de construção/manutenção).
- **Rede e conectividade**
  - Grafo de vias existentes com OSMnx/NetworkX.
  - Nós de travessia possíveis para rios.
- **Motor de otimização**
  - Least Cost Path (A* / Dijkstra com custo composto).
  - Penalização por inclinação, raio de curva e áreas sensíveis.
  - Função para comparar “ponte” vs “contorno”.
- **Saída**
  - Traçado recomendado (GeoJSON/Shapefile).
  - Relatório com extensão, custo estimado e justificativas.

## 3) Modelo de custo sugerido

Uma função de custo inicial pode ser:

```text
C_total = w1*C_declividade + w2*C_terraplenagem + w3*C_hidrologia +
          w4*C_ambiental + w5*C_desapropriacao + w6*C_obra_arte
```

Onde:
- `C_obra_arte` cobre pontes, viadutos, bueiros.
- `w1..w6` são pesos calibráveis por tipo de projeto (rodovia local, estadual etc.).

## 4) Regra objetiva para decidir ponte vs desvio

Para cada travessia candidata:

1. Gerar alternativa A (com ponte) e alternativa B (sem ponte).
2. Calcular custo de ciclo de vida (CAPEX + OPEX + risco) para horizonte (ex.: 30 anos).
3. Comparar:
   - Se `C_A + margem_risco < C_B`, escolhe ponte.
   - Caso contrário, escolhe desvio.

## 5) Stack de desenvolvimento (Python)

- **Dados OSM**: `osmnx`, `pyrosm`, `geopandas`.
- **Raster/DEM**: `rasterio`, `xarray`, `richdem` (ou GDAL tools).
- **Algoritmos**: `networkx`, `scipy`.
- **Serviço/API**: `FastAPI`.
- **Visualização**: `folium` ou `kepler.gl`.

## 6) Roadmap em 4 sprints

### Sprint 1 — Base geoespacial
- Definir área piloto.
- Baixar OSM + DEM.
- Produzir camadas normalizadas e raster de declividade.

### Sprint 2 — Superfície de custo
- Definir variáveis e pesos iniciais.
- Gerar raster de custo e validar com engenharia.

### Sprint 3 — Otimização de traçado
- Implementar A* com custo composto.
- Criar módulo de avaliação de travessias (ponte vs contorno).

### Sprint 4 — Produto mínimo
- Expor API para receber origem/destino/restrições.
- Gerar mapa interativo + relatório técnico.

## 7) Estrutura inicial de pastas

```text
.
├── configs/                # Configurações (pesos, CRS, parâmetros de execução)
├── data/
│   ├── external/           # Bases externas de referência
│   ├── interim/            # Dados intermediários de processamento
│   ├── processed/          # Dados finais processados
│   └── raw/                # Dados brutos (OSM, DEM)
├── docs/                   # Documentação técnica e decisões de arquitetura
├── notebooks/              # Exploração e validação de hipóteses
├── outputs/
│   ├── maps/               # Mapas gerados
│   └── reports/            # Relatórios de comparação de traçados
├── scripts/                # Scripts utilitários e pipelines
├── src/
│   ├── api/                # Endpoints (FastAPI)
│   ├── bridges/            # Lógica de ponte vs contorno
│   ├── cost/               # Construção da superfície/função de custo
│   ├── ingestion/          # Download e padronização OSM/DEM
│   ├── routing/            # Algoritmos de caminho (A*, Dijkstra)
│   ├── terrain/            # Derivação de declividade/curvatura
│   └── utils/              # Utilitários compartilhados
└── tests/                  # Testes automatizados
```

## 8) Próximo passo recomendado

Implementar um **protótipo da etapa “Dados e Terreno”** em uma área pequena (município ou corredor de 20–50 km), pois isso reduz risco técnico e permite calibrar custos rapidamente.

---

Se quiser, no próximo passo eu já posso preparar:
1) script Python para baixar OSM + DEM,
2) geração automática de raster de declividade e custo inicial,
3) endpoint inicial da API para solicitar origem/destino.

## 9) Script de ingestão por poligonal: OSM + DEM recortado

Script: `scripts/download_osm_dem.py`

### Entradas
- `--polygon`: GeoJSON desenhado no front-end (Leaflet/Mapbox).

### O que ele faz
- Usa os vértices da poligonal para consultar o OSM via Overpass com filtro por `poly`.
- Baixa geometrias de **rios/lagos/construções** dentro da área desenhada.
- Baixa DEM por bbox e recorta o raster para o **polígono exato**.

### Comandos

```bash
python scripts/download_osm_dem.py   --polygon data/external/area.geojson   --out-dir data/raw   --dem-type COP30   --opentopo-api-key "SUA_CHAVE"
```

Somente OSM:

```bash
python scripts/download_osm_dem.py --polygon data/external/area.geojson --skip-dem
```

Dry-run (sem rede):

```bash
python scripts/download_osm_dem.py --polygon data/external/area.geojson --dry-run
```

### Saídas
- `data/raw/osm/osm_features_raw.json`
- `data/raw/osm/osm_features.geojson`
- `data/raw/dem/dem_raw_bbox.tif`
- `data/raw/dem/dem_clipped_polygon.tif`
- `data/raw/metadata/request_metadata.json`

## 10) Estrutura em memória para o algoritmo: grade 2x2

Sim — dividir a área em grade de pequenos quadrados é uma estratégia muito prática para iniciar o cálculo de rota.

Script: `scripts/build_grid_model.py`

- Entrada: `dem_clipped_polygon.tif`
- Saída: JSON com células da grade (`id`, linha/coluna, coordenada, elevação).
- `--stride 2` representa amostragem em blocos 2x2 para reduzir volume inicial.

```bash
python scripts/build_grid_model.py   --dem data/raw/dem/dem_clipped_polygon.tif   --out data/interim/grid_model.json   --stride 2
```


## 11) Custo de superfície (declividade + construções) e equilíbrio de massas

Script: `scripts/build_cost_surface.py`

### Regras implementadas
- Terreno com declividade **até 30%**: custo **1**.
- Terreno com declividade **acima de 30%**: custo **10**.
- Células com construções/residências: custo **10**.

### Equilíbrio de massas
O script calcula um índice simplificado de corte/aterro para apoiar o traçado:
- `estimated_cut_volume_index`
- `estimated_fill_volume_index`
- `cut_fill_ratio`
- `mass_balance_imbalance_index` (0 = melhor equilíbrio)

A cota de referência pode ser definida com `--target-elevation`; se não for informada, usa a mediana do DEM.

### Uso

```bash
python scripts/build_cost_surface.py \
  --dem data/raw/dem/dem_clipped_polygon.tif \
  --osm-geojson data/raw/osm/osm_features.geojson \
  --cost-out data/interim/cost_surface.tif \
  --report-out data/interim/cost_surface_report.json
```

## 12) Área piloto definida

Para iniciar com baixa complexidade operacional, foi definida a área piloto **São Paulo Centro**.

### Arquivos
- Configuração: `configs/pilot_area_sao_paulo_centro.json`
- Poligonal GeoJSON: `data/external/pilot_area_sao_paulo_centro.geojson`

### BBox da área piloto
- west: `-46.67`
- south: `-23.58`
- east: `-46.62`
- north: `-23.53`

### Executar pipeline da área piloto

1. Baixar OSM + DEM (com recorte por polígono):

```bash
python scripts/download_osm_dem.py \
  --polygon data/external/pilot_area_sao_paulo_centro.geojson \
  --out-dir data/raw \
  --dem-type COP30 \
  --opentopo-api-key "SUA_CHAVE"
```

2. Gerar custo de superfície:

```bash
python scripts/build_cost_surface.py \
  --dem data/raw/dem/dem_clipped_polygon.tif \
  --osm-geojson data/raw/osm/osm_features.geojson \
  --cost-out data/interim/cost_surface.tif \
  --report-out data/interim/cost_surface_report.json
```

3. Gerar grade base para roteamento:

```bash
python scripts/build_grid_model.py \
  --dem data/raw/dem/dem_clipped_polygon.tif \
  --out data/interim/grid_model.json \
  --stride 2
```

### Criar outra área piloto rapidamente

```bash
python scripts/create_pilot_area.py \
  --name piloto_nova \
  --west -46.70 --south -23.60 --east -46.60 --north -23.50 \
  --out data/external/pilot_area_nova.geojson
```
