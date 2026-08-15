from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass

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
SUBTLE = (90, 94, 98)
MUTED = (120, 124, 128)

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


@dataclass(frozen=True, slots=True)
class HeroImage:
    data: bytes
    alt: str


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
    _draw_signature(draw)


def _draw_signature(draw: ImageDraw.ImageDraw) -> None:
    """A capa circula fora do site — Discover, WhatsApp, X — então precisa dizer
    de quem ela é sem depender do contexto da página que a hospeda."""
    base = HEIGHT - 62
    draw.rectangle(
        [72 * SCALE, (base - 18) * SCALE, (72 + 64) * SCALE, (base - 14) * SCALE],
        fill=GOLD,
    )
    name_font = _font(22 * SCALE, bold=True)
    draw.text((72 * SCALE, base * SCALE), "BOLSO COBERTO", font=name_font, fill=INK)
    domain_x = 72 * SCALE + draw.textlength("BOLSO COBERTO", font=name_font) + 16 * SCALE
    draw.text(
        (domain_x, (base + 2) * SCALE),
        "bolsocoberto.com.br",
        font=_font(20 * SCALE),
        fill=MUTED,
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
    headline: str = "",
) -> bytes:
    canvas = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), PAPER)
    draw = ImageDraw.Draw(canvas, "RGBA")
    _draw_chrome(draw, category)

    # A manchete vem antes do número: sem ela o cartão de duas matérias
    # diferentes sobre o mesmo indicador sai idêntico.
    headline_font = _font(44 * SCALE, bold=True)
    y = 104 * SCALE
    for line in _wrap(draw, headline, headline_font, (WIDTH - 144) * SCALE)[:3]:
        draw.text((72 * SCALE, y), line, font=headline_font, fill=INK)
        y += 56 * SCALE

    top = max(int(y // SCALE) + 26, 330)
    draw.text((72 * SCALE, top * SCALE), label, font=_font(26 * SCALE), fill=SUBTLE)
    draw.text((72 * SCALE, (top + 34) * SCALE), value, font=_font(72 * SCALE, bold=True), fill=INK)
    draw.text((72 * SCALE, (top + 136) * SCALE), reference, font=_font(22 * SCALE), fill=MUTED)

    if len(series) >= 3:
        _draw_series(draw, list(series), (600, top, WIDTH - 72, HEIGHT - 130))
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
) -> HeroImage | None:
    try:
        if fields:
            label = str(fields.get("label") or "")
            value = str(fields.get("value") or "")
            reference = str(fields.get("reference") or "")
            series = fields.get("series")
            data = render_data_hero(
                category=category,
                label=label,
                value=value,
                reference=reference,
                series=series if isinstance(series, list) else [],
                headline=headline,
            )
            return HeroImage(
                data=data,
                alt=_data_alt(label=label, value=value, reference=reference),
            )
        return HeroImage(
            data=render_brand_hero(category=category, headline=headline),
            alt=_brand_alt(headline),
        )
    except Exception:
        logger.exception("Falha ao gerar a capa; a pauta segue sem imagem")
        return None


# O alt precisa descrever o cartão que foi desenhado. Quando vinha do LLM ele
# descrevia uma fotografia inexistente ("gráfico sobre fundo azul escuro"), o
# que é informação errada para leitor de tela e para o Google Imagens.


def _data_alt(*, label: str, value: str, reference: str) -> str:
    if not label or not value:
        return "Cartão do Bolso Coberto com o gráfico do indicador."
    text = f"Cartão do Bolso Coberto: {label} em {value}"
    if reference:
        text += f" ({reference})"
    return f"{text}, com o gráfico dos últimos meses."[:300]


def _brand_alt(headline: str) -> str:
    text = (headline or "").strip()
    if not text:
        return "Cartão de capa do Bolso Coberto."
    return f"Cartão de capa do Bolso Coberto com a manchete: {text}"[:300]
