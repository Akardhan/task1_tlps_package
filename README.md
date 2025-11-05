
# TL-PS — Turnover Liquidity & Price Stability

*Microburbs Analyst Coder Quiz (Task 1: Real-estate metric)*

**TL-PS** is a suburb-level **exit-safety** score on a 0–100 scale that helps Australian residential investors prioritise markets where it’s **easier to sell** and **prices are steadier**.

* **Liquidity (12 months):** sales per 100 dwellings, squashed to 0–100 via a logistic curve.
* **Stability (36 months):** price volatility measured as the coefficient of variation (CV) of **monthly median** sold prices.
* **TL-PS = 0.55 × Liquidity + 0.45 × Stability** (rounded to 1 decimal).

The code reads your **transactions** parquet and **GNAF** (addresses) parquet, normalises suburb names, guards sparse data, and writes a **CSV** plus two **charts**.

---

## Why investors care

* **Quicker exits:** High turnover reduces time-on-market and discounting risk.
* **Less whiplash:** Stable monthly medians signal healthier demand/supply balance.
* **Screening tool:** Shortlist suburbs before deep due-diligence (vacancy, yields, reno scope, etc.).

---

## Repo contents

```
metric_tlps.py         # CLI script to compute TL-PS
tlps_by_suburb.csv     # Output (example)
top10_tlps.png         # Top 10 TL-PS bar chart
top10_components.png   # Liquidity vs Stability for Top 10
README_TLPS.md         # Short explainer (optional)
requirements.txt       # pandas, numpy, pyarrow, matplotlib
```

---

## Data inputs

* **transactions.parquet** — needs columns for:

  * price (e.g., `price`, `sale_price`, …)
  * date  (e.g., `date_sold`, `sale_date`, `contract_date`, epochs OK)
  * suburb (e.g., `suburb`, `locality`, `locality_name`)
  * state  (optional but recommended; e.g., `state`)

* **gnaf_prop.parquet** — needs:

  * suburb/locality name (e.g., `locality_name` or `suburb`)
  * state (e.g., `state`)
  * (Optional: `alias_principal`, `gnaf_pid` for deduping)

> The script auto-detects column names and lets you **override** any of them.

---

## Quick start

```bash
# 1) install deps (Anaconda recommended)
conda install -c conda-forge pyarrow pandas numpy matplotlib
# or: pip install -r requirements.txt

# 2) run (example: NSW dataset, dates in column date_sold)
python metric_tlps.py \
  --transactions transactions.parquet \
  --gnaf gnaf_prop.parquet \
  --date-col date_sold \
  --suburb-col locality_name \
  --state-col state \
  --state NSW --min-dwellings 500 \
  --out tlps_by_suburb.csv --charts 1
```

**Outputs**

* `tlps_by_suburb.csv`
* `top10_tlps.png`
* `top10_components.png`

---

## CLI options

```
--transactions <path>    Parquet with sales
--gnaf <path>            Parquet with GNAF addresses
--state <code>           Filter to state (e.g., NSW, VIC)
--min-dwellings <n>      Flag “small sample” under this count (default 500)
--out <path>             Output CSV (default tlps_by_suburb.csv)
--charts 1               Save two PNG charts
# Optional overrides (use when auto-detect isn’t enough)
--date-col <name>        Date field name (strings or epochs)
--date-unit s|ms|us|ns   Epoch unit if numeric
--price-col <name>       Price field name
--suburb-col <name>      *For GNAF* suburb/locality column (e.g., locality_name)
--state-col <name>       State column name
--postcode-col <name>    Postcode column name
```

---

## Interpretation guide

* **TL-PS (0–100):** higher = easier resale + lower price volatility.
* **Liquidity score:** rises with sales per 100 dwellings over the last 12 months.
* **Stability score:** 100 is very stable; falls as monthly-median prices swing more.
* **Notes:** “small sample” warns of thin bases (few dwellings → fragile signals).

**Usage:** Rank suburbs by TL-PS to focus research time; compare components to see *why* a suburb scores high/low.

---

## Method detail

1. **Normalise keys**: uppercase, strip punctuation/extra spaces; join on `(suburb,state)`.
2. **Dwellings**: count GNAF addresses per (suburb,state). (Optionally filter principal records and dedupe `gnaf_pid`.)
3. **Liquidity (12m)**: count sales per suburb in the last 12 months from the dataset’s max month; convert to “per 100 dwellings”; map via `logistic(x, k=0.9, x0=4)`.
4. **Stability (36m)**: monthly median prices per suburb; compute CV = std/mean; map to 0–100 with a soft cap at CV≈0.35; fall back to 50 if too little history.
5. **Blend**: `0.55*Liquidity + 0.45*Stability`, round to 1 decimal.

---

## Assumptions & limitations

* GNAF address points approximate **dwelling counts** (post filtering/deduping).
* Transactions represent **arm’s-length sales**.
* Monthly medians reduce outlier noise but don’t model **mix shifts** (house vs unit, price bands).
* Liquidity/stability horizons (12m/36m) are sensible defaults; can be parameterised.

---

## Troubleshooting

**“No valid dates in transactions.”**
Check the real date column and re-run with `--date-col <name>` (add `--date-unit ms` for epoch ms).

**Wrote 0 rows**
Your state filter removed everything (e.g., only NSW in file). Re-run without `--state` or use a state that exists.

**Suburbs show codes like NSW29…**
That’s a join to SA1/POA/SAL codes. Re-run with `--suburb-col locality_name` (or whichever GNAF field shows real names).

**Liquidity looks tiny**
Dwellings may be inflated by aliases/dupes. Enable principal/dedupe (already implemented) or tighten dedupe keys.

---

## Roadmap (if extended)

* Hedonic controls by property type/price band
* Vacancy & yield overlays; climate/insurance risk
* Bayesian shrinkage for low-volume suburbs
* Interactive map dashboard; time-series trends
* Partitioned GeoParquet + CI for national scaling

---

## One-line summary (for the form)

> **TL-PS** highlights suburbs where you can **buy with confidence and sell with ease**—by combining **how often properties trade** with **how steady prices are**.

---


**Contact:** Akardhan — *University of Adelaide*
