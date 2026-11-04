"""
Standalone SVG and PNG export of scopeline renderings (svg.render_svg) with a
fixed print palette: white background, black lines and text, and bands
filled with spot's default state color (#ffffaa). The palette is substituted
as literal colors, since cairosvg, used for the PNG, does not resolve CSS
custom properties. The canvas width follows the diagram's content.

    from scopelines.render.png import save_png
    save_png(result.scopelines, "out.png", operator=result.operator)
"""

import re
from pathlib import Path

import cairosvg

from . import svg as _st
from .svg import render_svg, MARGIN_L, MARGIN_R, DOMAIN_PAD
from .layout import build_row_blocks
from ..utils import negate_operator, gap_labels, nesting_depths


def _negated(scopeline):
	negated = scopeline.copy()
	negated.negate()
	return negated


BG_COLOR = "#ffffff"
LINE_COLOR = "#000000"
BAND_COLOR = "#ffffaa"  # Spot's own default (unhighlighted) state fill color

_FONT_OVERRIDE = "Arial, Helvetica, sans-serif"

# How many pixels one unit of x-domain (row["anchorPos"], the same
# abstract step unit render_svg's own per-block x-scale stretches to
# fill whatever width it's given -- see _derive_width) gets, and the
# floor under that so a trivial 0-1-anchor formula still gets a
# legible canvas rather than a sliver.
_PX_PER_ANCHOR_UNIT = 40
_MIN_WIDTH = 420


# Every CSS variable render_svg() draws with: all line and text colors
# collapse to one, and both band fills to one opaque fill.
_PALETTE_VARS = {
	"--bg": BG_COLOR,
	"--band": LINE_COLOR, "--band-strong": LINE_COLOR,
	"--band-soft": BAND_COLOR, "--band-always": BAND_COLOR,
	"--axis-line": LINE_COLOR, "--axis-arrow": LINE_COLOR,
	"--line": LINE_COLOR, "--text-muted": LINE_COLOR,
}


def _apply_palette(svg_fragment):
	"""Replaces every var(--name) render_svg() emits with its literal
	color (see _PALETTE_VARS and the module docstring for why a literal
	substitution instead of an actual CSS custom property)."""
	for name, color in _PALETTE_VARS.items():
		svg_fragment = svg_fragment.replace("var({})".format(name), color)
	return svg_fragment


def _derive_width(blocks):
	"""render_svg's own per-block x-scale always stretches row anchor
	positions to fill whatever canvas width W it's given (domain
	(0, max_anchor + DOMAIN_PAD) onto range (MARGIN_L, W - MARGIN_R) --
	see render_svg in svg.py), regardless of how much actual
	content there is, so a fixed W either stretches a simple formula's
	few ticks out with large gaps between them or crowds a complex
	formula's many ticks together. Deriving W from the diagram's own
	largest anchor position instead (the same quantity render_svg
	computes per block, just taken as a max across every block here, so
	every block gets equally proportioned spacing) keeps roughly
	constant, content-proportional spacing regardless of formula size,
	with a floor so a trivial 0-1-anchor formula still gets a legible
	canvas rather than a sliver."""

	max_anchor = max(
		(row["anchorPos"] for rows, _connectors in blocks for row in rows),
		default=0.0,
	)
	content_w = (max_anchor + DOMAIN_PAD) * _PX_PER_ANCHOR_UNIT
	return max(_MIN_WIDTH, round(MARGIN_L + MARGIN_R + content_w))


def render_bare_svg(scopelines, operator=None, negate=False):
	"""The bare, standalone SVG string -- same diagram render_svg()
	would draw for `scopelines`/`operator` (see build_row_blocks), just
	with the palette above substituted in, a canvas width derived from
	the content (see _derive_width) instead of render_svg's own fixed
	width, and
	explicit width/height attributes added (render_svg's own tag only
	carries a viewBox).

	negate=True renders the shape's negation instead of the shape
	itself: each root Scopeline is negated in place (Scopeline.negate(),
	via _negated -- a copy, the originals are
	left untouched) and the connectives flip by De Morgan (and<->or)."""

	if not isinstance(scopelines, (list, tuple)):
		scopelines = [scopelines]

	if negate:
		scopelines = [_negated(t) for t in scopelines]
		operator = negate_operator(operator)

	blocks = build_row_blocks(scopelines)
	width = _derive_width(blocks)

	original_w = _st.W
	_st.W = width
	try:
		inner = render_svg(blocks, operator=gap_labels(operator, len(scopelines)), depths=nesting_depths(operator, len(scopelines)))
	finally:
		_st.W = original_w

	inner = _apply_palette(inner)

	m = re.match(r'<svg viewBox="0 0 ([\d.]+) ([\d.]+)"', inner)
	w, h = m.group(1), m.group(2)

	tag_end = inner.index(">")
	open_tag, rest = inner[:tag_end], inner[tag_end + 1:]
	open_tag += ' width="{w}" height="{h}">'.format(w=w, h=h)

	bg_rect = '<rect x="0" y="0" width="100%" height="100%" fill="{}"/>'.format(BG_COLOR)
	font_rule = "<style>text{{font-family:{};}}</style>".format(_FONT_OVERRIDE)

	return open_tag + font_rule + bg_rect + rest


def save_svg(scopelines, out_path, operator="", negate=False):
	"""Writes the rendering of a result (see runner.Result) to `out_path` as
	SVG; with negate, renders its negation instead."""

	svg = render_bare_svg(scopelines, operator=operator, negate=negate)
	Path(out_path).parent.mkdir(parents=True, exist_ok=True)
	with open(out_path, "w", encoding="utf-8") as f:
		f.write(svg)
	return out_path


def save_png(scopelines, out_path, operator="", negate=False, scale=2):
	"""Same as save_svg, rasterized to PNG with cairosvg; `scale` multiplies
	the pixel density."""

	svg = render_bare_svg(scopelines, operator=operator, negate=negate)
	Path(out_path).parent.mkdir(parents=True, exist_ok=True)
	cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(out_path), scale=scale)
	return out_path
