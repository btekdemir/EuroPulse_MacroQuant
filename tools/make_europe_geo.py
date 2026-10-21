"""Build dashboard/europe_geo.json: compact Europe outlines for the Countries map (D66).

Source: Natural Earth 1:50m admin-0 countries (public domain), as TopoJSON in the world-atlas npm package
(https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-50m.json). Run once; the output is committed, so the
dashboard stays one self-contained file that works offline:

    python tools/make_europe_geo.py path/to/countries-50m.json

Keeps the euro area members and their neighbours, drops rings outside the map window (French Guiana, the
Canaries, Svalbard...), simplifies the lines and rounds coordinates, and names each country by the code the
dashboard uses (EL for Greece).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "dashboard" / "europe_geo.json"
BBOX = (-25.0, 34.0, 45.0, 71.5)  # lon_min, lat_min, lon_max, lat_max
TOL = 0.06  # degrees, Douglas-Peucker tolerance

EA = {"040": "AT", "056": "BE", "100": "BG", "191": "HR", "196": "CY", "233": "EE", "246": "FI", "250": "FR",
      "276": "DE", "300": "EL", "372": "IE", "380": "IT", "428": "LV", "440": "LT", "442": "LU", "470": "MT",
      "528": "NL", "620": "PT", "703": "SK", "705": "SI", "724": "ES"}
NEIGHBOURS = {"826": "GB", "756": "CH", "578": "NO", "752": "SE", "208": "DK", "616": "PL", "203": "CZ", "348": "HU",
              "642": "RO", "688": "RS", "070": "BA", "499": "ME", "008": "AL", "807": "MK", "804": "UA", "112": "BY",
              "498": "MD", "792": "TR", "352": "IS", "438": "LI", "020": "AD", "492": "MC", "674": "SM", "643": "RU",
              "504": "MA", "012": "DZ", "788": "TN", "434": "LY", "818": "EG", "760": "SY", "368": "IQ", "364": "IR",
              "268": "GE", "051": "AM", "031": "AZ", "422": "LB", "376": "IL", "400": "JO", "304": "GL"}


def decode_arcs(topo: dict) -> list[list[tuple[float, float]]]:
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    return arcs


def ring(arcs, idx: list[int]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for i in idx:
        pts = arcs[i] if i >= 0 else arcs[~i][::-1]
        out.extend(pts if not out else pts[1:])
    return out


def simplify(pts, tol):
    """Douglas-Peucker. A closed ring starts and ends on the same point, which would collapse it, so it is split at
    the point farthest from the start and each half is simplified."""
    if len(pts) < 4:
        return pts
    if pts[0] == pts[-1]:
        x0, y0 = pts[0]
        k = max(range(len(pts)), key=lambda i: (pts[i][0] - x0) ** 2 + (pts[i][1] - y0) ** 2)
        if 0 < k < len(pts) - 1:
            return _dp(pts[:k + 1], tol)[:-1] + _dp(pts[k:], tol)
    return _dp(pts, tol)


def _dp(pts, tol):
    if len(pts) < 3:
        return pts

    def dp(a, b):
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        n = (dx * dx + dy * dy) ** 0.5 or 1e-12
        best, k = -1.0, -1
        for i in range(a + 1, b):
            x0, y0 = pts[i]
            d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / n
            if d > best:
                best, k = d, i
        return [a, b] if best <= tol else dp(a, k)[:-1] + dp(k, b)

    sys.setrecursionlimit(100000)
    return [pts[i] for i in dp(0, len(pts) - 1)]


def inside(r) -> bool:
    cx = sum(p[0] for p in r) / len(r)
    cy = sum(p[1] for p in r) / len(r)
    return BBOX[0] <= cx <= BBOX[2] and BBOX[1] <= cy <= BBOX[3]


def main(src: str) -> None:
    topo = json.loads(Path(src).read_text())
    arcs = decode_arcs(topo)
    feats = []
    for g in topo["objects"]["countries"]["geometries"]:
        code = EA.get(g.get("id")) or NEIGHBOURS.get(g.get("id"))
        if not code:
            continue
        polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
        keep = []
        for poly in polys:
            rings = [ring(arcs, r) for r in poly]
            if not inside(rings[0]):
                continue
            tol = TOL / 3 if code in ("MT", "LU", "CY") else TOL  # keep the small members recognisable
            rs = [[[round(x, 2), round(y, 2)] for x, y in simplify(r, tol)] for r in rings]
            rs = [r for r in rs if len(r) >= 4]
            if rs:
                keep.append(rs)
        if keep:
            feats.append({"type": "Feature", "id": code, "properties": {"ea": code in EA.values()},
                          "geometry": {"type": "MultiPolygon", "coordinates": keep}})
    missing = set(EA.values()) - {f["id"] for f in feats}
    if missing:
        raise SystemExit(f"euro area members missing from the outlines: {sorted(missing)}")
    OUT.write_text(json.dumps({"type": "FeatureCollection", "source": "Natural Earth 1:50m admin-0 (public domain), "
                                "via world-atlas@2.0.2", "features": feats}, separators=(",", ":")))
    print(f"{OUT}: {len(feats)} countries, {OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main(sys.argv[1])
