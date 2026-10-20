"""Pre-registered fan calibration test (docs/DECISIONS.md D28).

Fan A: point + empirical quantiles of the h-step errors known at the origin (fixed width).
Fan B: point + σ_t × quantiles of standardised errors e/σ_o known at the origin (volatility-scaled),
       σ_t = RMS of the last 12 one-month errors known at t.
Both are recursive (no look-ahead). Scored by the pinball loss averaged over q = .05/.16/.84/.95 at h = 3;
B is adopted if it is lower with a DM p < 0.05.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hicp import backtest as bt

QS = (0.05, 0.16, 0.84, 0.95)
SIGMA_WINDOW, MIN_ERRORS = 12, 36
PERIODS = {"2010-2019": ("2010-01", "2019-12"), "2020-2023": ("2020-01", "2023-12"), "2024-now": ("2024-01", "2100-12"),
           "all scored": ("1900-01", "2100-12")}


def pinball(y: float, point: float, quants: dict[float, float]) -> float:
    """Mean quantile loss over QS for outcome y and band point + quants[q]."""
    out = 0.0
    for q in QS:
        Q = point + quants[q]
        out += (q - (1.0 if y < Q else 0.0)) * (y - Q)
    return out / len(QS)


def sigma_series(e1: pd.Series, origins: list[pd.Timestamp]) -> dict[pd.Timestamp, float | None]:
    """σ_t: RMS of the last 12 one-month errors whose target month is ≤ t (known at t)."""
    out = {}
    for t in origins:
        known = e1[e1.index <= t].dropna().sort_index().iloc[-SIGMA_WINDOW:]
        out[t] = float(np.sqrt((known ** 2).mean())) if len(known) >= SIGMA_WINDOW else None
    return out


def build(head_bu: pd.DataFrame) -> dict:
    """head_bu: bottom-up rows with origin, h, target, fc, actual (all origins, incl. the live one)."""
    origins = sorted(head_bu.origin.unique())
    e = {h: head_bu[head_bu.h == h].set_index("origin").assign(err=lambda x: x.actual - x.fc) for h in (1, 2, 3)}
    e1_by_target = e[1].dropna(subset=["err"]).set_index("target")["err"]
    sig = sigma_series(e1_by_target, origins)
    full_q = {h: e[h]["err"].dropna().quantile(list(QS)).to_dict() for h in (1, 2, 3)}  # current in-sample fan

    rows = []
    for h in (1, 2, 3):
        eh = e[h].dropna(subset=["err"])
        for t in origins:
            known = eh[eh.target <= t]
            if len(known) < MIN_ERRORS or sig[t] is None:
                continue
            z = pd.Series({o: r.err / sig[o] for o, r in known.iterrows() if sig.get(o)})
            if len(z) < MIN_ERRORS:
                continue
            qa = dict(zip(QS, np.quantile(known["err"].to_numpy(), QS)))
            qb = dict(zip(QS, sig[t] * np.quantile(z.to_numpy(), QS)))
            r = e[h].loc[t]
            row = {"origin": t, "h": h, "point": float(r.fc), "sigma": sig[t], "qa": qa, "qb": qb, "actual": r.actual}
            if pd.notna(r.actual):
                y = float(r.actual)
                for name, qq in (("A", qa), ("B", qb), ("current", full_q[h])):
                    row[f"loss_{name}"] = pinball(y, row["point"], qq)
                    # stored as float 0/1: numpy bools in an object column give a wrong .mean() in pandas 3
                    row[f"in68_{name}"] = float(row["point"] + qq[0.16] <= y <= row["point"] + qq[0.84])
                    row[f"in90_{name}"] = float(row["point"] + qq[0.05] <= y <= row["point"] + qq[0.95])
            rows.append(row)
    df = pd.DataFrame(rows)
    scored = df.dropna(subset=["actual"])

    summary = []
    for h in (1, 2, 3):
        for pname, (a, b) in PERIODS.items():
            g = scored[(scored.h == h) & (scored.origin >= pd.Timestamp(a)) & (scored.origin <= pd.Timestamp(b))]
            if not len(g):
                continue
            for m in ("A", "B", "current"):
                summary.append({"fan": m, "h": h, "period": pname, "n": int(len(g)), "pinball": float(g[f"loss_{m}"].mean()),
                                "in68": float(g[f"in68_{m}"].astype(float).mean()),
                                "in90": float(g[f"in90_{m}"].astype(float).mean())})
    g3 = scored[scored.h == 3]
    stat, p = bt.diebold_mariano(np.sqrt(g3.loss_B.to_numpy()), np.sqrt(g3.loss_A.to_numpy()), 3)
    adopt = bool(g3.loss_B.mean() < g3.loss_A.mean() and p < 0.05)
    live_t = origins[-1]
    live = {}
    for h in (1, 2, 3):  # the fan each method would publish at the live origin
        eh = e[h].dropna(subset=["err"]); known = eh[eh.target <= live_t]
        z = np.array([r.err / sig[o] for o, r in known.iterrows() if sig.get(o)])
        live[h] = {"A": dict(zip(QS, np.quantile(known["err"].to_numpy(), QS))),
                   "B": dict(zip(QS, sig[live_t] * np.quantile(z, QS))), "B_errors": (sig[live_t] * z).tolist()}
    return {"rows": df, "summary": summary, "decision": {"h": 3, "n": int(len(g3)), "mean_loss_A": float(g3.loss_A.mean()),
                                             "mean_loss_B": float(g3.loss_B.mean()), "dm_stat": stat, "dm_p": p, "adopt_B": adopt},
            "sigma": {f"{t:%Y-%m}": v for t, v in sig.items() if v is not None}, "live": live, "live_sigma": sig[live_t],
            "first_scored": f"{g3.origin.min():%Y-%m}" if len(g3) else None}
