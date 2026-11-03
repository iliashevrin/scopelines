"""
Cross-checks scopeline semantics against LTL with the independent oracle
(scopelines/oracle.py), which interprets the window semantics directly and
shares no code with the translation LTL(.) (Section VII-A of the paper).

  python3 verify_oracle.py random [--count 10000] [--max-nodes 5] [--seed 1]
      Random supported scopelines (with a non-trivial LTL(S)) over the
      atomic propositions {a, b}, each compared with spot's verdict for
      LTL(S) on every distinct lasso word with a prefix of at most 2 and a
      loop of at most 3 letters (1,216 words). Also checks negation duality
      (oracle(neg S) = not oracle(S)), and reports which cases of the proof
      of Theorem 1 the scopelines exercise, and how many of them evaluate
      some child over an empty window.

  python3 verify_oracle.py reported [results/detail.csv] [--lassos 1000] [--seed 1]
      Every found scopeline of a benchmark run, parsed back from its printed
      form, compared with spot's verdict for its original formula on N
      random lassos plus an accepting word of the formula and one of its
      negation, and checked equivalent to the formula by spot.

Both modes re-evaluate every oracle verdict with a doubled pumping bound
(see scopelines/oracle.py) and report any verdict that changes.
"""

import argparse
import csv
import itertools
import math
import os
import random
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import buddy
import spot

from scopelines.scopeline import Scopeline, Quantifier
from scopelines.oracle import Lasso, Oracle, oracle_holds
from scopelines.parse import parse_result
from scopelines.utils import result_str, result_ltl


# ----------------------------------------------------------------- helpers

def spot_verdicts(formula, lassos, aps):
	aut = spot.translate(formula)
	return [aut.intersects(spot.parse_word(w.to_spot(aps), aut.get_dict()).as_automaton()) for w in lassos]


def all_lassos(aps, max_prefix, max_loop):
	"""Every distinct lasso word with |prefix| <= max_prefix, |loop| <= max_loop."""
	letters = [frozenset(c) for r in range(len(aps) + 1) for c in itertools.combinations(aps, r)]
	horizon = max_prefix + math.lcm(*range(1, max_loop + 1))
	seen, out = set(), []
	for p in range(max_prefix + 1):
		for q in range(1, max_loop + 1):
			for prefix in itertools.product(letters, repeat=p):
				for loop in itertools.product(letters, repeat=q):
					w = Lasso(prefix, loop)
					key = tuple(w.letter(n) for n in range(horizon))
					if key not in seen:
						seen.add(key)
						out.append(w)
	return out


def word_to_lasso(word, aps):
	"""A spot twa_word (e.g. an accepting word) as a Lasso of full letters."""
	word.simplify()
	d = word.get_dict()
	def letter(b):
		cube = spot.bdd_to_formula(buddy.bdd_satone(b), d)
		lits = list(cube) if cube.kind() == spot.op_And else [cube]
		return frozenset(l.ap_name() for l in lits if l.kind() == spot.op_ap)
	return Lasso([letter(b) for b in word.prefix], [letter(b) for b in word.cycle])


def random_lasso(rng, aps, max_prefix=3, max_loop=3):
	density = rng.uniform(0.15, 0.85)
	pick = lambda: frozenset(a for a in aps if rng.random() < density)
	return Lasso([pick() for _ in range(rng.randint(0, max_prefix))],
		[pick() for _ in range(rng.randint(1, max_loop))])


def has_before(S):
	return S is not None and (S.before is not None or has_before(S.after))


# ----------------------------------------------------- random scopelines

APS = ("a", "b")


def random_event(rng, depth=2):
	r = rng.random()
	if depth == 0 or r < 0.4:
		ap = rng.choice(APS)
		return ap if rng.random() < 0.5 else "!" + ap
	if r < 0.6:
		return f"X({random_event(rng, depth - 1)})"
	op = rng.choice(["&", "|"])
	return f"({random_event(rng, depth - 1)}) {op} ({random_event(rng, depth - 1)})"


def random_scopeline(rng, max_nodes):
	"""A random chain; half the time, its lower part is shaped like a bounded
	after-chain (one plain polarity, opposite to a bounding node above it),
	so that is_supported() admits bounded cases often enough."""
	n = rng.randint(1, max_nodes)
	aligned = n >= 2 and rng.random() < 0.5
	bounded = rng.randint(1, n - 1) if aligned else 0
	universal = rng.random() < 0.5
	node = None
	for level in range(n):
		if aligned and level < bounded:
			quantifier = Quantifier.FORALL if universal else Quantifier.EXISTS
		elif aligned and level == bounded:
			quantifier = rng.choice([Quantifier.EXISTS, Quantifier.WEAK_EXISTS] if universal
				else [Quantifier.FORALL, Quantifier.STRONG_FORALL])
		elif level == 0:
			quantifier = rng.choice([Quantifier.FORALL, Quantifier.EXISTS])
		else:
			quantifier = rng.choice(list(Quantifier))
		parent = Scopeline(spot.formula(random_event(rng)), quantifier)
		if node is not None:
			node.strictly = rng.random() < 0.5
			before = (level == bounded) if aligned else rng.random() < 0.35
			if before:
				parent.before = node
			else:
				parent.after = node
		node = parent
	return node


def proof_cases(S):
	"""Which proof cases (Section IV-B) a supported scopeline exercises."""
	cases, bound, strict_bound = set(), None, False
	node = S
	while node is not None:
		leaf = node.before is None and node.after is None
		if bound is None:
			cases.add("base (1)" if leaf else ("step (4)" if node.before is not None else "step (1)"))
			if node.is_strong_forall() or node.is_weak_exists():
				cases.add("strong/weak, bounding" if node.before is not None else "strong/weak, unbounded")
		else:
			polarity = "(2)" if node.is_forall() else "(3)"
			cases.add(("base " if leaf else "step ") + polarity + (" strict" if strict_bound else ""))
			if node.after is not None and node.after.strictly:
				cases.add("strict after-child under a bound")
		if node.before is not None:
			bound, strict_bound = node, node.before.strictly
			node = node.before
		else:
			node = node.after
	return cases


class CountingOracle(Oracle):
	"""An Oracle that also records whether some node is evaluated over an
	empty window (e < i)."""
	def __init__(self, word, pump_factor=1):
		super().__init__(word, pump_factor)
		self.empty = False

	def sat(self, S, i, e=None):
		if e is not None and e < i:
			self.empty = True
		return super().sat(S, i, e)


def check_random(task):
	seed, max_nodes = task
	rng = random.Random(seed)
	while True:
		S = random_scopeline(rng, max_nodes)
		if not S.is_supported():
			continue
		ltl = S.to_ltl()
		if spot.are_equivalent(ltl, spot.formula.tt()) or spot.are_equivalent(ltl, spot.formula.ff()):
			continue
		break
	lassos = LASSOS
	expected = spot_verdicts(ltl, lassos, APS)
	neg = S.copy()
	neg.negate()
	out = {"scopeline": str(S), "ltl": str(ltl), "cases": sorted(proof_cases(S)),
		"checks": 0, "true": 0, "mismatch": [], "negation": [], "pump": [], "empty": False}
	for w, exp in zip(lassos, expected):
		oracle = CountingOracle(w)
		got = oracle.sat(S, 0)
		out["empty"] |= oracle.empty
		out["checks"] += 1
		out["true"] += got
		if got != exp:
			out["mismatch"].append(repr(w))
		if Oracle(w).sat(neg, 0) == got:
			out["negation"].append(repr(w))
		if has_before(S) and Oracle(w, pump_factor=2).sat(S, 0) != got:
			out["pump"].append(repr(w))
	return out


LASSOS = all_lassos(APS, max_prefix=2, max_loop=3)


# ---------------------------------------------------- reported scopelines

def check_reported(task):
	row, n_lassos, seed = task
	f = spot.formula(row["Formula"])
	nodes, joiner = parse_result(row["Scopeline"])
	printed = result_str(nodes, joiner or "")
	aps = sorted({a.ap_name() for a in spot.atomic_prop_collect(f)} |
		{a.ap_name() for S in nodes for e in S.get_events() for a in spot.atomic_prop_collect(e)})
	rng = random.Random(seed)
	lassos = [random_lasso(rng, aps) for _ in range(n_lassos)]
	for g in (f, spot.formula.Not(f)):
		word = spot.translate(g).accepting_word()
		if word is not None:
			lassos.append(word_to_lasso(word, aps))
	expected = spot_verdicts(f, lassos, aps)
	# printing may reorder an event's commutative operands; compare parsed
	# structures (spot normalizes those operands) rather than raw text
	reparsed, rejoiner = parse_result(printed)
	roundtrip = rejoiner == joiner and reparsed == nodes
	out = {"dataset": row["Dataset"], "formula": row["Formula"], "scopeline": row["Scopeline"],
		"roundtrip": roundtrip, "checks": 0, "true": 0, "mismatch": [], "pump": [],
		"exact": spot.are_equivalent(result_ltl(nodes, joiner or ""), f)}
	for w, exp in zip(lassos, expected):
		got = oracle_holds(nodes, joiner, w)
		out["checks"] += 1
		out["true"] += got
		if got != exp:
			out["mismatch"].append(repr(w))
		if any(has_before(S) for S in nodes) and oracle_holds(nodes, joiner, w, pump_factor=2) != got:
			out["pump"].append(repr(w))
	return out


# -------------------------------------------------------------------- main

def main():
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument("mode", choices=["random", "reported"])
	ap.add_argument("csv", nargs="?", default=str(Path(__file__).resolve().parent / "results" / "detail.csv"),
		help="reported mode: a benchmark detail.csv (default: results/detail.csv)")
	ap.add_argument("--count", type=int, default=10000, help="random mode: number of scopelines (default: 10000)")
	ap.add_argument("--max-nodes", type=int, default=5, help="random mode: maximal node count (default: 5)")
	ap.add_argument("--lassos", type=int, default=1000, help="reported mode: random lassos per scopeline (default: 1000)")
	ap.add_argument("--seed", type=int, default=1, help="random seed (default: 1)")
	ap.add_argument("--procs", type=int, default=os.cpu_count(), help="worker processes (default: all cores)")
	args = ap.parse_args()

	if args.mode == "random":
		tasks = [(args.seed * 1_000_003 + k, args.max_nodes) for k in range(args.count)]
		worker = check_random
		print(f"{len(LASSOS)} distinct lassos over {APS}", flush=True)
	else:
		rows = [r for r in csv.DictReader(open(args.csv)) if r["Found"] == "True"]
		tasks = [(r, args.lassos, args.seed * 1_000_003 + k) for k, r in enumerate(rows)]
		worker = check_reported

	results = []
	with ProcessPoolExecutor(args.procs) as pool:
		for k, res in enumerate(pool.map(worker, tasks, chunksize=4), 1):
			results.append(res)
			if res["mismatch"] or res["pump"] or res.get("negation") or res.get("roundtrip") is False or res.get("exact") is False:
				print("PROBLEM:", res, flush=True)
			if k % 100 == 0:
				print(f"  {k}/{len(tasks)} done", flush=True)

	checks = sum(r["checks"] for r in results)
	trues = sum(r["true"] for r in results)
	print(f"\n{args.mode}: {len(results)} scopelines, {checks} (scopeline, lasso) checks, "
		f"oracle true on {trues} ({100 * trues / checks:.1f}%)")
	print("  semantic mismatches:", sum(len(r["mismatch"]) for r in results),
		"in", sum(1 for r in results if r["mismatch"]), "scopelines")
	print("  verdicts changed by doubling the pumping bound:", sum(len(r["pump"]) for r in results))
	if args.mode == "random":
		print("  negation-duality violations:", sum(len(r["negation"]) for r in results))
		cases = {}
		for r in results:
			for c in r["cases"]:
				cases[c] = cases.get(c, 0) + 1
		print("  proof-case coverage (scopelines exercising each case):")
		for c in sorted(cases):
			print(f"    {c}: {cases[c]}")
		mixed = sum(1 for r in results if 0 < r["true"] < r["checks"])
		print(f"  scopelines with both verdicts among their lassos: {mixed}")
		print(f"  scopelines evaluating some child over an empty window: {sum(r['empty'] for r in results)}")
	else:
		print("  printed-form round-trip failures:", sum(1 for r in results if not r["roundtrip"]))
		print("  not equivalent to their formula (exact spot check):", sum(1 for r in results if not r["exact"]))
		mixed = sum(1 for r in results if 0 < r["true"] < r["checks"])
		print(f"  scopelines with both verdicts among their lassos: {mixed}")


if __name__ == "__main__":
	main()
