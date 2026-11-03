"""
Independent semantic oracle for scopelines -- a direct interpreter of the
window semantics (paper, Section III) on ultimately periodic (lasso) words.

It deliberately shares no code with Scopeline.to_ltl(): it reads only a
scopeline's structure (quantifier, event, strictly, before/after child)
and evaluates events on the word itself, so comparing its verdicts with
LTL(S) (or with the formula a scopeline was found for) can catch a
mismatch between the semantics and the translation.

Window semantics, with e = None standing for an infinite window [i, inf]:

	[i,e] |= always p          iff  forall j in [i,e]. p(j)
	[i,e] |= sometimes p       iff  exists j in [i,e]. p(j)
	[i,e] |= Q p after C       iff  Q j in [i,e]. p(j) ->/& [j(+1),e] |= C
	[i,e] |= Q p before C      iff  Q j in [i,e]. p(j) ->/& [i,j(-1)] |= C
	strong_forall adds "and exists j in [i,e]. p(j)", weak_exists adds
	"or forall j in [i,e]. !p(j)"; an empty window (e < i) leaves no j.

Events are evaluated on the whole word, so X may read past a window's end.

Infinite windows quantify over infinitely many j, which a lasso word
reduces to finitely many representatives:
  - after-children (and leaves, and the strong/weak clauses) only depend
    on the suffix from j, so one j per lasso state suffices -- exact;
  - a before-child's window [i,j] keeps growing with j. Its truth is a
    first-order property of the window's word, of quantifier rank r =
    the child's node count, so pumping the loop beyond 2^r iterations
    cannot change it (u^n and u^(n+1) are rank-r equivalent for n >= 2^r,
    and rank-r equivalence is a congruence). We unroll the loop
    pump_factor * 2^r + 1 times; verify_oracle.py re-checks every verdict
    with a doubled pump_factor.
"""

import spot

from .scopeline import Scopeline, Quantifier


class Lasso:
	"""An ultimately periodic word prefix . loop^omega over sets of APs."""

	def __init__(self, prefix, loop):
		assert len(loop) > 0
		self.prefix = tuple(frozenset(s) for s in prefix)
		self.loop = tuple(frozenset(s) for s in loop)
		self.p = len(self.prefix)
		self.q = len(self.loop)

	def norm(self, n):
		return n if n < self.p else self.p + (n - self.p) % self.q

	def letter(self, n):
		n = self.norm(n)
		return self.prefix[n] if n < self.p else self.loop[n - self.p]

	def to_spot(self, aps):
		"""spot.parse_word() syntax, each letter a full assignment over aps."""
		def lit(s):
			return " & ".join(str(spot.formula.ap(a)) if a in s else "!" + str(spot.formula.ap(a)) for a in aps) or "1"
		cycle = "cycle{" + "; ".join(lit(s) for s in self.loop) + "}"
		return "; ".join([lit(s) for s in self.prefix] + [cycle])

	def __repr__(self):
		show = lambda s: "{" + ",".join(sorted(s)) + "}"
		return " ".join(show(s) for s in self.prefix) + " (" + " ".join(show(s) for s in self.loop) + ")^w"


def holds(event, word, n):
	"""Truth of an event (Boolean combination of APs under X) at position n."""
	k = event.kind()
	if k == spot.op_tt:
		return True
	if k == spot.op_ff:
		return False
	if k == spot.op_ap:
		return event.ap_name() in word.letter(n)
	if k == spot.op_Not:
		return not holds(event[0], word, n)
	if k == spot.op_And:
		return all(holds(c, word, n) for c in event)
	if k == spot.op_Or:
		return any(holds(c, word, n) for c in event)
	if k == spot.op_Implies:
		return (not holds(event[0], word, n)) or holds(event[1], word, n)
	if k == spot.op_Equiv:
		return holds(event[0], word, n) == holds(event[1], word, n)
	if k == spot.op_Xor:
		return holds(event[0], word, n) != holds(event[1], word, n)
	if k == spot.op_X:
		return holds(event[0], word, n + 1)
	raise ValueError(f"not an event (Boolean combination under X): {event}")


class Oracle:
	"""Evaluates scopelines on one lasso word, memoizing (node, i, e)."""

	def __init__(self, word, pump_factor=1):
		self.w = word
		self.pump_factor = pump_factor
		self.memo = {}
		self.events = {}

	def ev(self, event, n):
		key = (id(event), self.w.norm(n))
		if key not in self.events:
			self.events[key] = holds(event, self.w, n)
		return self.events[key]

	def suffix_reps(self, i):
		# one j >= i per lasso state: every suffix from i on is one of these
		return range(i, max(i, self.w.p) + self.w.q)

	def before_ends(self, i, child):
		# quantified j >= i for a before-child over [i, j(-1)]: every lasso
		# state, and every loop count up to the pumping bound, per residue
		bound = self.pump_factor * 2 ** child.size()
		return range(i, max(i, self.w.p) + self.w.q * (bound + 1) + 1)

	def sat(self, S, i, e=None):
		"""pi, [i, e] |= S, with e = None for the infinite window [i, inf]."""
		if e is None:
			i = self.w.norm(i)
		key = (id(S), i, e)
		if key in self.memo:
			return self.memo[key]

		if S.before is None and S.after is None:
			js = self.suffix_reps(i) if e is None else range(i, e + 1)
			vals = [self.ev(S.event, j) for j in js]
			res = all(vals) if S.quantifier == Quantifier.FORALL else any(vals)
		else:
			if S.after is not None:
				child, shift = S.after, (1 if S.after.strictly else 0)
				js = self.suffix_reps(i) if e is None else range(i, e + 1)
				inner = lambda j: self.sat(child, j + shift, e)
			else:
				child, shift = S.before, (1 if S.before.strictly else 0)
				js = self.before_ends(i, child) if e is None else range(i, e + 1)
				inner = lambda j: self.sat(child, i, j - shift)
			guards = [(j, self.ev(S.event, j)) for j in js]
			if S.quantifier.is_forall:
				res = all((not g) or inner(j) for j, g in guards)
			else:
				res = any(g and inner(j) for j, g in guards)
			if S.quantifier == Quantifier.STRONG_FORALL:
				res = res and any(g for _, g in guards)
			elif S.quantifier == Quantifier.WEAK_EXISTS:
				res = res or all(not g for _, g in guards)

		self.memo[key] = res
		return res


def oracle_holds(scopelines, joiner, word, pump_factor=1):
	"""pi, 0 |= S1 joiner S2 ...  (joiner "and"/"or"; single scopeline: None),
	or, for a decomposed result, the nested AND/OR spec (op, children) over
	indices into scopelines (see utils.result_str)."""
	oracle = Oracle(word, pump_factor)
	if isinstance(joiner, tuple):
		def holds_spec(spec):
			if not isinstance(spec, tuple):
				return oracle.sat(scopelines[spec], 0)
			vals = [holds_spec(c) for c in spec[1]]
			return all(vals) if spec[0] == "and" else any(vals)
		return holds_spec(joiner)
	vals = [oracle.sat(S, 0) for S in scopelines]
	return all(vals) if joiner == "and" else any(vals)
