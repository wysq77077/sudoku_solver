# SudokuSolver (Python)

A pure-Python, logic-based Sudoku solver and difficulty rater. Given a puzzle, it
solves it step by step using human-style solving techniques (not brute-force
backtracking), prints a full log of every step it took, and reports the
difficulty of the puzzle.

## Background

This project started out as a small VBA macro for Excel that could solve
simple Sudoku puzzles using a handful of basic techniques (Naked Single,
Hidden Single, Locked Candidates...). Over time it grew far beyond that
original scope: it was ported to C# with a proper Windows GUI, and the set of
supported solving techniques was expanded step by step, all the way up to
advanced chain-based techniques such as AIC and ALS-XY-Chain.

This repository is a full reimplementation of that solver in Python. It is a
faithful, line-by-line port of the solving logic from the C# version (no
technique's behavior was changed in translation), packaged as a small,
dependency-free command-line tool. On top of the port, the internal data
structures were reworked for speed — see [Performance](#performance) below.

The GUI/history-replay features of the original C# version are intentionally
not included here: this is a CLI-only tool meant to be scripted and run in
batch.

## Requirements

- Python 3.14 or later
- No external packages required — everything is done with the standard
  library only (no NumPy, no pandas, etc.)

## Usage

```
python3 SudokuSolver.py [options] [puzzle]
```

`puzzle` is an 81-character string describing the board, row by row, using
digits `1`-`9` for givens and either `0` or `.` for empty cells. Example:

```
471023960053070120820416753267189400930605271140230806014762509096851342580094017
```

If `puzzle` is omitted, the tool reads from standard input instead, one
puzzle per line, and solves as many puzzles as there are lines (this makes it
easy to batch-process a whole file of puzzles, e.g. `python3 SudokuSolver.py < puzzles.txt`).
Blank lines in the input are skipped. If a line isn't a valid 81-character
puzzle string, processing stops right there.

### Options

| Option | Description |
|---|---|
| `-h`, `-H`, `--help` | Show the help message and exit |
| `-s`, `-S` | Don't print the step-by-step log — only print the answer, whether it was solved, and its difficulty |
| `-a`, `-A` | Also print the solved board as a 9x9 text grid, before the log |

### Example

```
$ python3 SudokuSolver.py -a 471023960053070120820416753267189400930605271140230806014762509096851342580094017
[Answer] 471523968653978124829416753267189435938645271145237896314762589796851342582394617
[Solved] True
[Difficulty] Trivial

   A B C D E F G H I
  +-----+-----+-----+
1 |4 7 1|5 2 3|9 6 8|
2 |6 5 3|9 7 8|1 2 4|
3 |8 2 9|4 1 6|7 5 3|
  +-----+-----+-----+
4 |2 6 7|1 8 9|4 3 5|
5 |9 3 8|6 4 5|2 7 1|
6 |1 4 5|2 3 7|8 9 6|
  +-----+-----+-----+
7 |3 1 4|7 6 2|5 8 9|
8 |7 9 6|8 5 1|3 4 2|
9 |5 8 2|3 9 4|6 1 7|
  +-----+-----+-----+

[  1] (Trivial ) A2 <6> Naked Single
[  2] (Trivial ) A7 <3> Naked Single
[  3] (Trivial ) A8 <7> Naked Single
...
[ 21] (Trivial ) Solved!
```

Every log line records the step number, the difficulty tier of the technique
used, and what happened — which digit was placed or eliminated, in which
cell(s), and why. If the solver ever reaches a state that is logically
impossible (a contradiction in the givens), it stops and reports that
instead of a normal answer.

## Implemented techniques

The solver tries techniques from easiest to hardest, always applying the
easiest one that currently works before moving on to a harder one. This is
also how the puzzle's overall difficulty is decided: it's the difficulty tier
of the hardest technique that was needed anywhere in the solve.

| Difficulty | Techniques |
|---|---|
| Trivial | Naked Single |
| Simple | Hidden Single |
| Easy | Locked Candidates (Pointing / Claiming) |
| Moderate | Naked Subsets (Pair / Triple / Quad — doubles as Hidden Subsets) |
| Clever | X-Wing, Skyscraper, 2-String Kite, Empty Rectangle |
| Tricky | Simple Coloring, Remote Pair, W-Wing |
| Hard | Swordfish, Sashimi/Finned X-Wing, XY-Wing |
| Expert | Jellyfish, Sashimi/Finned Swordfish, XYZ-Wing, XY-Chain |
| Genius | ALS-XZ, Grouped X-Chain / Grouped X-Cycle, ALS-XY-Wing |
| Insane | AIC (Alternating Inference Chain), ALS-XY-Chain |

This solver never guesses. It only places or eliminates a digit when one of
the techniques above proves it logically. If a puzzle needs a technique that
isn't in this list (or needs trial-and-error/bifurcation), the solver simply
stops without a full solution — see [Performance](#performance) for how
often that happens in practice.

## How the board is represented

A few notes for anyone reading or extending the code:

- **`self.board`** is a `10x10` list of ints (`List[List[int]]`), indexed
  `[x][y]` with `1`-based coordinates (`x` = column 1-9, `y` = row 1-9; index
  `0` in each dimension is simply unused, which keeps the 1-based coordinate
  math simple everywhere else). `0` means "not yet placed".
- **`self.notes`** is a `10x10x10` structure (`List[List[List[CellState]]]`)
  indexed `[digit][x][y]`. For every candidate digit in every cell it stores
  a `CellState` value, not just a plain "is this digit still possible"
  boolean. `CellState` distinguishes *why* a candidate left play — e.g.
  `LOCKED_CANDIDATE`, `NAKED_SUBSET`, `X_WING`, `XY_CHAIN`, `ALS_XY_CHAIN`,
  and so on, one member per technique — plus `OPEN` (still a live candidate)
  and `PLACED` (this is the actual value of the cell). This is what lets the
  log say exactly which technique removed a given candidate, and it's also
  how the final puzzle difficulty is computed (by looking at the hardest
  `CellState` that was ever assigned).
- **`self._mask_cache`** is a `10x10` array of 9-bit integers, one per cell,
  where bit `d` being set means digit `d` is still an open candidate in that
  cell. This is a cache derived from `self.notes` — it exists purely for
  speed (see below), and is kept in sync incrementally every time a
  candidate is placed or eliminated, rather than being recomputed from
  `self.notes` on every read.
- Almost Locked Sets (used by ALS-XZ, ALS-XY-Wing, and ALS-XY-Chain) are
  represented by an `AlsCandidate` dataclass that also caches its cell set as
  a `frozenset` and pre-sorts its cells by digit — again purely as a speed
  optimization, described below.
- Every solving step is recorded as a `LogEntry` (step number, message,
  technique name, difficulty tier), and the overall result is a
  `SolveResult` (solved flag, difficulty, per-technique usage counts, and
  contradiction info if any).

## Performance

An early version of this solver tried to speed things up by putting the
board and candidate notes into NumPy arrays. That turned out to be a dead
end: a 9x9 board is far too small for NumPy's bulk-array operations to pay
off, and each technique here works cell-by-cell and combination-by-combination
rather than as a bulk array operation — so NumPy's per-element access
overhead made things *slower*, not faster, especially on easy/medium
puzzles.

Profiling (with `cProfile`) pointed to a much more mundane bottleneck
instead: the ALS-XY-Chain search, and specifically the function that checks
whether two Almost Locked Sets share a cell, which gets called millions of
times per search and was rebuilding a Python `set` from scratch on every
single call. Fixing that — by caching each ALS's cells as a `frozenset` up
front and reusing it for O(1) intersection tests, plus a few similar caches
(candidate bitmasks, digit→cell lookups, etc.) — is what actually made the
solver faster, with no change to the solving logic itself. Depending on
puzzle difficulty this gave roughly a 1.5-3.8x speedup over the
straightforward first implementation, with the largest gains on the hardest
puzzles (where ALS-XY-Chain gets used the most).

### Benchmark: sudoku-exchange-puzzle-bank

To see how the solver performs on a large, independently-produced test set,
it was run against every puzzle in `diabolical.txt` from
[grantm/sudoku-exchange-puzzle-bank](https://github.com/grantm/sudoku-exchange-puzzle-bank),
which contains **119,681** puzzles rated by the "Sudoku Explainer" (SE)
scale, from SE 5.0 (moderately hard) up to SE 9.3 (about as hard as a Sudoku
puzzle gets without resorting to trial-and-error).

- **Environment:** AMD Ryzen 7 7735HS / 32 GB RAM, Python 3.14.6
- **Mode:** batch mode (all puzzles piped in via stdin, one process)
- **Total time:** ~8 hours 30 minutes for all 119,681 puzzles
- **Result:** 106,319 / 119,681 solved (**88.8%**)

The solver's logic-only approach (no guessing/backtracking) means it isn't
expected to solve every puzzle: some of the hardest SE-rated puzzles require
techniques that either aren't implemented here or genuinely require
trial-and-error, which this solver deliberately does not do. The solve rate
by SE rating shows this drop-off clearly — it stays effectively at 100%
through the "hard" range, then declines as puzzles move into the range where
the SE rating itself starts to assume forcing chains / bifurcation:

| SE Rating | Puzzles | Solved | Solve Rate |
|---:|---:|---:|---:|
| 5.0 | 536 | 536 | 100.0% |
| 5.2 | 391 | 391 | 100.0% |
| 5.4 | 6,000 | 5,998 | 100.0% |
| 5.5 | 6,000 | 5,998 | 100.0% |
| 5.6 | 6,000 | 5,998 | 100.0% |
| 5.7 | 6,000 | 5,997 | 100.0% |
| 5.8 | 65 | 65 | 100.0% |
| 5.9 | 37 | 37 | 100.0% |
| 6.0 | 11 | 11 | 100.0% |
| 6.1 | 2 | 2 | 100.0% |
| 6.2 | 661 | 660 | 99.8% |
| 6.3 | 6,000 | 5,999 | 100.0% |
| 6.4 | 6,000 | 5,998 | 100.0% |
| 6.6 | 5,346 | 5,346 | 100.0% |
| 6.7 | 6,000 | 6,000 | 100.0% |
| 6.8 | 6,000 | 6,000 | 100.0% |
| 6.9 | 6,000 | 5,997 | 100.0% |
| 7.0 | 4,822 | 4,819 | 99.9% |
| 7.1 | 9,404 | 9,393 | 99.9% |
| 7.2 | 8,945 | 8,917 | 99.7% |
| 7.3 | 6,000 | 5,856 | 97.6% |
| 7.4 | 1,700 | 1,597 | 93.9% |
| 7.5 | 575 | 506 | 88.0% |
| 7.7 | 874 | 710 | 81.2% |
| 7.8 | 2,497 | 1,782 | 71.4% |
| 7.9 | 732 | 499 | 68.2% |
| 8.0 | 236 | 144 | 61.0% |
| 8.1 | 10 | 5 | 50.0% |
| 8.2 | 2,030 | 1,870 | 92.1% |
| 8.3 | 6,000 | 4,666 | 77.8% |
| 8.4 | 6,000 | 2,881 | 48.0% |
| 8.5 | 3,701 | 995 | 26.9% |
| 8.6 | 308 | 37 | 12.0% |
| 8.7 | 49 | 16 | 32.7% |
| 8.8 | 768 | 243 | 31.6% |
| 8.9 | 2,190 | 309 | 14.1% |
| 9.0 | 1,620 | 41 | 2.5% |
| 9.1 | 150 | 0 | 0.0% |
| 9.2 | 20 | 0 | 0.0% |
| 9.3 | 1 | 0 | 0.0% |
| **Total** | **119,681** | **106,319** | **88.8%** |

The full raw results are included in this repository as
[`results.csv`](./results.csv).

Note that the solver's own `Difficulty` tiers (Trivial through Insane) and
the SE rating scale used by this puzzle bank are two different rating
systems built on different technique sets and scoring rules — they're not
directly comparable number-for-number, so the table above is best read as
"solve rate vs. SE rating", not as a comparison between the two scales.

## License

This project is licensed under the GNU General Public License v3 (GPL v3).

## Acknowledgments

- The original solving logic started life as a simple VBA tool and was later
  extended significantly in a C# port; this repository is a Python
  reimplementation of that C# logic.
- Test puzzles used for the benchmark above come from
  [grantm/sudoku-exchange-puzzle-bank](https://github.com/grantm/sudoku-exchange-puzzle-bank).
