"""Fault injection: does the semantic oracle catch a wrong translation?

Each of the nine mutations edits one line of Scopeline._to_ltl (Algorithm 1)
or is_supported (in memory), then reruns the random-mode comparison of
verify_oracle.py on the same random scopelines (seed 7, up to 4 nodes). The
unmutated code must show no disagreement, and every mutation some.

  python3 oracle_mutations.py [count [name-filter]]     (default count: 300)
"""
import inspect
import multiprocessing as mp
import sys
import textwrap

import verify_oracle
from scopelines import scopeline

MUTATIONS = {
	"strict universal bound uses the inclusive until (line 25 -> 27)":
		("_to_ltl", "ltl = u(ltl, bound_ltl)", "ltl = u(ltl, _and(ltl, bound_ltl))"),
	"inclusive universal bound uses the strict until (line 27 -> 25)":
		("_to_ltl", "ltl = u(ltl, _and(ltl, bound_ltl))", "ltl = u(ltl, bound_ltl)"),
	"existential bound drops the G!beta disjunct (line 33)":
		("_to_ltl", "ltl = _or(u(_not(bound_ltl), ltl), g(_not(bound_ltl)))", "ltl = u(_not(bound_ltl), ltl)"),
	"strict after-child not X-shifted (line 11)":
		("_to_ltl", "ltl = x(ltl)", "pass"),
	"strong_forall adjustment dropped (line 38)":
		("_to_ltl", "ltl = _and(ltl, f(self.event))", "pass"),
	"weak_exists adjustment dropped (line 40)":
		("_to_ltl", "ltl = _or(ltl, g(_not(self.event)))", "pass"),
	"condition (2) lifted (same polarity under a bound)":
		("is_supported", "if self.is_forall() == bound.is_forall():", "if False:"),
	"condition (3) lifted (strong/weak under a bound)":
		("is_supported", "if self.is_strong_forall() or self.is_weak_exists():", "if False:"),
	"condition (4) lifted (strict after-child, inclusive bound)":
		("is_supported", "if not bound.before.strictly and self.after is not None and self.after.strictly:", "if False:"),
}

ORIGINAL = {name: getattr(scopeline.Scopeline, name) for name in ("_to_ltl", "is_supported")}


def apply(mutation):
	for name, fn in ORIGINAL.items():
		setattr(scopeline.Scopeline, name, fn)
	if mutation is None:
		return
	name, old, new = MUTATIONS[mutation]
	src = textwrap.dedent(inspect.getsource(ORIGINAL[name]))
	assert src.count(old) == 1, (mutation, src.count(old))
	namespace = {}
	exec(src.replace(old, new), vars(scopeline), namespace)
	setattr(scopeline.Scopeline, name, namespace[name])


def run(mutation, count):
	apply(mutation)
	tasks = [(1_000_003 * 7 + k, 4) for k in range(count)]
	with mp.get_context("fork").Pool(6) as pool:
		results = pool.map(verify_oracle.check_random, tasks, chunksize=8)
	return sum(1 for r in results if r["mismatch"]), sum(len(r["mismatch"]) for r in results)


if __name__ == "__main__":
	count = int(sys.argv[1]) if len(sys.argv) > 1 else 300
	only = sys.argv[2] if len(sys.argv) > 2 else None
	for mutation in [None] + [m for m in MUTATIONS if only is None or only in m]:
		bad, lassos = run(mutation, count)
		print(f"{mutation or 'unmutated'}: {bad}/{count} scopelines disagree ({lassos} lassos)", flush=True)
