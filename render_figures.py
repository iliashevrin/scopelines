"""Renders the example scopelines of the paper (Figures 1 and 3-6) as PNG.

    python3 render_figures.py [out_dir]        (default: results/figures)

Figures 3-6 are the scopelines the search returns for the formulas in their
captions. Figure 1 shows a hand-written scopeline for a U b, the one the
introduction discusses; the search returns an equivalent inclusive form,
printed alongside.
"""

import sys
from pathlib import Path

import spot

from scopelines import Scopeline, Quantifier, find_scopeline, result_ltl
from scopelines.render.png import save_png

FIGURES = [
	("figure3_future", "G F a"),
	("figure4_nested", "G((a & F b) -> (!b U c))"),
	("figure5_next_ticks", "!G(a -> (X b | X X b | X X X b))"),
	("figure6_multiroot", "(F(s & X F t)) -> (!s U p)"),
]


def main():
	out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "results" / "figures"
	out.mkdir(parents=True, exist_ok=True)

	until = Scopeline(spot.formula("b"), Quantifier.EXISTS)
	until.before = Scopeline(spot.formula("a"), Quantifier.FORALL)
	until.before.strictly = True
	assert spot.are_equivalent(until.to_ltl(), spot.formula("a U b"))
	save_png([until], out / "figure1_until.png", scale=3)
	print(f"figure1_until: a U b  =>  {until}  (the search returns: {find_scopeline('a U b')})")

	for name, formula in FIGURES:
		result = find_scopeline(formula)
		assert result.found and spot.are_equivalent(result_ltl(result.scopelines, result.operator), spot.formula(formula))
		save_png(result.scopelines, out / f"{name}.png", operator=result.operator, scale=3)
		print(f"{name}: {formula}  =>  {result}")
	print(f"\nWrote the figures to {out}")


if __name__ == "__main__":
	main()
