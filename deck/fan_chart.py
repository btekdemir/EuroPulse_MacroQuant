"""Slide 1's fan chart as an image, drawn from deck/deck_data.json (D72).

    python deck/fan_chart.py   ->  deck/fan.png        (needs matplotlib)

A fan has no native PowerPoint form: imitated with stacked areas, its band edges rendered as thin vertical lines in
some viewers (PowerPoint, PDF exports). Drawn here once, it looks the same everywhere. Every value comes from the
data file: the last 24 months, the forecast path and its 68% / 90% quantiles.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
D = json.loads((HERE / "deck_data.json").read_text())
F = D["forecast"]
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
lab = lambda ym: f"{MON[int(ym[5:7]) - 1]} {ym[2:4]}"  # noqa: E731

INK, ACCENT, MUTED, B68, B90, GRID = "#0F1B2D", "#2A78D6", "#5B6B82", "#8FB8EA", "#C9DCF4", "#E3E8EF"
plt.rcParams.update({"font.family": "Arial", "font.size": 11, "axes.edgecolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED})

hist, path = F["history"], F["path"]
n_h = len(hist)
x_h = list(range(n_h))
x_f = list(range(n_h - 1, n_h + len(path)))           # the fan starts at the last published month
la = hist[-1]["yoy"]
q = {k: [la] + [p[k] for p in path] for k in ("q05", "q16", "q84", "q95")}
fc = [la] + [p["point"] for p in path]

fig, ax = plt.subplots(figsize=(6.6, 3.9), dpi=300)
ax.fill_between(x_f, q["q05"], q["q95"], color=B90, linewidth=0, label="90% band")
ax.fill_between(x_f, q["q16"], q["q84"], color=B68, linewidth=0, label="68% band")
ax.axvline(n_h - 1, color=MUTED, linewidth=0.8, linestyle=(0, (3, 3)))
ax.text(n_h - 1 + 0.25, 5.3, "Forecast", color=MUTED, fontsize=10, va="top")
ax.plot(x_h, [h["yoy"] for h in hist], color=INK, linewidth=2.2, label="Actual")
ax.plot(x_f, fc, color=ACCENT, linewidth=2.4, marker="o", markersize=4, markevery=list(range(1, len(fc))), label="Forecast")
end = path[-1]
ax.annotate(f"{lab(end['date'])}: {end['point']:.2f}%", xy=(x_f[-1], end["point"]), xytext=(6, 0), textcoords="offset points",
            color=ACCENT, fontsize=11, fontweight="bold", va="center")
ax.axhline(F["ecb_target"], color=MUTED, linewidth=0.8, linestyle=(0, (1, 3)))
ax.text(n_h - 1.4, F["ecb_target"] - 0.12, f"ECB target {F['ecb_target']:.0f}%", color=MUTED, fontsize=9, ha="right", va="top")

last_i = n_h + len(path) - 1
ticks = sorted(range(last_i, -1, -3))                    # every third month, ending on the forecast month (Dec 26)
ax.set_xticks(ticks, [lab((hist + path)[i]["date"]) for i in ticks], fontsize=9.5)
ax.set_xlim(-0.5, x_f[-1] + 4.2)                         # room for the end label
ax.set_ylim(1.0, 5.5)
ax.yaxis.set_major_formatter(matplotlib.ticker.FormatStrFormatter("%.1f%%"))
ax.grid(axis="y", color=GRID, linewidth=0.6)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.tick_params(axis="y", length=0)
ax.set_title("Headline HICP, % y/y: last 24 months and the forecast fan", color="#14284B", fontsize=12, loc="left")
ax.legend(loc="upper left", ncol=4, frameon=False, fontsize=9.5, bbox_to_anchor=(0, -0.1))
fig.tight_layout()
fig.savefig(HERE / "fan.png", dpi=300, facecolor="white")
print("deck/fan.png written")
