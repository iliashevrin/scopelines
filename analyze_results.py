"""Derives the numbers, Table I, and Figure 7 of the paper's evaluation
(Section VII) from a benchmark run (run_benchmark.py).

    python3 analyze_results.py [results/]

Reads results/detail.csv and results/dedup.json, prints the statistics, and
writes results/table1.tex and results/figure7.png.
"""

import argparse
import csv
import json
import statistics as st
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
import spot
from scipy.stats import spearmanr

from scopelines.parse import parse_result

DATASET_NAMES = {"1_dataset_tosem": "LTL Comprehension", "2_ltl2tl_vissoft": "ltl2timeline",
	"3_nl2spec_cav": "nl2spec", "4_spacewire": "SpaceWire", "5_dwyer_patterns": "Dwyer's Patterns"}


def load(results):
	rows = []
	for r in csv.DictReader(open(results / "detail.csv")):
		found = r["Found"] == "True"
		rows.append({"dataset": r["Dataset"], "formula": r["Formula"], "found": found, "status": r["Status"],
			"time": float(r["Search Time (s)"]) if found else None,
			"size": int(r["Node Count"]) if found else None, "depth": int(r["Node Depth"]) if found else None,
			"scopeline": r["Scopeline"], "png_time": float(r["PNG Time (s)"]) if found else None,
			"decomposed": r["Decomposed"] == "True"})
	keys = {tuple(k) for k in json.load(open(results / "dedup.json"))}
	return rows, [r for r in rows if (r["dataset"], r["formula"]) in keys]


def has_x(f):
	return f._is(spot.op_X) or any(has_x(c) for c in f)


def literals(event):
	"""The number of literals of an event, an X-chain over a literal counting as one."""
	k = event.kind()
	if k == spot.op_ap:
		return 1
	if k in (spot.op_tt, spot.op_ff):
		return 0
	if k in (spot.op_Not, spot.op_X) and event[0].kind() in (spot.op_ap, spot.op_X):
		return literals(event[0])
	return sum(literals(c) for c in event)


def events(r):
	scopelines, _ = parse_result(r["scopeline"])
	out = []
	def walk(s):
		out.append(s.event)
		for c in (s.before, s.after):
			if c is not None:
				walk(c)
	for s in scopelines:
		walk(s)
	return out, scopelines


def automaton(formula):
	aut = spot.translate(formula, "Buchi", "sbacc", "state-based", "complete")
	edges = sum(1 for s in range(aut.num_states()) for _ in aut.out(s))
	return aut.num_states(), edges, len(spot.atomic_prop_collect(spot.formula(formula)))


def table_row(name, rows):
	found = [r for r in rows if r["found"]]
	times = [r["time"] for r in found]
	sizes = [r["size"] for r in found]
	depths = [r["depth"] for r in found]
	lits = [literals(e) for r in found for e in events(r)[0]]
	return (f"{name} & {len(rows)} & {len(found)} ({100 * len(found) / len(rows):.1f}\\%) & {st.mean(times):.2f} & "
		f"{st.median(times):.2f} & {min(times):.2f}--{max(times):.2f} & {st.mean(sizes):.2f} ({min(sizes)}--{max(sizes)}) & "
		f"{st.mean(depths):.2f} ({min(depths)}--{max(depths)}) & {st.mean(lits):.2f} ({min(lits)}--{max(lits)}) \\\\")


def dwyer_survey(rows):
	"""Maps the 55 Dwyer formulas (11 patterns x 5 scopes, in file order) onto
	Dwyer et al.'s survey of real-world instances per pattern and scope."""
	dwyer = [r for r in rows if r["dataset"] == "5_dwyer_patterns"]
	if len(dwyer) != 55:
		return None
	patterns = ["Absence", "Existence", "BoundExist", "Universality", "Precedence", "Response",
		"PrecChain", "PrecChain", "RespChain", "RespChain", None]  # the last is the Constrained Chain
	scopes = ["Glbl", "Bfr", "Aftr", "Btwn", "Untl"]
	survey = {
		"Absence": [41, 5, 12, 18, 9], "Universality": [110, 1, 5, 2, 1], "Existence": [12, 1, 4, 8, 1],
		"BoundExist": [0, 0, 0, 1, 0], "Response": [241, 1, 3, 0, 0], "Precedence": [25, 0, 1, 0, 0],
		"RespChain": [8, 0, 0, 0, 0], "PrecChain": [1, 0, 0, 0, 0]}
	occurring, never, missed = [0, 0], [0, 0], []
	for i, r in enumerate(dwyer):
		pattern = patterns[i // 5]
		count = survey[pattern][i % 5] if pattern else 0  # the Constrained Chain is not surveyed
		target = occurring if count >= 1 else never
		target[0] += 1
		target[1] += r["found"]
		if count >= 1 and not r["found"]:
			missed.append(f"{pattern} / {scopes[i % 5]}")
	return occurring, never, missed


def figure7(found, notfound, path):
	edges_f = [r["edges"] for r in found]
	edges_nf = [r["edges"] for r in notfound]
	fig, (top, bottom) = plt.subplots(2, 1, figsize=(5.2, 3.9), sharex=True, gridspec_kw={"height_ratios": [1.3, 1]})
	top.scatter(edges_f, [r["time"] for r in found], alpha=0.6, color="#2b6cb0", s=18)
	top.scatter(edges_nf, [max(r["time"] for r in found) * 1.6] * len(edges_nf), marker="x", color="#4a5568", alpha=0.8, s=18)
	top.set_yscale("log")
	top.set_ylabel("Search time\n(s, log scale)", fontsize=10)
	sizes = [r["size"] for r in found]
	bottom.scatter(edges_f, sizes, marker="s", facecolors="none", edgecolors="#dd6b20", linewidths=1.0, s=20)
	bottom.set_yticks(range(1, max(sizes) + 2, 2))
	bottom.set_ylabel("Node count", fontsize=10)
	bottom.set_xscale("log")
	ticks = [5]
	while ticks[-1] < max(edges_f + edges_nf):
		ticks.append(ticks[-1] * 2)
	bottom.set_xticks(ticks)
	bottom.xaxis.set_major_formatter(matplotlib.ticker.ScalarFormatter())
	bottom.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
	bottom.set_xlabel("Number of edges in formula's Büchi automaton (log scale)", fontsize=10)
	for ax in (top, bottom):
		ax.tick_params(labelsize=9)
	fig.tight_layout()
	fig.savefig(path, dpi=300)


def main():
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("results", nargs="?", type=Path, default=Path(__file__).resolve().parent / "results",
		help="the output directory of run_benchmark.py (default: results/)")
	args = parser.parse_args()
	rows, distinct = load(args.results)
	found = [r for r in distinct if r["found"]]
	if not found:
		sys.exit("no formula was found in this run")
	n = len(distinct)

	print("== Datasets (Section VII-A)")
	for name in DATASET_NAMES:
		print(f"  {DATASET_NAMES[name]}: {sum(r['dataset'] == name for r in rows)} formulas after deduplication within the dataset")
	print(f"  {len(rows)} in total, {n} after deduplication across datasets")
	for r in distinct:
		r["states"], r["edges"], r["aps"] = automaton(r["formula"])
	aps = [r["aps"] for r in distinct]
	print(f"  atomic propositions per formula: {min(aps)} to {max(aps)}, {st.mean(aps):.2f} on average")

	print("\n== Table I (LaTeX rows)")
	table = [table_row(DATASET_NAMES[name], [r for r in rows if r["dataset"] == name])
		for name in DATASET_NAMES if any(r["dataset"] == name and r["found"] for r in rows)]
	table.append(table_row("Combined (dedup)", distinct))
	for line in table:
		print("  " + line)
	(args.results / "table1.tex").write_text("\n".join(table) + "\n")

	print("\n== Results (Section VII-B)")
	lits = [literals(e) for r in found for e in events(r)[0]]
	print(f"  found: {len(found)} of {n} ({100 * len(found) / n:.1f}%)")
	print(f"  events: {st.mean(lits):.2f} literals on average, {100 * sum(x == 1 for x in lits) / len(lits):.1f}% a single literal")
	small = sum(r["size"] <= 3 for r in found)
	print(f"  at most 3 nodes: {small} of {len(found)} ({100 * small / len(found):.1f}%)")
	deep = [r for r in found if r["depth"] >= 4]
	print(f"  depth 4 or higher: {len(deep)}, {sum(r['dataset'] == '5_dwyer_patterns' for r in deep)} of them from Dwyer's patterns")
	combos = [r for r in found if r["decomposed"]]
	chains = [len(events(r)[1]) for r in combos]
	nested = sum(isinstance(parse_result(r["scopeline"])[1], tuple) for r in combos)
	print(f"  AND/OR combinations: {len(combos)} of {len(found)} ({100 * len(combos) / len(found):.1f}%), "
		f"{sum(c >= 3 for c in chains)} of them with three to {max(chains, default=0)} chains, {nested} nested")
	single = [r for r in found if not r["decomposed"]]
	for label, group in (("single chains", single), ("combinations", combos)):
		if group:
			print(f"    {label}: {len(group)}, {st.mean(r['size'] for r in group):.2f} nodes "
				f"({min(r['size'] for r in group)}-{max(r['size'] for r in group)}), depth {st.mean(r['depth'] for r in group):.2f}")
	largest = max(found, key=lambda r: r["size"])
	print(f"  largest result: {largest['size']} nodes, for {largest['formula']}")
	with_x = [r for r in found if has_x(spot.formula(r["formula"]))]
	uses_x = sum(any(has_x(e) for e in events(r)[0]) for r in with_x)
	print(f"  detected formulas containing X: {len(with_x)}, of which {uses_x} ({100 * uses_x / max(len(with_x), 1):.1f}%) "
		"yield a scopeline with X in some event")
	times = [r["time"] for r in found]
	slowest = max(found, key=lambda r: r["time"])
	print(f"  search time: {st.mean(times):.2f}s on average, median {st.median(times):.2f}s, "
		f"up to {slowest['time']:.2f}s ({slowest['formula']})")
	fast = sum(t < 1 for t in times)
	print(f"  under one second: {fast} of {len(found)} ({100 * fast / len(found):.1f}%)")
	pngs = [r["png_time"] for r in found]
	print(f"  PNG rendering: {st.mean(pngs):.2f}s on average, at most {max(pngs):.2f}s")
	undetected = [r for r in distinct if not r["found"]]
	print(f"  undetected: {len(undetected)}, {sum(r['dataset'] == '5_dwyer_patterns' for r in undetected)} of them Dwyer's patterns; "
		f"{sum(r['status'] == 'timeout' for r in undetected)} timed out, {sum(r['status'] == 'exhausted' for r in undetected)} exhausted the search space")
	survey = dwyer_survey(rows)
	if survey:
		(occ_n, occ_found), (never_n, never_found), missed = survey
		print(f"  Dwyer survey: {occ_found} of the {occ_n} formulas whose combination occurs in practice are detected "
			f"(missing {', '.join(missed)}); {never_found} detected among the {never_n} never observed or not surveyed")

	print("\n== Scalability analysis (Section VII-B)")
	for feature in ("aps", "states", "edges"):
		values = [r[feature] for r in found]
		rho_t, p_t = spearmanr(values, [r["time"] for r in found])
		rho_n, p_n = spearmanr(values, [r["size"] for r in found])
		print(f"  Spearman, {feature:6} vs search time: rho={rho_t:.3f} (p={p_t:.1g}); vs node count: rho={rho_n:.3f} (p={p_n:.1g})")
	print(f"  formulas with more than 20 automaton edges: {sum(r['edges'] > 20 for r in distinct)} of {n}")
	figure7(found, undetected, args.results / "figure7.png")
	print(f"\nWrote {args.results}/table1.tex and {args.results}/figure7.png")


if __name__ == "__main__":
	main()
