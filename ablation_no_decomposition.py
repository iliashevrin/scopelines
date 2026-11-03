"""The decomposition ablation of Section VII-B: reruns, without decomposition,
every distinct formula whose result in a benchmark run is an AND/OR
combination, as well as every undetected one, and reports how many are
then detected (as single chains).

    python3 ablation_no_decomposition.py [results/] [--timeout 60] [--procs 4]

Formulas found as single chains are not rerun: decomposition only adds
searches alongside the search for the formula itself, which is
deterministic, so they are found either way.
"""

import argparse
import csv
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from scopelines.runner import find_scopeline


def rerun(task):
	formula, timeout = task
	result = find_scopeline(formula, timeout=timeout, decompose=False)
	return formula, result.found, sum(s.size() for s in result.scopelines) if result.found else None


def main():
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("results", nargs="?", type=Path, default=Path(__file__).resolve().parent / "results",
		help="the output directory of run_benchmark.py (default: results/)")
	parser.add_argument("--timeout", type=float, default=60, help="search time budget per formula (default: 60)")
	parser.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 2) // 2),
		help="formulas searched in parallel (default: half the cores)")
	args = parser.parse_args()

	keys = {tuple(k) for k in json.load(open(args.results / "dedup.json"))}
	rows = [r for r in csv.DictReader(open(args.results / "detail.csv")) if (r["Dataset"], r["Formula"]) in keys]
	combined = [r for r in rows if r["Decomposed"] == "True"]
	undetected = [r for r in rows if r["Found"] != "True"]
	single = len(rows) - len(combined) - len(undetected)
	tasks = [(r["Formula"], args.timeout) for r in combined + undetected]
	print(f"rerunning {len(tasks)} formulas without decomposition ({len(combined)} found as combinations, "
		f"{len(undetected)} undetected) ...", flush=True)
	with ProcessPoolExecutor(args.procs) as pool:
		outcome = {formula: (found, size) for formula, found, size in pool.map(rerun, tasks)}

	again = [r for r in combined if outcome[r["Formula"]][0]]
	gained = [r for r in undetected if outcome[r["Formula"]][0]]
	print(f"of the {len(combined)} formulas found as combinations, {len(again)} are detected without decomposition", end="")
	if again:
		chain = sum(outcome[r["Formula"]][1] for r in again) / len(again)
		combo = sum(int(r["Node Count"]) for r in again) / len(again)
		print(f", as single chains of {chain:.2f} nodes on average (their combinations: {combo:.2f})")
	else:
		print()
	print(f"of the {len(undetected)} undetected formulas, {len(gained)} are detected without decomposition")
	total = single + len(again) + len(gained)
	print(f"detection without decomposition: {total} of {len(rows)} ({100 * total / len(rows):.1f}%)")


if __name__ == "__main__":
	main()
