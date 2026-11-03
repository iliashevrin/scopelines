"""Runs the scopeline search over the datasets (Section VII of the paper).

For every formula, it searches for a scopeline under a time budget, renders
the result as PNG (timed, then discarded), and records the outcome. Each
dataset is then deduplicated semantically, and so is their union.

    python3 run_benchmark.py                         # full run, 60 s per formula
    python3 run_benchmark.py --limit 5 --timeout 10  # quick smoke test

Writes, under --out (default results/):
    detail.csv    one row per formula, after deduplication within its dataset
    summary.csv   per-dataset and combined (deduplicated) statistics
    dedup.json    the (dataset, formula) pairs kept by the combined deduplication
"""

import argparse
import csv
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

from scopelines.dedup import dedup_semantically
from scopelines.render.png import save_png
from scopelines.runner import find_scopeline
from scopelines.utils import result_str, score

HERE = Path(__file__).resolve().parent
DATASETS = sorted((HERE / "datasets").glob("*.csv"))


def load_formulas(path):
	with open(path, encoding="utf-8") as f:
		return [line.strip() for line in f if line.strip()]


def run_formula(dataset, formula, timeout):
	result = find_scopeline(formula, timeout=timeout)
	record = {"dataset": dataset, "formula": formula, "found": result.found, "status": result.status,
		"time": result.elapsed, "size": None, "depth": None, "score": None, "scopeline": "",
		"png_time": None, "decomposed": result.decomposed}
	if result.found:
		record["size"] = sum(s.size() for s in result.scopelines)
		record["depth"] = max(s.depth() for s in result.scopelines)
		record["score"] = score(result.scopelines, result.operator)
		record["scopeline"] = result_str(result.scopelines, result.operator)
		fd, png = tempfile.mkstemp(suffix=".png")
		os.close(fd)
		try:
			start = time.monotonic()
			save_png(result.scopelines, png, operator=result.operator)
			record["png_time"] = time.monotonic() - start
		finally:
			os.unlink(png)
	return record


def aggregate(name, records):
	found = [r for r in records if r["found"]]
	def stats(key):
		values = [r[key] for r in found if r[key] is not None]
		return (statistics.mean(values), min(values), max(values)) if values else (None, None, None)
	return {"dataset": name, "n": len(records), "found": len(found),
		"time": stats("time"), "median_time": statistics.median(r["time"] for r in found) if found else None,
		"size": stats("size"), "depth": stats("depth"), "png_time": stats("png_time"),
		"decomposed": sum(r["decomposed"] for r in found)}


def fmt(value, digits=2):
	return "-" if value is None else f"{value:.{digits}f}"


def print_table(results):
	header = ["Dataset", "N", "Found", "Rate", "Avg time", "Median", "Min-max time",
		"Avg nodes", "Max nodes", "Avg depth", "Decomposed", "Avg PNG", "Max PNG"]
	rows = [[r["dataset"], str(r["n"]), str(r["found"]), f"{100 * r['found'] / r['n']:.1f}%" if r["n"] else "-",
		fmt(r["time"][0]), fmt(r["median_time"]), f"{fmt(r['time'][1])}-{fmt(r['time'][2])}",
		fmt(r["size"][0]), fmt(r["size"][2], 0), fmt(r["depth"][0]), str(r["decomposed"]),
		fmt(r["png_time"][0], 3), fmt(r["png_time"][2], 3)] for r in results]
	widths = [max(len(header[i]), *(len(row[i]) for row in rows)) for i in range(len(header))]
	for row in [header, ["-" * w for w in widths]] + rows:
		print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


def write_outputs(out, all_records, results, deduped):
	out.mkdir(parents=True, exist_ok=True)
	with open(out / "detail.csv", "w", newline="") as f:
		w = csv.writer(f)
		w.writerow(["Dataset", "Formula", "Found", "Status", "Search Time (s)", "Node Count", "Node Depth",
			"Score", "Scopeline", "PNG Time (s)", "Decomposed"])
		for r in all_records:
			w.writerow([r["dataset"], r["formula"], r["found"], r["status"], r["time"], r["size"], r["depth"],
				r["score"], r["scopeline"], r["png_time"], r["decomposed"]])
	with open(out / "summary.csv", "w", newline="") as f:
		w = csv.writer(f)
		w.writerow(["Dataset", "N", "Found", "Avg Time (s)", "Median Time (s)", "Min Time (s)", "Max Time (s)",
			"Avg Node Count", "Min Node Count", "Max Node Count", "Avg Node Depth", "Min Node Depth",
			"Max Node Depth", "Decomposed", "Avg PNG Time (s)", "Max PNG Time (s)"])
		for r in results:
			w.writerow([r["dataset"], r["n"], r["found"], r["time"][0], r["median_time"], r["time"][1], r["time"][2],
				*r["size"], *r["depth"], r["decomposed"], r["png_time"][0], r["png_time"][2]])
	with open(out / "dedup.json", "w") as f:
		json.dump([[r["dataset"], r["formula"]] for r in deduped], f, indent=1)


def main():
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("--timeout", type=float, default=60, help="search time budget per formula, in seconds (default: 60)")
	parser.add_argument("--limit", type=int, help="only the first N formulas of each dataset, for a quick check")
	parser.add_argument("--out", type=Path, default=HERE / "results", help="output directory (default: results/)")
	args = parser.parse_args()

	all_records, results = [], []
	for path in DATASETS:
		formulas = load_formulas(path)[:args.limit]
		print(f"{path.stem}: {len(formulas)} formulas", file=sys.stderr)
		records = []
		for i, formula in enumerate(formulas, 1):
			record = run_formula(path.stem, formula, args.timeout)
			records.append(record)
			print(f"  [{i}/{len(formulas)}] {record['status']:9} {fmt(record['time']):>6}s  {formula}", file=sys.stderr, flush=True)
		before = len(records)
		records = dedup_semantically(records)
		if len(records) != before:
			print(f"  {before} -> {len(records)} after deduplication within the dataset", file=sys.stderr)
		all_records.extend(records)
		results.append(aggregate(path.stem, records))

	print(f"Deduplicating {len(all_records)} formulas across datasets ...", file=sys.stderr)
	deduped = dedup_semantically(all_records)
	print(f"  {len(all_records)} -> {len(deduped)} distinct formulas", file=sys.stderr)
	results.append(aggregate("combined (dedup)", deduped))

	print()
	print_table(results)
	write_outputs(args.out, all_records, results, deduped)
	print(f"\nWrote {args.out}/detail.csv, summary.csv, and dedup.json")


if __name__ == "__main__":
	main()
