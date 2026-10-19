"""HICP arithmetic: annual chain-linking, effective weights, exact contributions, base effects.

The HICP is an annually chain-linked Laspeyres index. Weights s_{i,y} for year y are expenditure
shares price-updated to December of y-1, and the link month is that December:

    I_t = I_{Dec(y-1)} · Σ_i s_{i,y} · I_{i,t} / I_{i,Dec(y-1)}                 (t in year y)

The same formula aggregates *countries* into the euro area* (country weights instead of item
weights). Whoever has a weight in year y is in the aggregate that year, which is exactly how
the changing composition works: a new member enters in January of its accession year.

Conventions: index frames are wide (rows = month-start dates, columns = series codes); weight
frames are wide (rows = year, columns = series codes, values in per mille). Weights are
renormalised to sum to one over the items present in each year. Published weights are rounded
to 0.01 per mille, so the raw sums are 1000 ± 0.03.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def dec(year: int) -> pd.Timestamp:
    return pd.Timestamp(year=year, month=12, day=1)


def _shares(weights: pd.DataFrame, items: list[str]) -> pd.DataFrame:
    """Per-year weights over ``items``, renormalised to sum to 1 (NaN = not in the basket)."""
    w = weights.reindex(columns=items).astype(float)
    w = w.where(w > 0)
    return w.div(w.sum(axis=1), axis=0)


def link_relatives(index: pd.DataFrame, items: list[str]) -> pd.DataFrame:
    """r_{i,t} = I_{i,t} / I_{i,Dec(y-1)}: each item's price relative to its link month."""
    out = pd.DataFrame(index=index.index, columns=items, dtype=float)
    for y in sorted(set(index.index.year)):
        base = dec(y - 1)
        if base not in index.index:
            continue
        rows = index.index.year == y
        out.loc[rows, items] = index.loc[rows, items].to_numpy() / index.loc[base, items].to_numpy()
    return out


def chain_link(index: pd.DataFrame, weights: pd.DataFrame, items: list[str], start: str,
               anchor: pd.Series) -> pd.Series:
    """Rebuild an aggregate index from its items, recursively from ``start``.

    The level is anchored once, at the December before ``start``, to ``anchor`` (the published
    aggregate); every later December is our own rebuilt value. So errors would compound if the
    method were wrong: this is the strict version of the reconciliation test.
    """
    s = _shares(weights, items)
    r = link_relatives(index, items)
    start_ts = pd.Timestamp(start)
    first_dec = dec(start_ts.year - 1)
    level = {first_dec: float(anchor.loc[first_dec])}
    out = {}
    for y in range(start_ts.year, index.index.max().year + 1):
        if y not in s.index:
            break
        months = index.index[(index.index.year == y) & (index.index >= start_ts)]
        sy = s.loc[y].dropna()
        rel = r.loc[months, sy.index]
        if rel.isna().any().any():
            missing = rel.columns[rel.isna().any()].tolist()
            raise ValueError(f"missing index data in {y} for {missing}")
        agg = level[dec(y - 1)] * (rel * sy).sum(axis=1)
        out.update(agg.to_dict())
        if dec(y) in agg.index:
            level[dec(y)] = float(agg.loc[dec(y)])
    return pd.Series(out, name="rebuilt").sort_index()


def yoy(index: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """Year-on-year % change from index levels: 100 · (I_t / I_{t-12} − 1)."""
    return 100 * (index / index.shift(12, freq="MS").reindex(index.index) - 1)


def effective_weights(index: pd.DataFrame, weights: pd.DataFrame, items: list[str]) -> pd.DataFrame:
    """w_eff_{i,t} = s_{i,y} · r_{i,t} / Σ_j s_{j,y} · r_{j,t}: each item's share of the basket at
    month-t prices. It equals s_i,y · (I_i,t / I_i,Dec) · (I_Dec / I_t) and sums to one exactly.
    A component whose price rose faster than the basket since December has w_eff > s."""
    s = _shares(weights, items)
    r = link_relatives(index, items)
    sy = s.reindex(r.index.year).set_axis(r.index)
    num = sy * r
    return num.div(num.sum(axis=1), axis=0)


def mom_shares(index: pd.DataFrame, weights: pd.DataFrame, items: list[str]) -> pd.DataFrame:
    """Shares that make headline m/m an exact weighted sum of component m/m.

    For month t in year y: φ_{i,t} = s_{i,y} · r_{i,t-1} / Σ_j s_{j,y} · r_{j,t-1}, where r is
    relative to Dec(y-1). In January r_{i,Dec} = 1, so φ = s_{i,y}: the new weights apply from the
    first month of the year. Then I_t / I_{t-1} − 1 = Σ_i φ_{i,t} · (I_{i,t} / I_{i,t-1} − 1).
    """
    s = _shares(weights, items)
    out = pd.DataFrame(index=index.index, columns=items, dtype=float)
    for t in index.index[1:]:
        y = t.year
        if y not in s.index or dec(y - 1) not in index.index:
            continue
        prev = t - pd.DateOffset(months=1)
        r_prev = index.loc[prev, items] / index.loc[dec(y - 1), items]
        num = s.loc[y] * r_prev
        out.loc[t] = (num / num.sum()).to_numpy()
    return out


def exact_contributions(index: pd.DataFrame, weights: pd.DataFrame, items: list[str],
                        total: str) -> pd.DataFrame:
    """Exact additive contributions (pp) of each item to the aggregate's YoY rate.

    A YoY rate spans two annual links: (t-12 → Dec(y-1)) priced with year y-1 weights and
    (Dec(y-1) → t) with year y weights. With I the published aggregate:

        c_{i,t} = 100 / I_{t-12} · [ I_{Dec(y-1)} · s_{i,y}   · (I_{i,t} / I_{i,Dec(y-1)} − 1)
                                   + I_{Dec(y-2)} · s_{i,y-1} · (I_{i,Dec(y-1)} − I_{i,t-12}) / I_{i,Dec(y-2)} ]

    In December t-12 = Dec(y-1), so the second term is zero by construction. The naive shortcut
    s_i × π_i ignores both the two-link structure and the drift of the effective share.
    """
    s = _shares(weights, items)
    rows = {}
    for t in index.index:
        y = t.year
        prev, d1, d2 = t - pd.DateOffset(years=1), dec(y - 1), dec(y - 2)
        if any(d not in index.index for d in (prev, d1, d2)) or y not in s.index or (y - 1) not in s.index:
            continue
        i_t, i_prev, i_d1, i_d2 = (index.loc[d, items] for d in (t, prev, d1, d2))
        # An item outside the basket in a link year (no weight, e.g. a country before it joined)
        # contributes nothing to that link, even if its index is missing.
        this_link = (index.at[d1, total] * s.loc[y] * (i_t / i_d1 - 1)).where(s.loc[y].notna(), 0.0)
        last_link = (index.at[d2, total] * s.loc[y - 1] * (i_d1 - i_prev) / i_d2).where(s.loc[y - 1].notna(), 0.0)
        rows[t] = 100 / index.at[prev, total] * (this_link + last_link)
    return pd.DataFrame.from_dict(rows, orient="index").reindex(columns=items).dropna(how="any")


def base_momentum(index: pd.Series, origin: pd.Timestamp, h: int) -> dict[str, float]:
    """Split the change in YoY from ``origin`` to ``origin + h`` into momentum and base effect.

    In logs the split is exact:
        ln(1+π_{t+h}) − ln(1+π_t) = [ln I_{t+h} − ln I_t]  −  [ln I_{t+h-12} − ln I_{t-12}]
                                     momentum (new m/m)        base effect (m/m a year ago, known)
    Both terms are scaled by the same factor so that they add up exactly to the change in the
    YoY rate in pp. "Locked in" = the base effect: it is known at the origin.
    """
    t, th = origin, origin + pd.DateOffset(months=h)
    i = index
    mom = np.log(i[th] / i[t])
    base = np.log(i[th - pd.DateOffset(years=1)] / i[t - pd.DateOffset(years=1)])
    yoy_t = 100 * (i[t] / i[t - pd.DateOffset(years=1)] - 1)
    yoy_th = 100 * (i[th] / i[th - pd.DateOffset(years=1)] - 1)
    dlog = mom - base
    scale = (yoy_th - yoy_t) / dlog if abs(dlog) > 1e-12 else 100.0
    return {"yoy_origin": yoy_t, "yoy_target": yoy_th, "delta_pp": yoy_th - yoy_t,
            "momentum_pp": scale * mom, "base_effect_pp": -scale * base}
