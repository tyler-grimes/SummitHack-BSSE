"""
Retrain price forecasting models for all ERCOT hubs using the full 2020–2026 dataset.

Usage:
    python scripts/retrain_models.py [--url http://localhost:8001]
"""

import argparse
import sys
import time

import requests

HUBS = ["HB_NORTH", "HB_SOUTH", "HB_WEST", "HB_HOUSTON"]
ISO = "ERCOT"
MARKETS = ["RT_ENERGY"]


def retrain(base_url: str) -> None:
    results = []
    total = len(HUBS) * len(MARKETS)
    for market in MARKETS:
        for hub in HUBS:
            print(f"  Training {ISO}/{hub}/{market} ...", end="", flush=True)
            t0 = time.time()
            try:
                resp = requests.post(
                    f"{base_url}/train",
                    json={"iso": ISO, "node": hub, "market": market},
                    timeout=600,  # XGBoost on 6 years of data may take several minutes
                )
                resp.raise_for_status()
                data = resp.json()
                elapsed = time.time() - t0
                print(f" done ({elapsed:.0f}s)")
                print(
                    f"    model_id={data['model_id']}  "
                    f"MAE={data['mae']:.2f}  RMSE={data['rmse']:.2f}  "
                    f"rows={data['training_rows']}"
                )
                results.append({"hub": hub, "market": market, "ok": True, **data})
            except Exception as exc:
                elapsed = time.time() - t0
                print(f" FAILED ({elapsed:.0f}s): {exc}")
                results.append({"hub": hub, "market": market, "ok": False, "error": str(exc)})

    print()
    ok = [r for r in results if r["ok"]]
    fail = [r for r in results if not r["ok"]]
    print(f"Summary: {len(ok)}/{total} models trained successfully")
    if fail:
        print("Failed:", [(r["hub"], r["market"]) for r in fail])
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrain ERCOT price forecasting models")
    parser.add_argument("--url", default="http://localhost:8001", help="Forecasting service base URL")
    args = parser.parse_args()

    # Health check
    try:
        r = requests.get(f"{args.url}/health", timeout=5)
        r.raise_for_status()
    except Exception as exc:
        print(f"Forecasting service not reachable at {args.url}: {exc}")
        sys.exit(1)

    print(f"Forecasting service OK at {args.url}")
    print(f"Retraining {len(HUBS) * len(MARKETS)} RT_ENERGY models (full 2020-2026 dataset, ~2190 days each)...")
    print()

    retrain(args.url)


if __name__ == "__main__":
    main()
