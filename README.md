# BESS Trading Optimization Platform

Agentic platform for Battery Energy Storage System (BESS) dispatch optimization across ERCOT. Caude-powered agents coordinate XGBoost price forecasting and CVXPY LP optimization to compute revenue-maximizing charge/discharge schedules. Simulation mode only — no live market execution.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Agent Layer (TypeScript)               │
│                                                         │
│  OrchestratorAgent ──► ForecastingAgent                 │
│         │          └──► OptimizationAgent               │
│         │          └──► MarketIntelAgent                │
│         │                                               │
│    ToolRegistry (10 tools wired to real services)        │
└──────────────┬──────────────────────┬───────────────────┘
               │                      │
    ┌──────────▼──────────┐  ┌────────▼────────────┐
    │  Forecasting Service│  │ Optimization Service │
    │  FastAPI  :8001     │  │ FastAPI  :8002       │
    │  XGBoost quantile   │  │ CVXPY LP solver      │
    │  regression         │  │ SoC-constrained      │
    │  p10 / p50 / p90    │  │ dispatch schedule    │
    └──────────┬──────────┘  └────────┬─────────────┘
               │                      │
    ┌──────────▼──────────────────────▼─────────────┐
    │              Infrastructure                    │
    │  TimescaleDB :5432  Kafka :9092  Redis :6379   │
    └────────────────────────────────────────────────┘
```

**LLM handles:** reasoning, coordination, anomaly triage, plan synthesis
**Solver handles:** optimization math — LP is deterministic, auditable, fast

## Monorepo layout

```
packages/
  agents/       TypeScript — Claude API tool-use loop, 4 agents, 10 tools
  shared/       TypeScript — shared types (AgentMessage, LMP, BatteryState)
  simulation/   TypeScript — backtest runner (synthetic LMP, P&L tracking)
services/
  forecasting/  Python — XGBoost quantile regression FastAPI service
  optimization/ Python — CVXPY LP dispatch solver FastAPI service
packages/
  data-pipeline/ Python — ERCOT/PJM fetchers → TimescaleDB ingest
infrastructure/
  timescaledb/migrations/001_initial.sql
docker-compose.yml
```

## Quick start

**Prerequisites:** Docker, Node.js 20+, Python 3.12+

```bash
# Start infrastructure
docker compose up -d timescaledb kafka redis zookeeper
# or: make infra-up

# Start Python services (separate terminals)
cd services/forecasting && uvicorn src.main:app --port 8001
cd services/optimization && uvicorn src.main:app --port 8002

# Run backtest simulation (no live services required — uses synthetic data)
cd packages/simulation
npm install
SIM_START_DATE=2024-01-01 SIM_END_DATE=2024-01-31 npm run run
```

## Services

| Service | Port | Description |
|---|---|---|
| TimescaleDB | 5432 | Time-series DB for LMP and battery state |
| Kafka | 9092 | Agent message bus |
| Redis | 6379 | Real-time battery SoC and risk exposure |
| Forecasting | 8001 | `POST /forecast` `POST /train` `POST /confidence` |
| Optimization | 8002 | `POST /optimize` `GET /battery/{asset_id}` |

## Simulation runner

Iterates over a date range, generates synthetic LMP with realistic daily/weekly shape, calls forecasting + optimization services, computes actual P&L against realized prices, tracks SoC across days.

```bash
cd packages/simulation

# Configure via env vars
SIM_ASSET_ID=BESS-001 \
SIM_ISO=ERCOT \
SIM_NODE=HB_NORTH \
SIM_START_DATE=2024-01-01 \
SIM_END_DATE=2024-03-31 \
npm run run
```

Sample output:
```
=== BESS Simulation Report ===
Asset: BESS-001 | ISO: ERCOT | Node: HB_NORTH
Period: 2024-01-01 → 2024-01-07 (7 days)
Markets: DA_ENERGY

Daily Results:
  2024-01-01  Expected:     $1,234.56  Actual:     $1,189.23  Accuracy:  96.3%  SoC: 50.0% → 48.2%  ✓
  ...

--- Summary ---
  Total Expected Revenue:  $8,642.11
  Total Actual Revenue:    $8,291.44
  Forecast Accuracy:       95.9%
  Avg Daily Revenue:       $1,184.49
  Total Cycles:            12.34
  Daily Sharpe Ratio:      1.847
```

## Battery model

Default parameters (override via optimization service Redis or `SimConfig`):

| Parameter | Default | Description |
|---|---|---|
| `capacity_mwh` | 100 | Total energy capacity |
| `max_charge_mw` / `max_discharge_mw` | 25 | Power limits |
| `eta_charge` / `eta_discharge` | 0.92 | Round-trip efficiency |
| `soc_min_pct` / `soc_max_pct` | 10% / 90% | Operating SoC range |
| `degradation_per_mwh` | $2.00 | Cycle degradation cost |

LP objective: `max Σ(discharge × price × η_d − charge × price / η_c − degradation × (charge + discharge))`

## Development

```bash
# Install all deps
npm install

# TypeScript checks
npm run typecheck    # tsc --noEmit
npm run lint         # eslint
npm run test         # vitest

# Python checks (per service)
cd services/forecasting
.venv/bin/pytest tests/ -q
.venv/bin/ruff check src/ tests/
.venv/bin/mypy src/

# All checks
make check
```

## Test coverage

| Package | Tests | Framework |
|---|---|---|
| `packages/agents` | 57 | vitest |
| `packages/simulation` | 135 | vitest |
| `services/forecasting` | 75 | pytest |
| `services/optimization` | 75 | pytest |
| `packages/data-pipeline` | 45 | pytest |
| **Total** | **387** | |

All tests are adversarial — written by an independent QA agent that did not write the implementation.

## Agent tools

| Tool | Backend | Description |
|---|---|---|
| `run_price_forecast` | Forecasting service | XGBoost p10/p50/p90 per node/market |
| `get_forecast_confidence` | Forecasting service | MAE, RMSE, bias, calibration metrics |
| `solve_dispatch` | Optimization service | CVXPY LP optimal schedule |
| `get_battery_state` | Optimization service + Redis | Real-time SoC and available power |
| `validate_bids` | In-process | ISO price cap + MW sign checks |
| `check_risk_limits` | Redis | Daily revenue ceiling, peak MW limit |
| `fetch_realtime_lmp` | TimescaleDB | Recent LMP by ISO/node |
| `fetch_ancillary_prices` | TimescaleDB | REG_UP/DOWN/SPIN/NONSPIN clearing prices |
| `detect_anomaly` | TimescaleDB | Z-score anomaly detection |
| `parse_iso_document` | — | Not implemented (post-MVP) |

## Environment variables

```bash
# Infrastructure
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=energy_trading
POSTGRES_USER=postgres
POSTGRES_PASSWORD=changeme
REDIS_URL=redis://localhost:6379
KAFKA_BOOTSTRAP_SERVERS=localhost:9092

# Service URLs (agents)
FORECASTING_SERVICE_URL=http://localhost:8001
OPTIMIZATION_SERVICE_URL=http://localhost:8002

# Risk limits
RISK_MAX_DAILY_REVENUE_DOLLARS=50000
RISK_MAX_POSITION_MW=100

# Simulation
SIM_ASSET_ID=BESS-001
SIM_ISO=ERCOT
SIM_NODE=HB_NORTH
SIM_START_DATE=2024-01-01
SIM_END_DATE=2024-01-31

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
```
