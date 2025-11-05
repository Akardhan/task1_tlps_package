#!/usr/bin/env python3
"""
Compute TL-PS (Turnover Liquidity & Price Stability) per suburb.

Inputs (Parquet):
  --transactions  transactions.parquet  (required; must have price, date, suburb; state/postcode optional)
  --gnaf          gnaf_prop.parquet     (required; must have suburb/locality; state optional)

Robust features:
- Column overrides: --date-col/--price-col/--suburb-col/--state-col/--postcode-col
- Date parsing: strings or epochs with --date-unit {s,ms,us,ns}
- Name normalisation: joins on (suburb,state) after uppercasing & stripping punctuation
- Includes ALL GNAF localities (0 sales handled), so dwellings never NaN
- Charts: --charts 1 writes top10_tlps.png + top10_components.png

Example (your data are NSW, date column = date_sold):
  python metric_tlps.py --transactions transactions.parquet --gnaf gnaf_prop.parquet \
    --date-col date_sold --state NSW --min-dwellings 500 \
    --out tlps_by_suburb.csv --charts 1
"""
import argparse, re
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

# ---------- helpers ----------
def coerce_datetime(x, unit=None):
    """Parse datetimes from strings or numeric epochs; returns UTC tz-aware Series."""
    if unit:
        return pd.to_datetime(x, errors="coerce", utc=True, unit=unit)
    s = pd.to_datetime(x, errors="coerce", utc=True)
    if s.notna().any():
        return s
    if pd.api.types.is_numeric_dtype(x):
        for u in ("s","ms","us","ns"):
            s = pd.to_datetime(x, errors="coerce", utc=True, unit=u)
            if s.notna().any():
                return s
    for fmt in ("%Y-%m-%d","%d/%m/%Y","%m/%d/%Y","%Y%m%d","%Y-%m"):
        s = pd.to_datetime(x, errors="coerce", utc=True, format=fmt)
        if s.notna().any():
            return s
    return pd.to_datetime(pd.Series([pd.NaT]*len(x)), utc=True)

def month_floor(series_utc):
    return series_utc.dt.tz_convert(None).dt.to_period("M").dt.to_timestamp()

def logistic(x, k=0.9, x0=4.0):
    """Smooth 0..100 curve for liquidity per 100 dwellings."""
    return 100.0 / (1.0 + np.exp(-k*(x - x0)))

def infer_col(df, patterns):
    """Pick first column whose name matches any regex in `patterns` (case-insensitive)."""
    pats = [re.compile(p, re.I) for p in patterns]
    for c in df.columns:
        for p in pats:
            if p.search(c):
                return c
    return None

def norm_suburb(s):
    return (s.astype(str)
             .str.upper()
             .str.replace(r"[^A-Z0-9 ]+", "", regex=True)
             .str.replace(r"\s+", " ", regex=True)
             .str.strip())

def norm_state(s):
    return s.astype(str).str.upper().str.strip()

# ---------- loaders ----------
def load_transactions(path, price_col=None, date_col=None, suburb_col=None, state_col=None, pc_col=None, date_unit=None):
    pf = pq.ParquetFile(path)
    parts = []
    for rb in pf.iter_batches():
        df = rb.to_pandas()

        p = price_col or infer_col(df, [r"^price$", r"sale_price", r"contract_price", r"sold_price"])
        d = date_col  or infer_col(df, [r"contract.*date", r"sale.*date", r"sold.*date", r"date_sold", r"settle.*date", r"date"])
        s = suburb_col or infer_col(df, [r"^suburb$", r"locality", r"locality_name"])
        st = state_col or infer_col(df, [r"^state$", r"state_code", r"state_abbrev"])
        pc = pc_col    or infer_col(df, [r"postcode", r"post_code", r"^pc$"])

        if not (p and d and s):
            raise SystemExit(f"transactions: need price/date/suburb; got cols={df.columns.tolist()} (picked price={p}, date={d}, suburb={s})")

        sub = df[[p, d, s] + [c for c in [st, pc] if c]].copy()
        newcols = ["price","date","suburb"]
        if st: newcols.append("state")
        if pc: newcols.append("postcode")
        sub.columns = newcols
        parts.append(sub)

    tx = pd.concat(parts, ignore_index=True)
    tx["price"] = pd.to_numeric(tx["price"], errors="coerce")
    tx = tx.dropna(subset=["price","date","suburb"])

    tx["date"] = coerce_datetime(tx["date"], unit=date_unit)
    if tx["date"].isna().all():
        raise SystemExit("No valid dates in transactions. Try --date-col <name> and/or --date-unit {s,ms,us,ns}")

    tx["m"] = month_floor(tx["date"])
    return tx

def load_gnaf(path, suburb_col=None, state_col=None):
    pf = pq.ParquetFile(path)
    parts = []
    for rb in pf.iter_batches():
        df = rb.to_pandas()

        s = suburb_col or infer_col(df, [r"^suburb$", r"locality", r"locality_name"])
        st = state_col or infer_col(df, [r"^state$", r"state_code", r"state_abbrev"])
        if not s:
            raise SystemExit("gnaf: need a suburb/locality column.")

        # keep only principal records if available (drops alias duplicates)
        if "alias_principal" in df.columns:
            df = df[df["alias_principal"].astype(str).str.upper().str.startswith("P")]

        # deduplicate addresses if a stable id exists
        if "gnaf_pid" in df.columns:
            df = df.drop_duplicates(subset=["gnaf_pid"])
        elif "address" in df.columns:
            df = df.drop_duplicates(subset=[s, "address"])

        cols = [s] + ([st] if st else [])
        sub = df[cols].copy()
        sub.columns = ["suburb"] + (["state"] if st else [])
        parts.append(sub)

    return pd.concat(parts, ignore_index=True)

# ---------- core computation ----------
def compute_tlps(tx, gnaf, state=None, min_dw=1):
    # normalise keys on both datasets
    tx["suburb_norm"] = norm_suburb(tx["suburb"])
    tx["state_norm"]  = norm_state(tx["state"]) if "state" in tx.columns else "NA"

    gnaf["suburb_norm"] = norm_suburb(gnaf["suburb"])
    gnaf["state_norm"]  = norm_state(gnaf["state"]) if "state" in gnaf.columns else "NA"

    # optional filter by state (using normalised)
    if state:
        stU = state.upper()
        tx   = tx[tx["state_norm"]==stU]
        gnaf = gnaf[gnaf["state_norm"]==stU]

    # dwellings per (suburb,state)
    dwellings = (gnaf.assign(n=1)
                      .groupby(["suburb_norm","state_norm"], as_index=False)["n"]
                      .sum()
                      .rename(columns={"n":"dwellings"}))

    # sales in last 12 months
    cutoff_12m = tx["m"].max() - pd.offsets.DateOffset(months=12)
    sales12 = (tx[tx["m"] > cutoff_12m]
                 .groupby(["suburb_norm","state_norm"], as_index=False)
                 .size().rename(columns={"size":"sales_12m"}))

    # include ALL GNAF localities; fill zero sales if none
    liq = dwellings.merge(sales12, on=["suburb_norm","state_norm"], how="left")
    liq["sales_12m"] = liq["sales_12m"].fillna(0)

    # display suburb name: prefer most common label from transactions; fallback to normalised
    disp = (tx.groupby(["suburb_norm","state_norm"])["suburb"]
              .agg(lambda s: s.value_counts().index[0] if len(s) else "")
              .reset_index().rename(columns={"suburb":"suburb_display"}))
    liq = liq.merge(disp, on=["suburb_norm","state_norm"], how="left")
    liq["suburb"] = liq["suburb_display"].where(liq["suburb_display"].notna() & (liq["suburb_display"]!=""), liq["suburb_norm"])

    # liquidity per 100 dwellings and score
    liq["liq_per_100"] = 100.0 * liq["sales_12m"] / liq["dwellings"].replace(0, np.nan)
    liq["liq_score"] = logistic(liq["liq_per_100"].fillna(0))

    # price stability over last 36 months (monthly medians → CV)
    last36 = tx["m"].max() - pd.offsets.DateOffset(months=36)
    mmed = (tx[tx["m"] > last36]
              .groupby(["suburb_norm","state_norm","m"], as_index=False)["price"]
              .median())
    cv = (mmed.groupby(["suburb_norm","state_norm"])["price"]
               .agg(["mean","std","count"]).reset_index())
    cv["cv"] = cv["std"] / cv["mean"]
    cv["stab_score"] = (1 - np.minimum(1.0, cv["cv"].fillna(1.0)/0.35)) * 100.0
    cv["enough_data"] = cv["count"] >= 18

    out = liq.merge(cv[["suburb_norm","state_norm","stab_score","enough_data"]],
                    on=["suburb_norm","state_norm"], how="left")

    # defaults & final score
    out["stab_score"] = out["stab_score"].fillna(50)  # neutral when too little history
    out["TLPS"] = (0.55*out["liq_score"] + 0.45*out["stab_score"]).round(1)
    out["notes"] = np.where(out["dwellings"].fillna(0) < min_dw, "small sample", "")

    # final ordering/columns
    out = out[["suburb","sales_12m","dwellings","liq_per_100","liq_score",
               "stab_score","enough_data","TLPS","notes"]].sort_values("TLPS", ascending=False)
    return out

# ---------- CLI ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transactions", required=True)
    ap.add_argument("--gnaf", required=True)
    ap.add_argument("--state", default=None)
    ap.add_argument("--min-dwellings", type=int, default=500)
    ap.add_argument("--out", default="tlps_by_suburb.csv")
    ap.add_argument("--charts", type=int, default=0)
    # optional overrides
    ap.add_argument("--date-col")
    ap.add_argument("--price-col")
    ap.add_argument("--suburb-col")
    ap.add_argument("--state-col")
    ap.add_argument("--postcode-col")
    ap.add_argument("--date-unit", choices=["s","ms","us","ns"])
    args = ap.parse_args()

    # load
    tx = load_transactions(
        args.transactions,
        price_col=args.price_col, date_col=args.date_col, suburb_col=None,
        state_col=args.state_col, pc_col=args.postcode_col, date_unit=args.date_unit
    )
    gnaf = load_gnaf(args.gnaf, suburb_col=args.suburb_col, state_col=args.state_col)


    # compute
    res = compute_tlps(tx, gnaf, state=args.state, min_dw=args.min_dwellings)
    res.to_csv(args.out, index=False)
    print(f"Wrote {len(res)} rows to {args.out}")

    # charts (optional)
    if args.charts:
        import matplotlib.pyplot as plt
        top = res[res["notes"]!="small sample"].head(10)

        # Chart 1: Overall TL-PS
        plt.figure()
        plt.barh(top["suburb"], top["TLPS"])
        plt.xlabel("TL-PS (0–100)")
        plt.ylabel("Suburb")
        plt.title("Top 10 suburbs by TL-PS")
        plt.gca().invert_yaxis()
        plt.tight_layout()
        plt.savefig("top10_tlps.png", dpi=160)
        plt.close()

        # Chart 2: Components
        import numpy as np
        plt.figure()
        y = np.arange(len(top))
        plt.barh(y, top["liq_score"], height=0.4, label="Liquidity")
        plt.barh(y+0.45, top["stab_score"], height=0.4, label="Stability")
        plt.yticks(y+0.22, top["suburb"])
        plt.xlabel("Score (0–100)")
        plt.title("Components for Top 10")
        plt.legend()
        plt.tight_layout()
        plt.savefig("top10_components.png", dpi=160)
        plt.close()

if __name__ == "__main__":
    main()
