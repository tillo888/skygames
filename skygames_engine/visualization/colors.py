"""Flyer colours: fixed categorical order (CVD-validated), assigned by flyer
order in the heat and never re-cycled. Beyond 8 flyers a dash pattern is
added so identity never depends on colour alone."""
from __future__ import annotations

CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
DASHES = ["-", "--", ":", "-."]
AB_LINE = "#e34948"


def flyer_style(i: int):
    return {"color": CATEGORICAL[i % len(CATEGORICAL)], "linestyle": DASHES[(i // len(CATEGORICAL)) % len(DASHES)]}


def hex_to_kml(hex_color: str, alpha: int = 255) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"{alpha:02x}{b}{g}{r}"
