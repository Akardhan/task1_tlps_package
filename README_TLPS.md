# TL-PS: Turnover Liquidity & Price Stability (0–100)

**Purpose:** Help investors avoid thin, whippy markets and buy where exits are safer.

## Inputs
- `transactions.parquet` — sales with *price, date, suburb, state/postcode*.
- `gnaf_prop.parquet` — address points (used to count dwellings by suburb).

## Method
1. **Liquidity (12m):** `sales in last 12 months / dwellings × 100` → logistic 0–100 score.
2. **Stability (36m):** coefficient of variation of monthly **median** sale prices → 0–100.
3. **TL-PS:** `0.55 × Liquidity + 0.45 × Stability` (weighted for exit speed).

**Guardrails:** dwellings `< min_dwellings` labelled *small sample*; insufficient months → neutral stability.

## Run
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python metric_tlps.py --transactions transactions.parquet --gnaf gnaf_prop.parquet --state SA --min-dwellings 500 --out tlps_by_suburb.csv --charts 1
```

Outputs:
- `tlps_by_suburb.csv`
- `top10_tlps.png` and `top10_components.png` (optional)

## Interpretation
- **Higher TL-PS = safer exit** (deep demand + stable pricing). Pair with Microburbs’ socio‑economic/risk layers.
- Treat *small sample* suburbs cautiously (few dwellings), and verify micro‑market nuances.

## Assumptions & Limits
- GNAF points proxy dwelling counts; sales are representative; monthly medians summarise price dynamics.
- Hedonic shifts not explicitly modelled (room for future work).
