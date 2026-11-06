"""Reactor HUD dibujado con flet.canvas.

Se usa como mejora puntual del escenario central; no cambia la estructura de
la interfaz ni la lógica de voz.
"""
from __future__ import annotations

import math

import flet as ft
import flet.canvas as cv
from flet.controls.painting import Paint, PaintingStyle

WIDTH = 520
HEIGHT = 340

ACCENT = "#38bdf8"
TEAL = "#5eead4"
DIM = "#1b4a5e"


def _stroke(color: str, width: float, opacity: float = 1.0) -> Paint:
    return Paint(
        color=ft.Colors.with_opacity(opacity, color),
        stroke_width=width,
        style=PaintingStyle.STROKE,
    )


def _fill(color: str, opacity: float = 1.0) -> Paint:
    return Paint(
        color=ft.Colors.with_opacity(opacity, color),
        style=PaintingStyle.FILL,
    )


def _color_for(state: str) -> str:
    return {
        "listening": "#f87171",
        "thinking": "#fbbf24",
        "speaking": TEAL,
    }.get(state, ACCENT)


def build_static_shapes(width: int = WIDTH, height: int = HEIGHT) -> list[cv.Shape]:
    cx, cy = width / 2, height * 0.45
    shapes: list[cv.Shape] = []

    for radius, opacity in ((145, 0.10), (132, 0.08), (112, 0.12), (88, 0.16)):
        shapes.append(
            cv.Circle(x=cx, y=cy, radius=radius, paint=_stroke(DIM, 1, opacity))
        )

    for index in range(60):
        angle = math.radians(index * 6 - 90)
        long = index % 5 == 0
        inner = 135
        outer = inner + (10 if long else 5)
        shapes.append(
            cv.Line(
                x1=cx + math.cos(angle) * inner,
                y1=cy + math.sin(angle) * inner,
                x2=cx + math.cos(angle) * outer,
                y2=cy + math.sin(angle) * outer,
                paint=_stroke(TEAL if long else DIM, 1.4 if long else 1, 0.45 if long else 0.28),
            )
        )

    for x1, x2 in ((cx - 215, cx - 185), (cx + 185, cx + 215)):
        shapes.append(cv.Line(x1=x1, y1=cy, x2=x2, y2=cy, paint=_stroke(DIM, 1, 0.45)))

    shapes.append(cv.Circle(x=cx, y=cy, radius=76, paint=_stroke("#0e7490", 1, 0.18)))
    return shapes


def build_dynamic_shapes(
    state: str, level: float, phase: float, width: int = WIDTH, height: int = HEIGHT
) -> list[cv.Shape]:
    cx, cy = width / 2, height * 0.45
    color = _color_for(state)
    level = max(0.0, min(1.0, level))
    shapes: list[cv.Shape] = []

    sweep = 70 + level * 110
    start = (phase * 55) % 360
    shapes.append(
        cv.Arc(
            x=cx - 145,
            y=cy - 145,
            width=290,
            height=290,
            start_angle=start,
            sweep_angle=sweep,
            paint=_stroke(color, 2.4, 0.85),
        )
    )

    sweep2 = 40 + level * 80
    start2 = (-phase * 40 + 120) % 360
    shapes.append(
        cv.Arc(
            x=cx - 122,
            y=cy - 122,
            width=244,
            height=244,
            start_angle=start2,
            sweep_angle=sweep2,
            paint=_stroke(TEAL, 1.8, 0.55),
        )
    )

    shapes.append(
        cv.Arc(
            x=cx - 98,
            y=cy - 98,
            width=196,
            height=196,
            start_angle=(-phase * 30) % 360,
            sweep_angle=120,
            paint=_stroke(color, 1.2, 0.30),
        )
    )

    for index in range(44):
        angle = math.radians(index * (360 / 44) - 90)
        inner = 66
        length = 8 + level * 26 * abs(math.sin(phase + index * 0.55))
        outer = inner + length
        shapes.append(
            cv.Line(
                x1=cx + math.cos(angle) * inner,
                y1=cy + math.sin(angle) * inner,
                x2=cx + math.cos(angle) * outer,
                y2=cy + math.sin(angle) * outer,
                paint=_stroke(color, 1.2, 0.30 + level * 0.55),
            )
        )

    for radius, opacity in ((58, 0.10), (47, 0.18), (36, 0.34)):
        shapes.append(
            cv.Circle(x=cx, y=cy, radius=radius, paint=_fill(color, opacity))
        )
    shapes.append(cv.Circle(x=cx, y=cy, radius=27, paint=_fill("#d9fbff", 0.92)))
    shapes.append(cv.Circle(x=cx, y=cy, radius=16, paint=_fill("#ffffff", 0.35)))

    for index in range(6):
        angle = math.radians(index * 60 + phase * 20)
        radius = 112 + (index % 4) * 7
        px = cx + math.cos(angle) * radius
        py = cy + math.sin(angle) * radius
        shapes.append(cv.Circle(x=px, y=py, radius=1.8, paint=_fill(color, 0.85)))

    return shapes
