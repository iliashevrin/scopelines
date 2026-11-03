"""
Converts scopelines (see scopeline.py) into row specs for rendering (svg.py):
one row per node, top to bottom along the chain, each with a band for the
node's window and ticks for its events.

  - A node's window is inherited from its parent unless the node's own scope
    narrows it: an after-child starts at its parent's event, a before-child
    ends there. A before-bound stays in effect through any number of nested
    after-children.
  - A strict child's band edge is drawn a constant gap away from its parent's
    event tick, instead of flush against it.
  - An event with X is drawn as a run of adjacent ticks, one per position it
    constrains (see _split_next_event).
  - Several scopelines (an AND/OR combination) become separate blocks, each
    laid out on its own from its own t=0.
"""

import spot

from ..utils import _not

STEP = 6.0

# how far a strict ('strictly before'/'strictly after') band edge sits
# from the anchor tick it's attached to, instead of starting/ending flush
GAP = 0.5

# Show a weak_exists/strong_forall row's compound quantifier as
# a single inline label (e.g. "always !a OR exists a") instead of the bare
# word -- see _compound_label. Purely a rendering choice (Scopeline itself
# is never touched); flip to False to go back to the plain single-word
# label ("weak_exists a", etc).
COMPACT_QUANTIFIER_LABELS = True


class UnsupportedScopelineShape(Exception):
	"""Raised when a Scopeline uses a structural shape this simple layout
	has no rendering for yet. Not currently raised anywhere -- kept
	available for whatever shape turns up next that genuinely needs a
	design conversation rather than a guess."""
	pass


def _x_depth(f):
	"""Peels off leading X's, returning (depth, core) -- (0, f) for a
	bare formula, (1, b) for X(b), (2, b) for X(X(b)), and so on."""
	depth = 0
	while f._is(spot.op_X):
		f = f[0]
		depth += 1
	return depth, f


def _split_next_event(event):
	"""If `event` is a top-level AND/OR where every child is some number
	of X's (possibly zero) over a pure-boolean core -- e.g. `a & Xb`,
	`a & X(X(b))`, `Xa | Xb & c` -- returns {"levels": [str-or-None, ...],
	"op": "&"/"|"}, one entry per X-depth from 0 (the "this state" term)
	up to however deep the search actually reached; a depth with no
	matching child (e.g. the plain-next slot in `a & XXb`, which has a
	"this" and a "next-next" but nothing in between) is None there rather
	than omitted, so the caller still knows to draw that tick -- just
	empty -- for even, constant-distance spacing. Otherwise None,
	including when there's no depth-0 ("this state") term to split
	around at all (a bare `Xb` or `XXb` -- there's nothing to split
	there, just one thing to show), or when nothing beyond depth 0 is
	present (plain `a & b`, no X anywhere -- also just one thing to
	show). X distributes over AND/OR in LTL, so if several children land
	at the same depth (e.g. `a & b & Xc`, or `Xa & Xb`), that depth's
	own children just combine under the same operator -- `Xa & Xb` ==
	`X(a & b)`."""

	if event._is(spot.op_And):
		combine = spot.formula.And
		op = "&"
	elif event._is(spot.op_Or):
		combine = spot.formula.Or
		op = "|"
	else:
		return None

	by_depth = {}
	for child in event:
		depth, core = _x_depth(child)
		if not core.is_boolean():
			# some other shape (nested temporal, X of a non-boolean, ...)
			# this split does not handle
			return None
		by_depth.setdefault(depth, []).append(core)

	if 0 not in by_depth or len(by_depth) < 2:
		return None

	max_depth = max(by_depth)
	levels = []
	for d in range(max_depth + 1):
		children = by_depth.get(d)
		if not children:
			levels.append(None)
		else:
			expr = children[0] if len(children) == 1 else combine(children)
			levels.append(str(expr))

	return {"levels": levels, "op": op}


def _compound_label(t):
	"""The inline "always !a OR exists a" style label for a
	weak_exists/strong_forall node -- see COMPACT_QUANTIFIER_LABELS.
	Returns None for anything else (including a leaf -- leaves are never
	constructed as weak_exists/strong_forall). The negated event is
	rebuilt through _not(), which simplify()s away a double negation
	(e.g. event "!a" -> "a"), so a weak_exists node whose own event is
	already negated doesn't show "!!a"."""

	if t.is_leaf():
		return None

	if t.is_weak_exists():
		return "always {} OR exists {}".format(str(_not(t.event)), str(t.event))

	if t.is_strong_forall():
		return "sometimes {} AND forall {}".format(str(t.event), str(t.event))

	return None


def _walk(t, state, incoming):
	"""state = (leftPos, leftLabel, leftSplit, leftBound, rightPos,
	rightLabel, rightSplit, rightBound, prevPos). *Pos/*Label are the
	anchor tick's own position and name; *Split is that same anchor's own
	nextSplit (see _split_next_event), carried along so a boundary tick
	whose anchor was itself a this/next split can be drawn the same way
	(see svg._split_tick_svg) instead of collapsing back to a
	single merged tick; *Bound is where the band's fill actually
	starts/ends -- equal to *Pos unless that side's incoming step was
	strict, in which case it sits GAP away. Returns (rows, endState). A
	root reached with incoming=None and only `past` set (no `future`) is
	fine -- it just means left_pos/left_bound stay at their initial (0.0,
	"t=0") default, since nothing has opened an 'after' yet to move
	them."""

	(left_pos, left_label, left_split, left_bound,
		right_pos, right_label, right_split, right_bound, prev_pos) = state

	pos = (prev_pos + STEP) if prev_pos is not None else STEP

	if incoming is not None:
		anchor_pos, anchor_label, anchor_split, strict = (
			incoming["anchorPos"], incoming["anchorLabel"], incoming["anchorSplit"], incoming["strict"])
		if incoming["direction"] == "after":
			# tighten the left bound to this new anchor; the right bound
			# (if one is already in effect from an ancestor 'before') is
			# inherited, not cleared -- an 'after' nested inside an
			# already-closed scope doesn't escape it
			left_pos, left_label, left_split = anchor_pos, anchor_label, anchor_split
			left_bound = anchor_pos + GAP if strict else anchor_pos
		else:
			# tighten the right bound to this new anchor; left is inherited
			right_pos, right_label, right_split = anchor_pos, anchor_label, anchor_split
			right_bound = anchor_pos - GAP if strict else anchor_pos

	if right_bound is not None:
		# a closed interval: this node's own position (both its probe and
		# whatever anchors off it next) sits inside its band's actual
		# (gap-adjusted) bounds rather than at the raw step position,
		# which could otherwise land past the interval's own right edge
		pos = round(left_bound + 0.5 * (right_bound - left_bound), 3)

	next_split = _split_next_event(t.event)

	row = {
		"event": str(t.event),
		"leaf": t.is_leaf(),
		"universal": t.is_forall(),
		"mustAppear": t.must_appear(),
		"anchorPos": pos,
		"leftPos": left_pos, "leftLabel": left_label, "leftSplit": left_split, "leftBound": left_bound,
		"rightPos": right_pos, "rightLabel": right_label, "rightSplit": right_split, "rightBound": right_bound,
		"nextSplit": next_split,
	}

	if COMPACT_QUANTIFIER_LABELS:
		compound_label = _compound_label(t)
		if compound_label is not None:
			row["compoundLabel"] = compound_label

	rows = [row]
	connectors = []

	# state as it was right after processing this node -- the branch point
	# for a 'before' subtree resets to this, not to wherever 'after' ends
	self_state = (left_pos, left_label, left_split, left_bound,
		right_pos, right_label, right_split, right_bound, pos)
	end_state = self_state

	if t.after is not None:
		after_incoming = {
			"direction": "after", "anchorPos": pos, "anchorLabel": str(t.event), "anchorSplit": next_split,
			"strict": t.after.strictly,
		}
		after_rows, after_connectors, end_state = _walk(t.after, self_state, after_incoming)
		offset = len(rows)
		connectors.extend({**c, "afterIndex": c["afterIndex"] + offset} for c in after_connectors)
		rows.extend(after_rows)

	if t.before is not None:
		before_incoming = {
			"direction": "before", "anchorPos": pos, "anchorLabel": str(t.event), "anchorSplit": next_split,
			"strict": t.before.strictly,
		}
		before_rows, before_connectors, end_state = _walk(t.before, self_state, before_incoming)
		offset = len(rows)
		connectors.extend({**c, "afterIndex": c["afterIndex"] + offset} for c in before_connectors)
		rows.extend(before_rows)

	return rows, connectors, end_state


def build_row_spec(scopeline):
	"""(rows, connectors) for a single Scopeline object, top to bottom
	along its chain. `connectors` is a list of {"afterIndex", "op", "anchorPos"} --
	a label ("and"/"or") to draw in the gap right after row index
	afterIndex, horizontally aligned with anchorPos -- one per real
	branch point (a node with both `past` and `future` set) in the
	tree."""
	rows, connectors, _ = _walk(scopeline, (0.0, "t=0", None, 0.0, None, None, None, None, None), None)
	return rows, connectors


def build_row_blocks(scopelines):
	"""(rows, connectors) pairs (see build_row_spec) for one or more
	Scopeline objects, one independent block per scopeline. `scopelines` may
	be a single Scopeline or a list/tuple of them. Each block is laid out
	on its own, starting fresh from its own t=0, and the blocks are
	stacked top to bottom."""
	if not isinstance(scopelines, (list, tuple)):
		scopelines = [scopelines]
	return [build_row_spec(_display_copy(t)) for t in scopelines]


def _push_x(f, depth=0):
	# X pushed down to the literals, e.g. "!a | X(!a | X!a)" -> "!a | X!a | XX!a"
	if f._is(spot.op_X):
		return _push_x(f[0], depth + 1)
	if f.kind() in (spot.op_ap, spot.op_tt, spot.op_ff) or (f._is(spot.op_Not) and f[0]._is(spot.op_ap)):
		for _ in range(depth):
			f = spot.formula.X(f)
		return f
	return f.map(lambda c: _push_x(c, depth))


def _display_copy(t):
	"""A copy of `t` whose events show X pushed down to the literals --
	spot's simplify() stores e.g. "!a | X(!a | X!a)", which neither reads
	well nor splits into per-step ticks."""
	t = t.copy()
	def walk(node):
		node.event = _push_x(node.event)
		for child in (node.before, node.after):
			if child is not None:
				walk(child)
	walk(t)
	return t
