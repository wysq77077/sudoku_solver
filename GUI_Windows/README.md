# SudokuSolver (C#, WinForms)

A logic-based Sudoku solver and difficulty rater with a graphical Windows
Forms interface. It solves puzzles step by step using human-style solving
techniques (not brute-force backtracking), and lets you watch — and step
back and forth through — exactly how it got there.

## Background

This project started out as a small VBA macro for Excel that could solve
simple Sudoku puzzles with a handful of basic techniques (Naked Single,
Hidden Single, Locked Candidates...). It was rewritten in C# with a proper
WinForms GUI, and the set of supported techniques was expanded step by step
all the way up to advanced chain-based techniques such as AIC and
ALS-XY-Chain.

This C# app is the original, graphical version of the solver. A separate,
dependency-free Python command-line port also exists, built directly on top
of this engine's logic. The two are meant for different situations: this
WinForms app is for watching one puzzle get solved interactively, with
before/after highlighting and step replay; the Python CLI is for scripting
and batch-processing many puzzles at once, which this GUI isn't set up for.

## Requirements

- .NET 6 or later (WinForms), on Windows
- Visual Studio 2022 (Community edition is fine) — or just the `dotnet` CLI

## Setup

**Using Visual Studio:**

1. Install Visual Studio 2022 with the ".NET desktop development" workload.
2. Put `SudokuSolver.csproj`, `Program.cs`, `Form1.cs`, `SudokuCellControl.cs`,
   and `SudokuEngine.cs` in one folder.
3. Open `SudokuSolver.csproj` in Visual Studio and press F5.

**Using the CLI only:**

```
dotnet new winforms -n SudokuSolver
cd SudokuSolver
# delete the generated default Program.cs / Form1.cs etc. and replace them
# with the files from this repository
dotnet run
```

## Usage

Paste an 81-character puzzle string (digits `1`-`9` for givens, `0` for
blanks) into the Import box and click **Import**, or click cells directly on
the grid and type digits, then click **Initialize**. From there you can:

- Click any technique button (grouped from easiest to hardest, left to
  right) to apply just that technique once.
- Click **Auto-Solve + Rate Difficulty** to solve the whole puzzle in one
  go and see its difficulty rating.
- Use the step-replay bar under the grid (`|◀ First`, `◀ Back 1 step`,
  `Forward 1 step ▶`, `Latest ▶|`) to move through the solve one step at a
  time, or click any line in the processing log to jump straight to that
  point. The cell each step acted on is highlighted in yellow; cells that
  were part of the *reasoning* behind a multi-cell technique (XY-Chain,
  W-Wing, Fish, AIC, etc.) are highlighted in pale blue (AIC gets its own
  darker blue, since its chains tend to be long).
- Toggle **Show candidate digits** to switch the pencil-mark display on or
  off, and use **Export** to get the current board back out as an
  81-character string.

This is a hands-on, one-puzzle-at-a-time tool by design — there's no
headless or batch mode. If you want to solve many puzzles in a script or
measure solve rates across a large test set, use the Python CLI port
instead.

## Project structure

| File | Role |
|---|---|
| `Program.cs` | Application entry point |
| `Form1.cs` | The WinForms UI: grid, buttons, step-replay bar, processing log |
| `SudokuCellControl.cs` | A custom-drawn control for a single cell (big digit or a 3x3 grid of pencil-mark candidates, with highlighting) |
| `SudokuEngine.cs` | The solving engine itself — every technique, the difficulty rater, and step history. Has no dependency on the UI at all |

## Implemented techniques

The solver tries techniques from easiest to hardest, always applying the
easiest one that currently works before moving on to a harder one. This is
also how the puzzle's overall difficulty is decided: it's the difficulty
tier of the hardest technique that was needed anywhere in the solve.

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

The solver never guesses — it only places or eliminates a digit when one of
the techniques above proves it logically.

## How the board is represented

- **`Board`** is a `10x10` array of ints (`int[10,10]`), indexed `[x,y]`
  with `1`-based coordinates (`x` = column 1-9, `y` = row 1-9). `0` means
  "not yet placed".
- **`Notes`** is a `10x10x10` array (`CellState[10,10,10]`) indexed
  `[digit,x,y]`. For every candidate digit in every cell it stores a
  `CellState`, not just a plain "is this still possible" flag —
  `CellState` records *why* a candidate left play (one member per
  technique, e.g. `LockedCandidate`, `NakedSubset`, `XWing`, `XyChain`,
  `AlsXyChain`...), plus `Open` (still live) and `Placed` (this is the
  cell's actual value). That's what lets the log say exactly which
  technique removed a given candidate, and it's also how the final puzzle
  difficulty is computed.
- **`History`** is a `List<BoardSnapshot>` — a full copy of `Board` and
  `Notes` taken right after every single step, which is what powers the
  step-replay bar and the clickable log. `Log` is the parallel
  `List<LogEntry>` of human-readable step descriptions.
- Board geometry (which cells belong to which row/column/box, which cells
  are "peers" of a given cell, etc.) is computed once and cached, since
  it's the same for every puzzle and gets queried extremely often.

## License

This project is licensed under the GNU General Public License v3 (GPL v3).

## Acknowledgments

The original solving logic started life as a simple VBA tool and was later
extended significantly into this C# WinForms application. A Python
command-line port, built on this same engine, is also available in this
repository for scripted/batch use.
