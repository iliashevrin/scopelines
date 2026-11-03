# Scopelines

Artifact of the paper *Scopelines: A Visualizable Semantic LTL Representation*
(FormaliSE 2027).

A **scopeline** is a representation of an LTL property that sits between LTL
and first-order logic: like first-order logic, it states every quantifier
explicitly (*forall*, *exists*, and their strong/weak variants), and like
LTL, it needs no index variables. Nested *before* and *after* scopes form a
chain, which is rendered as stacked bands on a timeline. For example,
`a U b` is the scopeline `exists b strictly before always a`.

This artifact contains:

- the translation of scopelines into LTL (Algorithm 1) and the search for
  scopelines equivalent to an LTL formula (Algorithm 2, with the
  decomposition heuristic of Section V);
- the renderer of scopelines as SVG/PNG (Section VI);
- the five datasets and the scripts that reproduce every result of the
  evaluation (Section VII): Table I, the statistics in the text, Figure 7,
  the decomposition ablation, and the oracle-based validation;
- the scripts that render the example figures (Figures 1 and 3-6).

## Requirements

- Python >= 3.10 with [Spot](https://spot.lre.epita.fr) (tested with 2.15.1)
  and the packages in `requirements.txt` (cairosvg, matplotlib, scipy).
  Spot is not on PyPI; see the Docker image below, or install its Python
  bindings from your distribution's packages, conda
  (`conda install -c conda-forge spot`), or a source build, and then run
  `pip install -r requirements.txt`.
- Linux (or macOS); the time budgets rely on `fork`.
- Any x86-64 or ARM64 machine with 4 cores and 8 GB of RAM. The paper's
  numbers come from an Intel Core i5-10210U laptop (4 cores/8 threads at
  1.60 GHz, 16 GB of RAM).

## Running with Docker (recommended)

The Docker image contains Python 3.12, Spot 2.15.1 (built from source), the
Python packages, and this repository, so nothing else needs installing. A
ready-made image (`scopelines-docker.tar.gz`, about 350 MB) is attached to the
[latest release](https://github.com/iliashevrin/scopelines/releases/latest);
alternatively, build it from this repository:

```sh
curl -LO https://github.com/iliashevrin/scopelines/releases/latest/download/scopelines-docker.tar.gz
docker load -i scopelines-docker.tar.gz      # the ready-made image, or build it:
docker build -t scopelines .                 # (about 15-20 minutes, mostly compiling Spot)
mkdir -p results
docker run --rm -it -v "$PWD/results:/scopelines/results" scopelines
```

This opens a shell in `/scopelines`, where every command below runs as is;
the mounted `results/` keeps the outputs on the host. Commands run as the
owner of `results/` (see `docker-entrypoint.sh`), so its files belong to you
if you created it, as above. If an earlier run left files owned by root in
it, remove them first, e.g. with `sudo rm -r results/*`. A single command also
works, e.g. `docker run --rm scopelines python3 find_scopeline.py 'G(a -> F b)'`.
The image is built for linux/amd64; on an ARM64 host, build it locally with
the command above.

### Viewing the rendered scopelines

The container has no display, so open the rendered SVG/PNG files on the
host, where they appear in `results/` (the figures of step 7 in
`results/figures/`). From a terminal on the host (a second one, or after
leaving the container):

```sh
xdg-open results/example.svg      # Linux
open results/example.svg          # macOS
start results\example.svg         # Windows
```

Double-clicking the file in a file manager works too, and SVG files open in
any web browser. Without Docker, the same commands open the files directly.

## Quick check (about 1 minute)

```sh
python3 find_scopeline.py 'G(a -> F b)' --svg results/example.svg
python3 run_benchmark.py --limit 4 --timeout 10
python3 analyze_results.py
python3 render_figures.py
python3 verify_oracle.py random --count 200
python3 verify_oracle.py reported
```

`find_scopeline.py` prints `(forall (a) after (sometimes (b)))`, its LTL
translation `G(a -> Fb)`, and `equivalent: True`, and draws the scopeline
in `results/example.svg` (see [Viewing the rendered
scopelines](#viewing-the-rendered-scopelines)). The benchmark runs the first
4 formulas of each dataset (20 in all, 19 distinct) and prints a table like
Table I; the oracle reports no mismatch.

## Reproducing the paper

All outputs go to `results/`. Steps 2, 3, and 5 read the results of step 1; the others are independent. The runtimes are on the laptop above, about 1.5 hours in all.

| Step | Command | Options (defaults) | Time | Paper |
|---|---|---|---|---|
| 1. Search all formulas | `python3 run_benchmark.py` | `--timeout` seconds per formula (60); `--limit N`, only the first N formulas of each dataset (all); `--out` directory (`results/`) | ~50 min | Section VII |
| 2. Derive the results | `python3 analyze_results.py` | results directory (`results/`) | ~5 s | Table I, Section VII-B, Figure 7 |
| 3. Decomposition ablation | `python3 ablation_no_decomposition.py` | results directory (`results/`); `--timeout` seconds per formula (60); `--procs`, formulas in parallel (half the cores) | ~15 min | Section VII-B |
| 4. Oracle, random scopelines | `python3 verify_oracle.py random` | `--count` scopelines (10000); `--max-nodes` (5); `--seed` (1); `--procs` (all cores) | ~17 min (8 threads) | Section VII-A |
| 5. Oracle, reported scopelines | `python3 verify_oracle.py reported` | a `detail.csv` (`results/detail.csv`); `--lassos` per scopeline (1000); `--seed` (1); `--procs` (all cores) | ~15 s | Section VII-A |
| 6. Fault injection | `python3 oracle_mutations.py` | number of random scopelines (300); a filter on the fault names (none) | ~6 min | Section VII-A |
| 7. Example figures | `python3 render_figures.py` | output directory (`results/figures`) | ~10 s | Figures 1, 3-6 |

**Step 1** searches every formula of `datasets/` for a scopeline, with a
budget of 60 seconds each, renders each result as PNG (timed, then
discarded), and deduplicates the formulas semantically, within each dataset
and across datasets (208 and 186 formulas). It writes `results/detail.csv`
(one row per formula: the scopeline found, the search time, node count,
depth, and whether it is an AND/OR combination of the formula's
components), `results/summary.csv`, and `results/dedup.json`.

**Step 2** prints, from those files:

- the dataset statistics of Section VII-A (formula counts, 1 to 15 atomic
  propositions, 3.28 on average);
- the rows of Table I (also written to `results/table1.tex`);
- the statistics of Section VII-B: detection (156 of 186), node counts and
  depths, event sizes, AND/OR combinations, the largest and the slowest
  result, the share found in under one second, PNG rendering times, the
  use of X in events, the undetected formulas, and the mapping of Dwyer's
  patterns onto the survey of real-world instances;
- the Spearman correlations of the scalability analysis, and Figure 7
  (`results/figure7.png`).

**Step 3** reruns, without decomposition, every formula found as an AND/OR
combination and every undetected one (8 of the 47 combinations are then
found, as single chains).

**Steps 4-6** validate the translation and the search with the independent
semantic oracle (`scopelines/oracle.py`), which interprets the window
semantics of Section III directly on lasso words:

- step 4 compares it with spot's verdicts for LTL(S) on 10,000 random
  supported scopelines, each on all 1,216 lasso words over {a, b} with a
  prefix of at most 2 and a loop of at most 3 letters (12,160,000 checks),
  and also checks negation duality, the cases of the proof of Theorem 1,
  and empty windows;
- step 5 compares every scopeline found in step 1 with its original
  formula on 1,000 random lasso words plus an accepting word of the formula
  and of its negation, and checks it equivalent with spot;
- step 6 injects the nine faults listed in the paper into the translation
  and the supported conditions, one at a time, and shows that the oracle
  catches each of them.

All of them should report no mismatch (and, for step 6, a mismatch for
every fault).

### What may differ

- **Search times** depend on the machine and its load, so they differ from
  Table I, and so do the statistics computed from them (average and median
  times, the slowest formula, and the Spearman correlations with search
  time). Detection does not, except for a formula whose search time is close
  to the 60-second budget: the slowest one in the paper took 55.83 seconds
  (50.16 seconds in our rerun), so on a slower machine it may time out.
  `run_benchmark.py --timeout` changes the budget. For the same reason, the
  decomposition ablation (step 3) reports 8 or 9 of the 47 combinations,
  depending on the run.
- **The scopelines found** are the same up to equivalent alternatives: a
  rerun on our machine reproduces the paper's detection, node counts, and
  depths exactly, but for 11 of the 208 formulas it prints a different
  equivalent scopeline -- the same chains in another order within an
  AND/OR, or an equivalent event (e.g. `a & !b & Xa` instead of `a & Xa`).
  The search is deterministic for a given run, but spot orders the operands
  of a conjunction or disjunction by internal identifiers, which depend on
  the formulas the process has created before. Two per-dataset event sizes
  in Table I may therefore differ by 0.01.
- PNG rendering times likewise depend on the machine.

## Using scopelines beyond the paper

From the command line, for any LTL formula in spot's syntax,
`find_scopeline.py` prints the scopeline found, its translation into LTL,
whether spot confirms the two equivalent, and the search time:

| Parameter | Meaning (default) |
|---|---|
| `formula` | the LTL formula, in spot's syntax |
| `--timeout SECONDS` | the search's time budget (60) |
| `--svg FILE` | write the rendering as SVG |
| `--png FILE` | write the rendering as PNG |
| `--negate` | render the negation of the scopeline instead |
| `--no-decompose` | search without the decomposition heuristic |

```sh
python3 find_scopeline.py '(G a) -> (F b)' --png results/out.png --timeout 30
python3 find_scopeline.py 'G(req -> X X ack)' --svg results/out.svg
python3 find_scopeline.py 'G(a -> F b)' --png results/negation.png --negate
```

In Docker, write the renderings under `results/` to open them on the host
(see [Viewing the rendered scopelines](#viewing-the-rendered-scopelines)).

Atomic propositions that start with F, G, or X followed by more letters must
be double-quoted (e.g. `"FCT_sent"`), as spot would otherwise read them as
operators.

From Python:

```python
import spot
from scopelines import find_scopeline, result_ltl, Scopeline, Quantifier
from scopelines.render.png import save_png

result = find_scopeline("G(a -> F b)", timeout=60)       # a runner.Result
print(result.status, result)                             # found (forall (a) after (sometimes (b)))
print(result_ltl(result.scopelines, result.operator))    # G(a -> Fb)
save_png(result.scopelines, "results/out.png", operator=result.operator)

# building a scopeline by hand and translating it into LTL
s = Scopeline(spot.formula("b"), Quantifier.EXISTS)
s.before = Scopeline(spot.formula("a"), Quantifier.FORALL)
s.before.strictly = True
print(s, s.is_supported(), s.to_ltl())                   # ... True a U b
```

Other datasets can be evaluated by adding CSV files (one formula per line)
to `datasets/`, and the search can be run without the decomposition
heuristic with `decompose=False` (`--no-decompose` on the command line).

### Code overview

| Module | Content |
|---|---|
| `scopelines/scopeline.py` | The scopeline data structure, the *supported* conditions, negation, and the translation into LTL (Algorithm 1) |
| `scopelines/search.py` | The search (Algorithm 2): events, `Check`, `Refine`, and the decomposition heuristic |
| `scopelines/runner.py` | `find_scopeline`: the search under a time budget, in a child process |
| `scopelines/render/` | Rendering: rows per node (`layout.py`), SVG drawing (`svg.py`), and standalone SVG/PNG export (`png.py`) |
| `scopelines/oracle.py` | The independent semantic oracle on lasso words |
| `scopelines/parse.py` | Parsing printed scopelines back into objects |
| `scopelines/dedup.py` | Semantic deduplication of formulas, up to renaming of atomic propositions |
| `scopelines/utils.py` | LTL construction helpers and helpers for search results |
| `datasets/` | The five datasets of Section VII-A |

## License

MIT; see `LICENSE`.
