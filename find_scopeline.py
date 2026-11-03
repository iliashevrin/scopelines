"""Searches for a scopeline equivalent to an LTL formula, and optionally renders it.

    python3 find_scopeline.py 'G(a -> F b)'
    python3 find_scopeline.py 'G(a -> F b)' --png out.png
    python3 find_scopeline.py '(G a) -> (F b)' --svg out.svg --timeout 30

The formula is in spot's syntax (e.g. G, F, X, U, W, R, !, &, |, ->, <->;
also [] and <> for G and F). Quote it with single quotes in a shell, and
double-quote atomic propositions that start with F, G, or X followed by
other letters (e.g. "FCT_sent"), which spot would otherwise read as
operators. Prints the scopeline, its translation LTL(S), and whether spot
confirms the two equivalent.
"""

import argparse
import sys

import spot

from scopelines import find_scopeline, result_ltl
from scopelines.render.png import save_png, save_svg


def main():
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("formula", help="LTL formula in spot syntax")
	parser.add_argument("--timeout", type=float, default=60, help="search time budget in seconds (default: 60)")
	parser.add_argument("--no-decompose", action="store_true", help="disable the decomposition heuristic")
	parser.add_argument("--png", help="write the rendering to this PNG file")
	parser.add_argument("--svg", help="write the rendering to this SVG file")
	parser.add_argument("--negate", action="store_true", help="render the negation of the scopeline instead")
	args = parser.parse_args()

	result = find_scopeline(args.formula, timeout=args.timeout, decompose=not args.no_decompose)
	if not result.found:
		print("no scopeline found ({})".format("the search space is exhausted" if result.status == "exhausted"
			else "timeout after {}s".format(args.timeout)))
		sys.exit(1)

	ltl = result_ltl(result.scopelines, result.operator)
	print("scopeline:  ", result)
	print("LTL(S):     ", ltl)
	print("equivalent: ", spot.are_equivalent(ltl, spot.formula(args.formula)))
	print("search time: {:.2f}s{}".format(result.elapsed, ", decomposed" if result.decomposed else ""))
	for path, save in ((args.png, save_png), (args.svg, save_svg)):
		if path:
			save(result.scopelines, path, operator=result.operator, negate=args.negate)
			print("wrote", path)


if __name__ == "__main__":
	main()
