"""LTL construction helpers (spot) and helpers for search results."""

import spot
spot.setup()

__all__ = ["negate_operator", "result_str", "result_ltl", "gap_labels", "nesting_depths", "_and", "_or", "implies", "u", "f", "x", "g", "_not", "peel",
"is_literal_event", "score"]


def _and(*exp):
	return spot.formula.And(exp)

def _or(*exp):
	return spot.formula.Or(exp)

def implies(exp1, exp2):
	return spot.formula.Implies(exp1, exp2)

def u(exp1, exp2):
	return spot.formula.U(exp1, exp2)

def f(exp):
	return spot.formula.F(exp)

def x(exp):
	return spot.formula.X(exp)

def g(exp):
	return spot.formula.G(exp)

def _not(exp):
	return spot.formula.Not(exp).simplify()

# A result is (scopelines, operator): operator is "" for a single
# scopeline, "and"/"or" for a flat combination, or, for a decomposed
# formula (ScopelineBuilder.iter_scopelines), a nested spec (op, children)
# whose children are indices into scopelines or nested specs.

def _flip(op):
	return "or" if op == "and" else "and" if op == "or" else op

def negate_operator(operator):
	if isinstance(operator, tuple):
		op, children = operator
		return (_flip(op), tuple(negate_operator(c) if isinstance(c, tuple) else c for c in children))
	return _flip(operator)

def result_str(scopelines, operator):
	def spec_str(spec, top):
		if not isinstance(spec, tuple):
			return str(scopelines[spec])
		text = " {} ".format(spec[0]).join(spec_str(c, False) for c in spec[1])
		return text if top else "(" + text + ")"
	if isinstance(operator, tuple):
		return spec_str(operator, True)
	return " {} ".format(operator).join(str(t) for t in scopelines)

def result_ltl(scopelines, operator):
	def spec_ltl(spec):
		if not isinstance(spec, tuple):
			return scopelines[spec].to_ltl()
		parts = [spec_ltl(c) for c in spec[1]]
		return spot.formula.And(parts) if spec[0] == "and" else spot.formula.Or(parts)
	if isinstance(operator, tuple):
		return spec_ltl(operator)
	parts = [t.to_ltl() for t in scopelines]
	return parts[0] if len(parts) == 1 else spot.formula.And(parts) if operator == "and" else spot.formula.Or(parts)

def gap_labels(operator, n):
	"""One label per gap between consecutive scopelines when rendering them
	as stacked blocks: the operator joining them, in as many parentheses as
	that operator is nested in the spec."""
	if not isinstance(operator, tuple):
		return operator
	paths = {}
	def walk(spec, path):
		for c in spec[1]:
			if isinstance(c, tuple):
				walk(c, path + [(id(c), c[0])])
			else:
				paths[c] = path
	walk(operator, [(id(operator), operator[0])])
	labels = []
	for i in range(n - 1):
		a, b = paths[i], paths[i + 1]
		common = 0
		while common < min(len(a), len(b)) and a[common] == b[common]:
			common += 1
		depth = common - 1
		labels.append("(" * depth + a[common - 1][1] + ")" * depth)
	return labels

def nesting_depths(operator, n):
	"""For rendering n stacked scopelines: the nesting depth of each gap's
	connector (0 for the outermost) and of each scopeline (the number of
	connectors enclosing it; 0 for a single scopeline)."""
	if not operator:
		return [], [0] * n
	if not isinstance(operator, tuple):
		return [0] * (n - 1), [1] * n
	paths = {}
	def walk(spec, path):
		for c in spec[1]:
			if isinstance(c, tuple):
				walk(c, path + [id(c)])
			else:
				paths[c] = path
	walk(operator, [id(operator)])
	gaps = []
	for i in range(n - 1):
		a, b = paths[i], paths[i + 1]
		common = 0
		while common < min(len(a), len(b)) and a[common] == b[common]:
			common += 1
		gaps.append(common - 1)
	return gaps, [len(paths[i]) for i in range(n)]

def peel(exp):
	if exp._is(spot.op_G) or exp._is(spot.op_F):
		return exp[0]
	else:
		return exp


def is_literal_event(event):
	"""True for a single (possibly negated) atomic proposition, e.g. `a`
	or `!a`; False for a compound boolean label like `a & b`."""
	if event._is(spot.op_ap):
		return True
	return event._is(spot.op_Not) and len(event) == 1 and event[0]._is(spot.op_ap)


def score(scopelines, operator):
	"""A simplicity score of a (scopelines, operator) result -- smaller is
	better; the benchmark's semantic deduplication keeps, within a class of
	equivalent formulas, a found one with the smallest score. Starts from the base size (sum of
	each root Scopeline.size()) and adds a +1 penalty for each:
	  - strong_forall/weak_exists node (a more elaborate quantifier than
	    plain forall/exists),
	  - implicit and/or from multiple root scopelines being joined,
	  - compound (non-literal) event label, e.g. "a & b"."""

	total = sum(t.size() for t in scopelines)

	if len(scopelines) > 1:
		total += len(scopelines) - 1

	def walk(node):
		nonlocal total
		if node.is_strong_forall() or node.is_weak_exists():
			total += 1
		if not is_literal_event(node.event):
			total += 1
		if node.before is not None:
			walk(node.before)
		if node.after is not None:
			walk(node.after)

	for t in scopelines:
		walk(t)

	return total