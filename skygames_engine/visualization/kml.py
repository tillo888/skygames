"""KML (Google Earth) and GeoJSON (web map layer) for a heat."""
from __future__ import annotations

from typing import List
from xml.sax.saxutils import escape

from .colors import AB_LINE, hex_to_kml


def _coords(lat, lon, alt):
    return "\n".join(f"{x},{y},{z}" for y, x, z in zip(lat, lon, alt))


def build_kml(heat_name: str, jumps: List[dict], line_width: int = 4) -> str:
    """``jumps``: list of dicts from ``pipeline.JumpResult.map_payload()``."""
    p = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
         f"<name>{escape(heat_name)} - Freefall tracks (exit to opening)</name>",
         f'<Style id="ab"><LineStyle><color>{hex_to_kml(AB_LINE)}</color><width>{line_width}</width>'
         f'</LineStyle><IconStyle><color>{hex_to_kml(AB_LINE)}</color></IconStyle></Style>']
    for k, j in enumerate(jumps):
        c = hex_to_kml(j["color"])
        p.append(f'<Style id="f{k}"><LineStyle><color>{c}</color><width>{line_width}</width></LineStyle>'
                 f'<IconStyle><color>{c}</color></IconStyle><LabelStyle><color>{c}</color></LabelStyle></Style>')
    for k, j in enumerate(jumps):
        n, g = escape(j["flyer"]), j["track"]
        alt = "<altitudeMode>absolute</altitudeMode>"
        p.append(f"<Folder><name>{n}</name>")
        p.append(f"<Placemark><name>{n} freefall</name><styleUrl>#f{k}</styleUrl><LineString>"
                 f"<tessellate>1</tessellate>{alt}<coordinates>{_coords(g['lat'], g['lon'], g['alt_m'])}"
                 "</coordinates></LineString></Placemark>")
        for label, i in (("EXIT", 0), ("OPENING", -1)):
            p.append(f"<Placemark><name>{n} {label}</name><styleUrl>#f{k}</styleUrl><Point>{alt}<coordinates>"
                     f"{g['lon'][i]},{g['lat'][i]},{g['alt_m'][i]}</coordinates></Point></Placemark>")
        A, B = j.get("A"), j.get("B")
        if A and B:
            for nm, P in (("window start", A), ("window end", B)):
                p.append(f"<Placemark><name>{n} {nm} ({P['alt_ft']:.0f} ft)</name><styleUrl>#f{k}</styleUrl>"
                         f"<Point>{alt}<coordinates>{P['lon']},{P['lat']},{P['alt_abs_m']}</coordinates></Point></Placemark>")
            d = j.get("distance_m")
            lbl = f"{n} A→B straight line" + (f" ({d:.1f} m)" if d is not None else "")
            p.append(f"<Placemark><name>{escape(lbl)}</name><styleUrl>#ab</styleUrl><LineString>{alt}<coordinates>"
                     f"{A['lon']},{A['lat']},{A['alt_abs_m']}\n{B['lon']},{B['lat']},{B['alt_abs_m']}"
                     "</coordinates></LineString></Placemark>")
        sm = j.get("speed_mark")
        if sm:
            p.append(f"<Placemark><name>{n} {sm['target_m']:g} m mark (Δt={sm['dt_s']:.2f} s)</name>"
                     f"<styleUrl>#f{k}</styleUrl><Point>{alt}<coordinates>{sm['lon']},{sm['lat']},{sm['alt_abs_m']}"
                     "</coordinates></Point></Placemark>")
        p.append("</Folder>")
    p.append("</Document></kml>")
    return "\n".join(p)


def build_geojson(jumps: List[dict]) -> dict:
    feats = []
    for j in jumps:
        g = j["track"]
        props = {"flyer": j["flyer"], "color": j["color"]}
        feats.append({"type": "Feature", "properties": {**props, "kind": "track"},
                      "geometry": {"type": "LineString",
                                   "coordinates": [[x, y, z] for y, x, z in zip(g["lat"], g["lon"], g["alt_m"])]}})
        A, B = j.get("A"), j.get("B")
        if A and B:
            feats.append({"type": "Feature", "properties": {**props, "kind": "ab_line", "distance_m": j.get("distance_m")},
                          "geometry": {"type": "LineString", "coordinates": [[A["lon"], A["lat"]], [B["lon"], B["lat"]]]}})
        if j.get("speed_mark"):
            sm = j["speed_mark"]
            feats.append({"type": "Feature", "properties": {**props, "kind": "speed_mark", "dt_s": sm["dt_s"]},
                          "geometry": {"type": "Point", "coordinates": [sm["lon"], sm["lat"]]}})
    return {"type": "FeatureCollection", "features": feats}
