"""Semantic deduplication of LTL formulas: equivalence via spot, also up to a
renaming of atomic propositions."""

import itertools

import spot


def _formula_aps(formula):
	# Direct AST walk rather than building an automaton just to read .ap()
	# -- cheap, and this runs inside an all-pairs search below.
	out = set()

	def walk(node):
		if node._is(spot.op_ap):
			out.add(node.ap_name())
			return
		for sub in node:
			walk(sub)

	walk(formula)
	return out


def _are_equivalent_up_to_renaming(f, rep):
	# spot.are_equivalent treats atomic propositions as opaque, unrelated
	# symbols, so it can't see that e.g. "G(a -> (c U b))" and
	# "G(x -> (c U y))" are the same requirement pattern wearing different
	# variable names -- a real, recurring case in hand-written requirement
	# sets (the same "signal received -> signal sent" shape reused across
	# different ports/modules under different names). Before giving up, try
	# every bijection between the two formulas' AP sets (relabeling at the
	# AST level via spot.relabel_apply, not by string substitution -- spot's
	# own compact printer can glue an operator directly onto a single-letter
	# AP with no separator, e.g. "Fa", which breaks naive word-boundary
	# text substitution) and check whether any relabeling makes them
	# equivalent. Factorial in AP count, but this runs once, over small
	# per-formula AP sets, during dataset deduplication.
	if spot.are_equivalent(f, rep):
		return True
	aps_f = sorted(_formula_aps(f))
	aps_rep = sorted(_formula_aps(rep))
	if len(aps_f) != len(aps_rep):
		return False
	for perm in itertools.permutations(aps_rep):
		m = spot.relabeling_map()
		for old, new in zip(aps_f, perm):
			m[spot.formula(old)] = spot.formula(new)
		if spot.are_equivalent(spot.relabel_apply(f, m), rep):
			return True
	return False


def dedup_semantically(records):

	# Groups records by Spot logical equivalence up to atomic-proposition
	# renaming (not textual match -- the same datasets can and do phrase
	# the same property differently, using different variable names for
	# it too). Within a group, keeps the most informative record rather
	# than an arbitrary/order-dependent one: a formula a scopeline was
	# found for beats one that wasn't, and among found ones the one whose
	# scopeline has the better (lower) utils.score() wins, since duplicates
	# are, semantically, the same question asked twice.

	groups = []  # list of (representative spot.formula, [records])
	for r in records:
		f = spot.formula(r["formula"])
		for rep, group in groups:
			if _are_equivalent_up_to_renaming(f, rep):
				group.append(r)
				break
		else:
			groups.append((f, [r]))

	deduped = []
	for _rep, group in groups:
		found_in_group = [r for r in group if r["found"]]
		best = min(found_in_group, key=lambda r: r["score"]) if found_in_group else group[0]
		deduped.append(best)

	return deduped
