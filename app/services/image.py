from __future__ import annotations

import io
from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

from app.core.logging import get_logger

logger = get_logger(__name__)

# Discover exige no mínimo 1200px de largura e mais de 300 mil pixels totais.
WIDTH = 1200
HEIGHT = 675
SCALE = 2  # desenha no dobro e reduz, que é o antialias mais barato aqui.

# brand/tokens.json não vai para a imagem Docker, então os tokens vivem aqui.
INK = (18, 20, 23)
PAPER = (250, 250, 247)
COVERAGE = (15, 122, 75)
GOLD = (232, 163, 23)
GRID = (223, 224, 218)

_BOLD_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)
_REGULAR_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
)

CATEGORY_LABELS = {"financas": "FINANÇAS", "seguros": "SEGUROS"}


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in _BOLD_CANDIDATES if bold else _REGULAR_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _encode(canvas: Image.Image) -> bytes:
    final = canvas.resize((WIDTH, HEIGHT), Image.LANCZOS)
    buffer = io.BytesIO()
    final.save(buffer, format="JPEG", quality=88, optimize=True, progressive=True)
    return buffer.getvalue()


def _draw_chrome(draw: ImageDraw.ImageDraw, category: str) -> None:
    draw.rectangle([0, 0, WIDTH * SCALE, 12 * SCALE], fill=COVERAGE)
    kicker = CATEGORY_LABELS.get(category, "BOLSO COBERTO")
    draw.text((72 * SCALE, 58 * SCALE), kicker, font=_font(22 * SCALE, bold=True), fill=GOLD)
    draw.text(
        (72 * SCALE, HEIGHT * SCALE - 62 * SCALE),
        "bolsocoberto.com.br",
        font=_font(20 * SCALE, bold=True),
        fill=(120, 124, 128),
    )


def _draw_series(
    draw: ImageDraw.ImageDraw,
    series: Sequence[float],
    box: tuple[int, int, int, int],
) -> None:
    left, top, right, bottom = (value * SCALE for value in box)
    smallest = min(series)
    largest = max(series)
    span = largest - smallest or max(abs(largest), 1.0) * 0.1
    padded_min = smallest - span * 0.25
    padded_max = largest + span * 0.25

    for index in range(4):
        y = top + (bottom - top) * index / 3
        draw.line([(left, y), (right, y)], fill=GRID, width=1 * SCALE)

    step = (right - left) / max(len(series) - 1, 1)
    points = [
        (
            left + step * index,
            bottom - (value - padded_min) / (padded_max - padded_min) * (bottom - top),
        )
        for index, value in enumerate(series)
    ]

    draw.polygon(
        [(points[0][0], bottom), *points, (points[-1][0], bottom)],
        fill=(COVERAGE[0], COVERAGE[1], COVERAGE[2], 40),
    )
    draw.line(points, fill=COVERAGE, width=5 * SCALE, joint="curve")
    last_x, last_y = points[-1]
    radius = 11 * SCALE
    draw.ellipse(
        [last_x - radius, last_y - radius, last_x + radius, last_y + radius],
        fill=GOLD,
        outline=PAPER,
        width=4 * SCALE,
    )


def render_data_hero(
    *,
    category: str,
    label: str,
    value: str,
    reference: str,
    series: Sequence[float],
) -> bytes:
    canvas = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), PAPER)
    draw = ImageDraw.Draw(canvas, "RGBA")
    _draw_chrome(draw, category)

    draw.text((72 * SCALE, 104 * SCALE), label, font=_font(40 * SCALE), fill=(90, 94, 98))
    draw.text((72 * SCALE, 158 * SCALE), value, font=_font(92 * SCALE, bold=True), fill=INK)
    draw.text((72 * SCALE, 272 * SCALE), reference, font=_font(24 * SCALE), fill=(120, 124, 128))

    if len(series) >= 3:
        _draw_series(draw, list(series), (72, 350, WIDTH - 72, HEIGHT - 96))
    return _encode(canvas)


def render_brand_hero(*, category: str, headline: str) -> bytes:
    """Capa de reserva quando não há série numérica ligada à pauta."""
    canvas = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), PAPER)
    draw = ImageDraw.Draw(canvas, "RGBA")
    _draw_chrome(draw, category)

    for index, radius in enumerate((300, 210, 120)):
        center_x = (WIDTH - 210) * SCALE
        center_y = (HEIGHT // 2 + 40) * SCALE
        tint = (COVERAGE[0], COVERAGE[1], COVERAGE[2], 26 + index * 22)
        draw.ellipse(
            [
                center_x - radius * SCALE,
                center_y - radius * SCALE,
                center_x + radius * SCALE,
                center_y + radius * SCALE,
            ],
            fill=tint,
        )

    font = _font(58 * SCALE, bold=True)
    y = 190 * SCALE
    for line in _wrap(draw, headline, font, (WIDTH - 420) * SCALE)[:4]:
        draw.text((72 * SCALE, y), line, font=font, fill=INK)
        y += 76 * SCALE
    return _encode(canvas)


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: float,
) -> list[str]:
    words = (text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def build_hero(
    *,
    category: str,
    headline: str,
    fields: dict[str, object] | None,
) -> bytes | None:
    try:
        if fields:
            series = fields.get("series")
            return render_data_hero(
                category=category,
                label=str(fields.get("label") or ""),
                value=str(fields.get("value") or ""),
                reference=str(fields.get("reference") or ""),
                series=series if isinstance(series, list) else [],
            )
        return render_brand_hero(category=category, headline=headline)
    except Exception:
        logger.exception("Falha ao gerar a capa; a pauta segue sem imagem")
        return None
