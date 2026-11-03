"""Parsing the printed form of a search result (str(Scopeline), joined with
"and"/"or", possibly in nested groups) back into Scopeline objects."""

import spot

from .scopeline import Scopeline, Quantifier



_KEYWORDS = {
	"forall": Quantifier.FORALL, "strong_forall": Quantifier.STRONG_FORALL,
	"exists": Quantifier.EXISTS, "weak_exists": Quantifier.WEAK_EXISTS,
}


def _matching_paren(s, k):
	assert s[k] == "(", (s, k)
	depth, quoted = 0, False
	for m in range(k, len(s)):
		c = s[m]
		if c == '"':
			quoted = not quoted
		elif not quoted and c == "(":
			depth += 1
		elif not quoted and c == ")":
			depth -= 1
			if depth == 0:
				return m
	raise ValueError(f"unbalanced parentheses in {s!r}")


def _expect(s, k, token):
	if not s.startswith(token, k):
		raise ValueError(f"expected {token!r} at {k} in {s!r}")
	return k + len(token)


def _parse_node(s, k):
	k = _expect(s, k, "(")
	space = s.index(" ", k)
	keyword = s[k:space]
	k = space + 1
	close = _matching_paren(s, k)
	event = spot.formula(s[k + 1:close])
	k = close + 1

	if keyword in ("always", "sometimes"):
		node = Scopeline(event, Quantifier.FORALL if keyword == "always" else Quantifier.EXISTS)
		return node, _expect(s, k, ")")

	k = _expect(s, k, " ")
	strictly = s.startswith("strictly ", k)
	if strictly:
		k += len("strictly ")
	direction = "before" if s.startswith("before ", k) else "after"
	k = _expect(s, k, direction + " ")
	child, k = _parse_node(s, k)
	child.strictly = strictly
	k = _expect(s, k, ")")

	if keyword not in _KEYWORDS:
		raise ValueError(f"unknown quantifier {keyword!r} in {s!r}")
	node = Scopeline(event, _KEYWORDS[keyword])
	setattr(node, direction, child)
	return node, k


def parse_result(text):
	"""Like parse_scopelines, but also reads a decomposed result's nested
	groups, e.g. '((S1) and (S2)) or (S3)': returns (scopelines, joiner),
	the joiner being None, "and"/"or", or a nested spec (op, children) over
	indices into scopelines when the groups nest."""
	leaves = []
	def sequence(s):
		items, joiner, k = [], None, 0
		while True:
			if s.startswith("((", k):
				close = _matching_paren(s, k)
				items.append(sequence(s[k + 1:close]))
				k = close + 1
			else:
				node, k = _parse_node(s, k)
				leaves.append(node)
				items.append(len(leaves) - 1)
			if k == len(s):
				break
			for word in (" and ", " or "):
				if s.startswith(word, k):
					if joiner not in (None, word.strip()):
						raise ValueError(f"mixed joiners in {s!r}")
					joiner, k = word.strip(), k + len(word)
					break
			else:
				raise ValueError(f"expected a joiner at {k} in {s!r}")
		return items[0] if len(items) == 1 else (joiner, tuple(items))
	spec = sequence(text)
	if not isinstance(spec, tuple):
		return leaves, None
	if all(not isinstance(c, tuple) for c in spec[1]):
		return leaves, spec[0]
	return leaves, spec
