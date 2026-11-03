"""
Draws scopelines as SVG: one band per node, stacked top to bottom, with
ticks for events (Section VI of the paper). Several scopelines joined by
AND/OR are stacked as separate blocks, each divider labeled with its
connective and indented by its nesting depth. See layout.py for how a
scopeline becomes rows, and png.py for the standalone SVG/PNG export.
"""

import html

from .layout import build_row_blocks, UnsupportedScopelineShape


W = 1160
MARGIN_L = 80
MARGIN_R = 80
ROW_H = 60
# Every label's font size is multiplied by LABEL_SCALE, and the vertical
# spacing grows with it, so that a rendering stays legible when scaled
# down to a printed column.
LABEL_SCALE = 1.6
ROW_GAP = 46 + 22
# indentation per nesting level of joined scopelines (see render_svg)
NEST_INDENT = 36
BLOCK_GAP = 66 + 16
TOP_PAD = 42 + 16
BOTTOM_PAD = 20
DOMAIN_PAD = 4.0

# a gap that hosts a logical connector (see render_svg) opens up a bit
# wider than a plain one -- the label needs the room, and a little extra
# air around "AND"/"OR" helps it read as joining two things rather than
# just being one more piece of clutter on the scopeline
CONNECTOR_EXTRA_GAP = 20

# event/anchor names are proposition identifiers and can in principle be
# arbitrarily long -- wrap labels onto a second line rather than assume
# everything fits on one
TICK_MAX_CHARS = 14
PROBE_MAX_CHARS = 18
LABEL_LINE_H = round(13 * LABEL_SCALE)

# a compound-quantifier label (row["compoundLabel"], e.g. "always !a OR
# exists a" -- see layout.COMPACT_QUANTIFIER_LABELS)
# spells out two whole terms plus a connector word, so it needs
# noticeably more room than a plain "weak_exists a" to still fit on one
# line for typical (short) event names
COMPOUND_MAX_CHARS = 40

# a row whose event splits into a this-state/next-state/next-next-state/...
# run (see layout._split_next_event) gets one tick per
# X-depth, evenly SPLIT_GAP apart, close together instead of one merged
# tick, the original label pushed up to make room, and a small secondary
# label over each populated tick -- a depth with nothing mapped to it
# (e.g. the plain "next" slot in "a & XXb", which has a "this" and a
# "next-next" but nothing in between) still gets a tick, for constant
# spacing, but dimmed with no label (see _split_ticks_svg's empty_color)
# rather than looking like an actual probed value. A boundary tick whose
# anchor was itself a split (row["leftSplit"]/["rightSplit"]) inherits
# the same multi-tick treatment instead of collapsing back into one.
SPLIT_GAP = 34
SPLIT_MAX_CHARS = 10
SPLIT_LABEL_CLEARANCE = 4  # gap between a tick and where its own secondary label starts, growing outward
SPLIT_EXTRA_TOP_PAD = 16 + 12
MONO_CHAR_WIDTH_RATIO = 0.6  # rough IBM Plex Mono advance width, as a fraction of font-size


def _x_scale(domain, range_px):
	d0, d1 = domain
	r0, r1 = range_px
	span = (d1 - d0) or 1.0
	return lambda v: r0 + (v - d0) / span * (r1 - r0)


def _wrap_label(text, max_chars):
	"""Greedy word wrap. A single word longer than max_chars on its own
	just stays on its own (unbroken) line rather than being hyphenated."""
	words = text.split(" ")
	lines, cur = [], ""
	for w in words:
		trial = (cur + " " + w) if cur else w
		if len(trial) > max_chars and cur:
			lines.append(cur)
			cur = w
		else:
			cur = trial
	if cur:
		lines.append(cur)
	return lines


def _label_lines_svg(px, baseline_y, lines, font_size, font_weight, color, anchor="middle"):
	"""Renders `lines` bottom-anchored at baseline_y -- extra lines grow
	upward, so a wrapped 2-line label doesn't push the last line (the one
	vertically closest to the tick/band) out of position. `anchor` lets a
	label grow away from a fixed edge (e.g. "end" so it only extends left)
	instead of always centering on `px` -- needed where two labels sit
	close enough together that centered growth would run them into each
	other regardless of how short either one is."""
	start_y = baseline_y - (len(lines) - 1) * LABEL_LINE_H
	tspans = "".join(
		'<tspan x="{:.1f}" y="{:.1f}">{}</tspan>'.format(px, start_y + i * LABEL_LINE_H, html.escape(line))
		for i, line in enumerate(lines)
	)
	return (
		'<text text-anchor="{anchor}" font-family="IBM Plex Mono, monospace" '
		'font-weight="{fw}" font-size="{fs}" fill="{color}">{tspans}</text>'
	).format(anchor=anchor, fw=font_weight, fs=font_size, color=color, tspans=tspans)


def _label_pixel_width(lines, font_size):
	"""Rough rendered width of the widest line, for deciding whether two
	adjacent labels can stay centered on their own tick without touching."""
	return max((len(line) for line in lines), default=0) * font_size * MONO_CHAR_WIDTH_RATIO


def _split_tick_xs(center_x, n):
	"""n tick x-positions, SPLIT_GAP apart, centered on center_x -- xs[0]
	is X-depth 0 ("this state"), xs[-1] the deepest depth present, same
	left-to-right == earlier-to-later reading as the rest of the
	scopeline."""
	return [center_x + (i - (n - 1) / 2) * SPLIT_GAP for i in range(n)]


def _split_side_labels_svg(xs, baseline_y, texts, font_size):
	"""One small label per populated tick (texts[i] is None for an
	empty/greyed placeholder depth -- see _split_ticks_svg -- which gets
	no label of its own at all). Each label centers directly above its
	own tick when it's narrow enough to fit against its nearest
	populated neighbor without touching -- the common case, since most
	propositions are short -- otherwise edge-anchors away from
	whichever neighbor it would collide with. Reduces to the original
	plain this/next behavior exactly when there are only two populated
	ticks."""
	populated = [i for i, t in enumerate(texts) if t is not None]
	lines_by_i = {i: _wrap_label(texts[i], SPLIT_MAX_CHARS) for i in populated}
	width_by_i = {i: _label_pixel_width(lines_by_i[i], font_size) for i in populated}

	parts = []
	for pos, i in enumerate(populated):
		px, w = xs[i], width_by_i[i]

		crowds_left = pos > 0 and (
			w / 2 + width_by_i[populated[pos - 1]] / 2 + SPLIT_LABEL_CLEARANCE > px - xs[populated[pos - 1]])
		crowds_right = pos < len(populated) - 1 and (
			w / 2 + width_by_i[populated[pos + 1]] / 2 + SPLIT_LABEL_CLEARANCE > xs[populated[pos + 1]] - px)

		if crowds_left and not crowds_right:
			anchor, ax = "start", px + SPLIT_LABEL_CLEARANCE
		elif crowds_right and not crowds_left:
			anchor, ax = "end", px - SPLIT_LABEL_CLEARANCE
		else:
			anchor, ax = "middle", px

		parts.append(_label_lines_svg(ax, baseline_y, lines_by_i[i], font_size, 600, "var(--band-strong)", anchor=anchor))

	return "\n".join(parts)


def _split_ticks_svg(xs, has_value, y0, y1, axis_y, circle_color, empty_color="var(--axis-arrow)"):
	"""One tick per x in `xs`. A populated position (has_value[i] True)
	is as bold as a plain tick, whether that's a probe's own split
	(circle_color = --band-strong, same as a plain probe's own circle)
	or a boundary tick inheriting one from its anchor (circle_color =
	--axis-arrow, same dim tone the boundary tick's single-circle
	counterpart uses). A position with has_value[i]=False (an X-depth
	nothing maps to, e.g. the plain-next slot in "a & XXb", which has a
	"this" and a "next-next" but nothing in between) still gets a tick,
	for even, constant-distance spacing -- but thinner and in the same
	muted empty_color for both circle and line, regardless of which
	circle_color the real ticks here are using, so it reads as a
	placeholder rather than an actual probed/boundary value either way.
	The circle is drawn before (so it paints behind) its own line, the
	same way every other tick's circle does."""
	parts = []
	for tx, present in zip(xs, has_value):
		color = circle_color if present else empty_color
		line_color = "var(--band-strong)" if present else empty_color
		width = "2.6" if present else "1.6"
		parts.append(
			'<circle cx="{tx:.1f}" cy="{ay:.1f}" r="6" fill="{color}"/>\n'
			'<line x1="{tx:.1f}" y1="{y0:.1f}" x2="{tx:.1f}" y2="{y1:.1f}" stroke="{lcolor}" stroke-width="{width}"/>'
			.format(tx=tx, y0=y0, y1=y1, ay=axis_y, color=color, lcolor=line_color, width=width)
		)
	return "\n".join(parts)


def _quantifier_label(row):
	"""Internal nodes get the lowercase quantifier word in front of the
	event name; leaves get "always"/"sometimes" instead -- never both,
	and never a quantifier word on a leaf. Non-leaf, mustAppear picks the
	"stronger" variant the same way Scopeline.__str__ does: strong_forall
	over plain forall, exists over weak_exists.

	row["compoundLabel"] (see layout.COMPACT_QUANTIFIER_
	LABELS, on by default) overrides all of the above with an inline
	"always !a OR exists a" style string for a weak_exists/strong_forall
	row."""
	if row.get("compoundLabel"):
		return row["compoundLabel"]
	if row["leaf"]:
		word = "always" if row["universal"] else "sometimes"
	elif row["universal"]:
		word = "strong_forall" if row["mustAppear"] else "forall"
	else:
		word = "exists" if row["mustAppear"] else "weak_exists"
	return word + " " + row["event"]


def _row_svg(row, x, row_top):
	axis_y = row_top + ROW_H / 2

	# the band's actual fill edges: normally the same as the anchor tick's
	# own position, but a strict before/after ('leftBound'/'rightBound' !=
	# 'leftPos'/'rightPos') sits a constant gap away from it instead
	band_x0 = x(row["leftBound"])
	tick_x0 = x(row["leftPos"])
	open_right = row["rightBound"] is None
	band_x1 = (W - MARGIN_R) if open_right else x(row["rightBound"])
	tick_x1 = None if open_right else x(row["rightPos"])
	probe_x = x(row["anchorPos"])

	# a boundary whose anchor was itself a this/next split (e.g. "a & Xb")
	# always opens or closes the band flush with the FIRST (this-state)
	# tick, never the second (next-state) one -- "a & Xb" is a single
	# state formula evaluated at one time index (X just looks one step
	# ahead as part of evaluating it), so "after"/"before" that anchor
	# means after/before THAT index, the this-state tick, the same index
	# a plain (non-split) anchor's own single tick would sit at. Both
	# ticks stay visible either way; only the band's own edge moves.
	# Anchored off tick_x0/tick_x1 (the split's own raw, un-strict
	# position) rather than adjusting whatever band_x0/band_x1 already
	# were -- when this side is ALSO strict, band_x0/band_x1 already sit
	# off to one side by the strict gap, and adding the split offset on
	# top of that (instead of replacing it) left a visible gap between
	# the band and the this-state tick instead of reaching it.
	if row.get("leftSplit"):
		band_x0 = _split_tick_xs(tick_x0, len(row["leftSplit"]["levels"]))[0]
	if row.get("rightSplit") and not open_right:
		band_x1 = _split_tick_xs(tick_x1, len(row["rightSplit"]["levels"]))[0]

	# an 'always' leaf holds throughout the whole interval, not at one
	# arbitrary point -- gently tint the whole band instead of a tick
	always_leaf = row["leaf"] and row["universal"]

	parts = []

	# full-width baseline for this row, so the part of the shared scopeline
	# before this row's own scope begins still reads as "the scopeline" --
	# capped with a small t=0 tick on the left and a continues-forever
	# arrow on the right, both always shown regardless of where THIS row's
	# own band happens to start/end, since the underlying scopeline itself
	# always runs from t=0 to infinity even when a row's own scope is
	# narrower than that
	parts.append(
		'<line x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}" stroke="var(--axis-line)" stroke-width="2"/>'
		.format(x(0.0), axis_y, W - MARGIN_R, axis_y)
	)
	# skip the small landmark when this row's own (labeled) left tick
	# already sits at t=0 -- no need to mark the same spot twice
	if row["leftPos"] != 0.0:
		parts.append(_start_tick_svg(x(0.0), axis_y))
	parts.append(_open_arrow_svg(W - MARGIN_R, axis_y))

	# band fill + solid border all the way around -- the only side that's
	# ever actually open is the right one (unbounded, continuing to
	# infinity); every other edge is a real boundary and gets a closing
	# line of its own, regardless of whether it's flush with its tick
	# (non-strict) or offset by the gap (strict)
	fill = "var(--band-always)" if always_leaf else "var(--band-soft)"
	parts.append(
		'<rect x="{:.1f}" y="{:.1f}" width="{:.1f}" height="{}" rx="8" fill="{}"/>'
		.format(band_x0, row_top, max(0.0, band_x1 - band_x0), ROW_H, fill)
	)

	# a strict before/after leaves a gap between the anchor's own tick
	# (drawn further down, at tick_x0/tick_x1) and where the band itself
	# actually starts/ends -- mark that second position with the same
	# dim circle a boundary tick gets too, sitting behind the band's own
	# edge line (appended right after this) the same way every tick's
	# circle sits behind its own line. Skipped when this side has a split
	# -- there band_x0/band_x1 already coincide with the split's own
	# outer tick (see above), which already has its own circle.
	if row["leftBound"] != row["leftPos"] and not row.get("leftSplit"):
		parts.append('<circle cx="{:.1f}" cy="{:.1f}" r="6" fill="var(--axis-arrow)"/>'.format(band_x0, axis_y))
	if not open_right and row["rightBound"] != row["rightPos"] and not row.get("rightSplit"):
		parts.append('<circle cx="{:.1f}" cy="{:.1f}" r="6" fill="var(--axis-arrow)"/>'.format(band_x1, axis_y))

	parts.append(
		'<line x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}" stroke="var(--band)" stroke-width="1.5"/>'
		.format(band_x0, row_top, band_x1, row_top)
	)
	parts.append(
		'<line x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}" stroke="var(--band)" stroke-width="1.5"/>'
		.format(band_x0, row_top + ROW_H, band_x1, row_top + ROW_H)
	)
	parts.append(
		'<line x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}" stroke="var(--band)" stroke-width="1.5"/>'
		.format(band_x0, row_top, band_x0, row_top + ROW_H)
	)
	if not open_right:
		parts.append(
			'<line x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}" stroke="var(--band)" stroke-width="1.5"/>'
			.format(band_x1, row_top, band_x1, row_top + ROW_H)
		)

	# left boundary tick -- at the anchor's own position (always present,
	# either a named anchor or t=0), which may sit a small gap away from
	# the band's actual edge above when this side is strict. Inherits its
	# anchor's own this/next split, if it had one, instead of collapsing
	# back into a single merged tick.
	if row.get("leftSplit"):
		parts.append(_split_tick_svg(tick_x0, row_top, row["leftSplit"]))
	else:
		parts.append(_tick_svg(tick_x0, row_top, row["leftLabel"]))

	# right boundary tick (only when this row's scope is actually closed --
	# the baseline's own always-shown arrow above covers the open case)
	if not open_right:
		if row.get("rightSplit"):
			parts.append(_split_tick_svg(tick_x1, row_top, row["rightSplit"]))
		else:
			parts.append(_tick_svg(tick_x1, row_top, row["rightLabel"]))

	# this row's own quantifier/operator + event label: a tick for
	# "forall/exists X" and "sometimes X" (a specific, if unfixed, point),
	# just the tinted band + a label for "always X" (no single point to mark).
	# A probe whose event splits into a this-state/next-state pair (e.g.
	# "a & Xb") gets two close ticks instead of one -- doesn't apply to
	# always_leaf, which has no single point to probe in the first place.
	label = _quantifier_label(row)
	max_chars = COMPOUND_MAX_CHARS if row.get("compoundLabel") else PROBE_MAX_CHARS
	if always_leaf:
		parts.append(_label_only_svg(probe_x, row_top, label, max_chars))
	elif row.get("nextSplit"):
		parts.append(_split_probe_svg(probe_x, row_top, axis_y, label, row["nextSplit"], max_chars))
	else:
		parts.append(_probe_svg(probe_x, row_top, axis_y, label, max_chars))

	return "\n".join(parts)


def _tick_svg(px, row_top, label):
	"""A plain boundary tick -- as bold as a probe tick (same stroke
	weight and color), with its own circle marker too, but dimmed
	(--axis-arrow, the same muted tone as the continues-forever arrow)
	rather than the bright --band-strong a probe's circle gets, so a
	boundary still visually reads as secondary to an actual probed
	point. Spans the row's full height rather than a shorter inset span,
	since it's marking a scope wall rather than a single probed point."""
	axis_y = row_top + ROW_H / 2
	label_svg = _label_lines_svg(px, row_top - 8, _wrap_label(label, TICK_MAX_CHARS), 12.5 * LABEL_SCALE, 600, "var(--band-strong)")
	return (
		'<circle cx="{px:.1f}" cy="{ay:.1f}" r="6" fill="var(--axis-arrow)"/>\n'
		'<line x1="{px:.1f}" y1="{y0:.1f}" x2="{px:.1f}" y2="{y1:.1f}" stroke="var(--band-strong)" stroke-width="2.6"/>\n{label_svg}'
	).format(px=px, y0=row_top, y1=row_top + ROW_H, ay=axis_y, label_svg=label_svg)


def _split_tick_svg(px, row_top, split):
	"""A boundary tick whose anchor was itself a this-state/next-state/...
	split (see layout._split_next_event): drawn as the
	same run of close ticks the anchor's own probe used (one per
	X-depth, empty ones included -- see _split_ticks_svg), rather than
	collapsing back into one merged tick. No big elevated label here --
	that already appeared once on the anchor's own row -- just each
	populated tick's own small label, at the same spot the single
	merged label used to sit."""
	axis_y = row_top + ROW_H / 2
	levels = split["levels"]
	xs = _split_tick_xs(px, len(levels))
	has_value = [v is not None for v in levels]
	ticks = _split_ticks_svg(xs, has_value, row_top, row_top + ROW_H, axis_y, circle_color="var(--axis-arrow)")
	labels = _split_side_labels_svg(xs, row_top - 8, levels, 10.5 * LABEL_SCALE)
	return ticks + "\n" + labels


def _probe_svg(px, row_top, axis_y, label, max_chars=PROBE_MAX_CHARS):
	label_svg = _label_lines_svg(px, row_top - 8, _wrap_label(label, max_chars), 15 * LABEL_SCALE, 600, "var(--band-strong)")
	return (
		'<circle cx="{px:.1f}" cy="{ay:.1f}" r="6" fill="var(--band-strong)"/>\n'
		'<line x1="{px:.1f}" y1="{y0:.1f}" x2="{px:.1f}" y2="{y1:.1f}" stroke="var(--band-strong)" stroke-width="2.6"/>\n{label_svg}'
	).format(px=px, y0=axis_y - 22, y1=axis_y + 22, ay=axis_y, label_svg=label_svg)


def _split_probe_svg(px, row_top, axis_y, label, split, max_chars=PROBE_MAX_CHARS):
	"""A close run of ticks instead of one, for a probe whose event is a
	this-state/next-state/next-next-state/... run (see
	layout._split_next_event): one tick per X-depth from
	0 ("this state") up to however deep the event reached -- a depth
	nothing maps to (e.g. the plain-next slot in "a & XXb") still gets a
	tick, for even spacing, but empty (see _split_ticks_svg) -- each
	populated one with its own small label directly above it. The
	original full-event label still appears exactly as it would for a
	plain probe, just pushed up to leave room underneath for the new
	ones."""

	levels = split["levels"]
	xs = _split_tick_xs(px, len(levels))
	has_value = [v is not None for v in levels]

	ticks = _split_ticks_svg(xs, has_value, axis_y - 22, axis_y + 22, axis_y, circle_color="var(--band-strong)")
	# elevated so it clears the secondary labels sitting underneath it
	main = _label_lines_svg(px, row_top - 30, _wrap_label(label, max_chars), 15 * LABEL_SCALE, 600, "var(--band-strong)")
	side_labels = _split_side_labels_svg(xs, row_top - 4, levels, 10.5 * LABEL_SCALE)

	return ticks + "\n" + main + "\n" + side_labels


def _label_only_svg(px, row_top, label, max_chars=PROBE_MAX_CHARS):
	return _label_lines_svg(px, row_top - 8, _wrap_label(label, max_chars), 15 * LABEL_SCALE, 600, "var(--band-strong)")


def _open_arrow_svg(px, axis_y):
	"""The scopeline-continues-forever marker at the right end of the
	shared baseline. Always drawn, regardless of whether THIS row's own
	band is open or closed -- a paler, darker tone than the baseline
	itself (--axis-arrow vs --axis-line), so it reads as a continuation
	of the line rather than competing with the row's own content."""
	return (
		'<path d="M {x0:.1f} {y:.1f} L {x1:.1f} {yu:.1f} L {x1:.1f} {yd:.1f} Z" fill="var(--axis-arrow)"/>\n'
		'<text x="{xt:.1f}" y="{yt:.1f}" font-family="IBM Plex Mono, monospace" font-weight="600" font-size="{fs}" fill="var(--axis-arrow)">&#8230;</text>'
	).format(x0=px, x1=px - 15, y=axis_y, yu=axis_y - 8, yd=axis_y + 8, xt=px + 10, yt=axis_y + 5, fs=16 * LABEL_SCALE)


def _start_tick_svg(px, axis_y):
	"""The t=0 landmark at the left end of the shared baseline -- always
	drawn, marking where the whole scopeline begins, independent of
	wherever THIS row's own band happens to start."""
	return '<line x1="{px:.1f}" y1="{y0:.1f}" x2="{px:.1f}" y2="{y1:.1f}" stroke="var(--axis-line)" stroke-width="2"/>'.format(
		px=px, y0=axis_y - 9, y1=axis_y + 9
	)


def _block_height(rows, connectors):
	"""The gap after a row that hosts a connector (see render_svg) is
	CONNECTOR_EXTRA_GAP wider than a plain ROW_GAP."""
	connector_after = {c["afterIndex"] for c in connectors}
	gaps = sum((ROW_GAP + CONNECTOR_EXTRA_GAP if i in connector_after else ROW_GAP) for i in range(len(rows) - 1))
	return len(rows) * ROW_H + gaps


def _connector_label_svg(px, y, op, anchor):
	"""The "AND"/"OR" that visually joins two scopeline blocks, or a
	branch point's own future/past split (see build_row_blocks /
	_split_next_event's sibling, layout._walk's
	connectors) -- uppercase and muted, distinct from the lowercase
	quantifier/event labels that are the actual scopeline content."""
	return (
		'<text x="{px:.1f}" y="{y:.1f}" text-anchor="{anchor}" font-family="IBM Plex Mono, monospace" '
		'font-weight="700" font-size="{fs}" letter-spacing="0.06em" fill="var(--text-muted)">{text}</text>'
	).format(px=px, y=y - 6, anchor=anchor, text=op.upper(), fs=13 * LABEL_SCALE)


def render_svg(blocks, operator=None, depths=None):
	"""`blocks` is a list of (rows, connectors) pairs -- one independent
	block per Scopeline object being rendered (see build_row_blocks). Each
	block gets its own x-scale, starting fresh from its own t=0 at the
	same left edge, stacked top to bottom with a divider between blocks
	so an AND/OR concatenation doesn't read as a continuous scopeline.
	`operator` ("and"/"or") labels that divider, when there's more than
	one block -- multiple root Scopelines only ever come from
	ScopelineBuilder joining them with a single shared operator. Each
	block's own `connectors` labels a branch point's future/past split
	the same way, right where the two subtrees meet."""

	# A split row's main label sits higher than a plain probe's to leave
	# room for the two secondary labels underneath it -- on the very
	# first row that can run past the usual top padding, so give the
	# whole diagram a bit more headroom whenever any row needs it.
	has_split = any(row.get("nextSplit") for rows, _c in blocks for row in rows)
	top_pad = TOP_PAD + SPLIT_EXTRA_TOP_PAD if has_split else TOP_PAD

	# multiple blocks only ever come from ScopelineBuilder joining them
	# with a single shared operator, so the gap between every pair of
	# blocks is a connector gap whenever operator is given at all
	# operator is one label for every gap, or a list with one label per gap
	# (a decomposed result's nested AND/OR, see utils.gap_labels)
	labels = operator if isinstance(operator, list) else [operator] * (len(blocks) - 1)
	# depths = (gap depths, block depths), see utils.nesting_depths: each
	# divider and each block is indented by its nesting depth, so an outer
	# connector's line is the longest and the bands sit innermost
	gap_depths, block_depths = depths if depths else ([0] * (len(blocks) - 1), [0] * len(blocks))
	# the innermost blocks start at MARGIN_L, as a single scopeline does, so
	# bands keep the same width; outer dividers reach into the left margin
	indent_x = lambda depth: MARGIN_L - (max(block_depths) - depth) * NEST_INDENT
	block_gap = BLOCK_GAP + CONNECTOR_EXTRA_GAP if any(labels) else BLOCK_GAP

	height = top_pad + sum(_block_height(rows, c) for rows, c in blocks) + block_gap * (len(blocks) - 1) + BOTTOM_PAD

	body = []
	block_top = top_pad
	for bi, (rows, connectors) in enumerate(blocks):
		if bi > 0:
			divider_y = block_top - block_gap / 2
			body.append(
				'<line x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}" stroke="var(--line)" stroke-width="1"/>'
				.format(indent_x(gap_depths[bi - 1]), divider_y, W - MARGIN_R, divider_y)
			)
			if labels[bi - 1]:
				body.append(_connector_label_svg(indent_x(gap_depths[bi - 1]), divider_y, labels[bi - 1], anchor="start"))

		# branching interleaves past/future rows, so the widest anchor isn't
		# necessarily the last row in the list -- take the max over all of them
		max_anchor = max(row["anchorPos"] for row in rows)
		domain = (0.0, max_anchor + DOMAIN_PAD)
		x = _x_scale(domain, (indent_x(block_depths[bi]), W - MARGIN_R))

		connector_after = {c["afterIndex"]: c for c in connectors}

		row_top = block_top
		for i, row in enumerate(rows):
			body.append(_row_svg(row, x, row_top))
			connector = connector_after.get(i)
			if connector:
				# biased toward THIS row's bottom edge rather than centered
				# in the gap -- centered would run into the NEXT row's own
				# tick label, which already claims the upper ~21px of the
				# ROW_GAP above its row_top
				gap_y = row_top + ROW_H + 12
				body.append(_connector_label_svg(x(connector["anchorPos"]), gap_y, connector["op"], anchor="middle"))
			row_top += ROW_H + (ROW_GAP + CONNECTOR_EXTRA_GAP if connector else ROW_GAP)

		block_top += _block_height(rows, connectors) + block_gap

	return (
		'<svg viewBox="0 0 {w} {h}" class="scopeline-svg" role="img" '
		'aria-label="Scopeline diagram" xmlns="http://www.w3.org/2000/svg">\n{body}\n</svg>'
	).format(w=W, h=height, body="\n".join(body))
