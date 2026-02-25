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
python scripts/download_osm_dem.py   --polygon data/external/area.geojson   --out-dir data/raw   --dem-type COP30   --dem-resolution-m 30   --opentopo-api-key "SUA_CHAVE"
```

Somente OSM:

```bash
python scripts/download_osm_dem.py --polygon data/external/area.geojson --skip-dem
```

Somente DEM (útil quando Overpass estiver indisponível):

Resoluções suportadas no OpenTopography neste projeto: **15m, 30m e 90m** (via `--dem-resolution-m`).

```bash
python scripts/download_osm_dem.py --polygon data/external/area.geojson --skip-osm --dem-resolution-m 15 --opentopo-api-key "SUA_CHAVE"
```

Também é possível usar variável de ambiente para a chave:

```bash
export OPENTOPO_API_KEY="SUA_CHAVE"
python scripts/download_osm_dem.py --polygon data/external/area.geojson --skip-osm
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

## 10) Estrutura em memória para o algoritmo: grade 15x15

Sim — dividir a área em grade de pequenos quadrados é uma estratégia muito prática para iniciar o cálculo de rota.

Script: `scripts/build_grid_model.py`

- Entrada: `dem_clipped_polygon.tif` + opcionalmente `cost_surface.tif`.
- Saída: JSON com:
  - nós (`id`, linha/coluna, coordenada, elevação, custo-base opcional),
  - arestas 8-direções com custo de movimento.
- Custo de aresta:
  - `horizontal_distance_m * thematic_cost_mean + vertical_penalty_factor * vertical_delta_m`
- `--stride 15` representa amostragem em blocos 15x15 para reduzir volume inicial.

```bash
python scripts/build_grid_model.py   --dem data/raw/dem/dem_clipped_polygon.tif   --cost-raster data/interim/cost_surface.tif   --out data/interim/grid_model.json   --stride 15   --vertical-penalty-factor 0.05
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
  --stride 15
```

### Criar outra área piloto rapidamente

```bash
python scripts/create_pilot_area.py \
  --name piloto_nova \
  --west -46.70 --south -23.60 --east -46.60 --north -23.50 \
  --out data/external/pilot_area_nova.geojson
```

## 13) Otimização da função de custo para água (ponte vs contorno)

A lógica de projetista foi incorporada à função de custo:
- **Desviar** da água é a prioridade padrão.
- **Atravessar** (ponte) continua permitido quando o contorno fica caro demais.

### Regra matemática implementada
- Terra plana (<=30%): custo `1`.
- Água (rios/lagos): custo `15`.
- Vias existentes (`highway`): custo reduzido (padrão `0.6`) para priorizar reaproveitamento do corredor já implantado.

Com grade de 5m, isso representa:
- 1 célula de água (5m) ~ 15 células de terra plana (75m).

Ou seja, o A* vai preferir contorno curto, mas escolherá ponte quando o desvio em terra ultrapassar aproximadamente essa equivalência de custo.
Além disso, quando houver corredor viário existente em terra, o custo menor desse corredor tende a puxar o traçado para reutilização de infraestrutura.

### Configuração de parâmetros
Arquivo: `configs/cost_parameters.json`.

### Gerar custo de superfície com água

```bash
python scripts/build_cost_surface.py \
  --dem data/raw/dem/dem_clipped_polygon.tif \
  --osm-geojson data/raw/osm/osm_features.geojson \
  --params configs/cost_parameters.json \
  --cost-out data/interim/cost_surface.tif \
  --report-out data/interim/cost_surface_report.json
```

## 14) A* sobre raster de custo

Script: `scripts/run_astar_cost_raster.py`

Exemplo:

```bash
python scripts/run_astar_cost_raster.py \
  --cost-raster data/interim/cost_surface.tif \
  --start-lon -46.665 --start-lat -23.575 \
  --end-lon -46.625 --end-lat -23.535 \
  --out outputs/reports/astar_path.json
```

## 15) Corte/aterro por alternativas de eixo com seção parametrizada

Script: `scripts/evaluate_earthwork_alternatives.py`

Essa etapa calcula corte/aterro ao longo de múltiplas alternativas de eixo (`LineString`) usando seção transversal parametrizada:
- largura de plataforma (`platform_width_m`),
- espessura de pavimento (`pavement_thickness_m`),
- talude de corte (`side_slope_cut_hv`) e aterro (`side_slope_fill_hv`),
- passo de estaqueamento (`station_step_m`).

### Arquivos de apoio
- Parâmetros: `configs/cross_section_parameters.json`
- Exemplo de alternativas: `data/external/axis_alternatives_example.geojson`

### Execução

```bash
python scripts/evaluate_earthwork_alternatives.py \
  --dem data/raw/dem/dem_clipped_polygon.tif \
  --axes-geojson data/external/axis_alternatives_example.geojson \
  --params configs/cross_section_parameters.json \
  --out-report outputs/reports/earthwork_alternatives_report.json
```

### Saída
O relatório inclui, para cada alternativa:
- `estimated_cut_volume_m3`
- `estimated_fill_volume_m3`
- `cut_fill_ratio`
- `mass_balance_imbalance_index`
- ranking por melhor equilíbrio de massas.

## 16) Etapa de QA/QC antes da superfície de custo

Script: `scripts/qaqc_inputs.py`

Essa etapa valida os insumos antes de gerar custo:
- DEM: proporção de NoData, CRS projetado (opcional), células quadradas.
- OSM GeoJSON: contagem de feições, presença de camadas (edificações/água/vias), geometrias inválidas.

### Execução QA/QC

```bash
python scripts/qaqc_inputs.py \
  --dem data/raw/dem/dem_clipped_polygon.tif \
  --osm-geojson data/raw/osm/osm_features.geojson \
  --max-dem-nodata-ratio 0.15 \
  --require-projected-crs \
  --out-report outputs/reports/qaqc_report.json
```

### Integrar QA/QC na geração de custo

```bash
python scripts/build_cost_surface.py \
  --dem data/raw/dem/dem_clipped_polygon.tif \
  --osm-geojson data/raw/osm/osm_features.geojson \
  --params configs/cost_parameters.json \
  --qaqc-report outputs/reports/qaqc_report.json \
  --cost-out data/interim/cost_surface.tif \
  --report-out data/interim/cost_surface_report.json
```

Se `overall_status = fail`, a geração de custo é interrompida até correção dos insumos.

## 17) A* ligado ao grafo de arestas (grid_model.json)

Script: `scripts/run_astar_graph.py`

Agora o A* pode usar diretamente o grafo gerado em `build_grid_model.py` (`cells + edges`), em vez de operar só no raster.

```bash
python scripts/run_astar_graph.py \
  --grid-model data/interim/grid_model.json \
  --start-lon -46.665 --start-lat -23.575 \
  --end-lon -46.625 --end-lat -23.535 \
  --out outputs/reports/astar_graph_path.json
```

### Comparar A* raster vs A* grafo

Script: `scripts/compare_astar_modes.py`

```bash
python scripts/compare_astar_modes.py \
  --raster-report outputs/reports/astar_path.json \
  --graph-report outputs/reports/astar_graph_path.json \
  --out outputs/reports/astar_compare_report.json
```

## 18) Varredura de cenários e ranking multiobjetivo

Script: `scripts/sweep_scenarios.py`

Objetivos do ranking:
- custo total da rota,
- índice de equilíbrio de massas,
- extensão estimada em água/ponte.

Arquivo de exemplo: `configs/scenarios_example.json`.

```bash
python scripts/sweep_scenarios.py \
  --scenarios configs/scenarios_example.json \
  --dem data/raw/dem/dem_clipped_polygon.tif \
  --osm-geojson data/raw/osm/osm_features.geojson \
  --start-lon -46.665 --start-lat -23.575 \
  --end-lon -46.625 --end-lat -23.535 \
  --out-report outputs/reports/scenario_sweep_report.json
```

## 19) Regras configuráveis de aceitação QA/QC

Arquivo: `configs/qaqc_thresholds.json`.

Principais regras:
- `max_dem_nodata_ratio`,
- `require_projected_crs`,
- `min_osm_feature_count`,
- `max_invalid_geometry_ratio`,
- `require_thematic_layers` (vias/água/edificações).

```bash
python scripts/qaqc_inputs.py \
  --dem data/raw/dem/dem_clipped_polygon.tif \
  --osm-geojson data/raw/osm/osm_features.geojson \
  --thresholds configs/qaqc_thresholds.json \
  --out-report outputs/reports/qaqc_report.json
```

## 20) Separar perfil de projeto (greide) antes de corte/aterro

Script novo: `scripts/build_design_profile.py`.

Esse passo gera cotas de projeto por estação e alternativa, para depois usar em `evaluate_earthwork_alternatives.py`.

```bash
python scripts/build_design_profile.py \
  --axes-geojson data/external/axis_alternatives_example.geojson \
  --station-step-m 20 \
  --start-elevation 720 \
  --grade-percent 0.5 \
  --out data/interim/design_profile.json
```

Depois, avaliar terraplenagem com greide:

```bash
python scripts/evaluate_earthwork_alternatives.py \
  --dem data/raw/dem/dem_clipped_polygon.tif \
  --axes-geojson data/external/axis_alternatives_example.geojson \
  --params configs/cross_section_parameters.json \
  --design-profile data/interim/design_profile.json \
  --out-report outputs/reports/earthwork_alternatives_report.json
```

## 22) Protótipo Etapa 1 (Dados e Terreno) em corredor ~50 km

Para reduzir risco e calibrar custos rapidamente, foi incluído um corredor piloto de aproximadamente 50 km:

- Polígono: `data/external/pilot_corridor_50km_sp.geojson`
- Configuração: `configs/prototype_data_terrain_50km.json`
- Orquestrador: `scripts/run_data_terrain_prototype.py`

Execução recomendada (sem rede, para validar estrutura e estimar grade):

```bash
python scripts/run_data_terrain_prototype.py --dem-resolution-m 30
```

Execução com download real de dados:

```bash
python scripts/run_data_terrain_prototype.py --dem-resolution-m 30 --run-download
```

O relatório gerado em `outputs/reports/data_terrain_prototype_50km.json` inclui:
- bbox e dimensões estimadas do corredor,
- tamanho efetivo da grade (`effective_grid_size_m = dem_resolution * stride`),
- quantidade estimada de células de processamento.

### Qual tamanho de grade estamos usando hoje?

No modelo atual, o tamanho da grade é definido por:

- `tamanho_grade_m = resolução_do_DEM * stride`
- resolução DEM selecionável: **15m / 30m / 90m** (`--dem-resolution-m`)
- `stride` padrão em `build_grid_model.py` é **15**.

Exemplo prático:
- Com DEM de 30 m (COP30) e `stride=15`, a grade efetiva fica em **450 m**.
- Com DEM de 15 m e `stride=15`, a grade efetiva fica em **225 m**.


### Escolha de resolução (15m/30m/90m)

No `download_osm_dem.py`, você pode escolher explicitamente a resolução:

```bash
python scripts/download_osm_dem.py \
  --polygon data/external/pilot_corridor_50km_sp.geojson \
  --dem-resolution-m 15 \
  --opentopo-api-key "SUA_CHAVE"
```

Troque para `30` ou `90` para comparar velocidade/nível de detalhe e calibrar o modelo.
