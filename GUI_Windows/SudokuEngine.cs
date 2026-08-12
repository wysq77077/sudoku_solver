using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;

namespace SudokuSolver
{
    /// <summary>
    /// The candidate state for each (value, x, y). Corresponds to VBA's N(vl,x,y).
    /// Turned into an enum instead of using magic numbers.
    /// </summary>
    public enum CellState
    {
        Open = 0,              // Still alive as a candidate
        Placed = 1,            // This value has been placed in this cell
        Eliminated = 2,        // Eliminated by a row/col/box conflict (corresponds to Delete_Candidate)

        // From here on, values are numbered consecutively in Difficulty order (no unused numbers).
        // Naked Single (Trivial) and Hidden Single (Simple) use Placed, passing the tier
        // directly as an argument to Place(), so they have no dedicated CellState.

        LockedCandidate = 3,     // Easy: eliminated by Locked Candidates (Pointing/Claiming)

        NakedSubset = 4,         // Moderate: eliminated by Naked/Hidden Pair through Quad

        XWing = 5,               // Clever: eliminated by Fish (size 2)
        Skyscraper = 6,          // Clever: eliminated by Skyscraper
        TwoStringKite = 7,       // Clever: eliminated by 2 String Kite
        EmptyRectangle = 8,      // Clever: eliminated by Empty Rectangle

        Coloring = 9,            // Tricky: eliminated/placed by Simple Coloring (formerly X-Chain)
        RemotePair = 10,         // Tricky: eliminated by Remote Pair
        WWing = 11,              // Tricky: eliminated by W-Wing

        Swordfish = 12,          // Hard: eliminated by Fish (size 3)
        SashimiFinnedXWing = 13, // Hard: eliminated by Sashimi/Finned X-Wing
        XyWing = 14,             // Hard: eliminated by XY-Wing

        Jerryfish = 15,          // Expert: eliminated by Fish (size 4)
        SashimiFinnedSwordfish = 16, // Expert: eliminated by Sashimi/Finned Swordfish
        XyzWing = 17,            // Expert: eliminated by XYZ-Wing
        XyChain = 18,            // Expert: eliminated by XY-Chain

        AlsXz = 19,              // Genius: eliminated by the ALS-XZ technique
        GroupedXChain = 20,      // Genius: eliminated by Grouped X-Chain/Grouped X-Cycle
        AlsXyWing = 21,          // Genius: eliminated by the ALS-XY-Wing technique

        Aic = 22,                // Insane: eliminated/placed by AIC (Alternating Inference Chain)
        AlsXyChain = 23,         // Insane: eliminated by ALS-XY-Chain (a search that chains ALSes together via RCC)
    }

    /// <summary>Represents the three kinds of groups on the board: row, column, and box.
    /// In VBA, the same logic was copy-pasted three times, once each for rows, columns, and boxes,
    /// but this enum and CellsOf() let a single piece of logic be reused for all three.</summary>
    public enum Unit { Row, Col, Box }

    /// <summary>Difficulty rank of a technique. Larger numbers are harder. Comparable via the enum's underlying value.</summary>
    public enum Difficulty
    {
        Trivial,  // 1: Naked Single
        Simple,   // 2: Hidden Single
        Easy,     // 3: Locked Candidates
        Moderate, // 4: Naked Subset
        Clever,   // 5: X-Wing, Skyscraper, 2 String Kite, Empty Rectangle
        Tricky,   // 6: Simple Coloring, Remote Pair, W-Wing
        Hard,     // 7: Swordfish, Sashimi/Finned X-Wing, XY-Wing
        Expert,   // 8: Jerryfish, XYZ-Wing, XY-Chain
        Genius,   // 9: ALS-XZ, ALS-XY-Wing
        Insane,   // 10: AIC, ALS-XY-Chain
    }

    public class LogEntry
    {
        public int Step { get; }
        public string Message { get; }
        public string Technique { get; }
        public Difficulty Tier { get; }

        /// <summary>The board coordinates (1-9) this step acted on.
        /// A line not tied to a specific cell (e.g. "Solved!") uses X=0, Y=0 to mean "no target".
        /// The UI uses this to highlight the relevant cell when a log line is clicked.</summary>
        public int X { get; }
        public int Y { get; }

        /// <summary>
        /// The group of cells (other than X,Y) highlighted as the "reasoning" behind this elimination/placement.
        /// Only set for techniques -- such as XY-Chain/W-Wing/XY-Wing/Fish/Remote Pairs -- that derive
        /// a single elimination from a relationship between multiple cells; empty for every other technique.
        /// The UI uses this to highlight the reasoning cells in pale blue, separate from the target cell (yellow).
        /// </summary>
        public IReadOnlyList<(int x, int y)> CauseCells { get; }

        public LogEntry(int step, string message, string technique, Difficulty tier, int x, int y,
            IReadOnlyList<(int x, int y)> causeCells = null)
        {
            Step = step;
            Message = message;
            Technique = technique;
            Tier = tier;
            X = x;
            Y = y;
            CauseCells = causeCells ?? Array.Empty<(int, int)>();
        }

        public override string ToString() => $"[{Step,3}] ({Tier,-8}) {Message}";
    }

    /// <summary>The result of one auto-solve run. Holds the difficulty rating and a breakdown of techniques used.</summary>
    public class SolveResult
    {
        public bool Solved { get; init; }
        public Difficulty Difficulty { get; init; }
        public Dictionary<string, int> TechniqueUsage { get; init; } = new();

        /// <summary>Whether a contradiction was detected (either the givens themselves contain a duplicate, or a cell ran out of candidates while solving).</summary>
        public bool HasContradiction { get; init; }

        /// <summary>A message describing the contradiction (used by the UI to show an alert). Null if there is no contradiction.</summary>
        public string ContradictionMessage { get; init; }
    }

    /// <summary>
    /// A full snapshot of the board and candidate state, taken right after one step (= one Log line) completes.
    /// Used to later replay "how the board changed step by step" forward or backward.
    /// History[0] is the "initial setup (right after the puzzle is loaded, before anything is solved)" and has no corresponding Log line.
    /// History[i] (i>=1) corresponds to Log[i-1] (i.e. the state right after some Place/Eliminate ran
    /// and one line was added to Log).
    /// X,Y is the cell that step acted on (0,0 if none), used by the UI for highlighting.
    /// </summary>
    public class BoardSnapshot
    {
        public int Step { get; }
        public string Message { get; }
        public int X { get; }
        public int Y { get; }
        public int[,] Board { get; }
        public CellState[,,] Notes { get; }

        /// <summary>The technique name of the corresponding LogEntry (same as LogEntry.Technique).
        /// The UI uses this to highlight AIC's reasoning cells in a different color from other techniques.</summary>
        public string Technique { get; }

        /// <summary>The corresponding LogEntry's reasoning cells (for the pale-blue highlight). See LogEntry.CauseCells for details.</summary>
        public IReadOnlyList<(int x, int y)> CauseCells { get; }

        public BoardSnapshot(int step, string message, string technique, int x, int y, int[,] board, CellState[,,] notes,
            IReadOnlyList<(int x, int y)> causeCells = null)
        {
            Step = step;
            Message = message;
            Technique = technique;
            X = x;
            Y = y;
            Board = board;
            Notes = notes;
            CauseCells = causeCells ?? Array.Empty<(int, int)>();
        }
    }

    /// <summary>
    /// The core logic that corresponds to VBA's Q(10,10) / N(10,10,10) / Delete_Candidate, etc.
    /// Does not depend on any UI (WinForms or console) at all.
    /// Coordinates follow VBA's convention: x=column (1-9), y=row (1-9), 1-based.
    /// </summary>
    public class SudokuEngine
    {
        public int[,] Board { get; } = new int[10, 10];
        public CellState[,,] Notes { get; } = new CellState[10, 10, 10];
        public List<LogEntry> Log { get; } = new List<LogEntry>();

        /// <summary>The history of board/candidate snapshots taken right after each step completes.
        /// The UI uses this to show "how the board changed step by step" forward or backward.
        /// Cleared every time Initialize() runs; after that, one entry is pushed every time
        /// Place/Eliminate is called and the log grows by one line (1-to-1 with Log, plus one extra for the initial setup at the front).</summary>
        public List<BoardSnapshot> History { get; } = new List<BoardSnapshot>();

        /// <summary>The start position, within Log, of the range that has not yet had a snapshot made in History.</summary>
        private int _snapshotCursor;

        /// <summary>
        /// Whenever the UI (Form1.cs) wants to clear Log after flushing everything up to this point into the log display, it must call this method rather than calling <c>Log.Clear()</c> directly.
        /// This always clears Log and resets <c>_snapshotCursor</c> together, mirroring the
        /// "Log.Clear() + _snapshotCursor=0" pairing that Initialize() performs internally, so
        /// it can also be called safely from the UI.
        /// </summary>
        public void AcknowledgeFlushedLog()
        {
            Log.Clear();
            _snapshotCursor = 0;
        }

        public bool IsSolved
        {
            get
            {
                for (int x = 1; x <= 9; x++)
                    for (int y = 1; y <= 9; y++)
                        if (Board[x, y] == 0) return false;
                return true;
            }
        }

        // ============================================================
        // Initialization and placement handling (VBA's CommandButton1 / Delete_Candidate)
        // ============================================================

        /// <summary>Whether a contradiction has been detected (either the givens themselves contain a duplicate, or a cell ran out of candidates while solving).
        /// Once true, this is not reset until Initialize() is run again for this puzzle
        /// (so the content of the first anomaly found is preserved).</summary>
        public bool HasContradiction { get; private set; }

        /// <summary>A message describing the contradiction (used by the UI to show an alert).</summary>
        public string ContradictionMessage { get; private set; }

        private void RecordContradiction(string message)
        {
            if (HasContradiction) return; // Only record the first one found
            HasContradiction = true;
            ContradictionMessage = message;
            // To avoid throwing off the max-difficulty computation (SolveResult.Difficulty),
            // this is deliberately tagged with the lowest tier, Trivial (a contradiction itself has nothing to do with difficulty).
            AddLog($"[Contradiction detected] {message}", "Contradiction", Difficulty.Trivial, 0, 0);
        }

        /// <summary>Verifies that the given clues don't contain a duplicate within the same row, column, or box.
        /// Called at the start of Initialize(), before anything has been placed yet.</summary>
        private void ValidateGivens(int[,] givens)
        {
            foreach (Unit unit in new[] { Unit.Row, Unit.Col, Unit.Box })
            {
                for (int idx = 1; idx <= 9; idx++)
                {
                    var seen = new Dictionary<int, (int x, int y)>();
                    foreach (var (x, y) in CellsOf(unit, idx))
                    {
                        int v = givens[x, y];
                        if (v == 0) continue;
                        if (seen.TryGetValue(v, out var other))
                        {
                            RecordContradiction(
                                $"Digit {v} is duplicated in {UnitName(unit)} (cells: {ColLetter(other.x)}{other.y} and {ColLetter(x)}{y})");
                            return; // Finding the first one is enough
                        }
                        seen[v] = (x, y);
                    }
                }
            }
        }

        /// <summary>Verifies that no unplaced cell has zero candidates left.
        /// Called every time at the end of DeleteCandidate() (right after candidates actually decreased).</summary>
        private void CheckContradiction()
        {
            if (HasContradiction) return;
            for (int x = 1; x <= 9; x++)
            {
                for (int y = 1; y <= 9; y++)
                {
                    if (Board[x, y] != 0) continue;
                    if (CandidateMask(x, y) == 0)
                    {
                        RecordContradiction($"{ColLetter(x)}{y} has no digit left that can be placed (the board is contradictory)");
                        return;
                    }
                }
            }
        }

        public void Initialize(int[,] givens)
        {
            AcknowledgeFlushedLog(); // Clears Log and resets _snapshotCursor together
            History.Clear();
            _stepCounter = 0;
            HasContradiction = false;
            ContradictionMessage = null;
            Array.Clear(Board, 0, Board.Length);
            Array.Clear(Notes, 0, Notes.Length);

            // Verify, before placing anything, that the givens themselves have no contradiction (a duplicate within the same row/column/box).
            ValidateGivens(givens);

            for (int x = 1; x <= 9; x++)
            {
                for (int y = 1; y <= 9; y++)
                {
                    int v = givens[x, y];
                    if (v != 0)
                    {
                        Board[x, y] = v;
                        Notes[v, x, y] = CellState.Placed;
                    }
                }
            }
            DeleteCandidate();

            // Push the "initial setup (nothing solved yet)" onto the front of History, for step replay.
            // Since this isn't an operation on a specific cell, X=0, Y=0 (nothing to highlight).
            History.Add(new BoardSnapshot(0, "Initial setup (right after the puzzle was loaded)", "Initialize", 0, 0, CloneBoard(), CloneNotes()));
            // In case the puzzle happened to already be fully filled in by the givens alone
            // (without using NakedSingle etc.), DeleteCandidate() may have already pushed "Solved!" to the log, so pick that up here.
            FlushSnapshots();
        }

        /// <summary>Marks other candidates in the same row/column/box as a placed cell as Eliminated.</summary>
        public void DeleteCandidate()
        {
            int placedCount = 0;
            for (int x = 1; x <= 9; x++)
            {
                for (int y = 1; y <= 9; y++)
                {
                    int v = Board[x, y];
                    if (v == 0) continue;
                    placedCount++;

                    foreach (var (px, py) in Peers(x, y))
                        if (Notes[v, px, py] == CellState.Open)
                            Notes[v, px, py] = CellState.Eliminated;

                    for (int t = 1; t <= 9; t++)
                        if (Notes[t, x, y] == CellState.Open) Notes[t, x, y] = CellState.Eliminated;

                    Notes[v, x, y] = CellState.Placed;
                }
            }
            // "Solved!" for the all-cells-placed case doesn't target a specific cell, so X=0, Y=0.
            if (placedCount == 81) AddLog("Solved!", "Result", Difficulty.Trivial, 0, 0);

            // After clearing candidates because of a placed cell, check here every time whether an
            // unplaced cell was left with zero candidates (i.e. a contradiction appeared somewhere on the board).
            CheckContradiction();
        }

        private int _stepCounter;

        private void AddLog(string message, string technique, Difficulty tier, int x, int y,
            IReadOnlyList<(int x, int y)> causeCells = null)
        {
            _stepCounter++;
            Log.Add(new LogEntry(_stepCounter, message, technique, tier, x, y, causeCells));
        }

        /// <summary>
        /// If Log has entries that don't have a snapshot associated with them yet,
        /// copies the current Board/Notes and pushes it onto History (one snapshot per log line).
        /// Assumes the board is already in "the contradiction-free state after that line's content
        /// has been applied" at the time this method is called (Place() calls it after DeleteCandidate(); Eliminate() calls it immediately).
        /// </summary>
        private void FlushSnapshots()
        {
            while (_snapshotCursor < Log.Count)
            {
                var entry = Log[_snapshotCursor];
                History.Add(new BoardSnapshot(entry.Step, entry.Message, entry.Technique, entry.X, entry.Y, CloneBoard(), CloneNotes(), entry.CauseCells));
                _snapshotCursor++;
            }
        }

        private int[,] CloneBoard()
        {
            var copy = new int[10, 10];
            Array.Copy(Board, copy, Board.Length);
            return copy;
        }

        private CellState[,,] CloneNotes()
        {
            var copy = new CellState[10, 10, 10];
            Array.Copy(Notes, copy, Notes.Length);
            return copy;
        }

        /// <summary>A lookup table for which difficulty each elimination reason (CellState) corresponds to.
        /// Eliminate() uses this so that callers don't have to specify a difficulty every time --
        /// the correct difficulty tag can still be attached to the log.</summary>
        private static readonly Dictionary<CellState, Difficulty> StateTier = new()
        {
            [CellState.LockedCandidate] = Difficulty.Easy,
            [CellState.NakedSubset] = Difficulty.Moderate,
            [CellState.XWing] = Difficulty.Clever,
            [CellState.Skyscraper] = Difficulty.Clever,
            [CellState.TwoStringKite] = Difficulty.Clever,
            [CellState.EmptyRectangle] = Difficulty.Clever,
            [CellState.Coloring] = Difficulty.Tricky,
            [CellState.RemotePair] = Difficulty.Tricky,
            [CellState.WWing] = Difficulty.Tricky,
            [CellState.Swordfish] = Difficulty.Hard,
            [CellState.SashimiFinnedXWing] = Difficulty.Hard,
            [CellState.XyWing] = Difficulty.Hard,
            [CellState.Jerryfish] = Difficulty.Expert,
            [CellState.SashimiFinnedSwordfish] = Difficulty.Expert,
            [CellState.XyzWing] = Difficulty.Expert,
            [CellState.XyChain] = Difficulty.Expert,
            [CellState.AlsXz] = Difficulty.Genius,
            [CellState.GroupedXChain] = Difficulty.Genius,
            [CellState.AlsXyWing] = Difficulty.Genius,
            [CellState.Aic] = Difficulty.Insane,
            [CellState.AlsXyChain] = Difficulty.Insane,
        };

        private void Place(int x, int y, int v, string technique, Difficulty tier, string detail = null)
        {
            Board[x, y] = v;
            Notes[v, x, y] = CellState.Placed;
            string message = detail == null
                ? $"{ColLetter(x)}{y} <{v}> {technique}"
                : $"{ColLetter(x)}{y} <{v}> {technique} ({detail})";
            AddLog(message, technique, tier, x, y);
            DeleteCandidate();
            // Takes the snapshot after DeleteCandidate() (i.e. once the candidate removals caused by
            // placing this cell have already been applied). If DeleteCandidate() also happened to push
            // "Solved!" to the log, that gets picked up here too.
            FlushSnapshots();
        }

        private bool Eliminate(int digit, int x, int y, CellState reason, string message,
            IReadOnlyList<(int x, int y)> causeCells = null)
        {
            if (Notes[digit, x, y] != CellState.Open) return false;
            Notes[digit, x, y] = reason;
            Difficulty tier = StateTier.TryGetValue(reason, out var t) ? t : Difficulty.Moderate;
            AddLog(message, reason.ToString(), tier, x, y, causeCells);
            FlushSnapshots();
            return true;
        }

        // ============================================================
        // Board geometry helpers (the core piece that eliminates row/column copy-paste)
        //
        // CellsOf/Peers/BoxIndex are pure shape information that never depends on the board's values,
        // but they are called extremely often by every technique, so they are computed once in the
        // static constructor and cached in arrays (the results are identical to the uncached version).
        // Direct array indexing is used instead of a Dictionary
        // to avoid the cost of hashing a tuple key (measurements showed the Dictionary version was
        // actually slower in the hot path in some cases).
        // ============================================================

        public static bool IsFree(CellState s) => s == CellState.Open;

        private static string ColLetter(int x) => ((char)('A' + x - 1)).ToString();

        private static readonly (int x, int y)[,][] UnitCellsArr = new (int, int)[3, 10][];
        private static readonly int[,] BoxIndexArr = new int[10, 10];
        private static readonly (int x, int y)[,][] PeersArr = new (int, int)[10, 10][];

        static SudokuEngine()
        {
            foreach (Unit unit in new[] { Unit.Row, Unit.Col, Unit.Box })
                for (int idx = 1; idx <= 9; idx++)
                    UnitCellsArr[(int)unit, idx] = ComputeCellsOf(unit, idx).ToArray();

            for (int x = 1; x <= 9; x++)
                for (int y = 1; y <= 9; y++)
                    BoxIndexArr[x, y] = ComputeBoxIndex(x, y);

            // Peers: every cell other than (x,y) itself that shares a row, column, or box with it.
            // The original Peers() returned cells shared between the row/column and the box as duplicates,
            // but callers only ever use the result to update Notes (idempotent) or build a HashSet,
            // so caching a de-duplicated array instead produces identical results.
            for (int x = 1; x <= 9; x++)
                for (int y = 1; y <= 9; y++)
                {
                    var set = new HashSet<(int, int)>();
                    foreach (var c in UnitCellsArr[(int)Unit.Row, y]) if (c.Item1 != x) set.Add(c);
                    foreach (var c in UnitCellsArr[(int)Unit.Col, x]) if (c.Item2 != y) set.Add(c);
                    foreach (var c in UnitCellsArr[(int)Unit.Box, BoxIndexArr[x, y]]) if (c != (x, y)) set.Add(c);
                    PeersArr[x, y] = set.ToArray();
                }
        }

        private static int BoxIndex(int x, int y) => BoxIndexArr[x, y];

        private static int ComputeBoxIndex(int x, int y) => ((y - 1) / 3) * 3 + ((x - 1) / 3) + 1;

        /// <summary>Returns the 9 cells belonging to the index-th group of the given Unit (row/column/box).</summary>
        private static IReadOnlyList<(int x, int y)> CellsOf(Unit unit, int index) => UnitCellsArr[(int)unit, index];

        private static IEnumerable<(int x, int y)> ComputeCellsOf(Unit unit, int index)
        {
            switch (unit)
            {
                case Unit.Row:
                    for (int x = 1; x <= 9; x++) yield return (x, index);
                    break;
                case Unit.Col:
                    for (int y = 1; y <= 9; y++) yield return (index, y);
                    break;
                default: // Box
                    int bx = ((index - 1) % 3) * 3 + 1;
                    int by = ((index - 1) / 3) * 3 + 1;
                    for (int dx = 0; dx < 3; dx++)
                        for (int dy = 0; dy < 3; dy++)
                            yield return (bx + dx, by + dy);
                    break;
            }
        }

        /// <summary>Every cell other than (x,y) itself that is in the same row, column, or box (de-duplicated).</summary>
        private static IReadOnlyList<(int x, int y)> Peers(int x, int y) => PeersArr[x, y];

        /// <summary>Whether two cells share a row, column, or box ("see" each other).</summary>
        private static bool Sees(int x1, int y1, int x2, int y2)
        {
            if (x1 == x2 && y1 == y2) return false;
            if (x1 == x2 || y1 == y2) return true;
            return BoxIndex(x1, y1) == BoxIndex(x2, y2);
        }

        /// <summary>
        /// Returns, for cell (x,y), the not-yet-eliminated candidate digits as a bool[10] (index 1-9).
        /// All false for an already-placed cell. Used to draw the GUI's pencil marks (small candidate digits).
        /// </summary>
        public bool[] GetCandidateFlags(int x, int y) => GetCandidateFlags(Board, Notes, x, y);

        /// <summary>
        /// The same processing as the instance version above, but against an arbitrary
        /// (usually taken from a History snapshot) Board/Notes. Used to show the candidates as of that snapshot during step replay.
        /// </summary>
        public static bool[] GetCandidateFlags(int[,] board, CellState[,,] notes, int x, int y)
        {
            var flags = new bool[10];
            if (board[x, y] != 0) return flags;
            for (int d = 1; d <= 9; d++)
                flags[d] = notes[d, x, y] == CellState.Open;
            return flags;
        }

        private int CandidateMask(int x, int y)
        {
            if (Board[x, y] != 0) return 0;
            int mask = 0;
            for (int d = 1; d <= 9; d++)
                if (IsFree(Notes[d, x, y])) mask |= (1 << d);
            return mask;
        }

        /// <summary>Collects every cell with exactly 2 candidates, as (x, y, mask).
        /// Consolidates the board-wide scan that XY-Wing/W-Wing/XY-Chain/Remote Pairs all need in common into one place.</summary>
        private List<(int x, int y, int mask)> CollectBivalueCells()
        {
            var result = new List<(int x, int y, int mask)>();
            for (int x = 1; x <= 9; x++)
                for (int y = 1; y <= 9; y++)
                {
                    int mask = CandidateMask(x, y);
                    if (PopCount(mask) == 2) result.Add((x, y, mask));
                }
            return result;
        }

        // For every bitmask from 0 to 1023, precompute a
        // table of "the array of set digits". MaskDigits() is called extremely often by every technique,
        // so this turns it into an O(1) table lookup instead of checking 9 bits and building a list every time.
        private static readonly int[][] MaskDigitsTable = BuildMaskDigitsTable();

        private static int[][] BuildMaskDigitsTable()
        {
            var table = new int[1024][];
            for (int m = 0; m < 1024; m++)
            {
                var list = new List<int>();
                for (int d = 1; d <= 9; d++)
                    if ((m & (1 << d)) != 0) list.Add(d);
                table[m] = list.ToArray();
            }
            return table;
        }

        private static int PopCount(int v) => System.Numerics.BitOperations.PopCount((uint)v);

        private static int[] MaskDigits(int mask) => MaskDigitsTable[mask];

        /// <summary>Enumerates every combination (as an array of indices) of size elements chosen from 0..n-1.</summary>
        private static IEnumerable<int[]> Combinations(int n, int size)
        {
            if (size <= 0 || size > n) yield break;
            var combo = new int[size];
            foreach (var c in CombinationsRec(0, n, size, combo, 0)) yield return c;
        }

        private static IEnumerable<int[]> CombinationsRec(int start, int n, int size, int[] combo, int depth)
        {
            if (depth == size) { yield return (int[])combo.Clone(); yield break; }
            for (int i = start; i <= n - (size - depth); i++)
            {
                combo[depth] = i;
                foreach (var c in CombinationsRec(i + 1, n, size, combo, depth + 1)) yield return c;
            }
        }

        // ============================================================
        // Technique 1: Naked Single (formerly CommandButton4)
        // ============================================================

        public bool NakedSingle()
        {
            bool changed = false;
            for (int x = 1; x <= 9; x++)
            {
                for (int y = 1; y <= 9; y++)
                {
                    if (Board[x, y] != 0) continue;
                    int mask = CandidateMask(x, y);
                    if (PopCount(mask) == 1)
                    {
                        Place(x, y, MaskDigits(mask)[0], "Naked Single", Difficulty.Trivial);
                        changed = true;
                    }
                }
            }
            return changed;
        }

        // ============================================================
        // Technique 2: Hidden Single (formerly CommandButton3; unified Block/Row/Col into one method)
        // ============================================================

        public bool HiddenSingle()
        {
            bool changed = false;
            foreach (Unit unit in new[] { Unit.Box, Unit.Row, Unit.Col })
            {
                for (int idx = 1; idx <= 9; idx++)
                {
                    for (int m = 1; m <= 9; m++)
                    {
                        var openCells = CellsOf(unit, idx).Where(c => IsFree(Notes[m, c.x, c.y])).ToList();
                        if (openCells.Count == 1)
                        {
                            var (x, y) = openCells[0];
                            Place(x, y, m, $"Hidden Single <{UnitName(unit)}>", Difficulty.Simple);
                            changed = true;
                        }
                    }
                }
            }
            return changed;
        }

        private static string UnitName(Unit u) => u switch
        {
            Unit.Row => "Horizontal",
            Unit.Col => "Vertical",
            _ => "Block"
        };

        // ============================================================
        // Technique 3: Locked Candidates (formerly CommandButton11=Claiming, CommandButton2=Pointing)
        // Pointing:  If a box's candidates for a digit fit on a single row/column, eliminate that digit from the rest of that row/column outside the box
        // Claiming:  If a row/column's candidates for a digit fit inside a single box, eliminate that digit from the rest of that box outside the row/column
        // ============================================================

        public bool LockedCandidates()
        {
            bool changed = false;
            for (int m = 1; m <= 9; m++)
            {
                changed |= PointingInBox(m);
                changed |= ClaimingInLine(m, Unit.Row);
                changed |= ClaimingInLine(m, Unit.Col);
            }
            return changed;
        }

        private bool PointingInBox(int m)
        {
            bool changed = false;
            for (int b = 1; b <= 9; b++)
            {
                var cells = CellsOf(Unit.Box, b).Where(c => IsFree(Notes[m, c.x, c.y])).ToList();
                if (cells.Count == 0) continue;

                if (cells.Select(c => c.y).Distinct().Count() == 1)
                {
                    int y = cells[0].y;
                    foreach (var (x2, y2) in CellsOf(Unit.Row, y))
                        if (BoxIndex(x2, y2) != b && IsFree(Notes[m, x2, y2]))
                            changed |= Eliminate(m, x2, y2, CellState.LockedCandidate,
                                $"{ColLetter(x2)}{y2}  Locked Candidate (Pointing, Row) <{m}>");
                }
                if (cells.Select(c => c.x).Distinct().Count() == 1)
                {
                    int x = cells[0].x;
                    foreach (var (x2, y2) in CellsOf(Unit.Col, x))
                        if (BoxIndex(x2, y2) != b && IsFree(Notes[m, x2, y2]))
                            changed |= Eliminate(m, x2, y2, CellState.LockedCandidate,
                                $"{ColLetter(x2)}{y2}  Locked Candidate (Pointing, Col) <{m}>");
                }
            }
            return changed;
        }

        private bool ClaimingInLine(int m, Unit lineUnit)
        {
            bool changed = false;
            for (int idx = 1; idx <= 9; idx++)
            {
                var cells = CellsOf(lineUnit, idx).Where(c => IsFree(Notes[m, c.x, c.y])).ToList();
                if (cells.Count == 0) continue;

                int box = BoxIndex(cells[0].x, cells[0].y);
                if (!cells.All(c => BoxIndex(c.x, c.y) == box)) continue;

                foreach (var (x2, y2) in CellsOf(Unit.Box, box))
                {
                    bool inSameLine = lineUnit == Unit.Row ? y2 == idx : x2 == idx;
                    if (!inSameLine && IsFree(Notes[m, x2, y2]))
                        changed |= Eliminate(m, x2, y2, CellState.LockedCandidate,
                            $"{ColLetter(x2)}{y2}  Locked Candidate (Claiming, {UnitName(lineUnit)}) <{m}>");
                }
            }
            return changed;
        }

        // ============================================================
        // Technique 4: Naked Subsets = Naked Pair through Quad (formerly CommandButton9 / the Hidden_Pair function)
        // VBA had duplication, simply calling the same function three times for rows/columns/boxes,
        // but here the Units are enumerated and folded into a single loop.
        // ============================================================

        public bool NakedSubsets(int maxSize = 5)
        {
            bool changed = false;
            foreach (Unit unit in new[] { Unit.Row, Unit.Col, Unit.Box })
                for (int idx = 1; idx <= 9; idx++)
                    changed |= NakedSubsetsInGroup(unit, idx, maxSize);
            return changed;
        }

        private bool NakedSubsetsInGroup(Unit unit, int idx, int maxSize)
        {
            var cells = CellsOf(unit, idx)
                .Where(c => Board[c.x, c.y] == 0)
                .Select(c => (c.x, c.y, mask: CandidateMask(c.x, c.y)))
                .Where(c => c.mask != 0)
                .ToList();

            bool changed = false;
            int n = cells.Count;
            for (int size = 2; size <= Math.Min(maxSize, n - 1); size++)
            {
                foreach (var combo in Combinations(n, size))
                {
                    int unionMask = 0;
                    foreach (int i in combo) unionMask |= cells[i].mask;
                    if (PopCount(unionMask) != size) continue;

                    // Finding a Naked Subset (size cells that between them have only size candidate
                    // digits) automatically makes the remaining (n-size) cells of that house a
                    // Hidden (n-size) Subset (because the number of unplaced cells in a house always
                    // equals the number of digits not yet placed in that house. The target cells and
                    // digits to eliminate are exactly the same either way, so the elimination logic is
                    // left unchanged; only the label used in the log is chosen based on whichever side has fewer candidate digits).
                    int hiddenSize = n - size;
                    string label = hiddenSize < size
                        ? $"Hidden Subset(size {hiddenSize}, {UnitName(unit)})"
                        : $"Naked Subset(size {size}, {UnitName(unit)})";

                    var inSubset = new HashSet<int>(combo);
                    for (int i = 0; i < n; i++)
                    {
                        if (inSubset.Contains(i)) continue;
                        var (x, y, mask) = cells[i];
                        int toRemove = mask & unionMask;
                        foreach (int d in MaskDigits(toRemove))
                            changed |= Eliminate(d, x, y, CellState.NakedSubset,
                                $"{ColLetter(x)}{y}  {label} removes <{d}>");
                    }
                }
            }
            return changed;
        }

        // ============================================================
        // Technique 5: Fish = X-Wing(size2) / Swordfish(size3) (formerly CommandButton8, CommandButton10)
        // VBA nearly copy-pasted the row and column versions wholesale; unified here into one method that switches direction via baseIsRow.
        // ============================================================

        /// <summary>Returns the CellState corresponding to Fish(size) (2=X-Wing, 3=Swordfish, 4=Jerryfish).</summary>
        private static CellState FishState(int size) => size switch
        {
            2 => CellState.XWing,
            3 => CellState.Swordfish,
            4 => CellState.Jerryfish,
            _ => throw new ArgumentOutOfRangeException(nameof(size), size, "Fish only supports size 2-4")
        };

        /// <summary>Returns the technique name corresponding to Fish(size) (for the log).</summary>
        private static string FishName(int size) => size switch
        {
            2 => "X-Wing",
            3 => "Swordfish",
            4 => "Jerryfish",
            _ => throw new ArgumentOutOfRangeException(nameof(size), size, "Fish only supports size 2-4")
        };

        public bool Fish(int size)
        {
            bool changed = false;
            changed |= FishDirection(size, baseIsRow: true);
            changed |= FishDirection(size, baseIsRow: false);
            return changed;
        }

        private bool FishDirection(int size, bool baseIsRow)
        {
            bool changed = false;
            Unit baseUnit = baseIsRow ? Unit.Row : Unit.Col;

            for (int m = 1; m <= 9; m++)
            {
                var lineMask = new int[10];
                for (int i = 1; i <= 9; i++)
                {
                    int mask = 0;
                    foreach (var (x, y) in CellsOf(baseUnit, i))
                    {
                        int cover = baseIsRow ? x : y;
                        if (IsFree(Notes[m, x, y])) mask |= (1 << cover);
                    }
                    lineMask[i] = mask;
                }

                var candidateLines = Enumerable.Range(1, 9)
                    .Where(i => lineMask[i] != 0 && PopCount(lineMask[i]) >= 2 && PopCount(lineMask[i]) <= size)
                    .ToList();

                foreach (var combo in Combinations(candidateLines.Count, size))
                {
                    var lines = combo.Select(i => candidateLines[i]).ToList();
                    int unionMask = lines.Aggregate(0, (acc, l) => acc | lineMask[l]);
                    if (PopCount(unionMask) != size) continue;

                    // Records the actual candidate cells making up this fish shape (cells on a base
                    // line where m is still alive) as "cause cells" (used by the UI for the pale-blue highlight).
                    var causeCells = new List<(int x, int y)>();
                    foreach (int l in lines)
                        foreach (int cover in MaskDigits(lineMask[l]))
                            causeCells.Add(baseIsRow ? (cover, l) : (l, cover));

                    foreach (int cover in MaskDigits(unionMask))
                    {
                        for (int line = 1; line <= 9; line++)
                        {
                            if (lines.Contains(line)) continue;
                            int x = baseIsRow ? cover : line;
                            int y = baseIsRow ? line : cover;
                            if (IsFree(Notes[m, x, y]))
                                changed |= Eliminate(m, x, y, FishState(size),
                                    $"{ColLetter(x)}{y}  {FishName(size)} ({(baseIsRow ? "Horizontal" : "Vertical")}) removes <{m}>",
                                    causeCells);
                        }
                    }
                }
            }
            return changed;
        }

        // ============================================================
        // Technique: Sashimi/Finned X-Wing (formerly CommandButton21. Verifying the user-devised
        // algorithm found a logical error (about 20% incorrect eliminations), so this has been
        // reimplemented with correct logic based on the standard definition. See readme.md for details)
        //
        // On base line (row) R1, find a row where digit d has exactly 2 candidates (Ca, Cb) (a strong link).
        // For another line R2, collect every candidate other than "Ca" (i.e. Cb itself + fin candidates),
        // and check whether they all fit inside a single box (the one containing the intersection of
        // Cb and R2) (if they do, digit must go in one of the cells on R2 within that box).
        // If so, digit can be eliminated from column Cb, in that box, on rows other than R1/R2 themselves.
        // VBA nearly copy-pasted the row-direction and column-direction versions wholesale; as with
        // Fish(), unified here into one method that switches direction via baseIsRow, removing the duplication.
        // ============================================================

        public bool SashimiFinnedXWing()
        {
            bool changed = false;
            changed |= SashimiFinnedXWingDirection(baseIsRow: true);
            changed |= SashimiFinnedXWingDirection(baseIsRow: false);
            return changed;
        }

        private bool SashimiFinnedXWingDirection(bool baseIsRow)
        {
            bool changed = false;
            Unit baseUnit = baseIsRow ? Unit.Row : Unit.Col;

            for (int d = 1; d <= 9; d++)
                for (int r1 = 1; r1 <= 9; r1++)
                {
                    // Collect the cover coordinates (x if baseIsRow, else y) where d is a candidate on R1
                    var cr1 = new List<int>();
                    foreach (var (x, y) in CellsOf(baseUnit, r1))
                        if (IsFree(Notes[d, x, y])) cr1.Add(baseIsRow ? x : y);
                    if (cr1.Count != 2) continue; // R1 must be a "base line" with exactly 2 candidates

                    // The Ca/Cb assignment is symmetric, so try both
                    foreach (var (ca, cb) in new[] { (cr1[0], cr1[1]), (cr1[1], cr1[0]) })
                        for (int r2 = 1; r2 <= 9; r2++)
                        {
                            if (r2 == r1) continue;

                            // Collect every candidate on R2 other than ca (i.e. Cb itself + fin candidates)
                            var others = new List<int>();
                            foreach (var (x, y) in CellsOf(baseUnit, r2))
                            {
                                int cover = baseIsRow ? x : y;
                                if (cover == ca) continue;
                                if (IsFree(Notes[d, x, y])) others.Add(cover);
                            }
                            if (others.Count == 0) continue;

                            // Whether all of others fit inside the box containing the intersection of Cb and R2
                            int box = baseIsRow ? BoxIndex(cb, r2) : BoxIndex(r2, cb);
                            bool confined = others.TrueForAll(cover =>
                                (baseIsRow ? BoxIndex(cover, r2) : BoxIndex(r2, cover)) == box);
                            if (!confined) continue;

                            // Whether Cb itself still remains as a candidate on R2 (= Finned type),
                            // or has already been eliminated so only the fins remain (= Sashimi type).
                            string kind = others.Contains(cb) ? "Finned" : "Sashimi";

                            var causeCells = new List<(int x, int y)>();
                            foreach (int cover in cr1)
                                causeCells.Add(baseIsRow ? (cover, r1) : (r1, cover));
                            foreach (int cover in others)
                                causeCells.Add(baseIsRow ? (cover, r2) : (r2, cover));

                            // Eliminate digit from column Cb within the box, on rows other than R1/R2
                            foreach (var (x, y) in CellsOf(Unit.Box, box))
                            {
                                int cover = baseIsRow ? x : y;
                                int line = baseIsRow ? y : x;
                                if (cover != cb) continue;
                                if (line == r1 || line == r2) continue;
                                if (IsFree(Notes[d, x, y]))
                                    changed |= Eliminate(d, x, y, CellState.SashimiFinnedXWing,
                                        $"{ColLetter(x)}{y}  {kind} X-Wing removes <{d}>",
                                        causeCells);
                            }
                        }
                }
            return changed;
        }

        // ============================================================
        // Technique: Sashimi/Finned Swordfish
        //
        // A generalization of Swordfish (size 3). Even when the union of cells (cover coordinates)
        // where the digit can be placed on 3 base lines (rows or columns) does not fit exactly
        // into a covering set K of 3 columns (or 3 rows), if all the candidates sticking out of K
        // (the fins) fit within a single box, then within that box, candidates on the row(s)/column(s)
        // of K passing through that box, other than the base lines, can be eliminated.
        //
        // [Detection algorithm]
        // - Choose 3 base lines (rows if baseIsRow, else columns) and the 3 covering lines (K)
        // - Among the cells on each base line where the digit can be placed, collect the cells not in K (= fins)
        // - If the total number of fins is 3 or more, this technique does not apply (out of scope)
        // - If there are 0 fins, it is a normal Swordfish (already handled by Fish(3), so out of scope here)
        // - Holds only when there is 1 fin, or 2 fins that both fit within the same box
        //
        // [Determining Sashimi/Finned (general definition)]
        // Among the base lines that produced a fin, if there is even one line that itself has
        // no candidate on the K side (i.e. the fin alone stands in for that row/column's role), it is Sashimi;
        // if not (i.e. the line that produced the fin also still has a candidate on the K side, so the fin is purely extra), it is Finned.
        // ============================================================

        public bool SashimiFinnedSwordfish()
        {
            bool changed = false;
            changed |= SashimiFinnedSwordfishDirection(baseIsRow: true);
            changed |= SashimiFinnedSwordfishDirection(baseIsRow: false);
            return changed;
        }

        private bool SashimiFinnedSwordfishDirection(bool baseIsRow)
        {
            bool changed = false;
            Unit baseUnit = baseIsRow ? Unit.Row : Unit.Col;

            for (int d = 1; d <= 9; d++)
            {
                var lineCandidates = new List<int>[10];
                for (int i = 1; i <= 9; i++)
                {
                    var list = new List<int>();
                    foreach (var (x, y) in CellsOf(baseUnit, i))
                    {
                        int cover = baseIsRow ? x : y;
                        if (IsFree(Notes[d, x, y])) list.Add(cover);
                    }
                    lineCandidates[i] = list;
                }

                var nonEmptyLines = Enumerable.Range(1, 9).Where(i => lineCandidates[i].Count > 0).ToList();

                foreach (var lineCombo in Combinations(nonEmptyLines.Count, 3))
                {
                    var lines = lineCombo.Select(i => nonEmptyLines[i]).ToList();
                    var candSets = lines.Select(l => lineCandidates[l]).ToList();

                    var totalUnion = new SortedSet<int>();
                    foreach (var set in candSets)
                        foreach (var cover in set)
                            totalUnion.Add(cover);

                    if (totalUnion.Count <= 3) continue; // No fins (already handled by the normal Fish(3))

                    var totalUnionList = totalUnion.ToList();

                    foreach (var kCombo in Combinations(totalUnionList.Count, 3))
                    {
                        var k = kCombo.Select(i => totalUnionList[i]).ToHashSet();

                        // Collect the actual coordinates of the fins (candidates not in K) and which base line each fin came from
                        var finCells = new List<(int x, int y)>();
                        var linesWithFin = new HashSet<int>();
                        for (int li = 0; li < lines.Count; li++)
                        {
                            int line = lines[li];
                            foreach (var cover in candSets[li])
                            {
                                if (k.Contains(cover)) continue;
                                finCells.Add(baseIsRow ? (cover, line) : (line, cover));
                                linesWithFin.Add(li);
                            }
                        }
                        if (finCells.Count == 0) continue;  // No fins (already handled by the normal Fish(3))
                        if (finCells.Count > 2) continue;   // 3 or more fins does not hold

                        var finBoxes = finCells.Select(c => BoxIndex(c.x, c.y)).Distinct().ToList();
                        if (finBoxes.Count != 1) continue;  // Fins must fit within a single box
                        int box = finBoxes[0];

                        // Determine Sashimi/Finned: if any of the lines that produced a fin
                        // has no candidate on the K side at all, it's Sashimi; if all of them do, it's Finned
                        bool isSashimi = linesWithFin.Any(li => !candSets[li].Any(cov => k.Contains(cov)));
                        string kind = isSashimi ? "Sashimi" : "Finned";

                        // Cause cells: every actual candidate cell on the 3 base lines (both the K side and the fin side)
                        var causeCells = new List<(int x, int y)>();
                        for (int li = 0; li < lines.Count; li++)
                        {
                            int line = lines[li];
                            foreach (var cover in candSets[li])
                                causeCells.Add(baseIsRow ? (cover, line) : (line, cover));
                        }

                        // Within the fin's box, from the column(s)/row(s) of K passing through that box,
                        // eliminate candidates on rows/columns other than the base lines
                        foreach (int cover in k)
                        {
                            bool passesThroughBox = CellsOf(Unit.Box, box).Any(c => (baseIsRow ? c.x : c.y) == cover);
                            if (!passesThroughBox) continue;

                            foreach (var (x, y) in CellsOf(Unit.Box, box))
                            {
                                int c2 = baseIsRow ? x : y;
                                int line2 = baseIsRow ? y : x;
                                if (c2 != cover) continue;
                                if (lines.Contains(line2)) continue;
                                if (!IsFree(Notes[d, x, y])) continue;
                                changed |= Eliminate(d, x, y, CellState.SashimiFinnedSwordfish,
                                    $"{ColLetter(x)}{y}  {kind} Swordfish ({(baseIsRow ? "Horizontal" : "Vertical")}) removes <{d}>",
                                    causeCells);
                            }
                        }
                    }
                }
            }
            return changed;
        }

        // ============================================================
        // Technique: 2 String Kite (formerly CommandButton18)
        //
        // For a given digit num,
        //   - find a strong link in row "row" where num has exactly 2 candidate columns (ax, bx)
        //   - find a strong link in column "col" where num has exactly 2 candidate rows (cy, dy)
        // If the row-link and column-link don't share a cell
        // (col != ax,bx and row != cy,dy -- if they do share one, it reduces to a different shape such as X-Wing and is out of scope),
        // and one end of the row-link, (ax,row) or (bx,row), and one end of the column-link, (col,cy)
        // or (col,dy), are in the same box (i.e. see each other), then the following holds:
        //   If num is absent from one endpoint, the strong link forces num into the other endpoint.
        //   If num is present at one endpoint, the other endpoint in the same box cannot have num
        //   (uniqueness within a box), so the strong link on that row/column forces num into its other endpoint instead.
        // Either way, num must end up in at least one of the row-link's remaining endpoint (column) and
        // the column-link's remaining endpoint (row), so num can be eliminated from the cell at their intersection.
        //
        // The original VBA checked the 4 patterns exclusively with ElseIf (only the first match), but
        // depending on the boxes' relative positions, multiple patterns can actually hold at once and
        // each can lead to a different target cell being eliminated, so this port replaces that with
        // independent if-checks so that no valid elimination is missed.
        // ============================================================

        public bool TwoStringKite()
        {
            bool changed = false;
            for (int num = 1; num <= 9; num++)
            {
                for (int row = 1; row <= 9; row++)
                {
                    var rowCells = new List<int>();
                    for (int x = 1; x <= 9; x++)
                        if (IsFree(Notes[num, x, row])) rowCells.Add(x);
                    if (rowCells.Count != 2) continue;
                    int ax = rowCells[0], bx = rowCells[1];

                    for (int col = 1; col <= 9; col++)
                    {
                        var colCells = new List<int>();
                        for (int y = 1; y <= 9; y++)
                            if (IsFree(Notes[num, col, y])) colCells.Add(y);
                        if (colCells.Count != 2) continue;
                        int cy = colCells[0], dy = colCells[1];

                        // Skip if the row-link and column-link share a cell
                        if (col == ax || col == bx || row == cy || row == dy) continue;

                        changed |= TryTwoStringKite(num, ax, row, bx, col, cy, dy);
                        changed |= TryTwoStringKite(num, ax, row, bx, col, dy, cy);
                        changed |= TryTwoStringKite(num, bx, row, ax, col, cy, dy);
                        changed |= TryTwoStringKite(num, bx, row, ax, col, dy, cy);
                    }
                }
            }
            return changed;
        }

        /// <summary>
        /// Checks whether the row-link endpoint (rowEndX, row) and the column-link endpoint (col, colEndY)
        /// are in the same box, and if so, eliminates num from the cell where the remaining endpoint's
        /// column, (otherRowEndX, row), meets the remaining endpoint's row, (col, otherColEndY) --
        /// i.e. the cell (otherRowEndX, otherColEndY).
        private bool TryTwoStringKite(int num, int rowEndX, int row, int otherRowEndX, int col, int colEndY, int otherColEndY)
        {
            if (BoxIndex(rowEndX, row) != BoxIndex(col, colEndY)) return false;

            int tx = otherRowEndX, ty = otherColEndY;
            if (!IsFree(Notes[num, tx, ty])) return false;

            // Uses both endpoints of the row-link (2 cells) plus both endpoints of the column-link (2 cells) as the "cause cells" for this elimination.
            var causeCells = new[] { (rowEndX, row), (otherRowEndX, row), (col, colEndY), (col, otherColEndY) };
            return Eliminate(num, tx, ty, CellState.TwoStringKite,
                $"{ColLetter(tx)}{ty}  2 String Kite removes <{num}>", causeCells);
        }

        // ============================================================
        // Technique: Skyscraper (formerly CommandButton19)
        //
        // For a given digit (row-based case):
        //   - a strong link (the "base") where row row1 has exactly 2 candidate columns (x1, x2) for digit
        //   - in column x1, other than row1, digit has exactly 1 candidate row (targetY1) -> column x1 is also a strong link
        //   - in column x2, other than row1, digit has exactly 1 candidate row (targetY2) -> column x2 is also a strong link
        // all hold, and targetY1 != targetY2, then digit can be eliminated from every cell seen by
        // both of the roof's two points, (x1,targetY1) and (x2,targetY2).
        // (the 3 cells row1/targetY1/x1 and the 3 cells row1/targetY2/x2 each form "two rows with a
        //  strong link in the same column", which is exactly the standard Skyscraper technique)
        //
        // The column-based case swaps rows and columns from the above and works the same way.
        // ============================================================

        public bool Skyscraper()
        {
            bool changed = false;
            for (int digit = 1; digit <= 9; digit++)
            {
                changed |= SkyscraperDirection(digit, baseIsRow: true);
                changed |= SkyscraperDirection(digit, baseIsRow: false);
            }
            return changed;
        }

        /// <summary>baseIsRow=true: uses rows as the base and searches for a strong link in the column direction (formerly the row-based case).
        /// baseIsRow=false: uses columns as the base and searches for a strong link in the row direction (formerly the column-based case).
        /// Uses the same baseIsRow pattern as Fish()/SashimiFinnedXWing() to remove the row/column copy-paste.</summary>
        private bool SkyscraperDirection(int digit, bool baseIsRow)
        {
            bool changed = false;
            Unit baseUnit = baseIsRow ? Unit.Row : Unit.Col;

            for (int baseIdx = 1; baseIdx <= 9; baseIdx++)
            {
                var covers = new List<int>();
                foreach (var (x, y) in CellsOf(baseUnit, baseIdx))
                    if (IsFree(Notes[digit, x, y])) covers.Add(baseIsRow ? x : y);
                if (covers.Count != 2) continue;
                int c1 = covers[0], c2 = covers[1];

                int t1 = FindLoneCandidate(digit, c1, baseIdx, baseIsRow);
                if (t1 == 0) continue;
                int t2 = FindLoneCandidate(digit, c2, baseIdx, baseIsRow);
                if (t2 == 0 || t1 == t2) continue;

                var (ax, ay) = baseIsRow ? (c1, t1) : (t1, c1);
                var (bx, by) = baseIsRow ? (c2, t2) : (t2, c2);
                var baseCell1 = baseIsRow ? (c1, baseIdx) : (baseIdx, c1);
                var baseCell2 = baseIsRow ? (c2, baseIdx) : (baseIdx, c2);
                var causeCells = new[] { baseCell1, baseCell2, (ax, ay), (bx, by) };
                changed |= EliminateSkyscraper(digit, ax, ay, bx, by, causeCells);
            }
            return changed;
        }

        /// <summary>baseIsRow=true: scans column cover vertically, and if it has exactly one candidate row other than row baseIdx, returns that row.
        /// baseIsRow=false: scans row cover horizontally, and if it has exactly one candidate column other than column baseIdx, returns that column.
        /// (a unified version of the former FindLoneCandidateRow/Col)</summary>
        private int FindLoneCandidate(int digit, int cover, int baseIdx, bool baseIsRow)
        {
            int count = 0, target = 0;
            for (int i = 1; i <= 9; i++)
            {
                if (i == baseIdx) continue;
                var (x, y) = baseIsRow ? (cover, i) : (i, cover);
                if (IsFree(Notes[digit, x, y])) { count++; target = i; }
            }
            return count == 1 ? target : 0;
        }

        /// <summary>Eliminates digit from every cell seen by both of the roof's two points, (ax,ay) and (bx,by).</summary>
        private bool EliminateSkyscraper(int digit, int ax, int ay, int bx, int by, IReadOnlyList<(int x, int y)> causeCells)
        {
            bool changed = false;
            foreach (var (x, y) in CommonPeersOf(new[] { (ax, ay), (bx, by) }))
                if (IsFree(Notes[digit, x, y]))
                    changed |= Eliminate(digit, x, y, CellState.Skyscraper,
                        $"{ColLetter(x)}{y}  Skyscraper removes <{digit}>", causeCells);
            return changed;
        }

        // ============================================================
        // Empty Rectangle
        //
        // Within a single box B, if the cells where a digit can be placed fit entirely on
        // "one row R" and "one column C" (with at least one cell on each) -- an empty rectangle --
        // then if one end of a strong link outside B (a row/column with only 2 candidate cells) lies on R or C,
        // the digit can be eliminated from the cell where the other end A's row/column meets C/R.
        // ============================================================

        public bool EmptyRectangle()
        {
            bool changed = false;
            for (int digit = 1; digit <= 9; digit++)
            {
                for (int box = 1; box <= 9; box++)
                    changed |= EmptyRectangleInBox(digit, box);
            }
            return changed;
        }

        private bool EmptyRectangleInBox(int digit, int box)
        {
            var boxCells = CellsOf(Unit.Box, box);
            var candidates = boxCells.Where(c => IsFree(Notes[digit, c.x, c.y])).ToList();
            if (candidates.Count < 2) return false;

            var boxRows = boxCells.Select(c => c.y).Distinct().ToList();
            var boxCols = boxCells.Select(c => c.x).Distinct().ToList();

            bool changed = false;
            foreach (int r in boxRows.Where(r => candidates.Any(c => c.y == r)))
            {
                foreach (int c in boxCols.Where(c => candidates.Any(cc => cc.x == c)))
                {
                    // Whether all cells fit "on row R or column C"
                    if (!candidates.All(cell => cell.x == c || cell.y == r)) continue;
                    // If either the vertical arm or the horizontal arm has no cells, it's just a straight line
                    // (equivalent to Locked Candidates) rather than a true empty rectangle, so exclude it.
                    bool hasRowArm = candidates.Any(cell => cell.y == r && cell.x != c);
                    bool hasColArm = candidates.Any(cell => cell.x == c && cell.y != r);
                    if (!hasRowArm || !hasColArm) continue;

                    changed |= SearchEmptyRectangleLinks(digit, box, r, c, boxRows, boxCols, candidates);
                }
            }
            return changed;
        }

        private bool SearchEmptyRectangleLinks(int digit, int box, int r, int c,
            List<int> boxRows, List<int> boxCols, List<(int x, int y)> candidates)
        {
            bool changed = false;

            // 4a) A strong link on an external column C'. If one end lies on row R, eliminate from the cell where the other end A's row meets C.
            for (int cPrime = 1; cPrime <= 9; cPrime++)
            {
                if (boxCols.Contains(cPrime)) continue; // Exclude the box's own columns (external columns only)

                var linkCells = CellsOf(Unit.Col, cPrime).Where(cell => IsFree(Notes[digit, cell.x, cell.y])).ToList();
                if (linkCells.Count != 2) continue;

                var onRowMatches = linkCells.Where(cell => cell.y == r).ToList();
                if (onRowMatches.Count != 1) continue; // No match, or (theoretically impossible but) both matching, is excluded
                var a = linkCells[0] == onRowMatches[0] ? linkCells[1] : linkCells[0];

                int tx = c, ty = a.y;
                if (BoxIndex(tx, ty) == box) continue; // Exclude when the target is inside the box itself (the proof does not hold)
                if (!IsFree(Notes[digit, tx, ty])) continue;

                var causeCells = candidates.Concat(linkCells).ToList();
                changed |= Eliminate(digit, tx, ty, CellState.EmptyRectangle,
                    $"{ColLetter(tx)}{ty}  Empty Rectangle (Block {box}, R={r}, C={ColLetter(c)}, "
                    + $"strong link on external column {ColLetter(cPrime)}) removes <{digit}>", causeCells);
            }

            // 4b) A strong link on an external row R'. If one end lies on column C, eliminate from the cell where the other end A's column meets R.
            for (int rPrime = 1; rPrime <= 9; rPrime++)
            {
                if (boxRows.Contains(rPrime)) continue; // Exclude the box's own rows (external rows only)

                var linkCells = CellsOf(Unit.Row, rPrime).Where(cell => IsFree(Notes[digit, cell.x, cell.y])).ToList();
                if (linkCells.Count != 2) continue;

                var onColMatches = linkCells.Where(cell => cell.x == c).ToList();
                if (onColMatches.Count != 1) continue; // No match, or (theoretically impossible but) both matching, is excluded
                var a = linkCells[0] == onColMatches[0] ? linkCells[1] : linkCells[0];

                int tx = a.x, ty = r;
                if (BoxIndex(tx, ty) == box) continue; // Exclude when the target is inside the box itself (the proof does not hold)
                if (!IsFree(Notes[digit, tx, ty])) continue;

                var causeCells = candidates.Concat(linkCells).ToList();
                changed |= Eliminate(digit, tx, ty, CellState.EmptyRectangle,
                    $"{ColLetter(tx)}{ty}  Empty Rectangle (Block {box}, R={r}, C={ColLetter(c)}, "
                    + $"strong link on external row {rPrime}) removes <{digit}>", causeCells);
            }
            return changed;
        }

        // ============================================================
        // Technique 6: XY-Wing (formerly CommandButton12)
        // The standard algorithm: from a bivalue cell (pivot) and two bivalue cells that see it
        // (wing1, wing2), eliminate their shared third candidate from every cell that sees both wings.
        // ============================================================

        public bool XyWing()
        {
            bool changed = false;
            var bivalue = CollectBivalueCells();

            foreach (var pivot in bivalue)
            {
                var pivotDigits = MaskDigits(pivot.mask);
                var wings = bivalue.Where(c => Sees(pivot.x, pivot.y, c.x, c.y)).ToList();

                for (int i = 0; i < wings.Count; i++)
                {
                    for (int j = i + 1; j < wings.Count; j++)
                    {
                        var w1 = wings[i];
                        var w2 = wings[j];

                        var common1 = pivotDigits.Intersect(MaskDigits(w1.mask)).ToList();
                        var common2 = pivotDigits.Intersect(MaskDigits(w2.mask)).ToList();
                        if (common1.Count != 1 || common2.Count != 1 || common1[0] == common2[0]) continue;

                        var wingShared = MaskDigits(w1.mask).Intersect(MaskDigits(w2.mask)).ToList();
                        if (wingShared.Count != 1) continue;
                        int c = wingShared[0];
                        if (pivotDigits.Contains(c)) continue;

                        var causeCells = new[] { (pivot.x, pivot.y), (w1.x, w1.y), (w2.x, w2.y) };
                        var targets = CommonPeersOf(new[] { (w1.x, w1.y), (w2.x, w2.y) });
                        targets.Remove((pivot.x, pivot.y)); // pivot itself sees both wings, but is excluded from the targets
                        foreach (var (x, y) in targets)
                            if (IsFree(Notes[c, x, y]))
                                changed |= Eliminate(c, x, y, CellState.XyWing,
                                    $"{ColLetter(x)}{y}  XY-Wing removes <{c}>", causeCells);
                    }
                }
            }
            return changed;
        }

        // ============================================================
        // Technique: XYZ-Wing (formerly CommandButton20)
        // Consists of a pivot (with exactly 3 candidates) and two bivalue cells that see it (pincers).
        // One pincer shares a row or column with the pivot; the other shares the pivot's box.
        // If there is exactly one digit that both pincers' candidates have in common, that digit is
        // "a third digit that is also one of the pivot's own candidates", and it can be eliminated
        // from every cell seen by all three of the pivot and both pincers
        // (an extended form of XY-Wing that also involves the pivot's own candidate).
        // VBA split this across IsValidPincerB() / SearchPincerC() / GetCandidates() / IsSubset(), but
        // in C# it's unified into one method using the existing CandidateMask() / MaskDigits() / Sees().

        public bool XyzWing()
        {
            bool changed = false;
            for (int ax = 1; ax <= 9; ax++)
                for (int ay = 1; ay <= 9; ay++)
                {
                    int pivotMask = CandidateMask(ax, ay);
                    if (PopCount(pivotMask) != 3) continue; // The pivot must have exactly 3 candidates

                    // Pincer candidate 1: shares a row or column with the pivot, has 2 candidates, a subset of the pivot's
                    var pincersRowCol = new List<(int x, int y, int mask)>();
                    for (int bx = 1; bx <= 9; bx++)
                    {
                        if (bx == ax) continue;
                        int m = CandidateMask(bx, ay);
                        if (PopCount(m) == 2 && (m & ~pivotMask) == 0) pincersRowCol.Add((bx, ay, m));
                    }
                    for (int by = 1; by <= 9; by++)
                    {
                        if (by == ay) continue;
                        int m = CandidateMask(ax, by);
                        if (PopCount(m) == 2 && (m & ~pivotMask) == 0) pincersRowCol.Add((ax, by, m));
                    }
                    if (pincersRowCol.Count == 0) continue;

                    // Pincer candidate 2: shares the pivot's box, has 2 candidates, a subset of the pivot's
                    var pincersBox = new List<(int x, int y, int mask)>();
                    foreach (var (cx, cy) in CellsOf(Unit.Box, BoxIndex(ax, ay)))
                    {
                        if (cx == ax && cy == ay) continue;
                        int m = CandidateMask(cx, cy);
                        if (PopCount(m) == 2 && (m & ~pivotMask) == 0) pincersBox.Add((cx, cy, m));
                    }
                    if (pincersBox.Count == 0) continue;

                    foreach (var b in pincersRowCol)
                        foreach (var c in pincersBox)
                        {
                            if (b.x == c.x && b.y == c.y) continue; // B and C can't be the same cell

                            int sharedMask = b.mask & c.mask;
                            if (PopCount(sharedMask) != 1) continue; // Requires "exactly 1 match, 1 difference"
                            int targetDigit = MaskDigits(sharedMask)[0];

                            var causeCells = new[] { (ax, ay), (b.x, b.y), (c.x, c.y) };
                            foreach (var (x, y) in CommonPeersOf(causeCells))
                                if (IsFree(Notes[targetDigit, x, y]))
                                    changed |= Eliminate(targetDigit, x, y, CellState.XyzWing,
                                        $"{ColLetter(x)}{y}  XYZ-Wing removes <{targetDigit}>",
                                        causeCells);
                        }
                }
            return changed;
        }

        // ============================================================
        // Technique 7: Remote Pairs (formerly CommandButton15. Implemented here using the standard
        // algorithm: build a graph linking cells that share the same bivalue pair, 2-color it, and
        // remove both candidates from any outside cell that sees two differently-colored cells)
        // ============================================================

        public bool RemotePairs()
        {
            bool changed = false;
            var byPair = new Dictionary<int, List<(int x, int y)>>();
            foreach (var (x, y, mask) in CollectBivalueCells())
            {
                if (!byPair.TryGetValue(mask, out var list))
                {
                    list = new List<(int, int)>();
                    byPair[mask] = list;
                }
                list.Add((x, y));
            }

            foreach (var (mask, cells) in byPair)
            {
                if (cells.Count < 4) continue; // A closed chain of even length needs at least 4 cells
                var digits = MaskDigits(mask);
                int n = cells.Count;

                var adjacency = BuildAdjacency(cells, (a, b) => Sees(a.x, a.y, b.x, b.y));
                var (colors, components) = ColorGraph(adjacency, n);

                // Both A and B can only be eliminated from an outside cell that sees two "differently
                // colored" cells in the chain (two same-colored cells are only contradictory under one
                // of the two scenarios, so they don't justify an elimination on their own; for two
                // differently-colored cells, whichever value the chain starts from, an outside cell that sees both will always see one cell holding A and one holding B).
                foreach (var comp in components)
                {
                    for (int a = 0; a < comp.Count; a++)
                    {
                        for (int b = a + 1; b < comp.Count; b++)
                        {
                            int i = comp[a], j = comp[b];
                            if (colors[i] == colors[j]) continue;
                            if (adjacency[i].Contains(j)) continue; // A directly adjacent pair is already handled by ordinary pair elimination

                            var causeCells = comp.Select(idx => cells[idx]).ToList();
                            foreach (var (x, y) in CommonPeersOf(new[] { cells[i], cells[j] }))
                                foreach (int d in digits)
                                    if (IsFree(Notes[d, x, y]))
                                        changed |= Eliminate(d, x, y, CellState.RemotePair,
                                            $"{ColLetter(x)}{y}  Remote Pair removes <{d}>", causeCells);
                        }
                    }
                }
            }
            return changed;
        }

        // ============================================================
        // Technique 8: Simple Coloring (formerly CommandButton7 / X-Chain. Implemented here as the
        // full standard Simple Coloring algorithm)
        // ============================================================

        public bool SimpleColoring()
        {
            bool changed = false;
            for (int m = 1; m <= 9; m++)
            {
                var cells = new List<(int x, int y)>();
                for (int x = 1; x <= 9; x++)
                    for (int y = 1; y <= 9; y++)
                        if (IsFree(Notes[m, x, y])) cells.Add((x, y));
                int n = cells.Count;
                if (n < 2) continue;

                // strong link = a relationship where a unit has exactly 2 candidates left
                var adjacency = new List<int>[n];
                for (int i = 0; i < n; i++) adjacency[i] = new List<int>();
                var index = new Dictionary<(int, int), int>();
                for (int i = 0; i < n; i++) index[cells[i]] = i;

                foreach (Unit unit in new[] { Unit.Row, Unit.Col, Unit.Box })
                {
                    for (int idx = 1; idx <= 9; idx++)
                    {
                        var inUnit = CellsOf(unit, idx).Where(c => IsFree(Notes[m, c.x, c.y])).ToList();
                        if (inUnit.Count != 2) continue;
                        int a = index[inUnit[0]];
                        int b = index[inUnit[1]];
                        if (!adjacency[a].Contains(b)) { adjacency[a].Add(b); adjacency[b].Add(a); }
                    }
                }

                var (colors, components) = ColorGraph(adjacency, n);

                foreach (var comp in components)
                {
                    if (comp.Count < 2) continue;

                    // Rule 1: if two same-colored cells see each other, that color is contradictory,
                    // so this digit can be placed in every cell of the opposite color (Color Wrap).
                    int contradictingColor = FindContradictingColor(comp, cells, colors);
                    if (contradictingColor != -1)
                    {
                        foreach (int i in comp)
                        {
                            if (colors[i] == contradictingColor) continue;
                            var (x, y) = cells[i];
                            if (Board[x, y] == 0)
                            {
                                Place(x, y, m, "Simple Coloring (Color Wrap)", Difficulty.Clever);
                                changed = true;
                            }
                        }
                        continue;
                    }

                    // Rule 2: if a cell outside the chain sees both a color-0 cell and a color-1 cell,
                    // this digit can't hold there, so it can be eliminated (Color Trap).
                    var compSet = new HashSet<int>(comp);
                    for (int x = 1; x <= 9; x++)
                        for (int y = 1; y <= 9; y++)
                        {
                            if (!IsFree(Notes[m, x, y])) continue;
                            if (index.TryGetValue((x, y), out int selfIdx) && compSet.Contains(selfIdx)) continue;

                            bool seesColor0 = comp.Any(i => colors[i] == 0 && Sees(x, y, cells[i].x, cells[i].y));
                            bool seesColor1 = comp.Any(i => colors[i] == 1 && Sees(x, y, cells[i].x, cells[i].y));
                            if (seesColor0 && seesColor1)
                                changed |= Eliminate(m, x, y, CellState.Coloring,
                                    $"{ColLetter(x)}{y}  Simple Coloring removes <{m}>");
                        }
                }
            }
            return changed;
        }

        // ============================================================
        // Technique 9: XY-Chain (formerly CommandButton16)
        //
        // Algorithm: link bivalue cells (cells with exactly 2 candidates) to each other whenever
        // they "see each other and share at least one candidate digit", then assume one of the
        // starting cell's two digits is "true" and follow the chain recursively.
        // If the chain reaches 3 or more cells, the end cell sees the start cell, and the digit
        // that becomes newly true at the end matches "the digit the start cell didn't assume
        // first", then that digit can be eliminated from every cell seen by both the start and
        // end cells (because whichever value the start cell actually holds, that digit ends up
        // at either the start or the end).
        // [Additional enhancement] maxLength lets the chain's length (node count) be capped.
        // The auto-solver (SolveAll) calls this while raising the cap from 3 to 10 one at a time,
        // so that a shorter chain is preferred and shown whenever one is enough to solve it.
        // Calling it from the manual XY-Chain button uses the default (unlimited) value.
        // ============================================================

        public bool XyChain(int maxLength = int.MaxValue)
        {
            bool changed = false;
            var bivalue = CollectBivalueCells()
                .Select(c => (c.x, c.y, d1: MaskDigits(c.mask)[0], d2: MaskDigits(c.mask)[1]))
                .ToList();

            int total = bivalue.Count;
            if (total < 3) return false; // Nothing applies with fewer than 3 bivalue cells (corresponds to VBA's i<3)

            // Adjacency: two cells are considered chain-linked if they see each other and share at least one candidate digit
            var adjacency = new List<int>[total];
            for (int i = 0; i < total; i++) adjacency[i] = new List<int>();
            for (int i = 0; i < total; i++)
                for (int j = i + 1; j < total; j++)
                {
                    var a = bivalue[i];
                    var b = bivalue[j];
                    if (!Sees(a.x, a.y, b.x, b.y)) continue;
                    if (a.d1 == b.d1 || a.d1 == b.d2 || a.d2 == b.d1 || a.d2 == b.d2)
                    {
                        adjacency[i].Add(j);
                        adjacency[j].Add(i);
                    }
                }

            for (int start = 0; start < total; start++)
            {
                if (adjacency[start].Count == 0) continue; // No linked cells means no chain is possible

                var startCell = bivalue[start];

                // Explores both ways: assuming candidate digit 1 is "true first", then digit 2
                var visited1 = new bool[total];
                visited1[start] = true;
                changed |= FindXyChain(start, start, startCell.d1, startCell.d2, 1, bivalue, adjacency, visited1, new List<int> { start }, maxLength);

                var visited2 = new bool[total];
                visited2[start] = true;
                changed |= FindXyChain(start, start, startCell.d2, startCell.d1, 1, bivalue, adjacency, visited2, new List<int> { start }, maxLength);
            }
            return changed;
        }

        /// <summary>
        /// A recursive search that walks the chain one step at a time from currentIdx, starting from startIdx.
        /// lockDigit: the digit currently assumed "true" at the current node (updated with each step).
        /// startUnusedDigit: the digit the start cell did NOT assume first. Fixed and unchanged throughout the recursion.
        /// path: the path (sequence of cell indices) from the start cell to the current node. Passed as the "cause cells" if a match is found.
        /// maxLength: the cap on the chain's total node count (including start and end). The search never goes deeper than this.
        /// </summary>
        private bool FindXyChain(int startIdx, int currentIdx, int lockDigit, int startUnusedDigit, int length,
            List<(int x, int y, int d1, int d2)> cells, List<int>[] adjacency, bool[] visited, List<int> path, int maxLength)
        {
            // Once the node cap has already been reached, stop here, since going any further
            // (adding one more cell) would necessarily exceed the cap.
            if (length >= maxLength) return false;

            bool changed = false;
            var start = cells[startIdx];

            foreach (int nextIdx in adjacency[currentIdx])
            {
                if (visited[nextIdx]) continue;
                var next = cells[nextIdx];
                if (next.d1 != lockDigit && next.d2 != lockDigit) continue; // Doesn't hold the locked digit

                // Handoff: if the locked digit is true, then since this is a bivalue cell, the other digit becomes true at the next node
                int nextLock = next.d1 == lockDigit ? next.d2 : next.d1;

                // Goal check: chain length >= 3, the end cell sees the start cell, and
                // the newly-locked digit matches the start cell's "digit not used first"
                // (length < maxLength is already guaranteed at this point, so if this succeeds,
                //  the total node count length+1 is always <= maxLength)
                if (length >= 3 && nextLock == startUnusedDigit && Sees(start.x, start.y, next.x, next.y))
                {
                    var fullChain = new List<(int x, int y)>(path.Count + 1);
                    foreach (int idx in path) fullChain.Add((cells[idx].x, cells[idx].y));
                    fullChain.Add((next.x, next.y));
                    return ApplyXyChainElimination(start.x, start.y, next.x, next.y, nextLock, fullChain);
                    // A match was found, so stop searching the remaining neighbors from this node (corresponds to VBA's Exit Sub)
                }

                visited[nextIdx] = true;
                path.Add(nextIdx);
                changed |= FindXyChain(startIdx, nextIdx, nextLock, startUnusedDigit, length + 1, cells, adjacency, visited, path, maxLength);
                path.RemoveAt(path.Count - 1);
                visited[nextIdx] = false;
            }
            return changed;
        }

        /// <summary>Once an XY-Chain holds, eliminates the target digit from every cell seen by both the start and end cells.
        /// chainCells: every cell on the path from the start to the end (the "cause cells" for this inference).</summary>
        private bool ApplyXyChainElimination(int sx, int sy, int ex, int ey, int digit, IReadOnlyList<(int x, int y)> chainCells)
        {
            bool changed = false;
            foreach (var (x, y) in CommonPeersOf(new[] { (sx, sy), (ex, ey) }))
                if (IsFree(Notes[digit, x, y]))
                    changed |= Eliminate(digit, x, y, CellState.XyChain,
                        $"{ColLetter(x)}{y}  XY-Chain removes <{digit}>", chainCells);
            return changed;
        }

        // ============================================================
        // Technique 9: W-Wing (formerly CommandButton17)
        //
        // Finds a pair of cells (pincers) that share the same bivalue {a,b} and don't see each other
        // (if they did, a Naked Pair would already handle it).
        // For one of the two candidates a,b (the "link" side), if a strong link exists (in any row,
        // column, or box -- meaning that unit has exactly 2 candidate cells left for that digit)
        // whose two endpoints each see one of the two pincers, then the other digit (the "erase"
        // side) can be eliminated from every cell that sees both pincers.
        //
        // VBA wrote nearly the same strong-link search three times, once each for the row, column,
        // and box directions (patterns A/B/C); this port folds that into a single HasWWingLink()
        // using this class's Unit enum / CellsOf() / Sees() framework.
        // ============================================================

        public bool WWing()
        {
            bool changed = false;
            var bivalue = CollectBivalueCells();

            for (int i = 0; i < bivalue.Count; i++)
            {
                for (int j = i + 1; j < bivalue.Count; j++)
                {
                    var c1 = bivalue[i];
                    var c2 = bivalue[j];
                    if (c1.mask != c2.mask) continue;           // Requires the candidate pair to match exactly
                    if (Sees(c1.x, c1.y, c2.x, c2.y)) continue; // Requires the cells to not see each other (if they did, it would be a Naked Pair)

                    var digits = MaskDigits(c1.mask);
                    int d1 = digits[0], d2 = digits[1];

                    // Cells c1,c2 have 2 candidate digits; try both as the strong-link (link) side
                    // (corresponds to VBA's For loopNum = 1 To 2).
                    foreach (var (linkDigit, eraseDigit) in new[] { (d1, d2), (d2, d1) })
                    {
                        if (!HasWWingLink(linkDigit, c1.x, c1.y, c2.x, c2.y, out var link1, out var link2)) continue;

                        // Both pincers + the strong link's 2 cells become the "cause cells" for this elimination.
                        var causeCells = new[] { (c1.x, c1.y), (c2.x, c2.y), link1, link2 };

                        foreach (var (x, y) in CommonPeersOf(new[] { (c1.x, c1.y), (c2.x, c2.y) }))
                            if (IsFree(Notes[eraseDigit, x, y]))
                                changed |= Eliminate(eraseDigit, x, y, CellState.WWing,
                                    $"{ColLetter(x)}{y}  W-Wing removes <{eraseDigit}>", causeCells);
                        // Once this holds for one digit direction, that's enough for this pincer pair
                        // (corresponds to VBA's GoTo NextLoop. No break, since the other digit direction is tried independently too)
                    }
                }
            }
            return changed;
        }

        /// <summary>
        /// For digit, determines whether a strong link exists (in any row, column, or box, with
        /// exactly 2 candidate cells left for that digit) whose two endpoints each see one of
        /// (x1,y1) and (x2,y2) respectively (unifies VBA's patterns A/B/C).
        /// If found, returns the strong link's two cells via link1/link2
        /// (used by the UI to highlight them in pale blue as "cause cells").
        /// </summary>
        private bool HasWWingLink(int digit, int x1, int y1, int x2, int y2,
            out (int x, int y) link1, out (int x, int y) link2)
        {
            link1 = default;
            link2 = default;

            foreach (Unit unit in new[] { Unit.Row, Unit.Col, Unit.Box })
            {
                for (int idx = 1; idx <= 9; idx++)
                {
                    var cells = CellsOf(unit, idx)
                        .Where(c => Notes[digit, c.x, c.y] == CellState.Open)
                        .ToList();
                    if (cells.Count != 2) continue; // Not a strong link (exactly 2 cells) -- out of scope

                    var (rx1, ry1) = cells[0];
                    var (rx2, ry2) = cells[1];

                    bool matchA = Sees(rx1, ry1, x1, y1) && Sees(rx2, ry2, x2, y2);
                    bool matchB = Sees(rx1, ry1, x2, y2) && Sees(rx2, ry2, x1, y1);
                    if (matchA || matchB)
                    {
                        link1 = (rx1, ry1);
                        link2 = (rx2, ry2);
                        return true;
                    }
                }
            }
            return false;
        }

        // ---- Graph helpers shared by Simple Coloring / Remote Pairs ----

        private static List<int>[] BuildAdjacency<T>(List<T> items, Func<T, T, bool> areLinked)
        {
            int n = items.Count;
            var adjacency = new List<int>[n];
            for (int i = 0; i < n; i++) adjacency[i] = new List<int>();
            for (int i = 0; i < n; i++)
                for (int j = i + 1; j < n; j++)
                    if (areLinked(items[i], items[j]))
                    {
                        adjacency[i].Add(j);
                        adjacency[j].Add(i);
                    }
            return adjacency;
        }

        /// <summary>
        /// Splits the graph into connected components and alternately 2-colors within each (coloring it as a chain).
        /// Isolated points (no adjacency) are not included in any component.
        /// The returned colors array is shared across all nodes, but the colors only have meaning
        /// within the same component -- comparing color numbers across different components is
        /// meaningless, so callers must not conflate them.
        private static (int[] colors, List<List<int>> components) ColorGraph(List<int>[] adjacency, int n)
        {
            var colors = new int[n];
            for (int i = 0; i < n; i++) colors[i] = -1;
            var components = new List<List<int>>();

            for (int start = 0; start < n; start++)
            {
                if (colors[start] != -1 || adjacency[start].Count == 0) continue;

                var comp = new List<int> { start };
                colors[start] = 0;
                var queue = new Queue<int>();
                queue.Enqueue(start);
                while (queue.Count > 0)
                {
                    int cur = queue.Dequeue();
                    foreach (int next in adjacency[cur])
                    {
                        if (colors[next] != -1) continue;
                        colors[next] = 1 - colors[cur];
                        queue.Enqueue(next);
                        comp.Add(next);
                    }
                }
                components.Add(comp);
            }
            return (colors, components);
        }

        private static int FindContradictingColor(List<int> comp, List<(int x, int y)> cells, int[] colors)
        {
            bool bad0 = false, bad1 = false;
            for (int a = 0; a < comp.Count; a++)
                for (int b = a + 1; b < comp.Count; b++)
                {
                    int i = comp[a], j = comp[b];
                    if (colors[i] != colors[j]) continue;
                    var (x1, y1) = cells[i];
                    var (x2, y2) = cells[j];
                    if (!Sees(x1, y1, x2, y2)) continue;
                    if (colors[i] == 0) bad0 = true; else bad1 = true;
                }
            if (bad0 && !bad1) return 0;
            if (bad1 && !bad0) return 1;
            return -1; // Both contradictory, or neither -- undecidable
        }

        // ============================================================
        // ALS-XZ
        // ============================================================

        /// <summary>
        /// The data for one detected ALS (Almost Locked Set) candidate.
        /// - House/HouseIndex: which house (row/col/box) and index it was found in
        /// - Size: the number of cells making up the ALS (= q)
        /// - Mask: the bitmask of the whole ALS's candidate digits (bit d = digit d; the number of set bits is Size+1)
        /// - Cells: the coordinates of the cells making up the ALS
        /// - CellMasks: the candidate-digit bitmask for each cell, matching up with Cells
        /// </summary>
        private class AlsCandidate
        {
            public Unit House;
            public int HouseIndex;
            public int Size;
            public int Mask;
            public List<(int x, int y)> Cells;
            public int[] CellMasks;

            // Cell-set intersection tests (AlsSharesCell/FindRccDigits) are called millions of times
            // during searches such as ALS-XY-Chain, so instead of rebuilding a HashSet every time,
            // one is built once here and cached (for O(1) intersection tests).
            public HashSet<(int x, int y)> CellSet;

            // The "list of cells holding digit d" is also called frequently, so instead of rebuilding
            // the list every time (CellsWithDigit), it is sorted by digit and cached once here
            // at construction time.
            public Dictionary<int, List<(int x, int y)>> CellsByDigit;

            /// <summary>Must always be called after setting Cells/CellMasks; builds CellSet/CellsByDigit.</summary>
            public void BuildCache()
            {
                CellSet = new HashSet<(int x, int y)>(Cells);
                CellsByDigit = new Dictionary<int, List<(int x, int y)>>();
                for (int i = 0; i < Cells.Count; i++)
                {
                    foreach (int d in MaskDigits(CellMasks[i]))
                    {
                        if (!CellsByDigit.TryGetValue(d, out var list))
                        {
                            list = new List<(int x, int y)>();
                            CellsByDigit[d] = list;
                        }
                        list.Add(Cells[i]);
                    }
                }
            }
        }

        /// <summary>
        /// Given the candidate digits (as a bitmask) of 9 cells, finds every ALS contained within them.
        /// Algorithm:
        /// - Collect only the m unplaced cells (2 or more candidates)
        /// - For every combination of q (1&lt;=q&lt;m) cells chosen from the m, let Ans be the OR of the chosen cells' candidate bitmasks
        /// - If the number of set bits in Ans is q+1, that combination is an ALS
        /// </summary>
        private static IEnumerable<(List<(int x, int y)> cells, int mask)> FindAlsInGroup(
            IReadOnlyList<(int x, int y)> group, Func<int, int, int> candidateMask, Func<int, int, bool> isUnsolved)
        {
            var open = group.Where(c => isUnsolved(c.x, c.y)).ToList();
            int m = open.Count;
            for (int q = 1; q < m; q++)
            {
                foreach (var comboIdx in Combinations(m, q))
                {
                    var chosen = comboIdx.Select(i => open[i]).ToList();
                    int mask = 0;
                    foreach (var c in chosen) mask |= candidateMask(c.x, c.y);
                    if (PopCount(mask) == q + 1)
                        yield return (chosen, mask);
                }
            }
        }

        /// <summary>Scans the whole board (every row/column/box), and returns every ALS found, with duplicates removed.</summary>
        private List<AlsCandidate> CollectAls()
        {
            var found = new List<AlsCandidate>();
            foreach (Unit unit in new[] { Unit.Row, Unit.Col, Unit.Box })
            {
                for (int idx = 1; idx <= 9; idx++)
                {
                    var group = CellsOf(unit, idx).ToList();
                    foreach (var (cells, mask) in FindAlsInGroup(group, CandidateMask, (x, y) => Board[x, y] == 0))
                    {
                        var als = new AlsCandidate
                        {
                            House = unit,
                            HouseIndex = idx,
                            Size = cells.Count,
                            Mask = mask,
                            Cells = cells,
                            CellMasks = cells.Select(c => CandidateMask(c.x, c.y)).ToArray()
                        };
                        als.BuildCache();
                        found.Add(als);
                    }
                }
            }

            // Deduplication: an ALS with the same "number of candidate digits, candidate bitmask,
            // constituent cells, and each cell's candidates" is automatically identical whenever
            // the set of constituent cells is the same (as long as the board state hasn't changed),
            // so using just the cell set as the key is enough. Rather than building a string every
            // time, a sorted sequence of cells is used as a tuple key (relying on HashSet<T>'s
            // standard structural equality).
            var seen = new HashSet<string>();
            var result = new List<AlsCandidate>();
            foreach (var als in found)
            {
                var sortedCells = als.Cells.OrderBy(c => c.x).ThenBy(c => c.y);
                string key = string.Join(",", sortedCells.Select(c => $"{c.x}-{c.y}"));
                if (seen.Add(key)) result.Add(als);
            }
            return result;
        }

        /// <summary>Whether the given group of cells all fit within a single house (row, column, or box).</summary>
        private static bool AllInOneHouse(IReadOnlyList<(int x, int y)> cells)
        {
            int n = cells.Count;
            if (n == 0) return false;
            if (n == 1) return true;

            var first = cells[0];
            bool sameRow = true, sameCol = true, sameBox = true;
            int firstBox = BoxIndex(first.x, first.y);
            for (int i = 1; i < n; i++)
            {
                var c = cells[i];
                if (sameRow && c.y != first.y) sameRow = false;
                if (sameCol && c.x != first.x) sameCol = false;
                if (sameBox && BoxIndex(c.x, c.y) != firstBox) sameBox = false;
                if (!sameRow && !sameCol && !sameBox) return false; // Exit early once all 3 possibilities are confirmed false
            }
            return true;
        }

        /// <summary>A shared empty list reused when nothing is found in the cache (to cut down on allocations).</summary>
        private static readonly List<int> EmptyIntList = new List<int>();
        private static readonly List<(int x, int y)> EmptyCellList = new List<(int x, int y)>();

        /// <summary>Extracts, from within an ALS, only the cells that have the given digit as a candidate
        /// (simply returns the CellsByDigit already built by AlsCandidate.BuildCache(), so this is O(1)).</summary>
        private static List<(int x, int y)> CellsWithDigit(AlsCandidate als, int digit)
        {
            return als.CellsByDigit.TryGetValue(digit, out var list) ? list : EmptyCellList;
        }

        /// <summary>Finds the cells seen in common by all the given cells (excluding themselves).</summary>
        private static HashSet<(int x, int y)> CommonPeersOf(IReadOnlyList<(int x, int y)> cells)
        {
            HashSet<(int x, int y)> result = null;
            foreach (var c in cells)
            {
                var peers = new HashSet<(int x, int y)>(Peers(c.x, c.y));
                result = result == null ? peers : new HashSet<(int x, int y)>(result.Where(p => peers.Contains(p)));
            }
            return result ?? new HashSet<(int x, int y)>();
        }

        /// <summary>
        /// Finds every digit that forms an RCC (Restricted Common Candidate) between two ALSes (A, B;
        /// assumed not to share any cells). A digit is an RCC if, among the shared candidates, every
        /// cell in A union B holding that digit fits within a single house (shared logic used by both
        /// ALS-XZ step 9 and ALS-XY-Wing step 11).
        /// </summary>
        private static List<int> FindRccDigits(AlsCandidate A, AlsCandidate B)
        {
            var result = new List<int>();
            if (A.CellSet.Overlaps(B.CellSet)) return result; // Excluded if the cells overlap

            int common = A.Mask & B.Mask;
            foreach (int z in MaskDigits(common))
            {
                var zCells = CellsWithDigit(A, z).Concat(CellsWithDigit(B, z)).ToList();
                if (AllInOneHouse(zCells)) result.Add(z);
            }
            return result;
        }

        /// <summary>
        /// The ALS-XZ technique.
        /// - Find every ALS on the board (s of them), and choose 2 of them (A, B)
        /// - Check further if A and B share 2 or more candidate digits
        /// - For some digit Z among the shared candidates, if every cell in A union B holding Z fits within a single house, an RCC holds
        /// - Once an RCC holds, for a shared candidate X different from Z, if there is a cell seen in
        ///   common by every cell in A union B holding X (excluding A and B themselves), X can be eliminated from that cell
        /// </summary>
        public bool AlsXz()
        {
            var alsList = CollectAls();
            bool changed = false;
            int s = alsList.Count;

            for (int i = 0; i < s; i++)
            {
                var A = alsList[i];
                for (int j = i + 1; j < s; j++)
                {
                    var B = alsList[j];

                    int common = A.Mask & B.Mask;
                    if (PopCount(common) < 2) continue; // Needs at least 2 shared candidates: one for Z, one for X

                    var rccDigits = FindRccDigits(A, B);
                    if (rccDigits.Count == 0) continue;

                    var commonDigits = MaskDigits(common);

                    foreach (int z in rccDigits)
                    {
                        // RCC holds. Try eliminating for each shared candidate X different from Z
                        foreach (int x in commonDigits)
                        {
                            if (x == z) continue;

                            var xCells = CellsWithDigit(A, x).Concat(CellsWithDigit(B, x)).ToList();
                            if (xCells.Count == 0) continue;

                            // Find the cells seen in common by all of xCells (A and B never "see" themselves, so they are automatically excluded)
                            var commonPeers = CommonPeersOf(xCells);
                            if (commonPeers.Count == 0) continue;

                            var causeCells = A.Cells.Concat(B.Cells).ToList();
                            foreach (var (tx, ty) in commonPeers)
                            {
                                if (Board[tx, ty] != 0) continue;
                                if (Notes[x, tx, ty] != CellState.Open) continue;
                                changed |= Eliminate(x, tx, ty, CellState.AlsXz,
                                    $"{ColLetter(tx)}{ty}  ALS-XZ (RCC<{z}>, ALS {UnitName(A.House)}{A.HouseIndex}+{UnitName(B.House)}{B.HouseIndex}) removes <{x}>",
                                    causeCells);
                            }
                        }
                    }
                }
            }
            return changed;
        }

        // ============================================================
        // Grouped X-Chain / Grouped X-Cycle
        //
        // An implementation based on the user-supplied definition. For a single candidate digit,
        //
        // - Strong link: a relationship where, within a house, the "nodes" for that digit are limited to exactly two
        // - Node: a set of 1-3 candidate cells lined up in a single column or row within one box
        //   (for row/column houses, the segment within each box that the house spans automatically becomes one node.
        //    for box houses, among the box's 3 rows and 3 columns, find two disjoint lines that together
        //    cover all the candidate cells exactly, and if found, those two lines become the two nodes.
        //    if none is found, that box is treated as having no strong link)
        // - Weak link: a relationship where some cell of one node and some cell of the other node
        //   belong to (see) the same house. When alternating between strong links A and B, the house
        //   the weak link belongs to must differ from both A's and B's houses
        //
        // Starting from a strong link, the chain is extended alternately as strong link -> weak link
        // -> strong link -> ..., and the digit can be removed from cells seen simultaneously by the
        // nodes at both ends of the chain (the intersection of each end's "commonly seen cells") (a normal chain).
        // If the chain loops back to the starting node, it becomes a Grouped X-Cycle, and in each
        // house that one of the loop's weak links belongs to, the digit can be removed from every
        // other cell not part of the loop (nodes).
        //
        // As soon as any elimination succeeds, the search stops with no further exploration
        // (per the user's instruction -- unlike other techniques, this doesn't "apply every one found").
        // From the auto-solver, this is called while raising the maximum node count in the chain
        // from 3 up to 10 one at a time (per the user's instruction).
        // ============================================================

        /// <summary>A Grouped X-Chain node = for a single digit, the set of 1-3 candidate cells lined up
        /// vertically or horizontally within one box. Nodes with the same cell set (+ digit) are considered identical.</summary>
        private class GNode : IEquatable<GNode>
        {
            public List<(int x, int y)> Cells; // sorted in ascending order
            public int Digit;
            public HashSet<(int x, int y)> CellSet;

            public bool Equals(GNode other) => other != null && Digit == other.Digit && CellSet.SetEquals(other.CellSet);
            public override bool Equals(object obj) => obj is GNode g && Equals(g);
            public override int GetHashCode()
            {
                int h = Digit * 97;
                foreach (var c in Cells) h ^= c.x * 31 + c.y; // Combined via XOR so the order of cells doesn't affect the result
                return h;
            }
            public override string ToString() =>
                Cells.Count == 1
                    ? $"{ColLetter(Cells[0].x)}{Cells[0].y}"
                    : $"[{string.Join("", Cells.Select(c => $"{ColLetter(c.x)}{c.y}"))}]";
        }

        private static GNode MakeGNode(List<(int x, int y)> cells, int digit)
        {
            var sorted = cells.OrderBy(c => c.x).ThenBy(c => c.y).ToList();
            return new GNode { Cells = sorted, Digit = digit, CellSet = new HashSet<(int, int)>(sorted) };
        }

        private class GStrongLink
        {
            public GNode A, B;
            public Unit HouseUnit;
            public int HouseIndex;
        }

        /// <summary>Finds the list of nodes (1-3 cell line-shaped sets) for the given house and digit.</summary>
        private List<GNode> FindGroupedNodes(Unit unit, int idx, int digit)
        {
            var cells = CellsOf(unit, idx).Where(c => IsFree(Notes[digit, c.x, c.y])).ToList();
            if (cells.Count == 0) return new List<GNode>();

            if (unit != Unit.Box)
            {
                // Row/column house: splitting by box directly gives the cells lined up along this house's direction
                // (cells within the same box automatically form a line: the same row for a row house, the same column for a column house)
                return cells.GroupBy(c => BoxIndex(c.x, c.y))
                            .Select(g => MakeGNode(g.ToList(), digit))
                            .ToList();
            }

            // Box house: among the box's 3 rows and 3 columns, list only the rows/columns that have
            // candidate cells as "line candidates", then look for a pair of two that covers all candidate cells exactly, with no overlap.
            var rowLines = cells.Select(c => c.y).Distinct()
                .Select(y => cells.Where(c => c.y == y).ToList()).ToList();
            var colLines = cells.Select(c => c.x).Distinct()
                .Select(x => cells.Where(c => c.x == x).ToList()).ToList();
            var lineCandidates = rowLines.Concat(colLines).ToList();

            for (int i = 0; i < lineCandidates.Count; i++)
                for (int j = i + 1; j < lineCandidates.Count; j++)
                {
                    var l1 = lineCandidates[i];
                    var l2 = lineCandidates[j];
                    if (l1.Any(c => l2.Contains(c))) continue; // The intersection cell must not be a candidate
                    if (l1.Count + l2.Count != cells.Count) continue; // Check whether it covers exactly, with nothing missing or extra
                    return new List<GNode> { MakeGNode(l1, digit), MakeGNode(l2, digit) };
                }
            return new List<GNode>(); // If it can't be split into 2 nodes, this box has no strong link
        }

        /// <summary>Collects all grouped strong links for the given digit from across the entire board.</summary>
        private List<GStrongLink> CollectGroupedStrongLinks(int digit)
        {
            var links = new List<GStrongLink>();
            foreach (Unit unit in new[] { Unit.Row, Unit.Col, Unit.Box })
                for (int idx = 1; idx <= 9; idx++)
                {
                    var nodes = FindGroupedNodes(unit, idx, digit);
                    if (nodes.Count == 2)
                        links.Add(new GStrongLink { A = nodes[0], B = nodes[1], HouseUnit = unit, HouseIndex = idx });
                }
            return links;
        }

        /// <summary>Enumerates every house (row/col/box) that fully contains the node.
        /// A single-cell node can match all three. A multi-cell node (a line-shaped set) only
        /// matches the row or column its line runs along, plus the containing box.</summary>
        private static IEnumerable<(Unit unit, int idx)> HousesContainingNode(GNode node)
        {
            var first = node.Cells[0];
            if (node.Cells.All(c => c.y == first.y)) yield return (Unit.Row, first.y);
            if (node.Cells.All(c => c.x == first.x)) yield return (Unit.Col, first.x);
            int box = BoxIndex(first.x, first.y);
            if (node.Cells.All(c => BoxIndex(c.x, c.y) == box)) yield return (Unit.Box, box);
        }

        /// <summary>Checks whether a weak link exists between two nodes in a house different from
        /// either of the two given houses (the houses of the immediately preceding/following strong link), and returns that house if so.
        ///
        /// [Important] A weak link requires more than just "some cell of each node sees some cell of the other."
        /// A multi-cell node (e.g. [D5,E5]) only carries the undetermined information that "this digit
        /// goes in either D or E," so if only part of the node's cells belong to house H
        /// (e.g. only D5 belongs to column 4, not E5), the conclusion for house H ("this node OR
        /// the other node must go in H") does not hold. That conclusion for house H is only valid
        /// when all of the node's cells are contained in house H. For this reason, the houses that
        /// can be treated as a weak link are restricted to "houses that fully contain each of the two nodes"
        /// (for a single-cell node, the row/column/box it belongs to automatically "fully contains" it).
        /// </summary>
        private static (Unit unit, int idx)? FindWeakLinkHouse(GNode a, GNode b,
            (Unit unit, int idx) exclude1, (Unit unit, int idx) exclude2)
        {
            var housesA = HousesContainingNode(a).ToList();
            var housesB = new HashSet<(Unit unit, int idx)>(HousesContainingNode(b));
            foreach (var house in housesA)
            {
                if (house.unit == exclude1.unit && house.idx == exclude1.idx) continue;
                if (house.unit == exclude2.unit && house.idx == exclude2.idx) continue;
                if (housesB.Contains(house)) return house;
            }
            return null;
        }

        /// <summary>
        /// The Grouped X-Chain technique. maxNodes caps the number of nodes in the chain (default unlimited).
        /// Stops immediately once the first elimination found is applied.
        /// </summary>
        public bool GroupedXChain(int maxNodes = int.MaxValue)
        {
            for (int digit = 1; digit <= 9; digit++)
            {
                var strongLinks = CollectGroupedStrongLinks(digit);
                if (strongLinks.Count == 0) continue;

                foreach (var link in strongLinks)
                {
                    foreach (var (start, next) in new[] { (link.A, link.B), (link.B, link.A) })
                    {
                        var path = new List<GNode> { start, next };
                        var usedCells = new HashSet<(int x, int y)>(start.Cells);
                        usedCells.UnionWith(next.Cells);
                        var weakHouses = new List<(Unit unit, int idx)>();
                        var firstHouse = (link.HouseUnit, link.HouseIndex);
                        if (ExploreGroupedChain(digit, path, usedCells, weakHouses, firstHouse, firstHouse,
                                strongLinks, Math.Max(2, maxNodes)))
                            return true; // Stop the whole search as soon as the first elimination is found (per the user's instruction)
                    }
                }
            }
            return false;
        }

        /// <summary>
        /// A recursive search that extends the chain from the node at the end of path, alternating
        /// weak link -> strong link. lastStrongHouse: the house of the immediately preceding
        /// strong link (the next weak link must differ from this). firstStrongHouse: the house
        /// of the chain's first strong link (when looping back to the start as a cycle, that weak
        /// link must also differ from this). usedCells: the accumulated cells of every node used
        /// so far in the chain.
        ///
        /// [Important] Forbidding node reuse cannot rely only on whether the nodes themselves match
        /// (the same cell set). E.g., if a single-cell node {E5} is used on the path and later a
        /// 2-cell node {D5,E5} (which includes E5) from a different box house is connected as a
        /// "different node", the truth value of cell E5 ends up being handled twice, separately, in
        /// the chain, breaking the logic -- so this uses the same cell-level check as ALS-XY-Chain:
        /// don't reuse a node overlapping any cell already used on the path.
        private bool ExploreGroupedChain(int digit, List<GNode> path, HashSet<(int x, int y)> usedCells,
            List<(Unit unit, int idx)> weakHouses, (Unit unit, int idx) lastStrongHouse,
            (Unit unit, int idx) firstStrongHouse, List<GStrongLink> strongLinks, int maxNodes)
        {
            var current = path[path.Count - 1];
            var start = path[0];

            // 1) Cycle check: with 2 or more strong links already used, can we get back to the start node via a weak link?
            if (path.Count >= 4)
            {
                var cycleHouse = FindWeakLinkHouse(current, start, lastStrongHouse, firstStrongHouse);
                if (cycleHouse.HasValue)
                {
                    weakHouses.Add(cycleHouse.Value);
                    bool cycleFound = TryApplyGroupedXCycle(digit, path, weakHouses);
                    weakHouses.RemoveAt(weakHouses.Count - 1);
                    if (cycleFound) return true;
                }
            }

            if (path.Count >= maxNodes) return false; // Do not extend the chain any further

            // 2) Normal chain: look for whether we can connect to another strong link via a weak link
            foreach (var link in strongLinks)
            {
                foreach (var (nearEnd, farEnd) in new[] { (link.A, link.B), (link.B, link.A) })
                {
                    // Don't use a node that overlaps even one cell already used on the path (returning to the start is already handled above as a cycle)
                    if (nearEnd.CellSet.Overlaps(usedCells) || farEnd.CellSet.Overlaps(usedCells)) continue;

                    var linkHouse = (link.HouseUnit, link.HouseIndex);
                    var weakHouse = FindWeakLinkHouse(current, nearEnd, lastStrongHouse, linkHouse);
                    if (!weakHouse.HasValue) continue;

                    path.Add(nearEnd);
                    path.Add(farEnd);
                    usedCells.UnionWith(nearEnd.Cells);
                    usedCells.UnionWith(farEnd.Cells);
                    weakHouses.Add(weakHouse.Value);

                    bool found = TryApplyGroupedChainElimination(digit, start, farEnd, path);
                    if (!found)
                        found = ExploreGroupedChain(digit, path, usedCells, weakHouses, linkHouse, firstStrongHouse,
                            strongLinks, maxNodes);

                    weakHouses.RemoveAt(weakHouses.Count - 1);
                    usedCells.ExceptWith(farEnd.Cells);
                    usedCells.ExceptWith(nearEnd.Cells);
                    path.RemoveAt(path.Count - 1);
                    path.RemoveAt(path.Count - 1);

                    if (found) return true;
                }
            }
            return false;
        }

        /// <summary>Attempts elimination for a normal chain (start and end are different nodes).
        /// Removes the digit from cells seen simultaneously by both end nodes (the intersection
        /// of their respective CommonPeersOf results), excluding cells that make up the chain itself.</summary>
        private bool TryApplyGroupedChainElimination(int digit, GNode start, GNode end, List<GNode> path)
        {
            var peersOfStart = CommonPeersOf(start.Cells);
            if (peersOfStart.Count == 0) return false;
            var peersOfEnd = CommonPeersOf(end.Cells);
            if (peersOfEnd.Count == 0) return false;

            var chainCells = new HashSet<(int x, int y)>();
            foreach (var n in path) chainCells.UnionWith(n.Cells);

            var causeCells = path.SelectMany(n => n.Cells).ToList();
            string desc = string.Join("-", path.Select(n => n.ToString()));

            bool changed = false;
            foreach (var (tx, ty) in peersOfStart)
            {
                if (!peersOfEnd.Contains((tx, ty))) continue;
                if (chainCells.Contains((tx, ty))) continue; // Don't target cells that are part of the chain itself
                if (Board[tx, ty] != 0) continue;
                if (Notes[digit, tx, ty] != CellState.Open) continue;
                changed |= Eliminate(digit, tx, ty, CellState.GroupedXChain,
                    $"{ColLetter(tx)}{ty}  Grouped X-Chain ({desc}) removes <{digit}>", causeCells);
            }
            return changed;
        }

        /// <summary>Attempts elimination for a Grouped X-Cycle (loop). In each house that one of the
        /// loop's weak links belongs to, removes the digit from every other cell not part of the loop (nodes).</summary>
        private bool TryApplyGroupedXCycle(int digit, List<GNode> path, List<(Unit unit, int idx)> weakHouses)
        {
            var cycleCells = new HashSet<(int x, int y)>();
            foreach (var n in path) cycleCells.UnionWith(n.Cells);

            var causeCells = path.SelectMany(n => n.Cells).ToList();
            string desc = string.Join("-", path.Select(n => n.ToString())) + "-(loop)";

            bool changed = false;
            foreach (var house in weakHouses)
            {
                foreach (var (x, y) in CellsOf(house.unit, house.idx))
                {
                    if (cycleCells.Contains((x, y))) continue;
                    if (Board[x, y] != 0) continue;
                    if (Notes[digit, x, y] != CellState.Open) continue;
                    changed |= Eliminate(digit, x, y, CellState.GroupedXChain,
                        $"{ColLetter(x)}{y}  Grouped X-Cycle ({desc}) removes <{digit}>", causeCells);
                }
            }
            return changed;
        }

        // ============================================================
        // ALS-XY-Wing
        // ============================================================

        /// <summary>
        /// The ALS-XY-Wing technique.
        /// - Find every ALS on the board (s of them), and choose any 3: D (pivot), E, F
        /// - An RCC must exist between D and E, and between D and F, and the two RCC digits (x1, x2) must differ
        /// - If E and F share a common candidate W different from x1, x2, and there is a cell seen in
        ///   common by every cell in E union F holding W (excluding D, E, F themselves), W can be eliminated from that cell
        ///
        /// Since the RCC check (FindRccDigits) is reused across every ALS pair combination, the
        /// (i,j) pair results are cached first before searching triples (naively recomputing the
        /// RCC inside a triple-nested loop every time would cost O(s^3) times the RCC search, which is very slow).
        /// </summary>
        public bool AlsXyWing()
        {
            var alsList = CollectAls();
            int s = alsList.Count;
            bool changed = false;

            // Cache the RCC digit list for each (i,j) pair (i<j) (symmetric, so only i<j is computed)
            var rccCache = new Dictionary<(int i, int j), List<int>>();
            for (int i = 0; i < s; i++)
                for (int j = i + 1; j < s; j++)
                {
                    var digits = FindRccDigits(alsList[i], alsList[j]);
                    if (digits.Count > 0) rccCache[(i, j)] = digits;
                }

            List<int> GetRcc(int i, int j) =>
                rccCache.TryGetValue(i < j ? (i, j) : (j, i), out var d) ? d : EmptyIntList;

            for (int di = 0; di < s; di++)
            {
                var D = alsList[di];
                for (int ei = 0; ei < s; ei++)
                {
                    if (ei == di) continue;
                    var rccDE = GetRcc(di, ei);
                    if (rccDE.Count == 0) continue;
                    var E = alsList[ei];

                    for (int fi = ei + 1; fi < s; fi++)
                    {
                        if (fi == di) continue;
                        var rccDF = GetRcc(di, fi);
                        if (rccDF.Count == 0) continue;
                        var F = alsList[fi];

                        // E and F must also be disjoint (share no cells)
                        if (E.CellSet.Overlaps(F.CellSet)) continue;

                        // Step 11: look for combinations where the RCC digit between D-E (x1) differs from the RCC digit between D-F (x2)
                        foreach (int x1 in rccDE)
                        {
                            foreach (int x2 in rccDF)
                            {
                                if (x1 == x2) continue;

                                // Step 12: look for a shared candidate W of E,F that differs from x1,x2
                                int commonEF = E.Mask & F.Mask;
                                foreach (int w in MaskDigits(commonEF))
                                {
                                    if (w == x1 || w == x2) continue;

                                    var wCells = CellsWithDigit(E, w).Concat(CellsWithDigit(F, w)).ToList();
                                    if (wCells.Count == 0) continue;

                                    var commonPeers = CommonPeersOf(wCells);
                                    if (commonPeers.Count == 0) continue;

                                    var causeCells = D.Cells.Concat(E.Cells).Concat(F.Cells).ToList();
                                    foreach (var (tx, ty) in commonPeers)
                                    {
                                        if (Board[tx, ty] != 0) continue;
                                        if (Notes[w, tx, ty] != CellState.Open) continue;
                                        changed |= Eliminate(w, tx, ty, CellState.AlsXyWing,
                                            $"{ColLetter(tx)}{ty}  ALS-XY-Wing (D={UnitName(D.House)}{D.HouseIndex}, RCC<{x1}>/<{x2}>) removes <{w}>",
                                            causeCells);
                                    }
                                }
                            }
                        }
                    }
                }
            }
            return changed;
        }

        // ALS-XY-Chain
        // ALS-XY-Chain
        //
        // An implementation based on the definition in the request document (ALSRequest.txt). ALSes
        // are chained together via RCC (Restricted Common Candidate; determined by the same
        // FindRccDigits() used by ALS-XZ/ALS-XY-Wing), and if the two ALSes at the ends of the
        // chain share a common candidate Z different from every RCC digit used in the chain, Z is
        // eliminated from every cell seen in common by every cell holding Z in either end ALS
        // (excluding the cells of the ALSes making up the chain itself). Enumerating/deduplicating
        // ALSes (CollectAls) and determining RCCs (FindRccDigits) reuse the existing ALS-XZ/ALS-XY-Wing
        // implementations as-is, per the request document.
        /// <summary>
        /// The ALS-XY-Chain technique. Steps, per the request document:
        /// 1) Find every ALS on the board (CollectAls)
        /// 2) Extend a chain ALS(a)-ALS(b)-ALS(c)-... using an RCC digit different from the previous
        ///    one each time (only unvisited ALSes; never link using the same digit as the previous RCC)
        /// 3-4) Every time the chain reaches 3 or more ALSes (= 2 or more RCCs), check whether the
        ///    start ALS (a) and the current end ALS share a common candidate Z different from every
        ///    RCC digit used in the chain. If found, apply step 5); if not, keep extending the chain and searching (stop once nothing more is found).
        /// 5) Eliminate Z from every cell seen in common by every cell holding Z in either end ALS
        ///    (excluding the cells of the ALSes making up the chain itself).
        /// maxAlsCount: caps the number of ALSes in the chain (default unlimited). SolveAll() calls
        /// this while raising the cap starting from short chains, the same way it does for XyChain's
        /// maxLength (to avoid a combinatorial explosion while preferring to find short, readable chains first).
        /// </summary>
        public bool AlsXyChain(int maxAlsCount = int.MaxValue)
        {
            var alsList = CollectAls();
            int s = alsList.Count;
            if (s < 3) return false; // Nothing applies without at least 3 ALSes (a,b,c)

            // Cache the RCC digit list for each (i,j) pair (reused the same way as in ALS-XY-Wing)
            var rccCache = new Dictionary<(int i, int j), List<int>>();
            for (int i = 0; i < s; i++)
                for (int j = i + 1; j < s; j++)
                {
                    var digits = FindRccDigits(alsList[i], alsList[j]);
                    if (digits.Count > 0) rccCache[(i, j)] = digits;
                }

            List<int> GetRcc(int i, int j) =>
                rccCache.TryGetValue(i < j ? (i, j) : (j, i), out var d) ? d : EmptyIntList;

            bool changed = false;
            for (int start = 0; start < s; start++)
            {
                var visited = new bool[s];
                visited[start] = true;
                var usedCells = new HashSet<(int x, int y)>(alsList[start].Cells);
                changed |= ExtendAlsChain(start, start, -1, new List<int>(), new List<int> { start },
                    alsList, GetRcc, visited, Math.Max(3, maxAlsCount), usedCells);
            }
            return changed;
        }

        /// <summary>
        /// A recursive search that extends the chain one step at a time from currentIdx, starting from startIdx.
        /// lastDigit: the RCC digit used on the immediately preceding edge (-1 is a sentinel meaning "no edge used yet (the start)").
        /// usedDigits: every RCC digit used so far in the chain (used directly for the "different" check in steps 3-4).
        /// path: the sequence of ALS indices making up the chain from the start to the current node.
        /// usedCells: the accumulated cells of every ALS in path. Checking overlap against this in
        /// O(1) consolidates what used to require calling AlsSharesCell() once per ALS in path into
        /// a single HashSet.Overlaps() call (this was the most frequently called check in the
        /// ALS-XY-Chain search, making it the single biggest speedup here).
        /// Even when Z is found by the step-3 check, the search is not stopped (matching the same
        /// "apply every one found" policy as ALS-XZ/ALS-XY-Wing) -- other ways to extend the chain keep being tried.
        /// </summary>
        private bool ExtendAlsChain(int startIdx, int currentIdx, int lastDigit, List<int> usedDigits, List<int> path,
            List<AlsCandidate> alsList, Func<int, int, List<int>> getRcc, bool[] visited, int maxAlsCount,
            HashSet<(int x, int y)> usedCells)
        {
            if (path.Count >= maxAlsCount) return false; // Do not extend the chain any further

            bool changed = false;
            var A = alsList[startIdx];

            for (int nextIdx = 0; nextIdx < alsList.Count; nextIdx++)
            {
                if (visited[nextIdx]) continue;
                var candidate = alsList[nextIdx];

                // Guarantees the RCC precondition (sharing no cells) against the whole chain, not
                // just the immediately preceding ALS (excluded if the candidate ALS shares a cell with any ALS already on the chain)
                if (candidate.CellSet.Overlaps(usedCells)) continue;

                var rccDigits = getRcc(currentIdx, nextIdx);
                if (rccDigits.Count == 0) continue;

                foreach (int rcc in rccDigits)
                {
                    if (rcc == lastDigit) continue; // Can't chain using the same digit as the immediately preceding RCC (steps 2, 4)

                    path.Add(nextIdx);
                    visited[nextIdx] = true;
                    usedDigits.Add(rcc);
                    usedCells.UnionWith(candidate.CellSet);

                    if (path.Count >= 3) // Steps 3-4: check every time the chain reaches 3 or more ALSes (= 2 or more RCCs)
                    {
                        int commonMask = A.Mask & candidate.Mask;
                        foreach (int z in MaskDigits(commonMask))
                        {
                            if (usedDigits.Contains(z)) continue; // Must differ from every RCC digit used in the chain
                            changed |= TryApplyAlsXyChainElimination(A, candidate, z, alsList, path, usedDigits);
                        }
                    }

                    // Step 4: regardless of whether one was found, keep exploring the other possibilities too
                    changed |= ExtendAlsChain(startIdx, nextIdx, rcc, usedDigits, path, alsList, getRcc, visited,
                        maxAlsCount, usedCells);

                    usedCells.ExceptWith(candidate.CellSet);
                    usedDigits.RemoveAt(usedDigits.Count - 1);
                    visited[nextIdx] = false;
                    path.RemoveAt(path.Count - 1);
                }
            }
            return changed;
        }

        /// <summary>Whether two ALSes share a cell.</summary>
        private static bool AlsSharesCell(AlsCandidate a, AlsCandidate b) => a.CellSet.Overlaps(b.CellSet);

        /// <summary>
        /// Once ALS-XY-Chain holds, eliminates Z from every cell seen in common by every cell
        /// holding Z in either the start ALS (A) or end ALS (G) (excluding the cells of every ALS making up the chain itself) (step 5 of the request document).
        /// </summary>
        private bool TryApplyAlsXyChainElimination(AlsCandidate A, AlsCandidate G, int z,
            List<AlsCandidate> alsList, List<int> path, List<int> usedDigits)
        {
            var zCells = CellsWithDigit(A, z).Concat(CellsWithDigit(G, z)).ToList();
            if (zCells.Count == 0) return false;

            var commonPeers = CommonPeersOf(zCells);
            if (commonPeers.Count == 0) return false;

            var causeCells = path.SelectMany(idx => alsList[idx].Cells).ToList();
            var chainCellSet = new HashSet<(int x, int y)>(causeCells);
            string chainDesc = BuildAlsChainDescription(path, usedDigits, alsList);

            bool changed = false;
            foreach (var (tx, ty) in commonPeers)
            {
                // Cells that are part of the chain itself are the actual components of the inference, so they are never targeted for elimination
                // (the same lesson learned from the AIC implementation: "never let an elimination slip through for overlapping with a chain's intermediate node").
                if (chainCellSet.Contains((tx, ty))) continue;
                if (Board[tx, ty] != 0) continue;
                if (Notes[z, tx, ty] != CellState.Open) continue;
                changed |= Eliminate(z, tx, ty, CellState.AlsXyChain,
                    $"{ColLetter(tx)}{ty}  ALS-XY-Chain ({chainDesc}) removes <{z}>", causeCells);
            }
            return changed;
        }

        /// <summary>For the log display, formats the house names and RCC digits making up the chain
        /// in a form like "R3-<2>-C5-<4>-B7".</summary>
        private static string BuildAlsChainDescription(List<int> path, List<int> usedDigits, List<AlsCandidate> alsList)
        {
            var sb = new StringBuilder();
            for (int i = 0; i < path.Count; i++)
            {
                var als = alsList[path[i]];
                sb.Append(UnitName(als.House)).Append(als.HouseIndex);
                if (i < usedDigits.Count) sb.Append($"-<{usedDigits[i]}>-");
            }
            return sb.ToString();
        }

        // ============================================================
        // AIC (Alternating Inference Chain)
        //
        // An implementation based on the user-supplied requirements document (AIC.md). Scope of this implementation:
        // - Only patterns 1/2/3 from section 5.2 are implemented (normal AIC / self-contradiction placement / self-contradiction deletion)
        // - Nice Loop (closed-loop) detection from section 5.1 is left unimplemented, since it was to
        //   be defined separately. However, the general rule for preventing infinite loops --
        //   "backtrack whenever a node already visited is reached again" -- is needed regardless of
        //   whether Nice Loop detection succeeds, so just that part is implemented (the "simple
        //   repeat visit" branch from section 5.1).
        // - The search depth (number of strong links used) is max_strong_links=2-5, per the user's instruction.
        // - As soon as one match is found in a single Aic() call, it is applied and the search stops
        //   immediately (taking section 5.2's "stop" of the requirements document literally. This
        //   differs from other techniques such as XyChain, but that is an intentional choice per the user's instruction).

        private enum AicLinkKind { Weak, Strong }

        /// <summary>An AIC node = a (cell, digit) pair.</summary>
        private readonly struct AicNode : IEquatable<AicNode>
        {
            public readonly int X, Y, Digit;
            public AicNode(int x, int y, int digit) { X = x; Y = y; Digit = digit; }
            public bool Equals(AicNode o) => X == o.X && Y == o.Y && Digit == o.Digit;
            public override bool Equals(object obj) => obj is AicNode o && Equals(o);
            public override int GetHashCode() => (X * 10 + Y) * 10 + Digit;
            public override string ToString() => $"{ColLetter(X)}{Y}<{Digit}>";
        }

        private class AicStrongLink
        {
            public AicNode A;
            public AicNode B;
        }

        /// <summary>
        /// Extracts every strong link from across the whole board (section 2.2 of the requirements document).
        /// - House-type: within some house, exactly 2 cells can hold some digit z
        /// - Cell-type (bivalue): a cell with exactly 2 candidate digits
        /// If the same strong link between two nodes is found redundantly via multiple routes
        /// (different houses, etc.), it is merged into one.
        /// </summary>
        private List<AicStrongLink> CollectAicStrongLinks()
        {
            var links = new List<AicStrongLink>();
            var seen = new HashSet<(int, int)>();

            void AddLink(AicNode a, AicNode b)
            {
                int ia = a.GetHashCode(), ib = b.GetHashCode();
                var key = ia < ib ? (ia, ib) : (ib, ia);
                if (seen.Add(key)) links.Add(new AicStrongLink { A = a, B = b });
            }

            // House-type
            foreach (Unit unit in new[] { Unit.Row, Unit.Col, Unit.Box })
                for (int idx = 1; idx <= 9; idx++)
                    for (int z = 1; z <= 9; z++)
                    {
                        (int x, int y)? first = null, second = null;
                        int count = 0;
                        foreach (var (x, y) in CellsOf(unit, idx))
                        {
                            if (!IsFree(Notes[z, x, y])) continue;
                            count++;
                            if (count == 1) first = (x, y);
                            else if (count == 2) second = (x, y);
                            else break;
                        }
                        if (count == 2)
                            AddLink(new AicNode(first.Value.x, first.Value.y, z), new AicNode(second.Value.x, second.Value.y, z));
                    }

            // Cell-type (bivalue)
            foreach (var (x, y, mask) in CollectBivalueCells())
            {
                var digits = MaskDigits(mask);
                AddLink(new AicNode(x, y, digits[0]), new AicNode(x, y, digits[1]));
            }

            return links;
        }

        private static Dictionary<AicNode, List<AicNode>> BuildAicAdjacency(List<AicStrongLink> links)
        {
            var adjacency = new Dictionary<AicNode, List<AicNode>>();
            void Add(AicNode from, AicNode to)
            {
                if (!adjacency.TryGetValue(from, out var list)) { list = new List<AicNode>(); adjacency[from] = list; }
                list.Add(to);
            }
            foreach (var link in links) { Add(link.A, link.B); Add(link.B, link.A); }
            return adjacency;
        }

        /// <summary>
        /// The AIC technique. Starting from a strong link, extends a chain of alternating links
        /// via IDDFS (using 2 to 5 strong links), and as soon as one of patterns 1/2/3 holds,
        /// applies just that one match and stops immediately.
        /// </summary>
        public bool Aic()
        {
            var strongLinks = CollectAicStrongLinks();
            if (strongLinks.Count == 0) return false;
            var adjacency = BuildAicAdjacency(strongLinks);

            for (int maxStrong = 2; maxStrong <= 5; maxStrong++)
            {
                foreach (var link in strongLinks)
                {
                    foreach (var (start, anchorOther) in new[] { (link.A, link.B), (link.B, link.A) })
                    {
                        var path = new List<AicNode> { start };
                        // anchorOther (the other end of the chosen strong link) is also marked visited from the start.
                        // This reflects the premise "A is false, so B is true" -- the strong link itself is
                        // already consumed by that premise, so reaching it again during the search (via
                        // either a weak or strong path) wouldn't add new information, so it is treated as a
                        // repeat visit and subject to backtracking just like any other.
                        var visited = new HashSet<AicNode> { start, anchorOther };
                        if (ExploreAic(path, visited, AicLinkKind.Weak, 0, maxStrong, adjacency, anchorOther))
                            return true;
                    }
                }
            }
            return false;
        }

        /// <summary>Tries every possible transition of type nextType from the node at the end of the current path (section 4 of the requirements document).</summary>
        private bool ExploreAic(List<AicNode> path, HashSet<AicNode> visited, AicLinkKind nextType,
            int strongCount, int maxStrong, Dictionary<AicNode, List<AicNode>> adjacency, AicNode anchorOther)
        {
            var current = path[path.Count - 1];
            AicNode? prev = path.Count >= 2 ? path[path.Count - 2] : (AicNode?)null;

            if (nextType == AicLinkKind.Weak)
            {
                // Route A: a weak link to the same cell, different digit
                int mask = CandidateMask(current.X, current.Y);
                foreach (int d in MaskDigits(mask))
                {
                    if (d == current.Digit) continue;
                    var next = new AicNode(current.X, current.Y, d);
                    // A simple reversal back along the strong link just taken is not a meaningful inference, so it is excluded
                    // (section 4.1 of the requirements document only spells this out for Route B, but
                    //  the same applies right after a cell-type strong link if Route A returns to the same counterpart, so it's applied here too).
                    if (prev.HasValue && next.Equals(prev.Value)) continue;
                    if (TryAicAdvance(path, visited, next, AicLinkKind.Weak, strongCount, maxStrong, adjacency, anchorOther))
                        return true;
                }

                // Route B: a weak link to a different cell (same house), same digit
                foreach (Unit unit in new[] { Unit.Row, Unit.Col, Unit.Box })
                {
                    int idx = unit == Unit.Row ? current.Y : unit == Unit.Col ? current.X : BoxIndex(current.X, current.Y);
                    foreach (var (x, y) in CellsOf(unit, idx))
                    {
                        if (x == current.X && y == current.Y) continue;
                        if (!IsFree(Notes[current.Digit, x, y])) continue;
                        var next = new AicNode(x, y, current.Digit);
                        if (prev.HasValue && next.Equals(prev.Value)) continue; // Excludes a simple reversal (as specified in section 4.1)
                        if (TryAicAdvance(path, visited, next, AicLinkKind.Weak, strongCount, maxStrong, adjacency, anchorOther))
                            return true;
                    }
                }
            }
            else // Strong
            {
                if (strongCount >= maxStrong) return false; // 5.3: pruned by the depth limit
                if (adjacency.TryGetValue(current, out var neighbors))
                {
                    foreach (var next in neighbors)
                    {
                        // Excludes a simple reversal back along the weak link just taken (for the same
                        // reason, symmetric to Route B's reversal exclusion in 4.1). Without this, the
                        // degenerate pattern of "going weak -> strong along a single strong link and
                        // immediately returning to the start" would be misdetected as a valid
                        // self-contradiction (since a single strong link between 2 cells alone doesn't
                        // determine which of the two is actually true).
                        if (prev.HasValue && next.Equals(prev.Value)) continue;
                        // Answer 3 from the requirements document: try every strong link found (if there is more than one)
                        if (TryAicAdvance(path, visited, next, AicLinkKind.Strong, strongCount, maxStrong, adjacency, anchorOther))
                            return true;
                    }
                }
            }
            return false;
        }

        /// <summary>Determines whether the search can advance to the node one step ahead, next (the
        /// evaluation/decision phase of section 5). If a successful pattern holds, applies the
        /// elimination/placement immediately and returns true. Otherwise extends the chain one step and recurses, returning that result (backtracking if it fails).</summary>
        private bool TryAicAdvance(List<AicNode> path, HashSet<AicNode> visited, AicNode next, AicLinkKind arrivedVia,
            int strongCount, int maxStrong, Dictionary<AicNode, List<AicNode>> adjacency, AicNode anchorOther)
        {
            var start = path[0];
            int newStrongCount = strongCount + (arrivedVia == AicLinkKind.Strong ? 1 : 0);

            if (next.Equals(start))
            {
                // 5.2 Patterns 2/3 -> treated uniformly as a Nice Loop.
                //
                // Since the search always starts from a weak link (per section 3 of the requirements
                // document), the kind of link that returns to the start determines the nature of the whole loop:
                // - Returns via a weak link (Pattern 3): start (weak) and end (weak) are the same kind -> a discontinuous loop.
                //   A genuine self-contradiction where assuming "true" leads to "false"; sound on its own.
                // - Returns via a strong link (formerly Pattern 2): start (weak) and end (strong) differ -> a continuous loop.
                //   This does not mean "the start cell is determined"; rather, since the whole loop
                //   closes while keeping its alternating structure intact, every weak link in the loop
                //   is "effectively also a strong link", so the user-specified Nice Loop elimination
                //   rules (cell-spanning / within-cell) should be applied to all of them.
                if (arrivedVia == AicLinkKind.Weak)
                    return TryApplyAicSelfContradictionDelete(start, path);
                return TryApplyAicContinuousNiceLoop(path);
            }

            if (visited.Contains(next))
                return false; // 5.1: a repeat visit to something other than the start (and the strong link's counterpart). Backtrack

            if (arrivedVia == AicLinkKind.Strong
                && next.Digit == anchorOther.Digit
                && !(next.X == anchorOther.X && next.Y == anchorOther.Y)
                && Sees(next.X, next.Y, anchorOther.X, anchorOther.Y))
            {
                // 5.2 Pattern 1: normal AIC
                //
                // The reference point for the conclusion must be anchorOther (=A, the side assumed
                // "false") -- the counterpart of the strong link that established B as true --
                // rather than the search's starting node start (=B). The search continues from B via
                // a weak link under the premise "A is false, so B is true"; using start as the
                // reference would only prove the one-directional implication "B=z => end=z", which
                // is not enough for Pattern 1's conclusion, which requires the two-directional relationship "at least one of the two is true".
                // The correct statement is "A is false => end=z", i.e. "at least one of A and end is z", which also holds trivially if A is assumed true instead, so it always holds.
                if (TryApplyAicNormal(anchorOther, next, path)) return true;
                // If no cell could actually be eliminated, this isn't a meaningful endpoint, so the
                // search continues instead of stopping (falls through below).
            }

            // 5.3: if the depth limit hasn't been reached, extend the chain
            path.Add(next);
            visited.Add(next);
            var nextType = arrivedVia == AicLinkKind.Weak ? AicLinkKind.Strong : AicLinkKind.Weak;
            bool found = ExploreAic(path, visited, nextType, newStrongCount, maxStrong, adjacency, anchorOther);
            if (!found)
            {
                path.RemoveAt(path.Count - 1);
                visited.Remove(next);
            }
            return found;
        }

        private static List<(int x, int y)> AicChainCells(List<AicNode> path, AicNode? tail = null, AicNode? head = null)
        {
            var cells = new List<(int x, int y)>();
            if (head.HasValue) cells.Add((head.Value.X, head.Value.Y));
            cells.AddRange(path.Select(n => (n.X, n.Y)));
            if (tail.HasValue) cells.Add((tail.Value.X, tail.Value.Y));
            return cells;
        }

        private static string AicChainDesc(List<AicNode> path, AicNode? tail = null, AicNode? head = null)
        {
            var nodes = new List<AicNode>();
            if (head.HasValue) nodes.Add(head.Value);
            nodes.AddRange(path);
            if (tail.HasValue) nodes.Add(tail.Value);
            return string.Join("-", nodes);
        }

        /// <summary>Pattern 1: eliminates digit z from every third cell seen by both the reference point
        /// (anchorOther, the counterpart of the starting strong link) and the end node (a different cell, same digit z, reached via a strong link, seeing each other).</summary>
        private bool TryApplyAicNormal(AicNode reference, AicNode end, List<AicNode> path)
        {
            // Every cell on the chain's path (the reference point, intermediate nodes, and the end,
            // all of them) is itself a component of this inference, so it is excluded from being
            // targeted for elimination. CommonPeersOf(reference, end) automatically excludes the two
            // of them, but doesn't handle the case where an intermediate node happens to be seen by
            // both, so reference + the whole path must be excluded explicitly.
            var pathCells = new HashSet<(int x, int y)>(AicChainCells(path, end, reference));

            var targets = CommonPeersOf(new[] { (reference.X, reference.Y), (end.X, end.Y) })
                .Where(t => !pathCells.Contains(t) && IsFree(Notes[reference.Digit, t.x, t.y])).ToList();
            if (targets.Count == 0) return false;

            var causeCells = AicChainCells(path, end, reference);
            string desc = AicChainDesc(path, end, reference);
            bool changed = false;
            foreach (var (x, y) in targets)
                changed |= Eliminate(reference.Digit, x, y, CellState.Aic,
                    $"{ColLetter(x)}{y}  AIC ({desc}) removes <{reference.Digit}>", causeCells);
            return changed;
        }

        /// <summary>
        /// Continuous Nice Loop: when the search returns to the start via a strong link (i.e. of a
        /// different kind from the starting weak link), the whole loop closes while keeping its alternating structure intact.
        /// In this case every weak link within the loop is "effectively also a strong link", so the
        /// two user-specified elimination rules are applied to every weak link in the loop:
        /// - A cell-spanning weak link: the digit can be removed from every other cell seen by both of its two cells
        /// - A within-cell weak link: every other candidate in that cell not part of the loop can be removed
        /// </summary>
        private bool TryApplyAicContinuousNiceLoop(List<AicNode> path)
        {
            int n = path.Count;
            var pathCells = new HashSet<(int x, int y)>(path.Select(p => (p.X, p.Y)));

            // In case the same cell appears more than once in the loop (with different digits),
            // collect the set of digits used in the loop for each cell.
            var digitsInLoopByCell = new Dictionary<(int x, int y), HashSet<int>>();
            foreach (var node in path)
            {
                var cell = (node.X, node.Y);
                if (!digitsInLoopByCell.TryGetValue(cell, out var set))
                {
                    set = new HashSet<int>();
                    digitsInLoopByCell[cell] = set;
                }
                set.Add(node.Digit);
            }

            string desc = AicChainDesc(path, path[0]); // Displayed as closing back at the start
            var causeCells = path.Select(p => (p.X, p.Y)).ToList();
            bool changed = false;

            // Link i (1-based): path[i-1] -> path[i % n]. Odd-numbered = weak, even-numbered = strong
            // (fixed to this alternating pattern by the convention that the search always starts with a weak link).
            for (int i = 0; i < n; i++)
            {
                int linkIndex = i + 1;
                if (linkIndex % 2 == 0) continue; // Even index = strong link, so skip

                var p = path[i];
                var q = path[(i + 1) % n];

                if (p.X == q.X && p.Y == q.Y)
                {
                    // A within-cell weak link: remove every other candidate digit not part of the loop
                    var inLoop = digitsInLoopByCell[(p.X, p.Y)];
                    int mask = CandidateMask(p.X, p.Y);
                    foreach (int d in MaskDigits(mask))
                    {
                        if (inLoop.Contains(d)) continue;
                        changed |= Eliminate(d, p.X, p.Y, CellState.Aic,
                            $"{ColLetter(p.X)}{p.Y}  AIC Nice Loop ({desc}) removes <{d}>", causeCells);
                    }
                }
                else
                {
                    // A cell-spanning weak link: remove the digit from every other cell seen by both
                    int digit = p.Digit; // Route B's weak link, so p.Digit should equal q.Digit
                    foreach (var (x, y) in CommonPeersOf(new[] { (p.X, p.Y), (q.X, q.Y) }))
                    {
                        if (pathCells.Contains((x, y))) continue;
                        if (!IsFree(Notes[digit, x, y])) continue;
                        changed |= Eliminate(digit, x, y, CellState.Aic,
                            $"{ColLetter(x)}{y}  AIC Nice Loop ({desc}) removes <{digit}>", causeCells);
                    }
                }
            }
            return changed;
        }

        /// <summary>Pattern 3: returned to the start via a weak link (self-contradiction). Eliminates that digit from the starting cell.</summary>
        private bool TryApplyAicSelfContradictionDelete(AicNode start, List<AicNode> path)
        {
            if (!IsFree(Notes[start.Digit, start.X, start.Y])) return false;
            var causeCells = AicChainCells(path);
            string desc = AicChainDesc(path);
            return Eliminate(start.Digit, start.X, start.Y, CellState.Aic,
                $"{ColLetter(start.X)}{start.Y}  AIC ({desc}) removes <{start.Digit}> (self-contradiction)", causeCells);
        }



        /// <summary>
        /// Automatically applies techniques from easiest to hardest, repeating until nothing changes.
        /// Tallies which techniques were actually used from Log, and rates this puzzle's difficulty
        /// as the hardest technique among them (i.e. the highest-tier technique a human would need to solve it).
        /// </summary>
        public SolveResult SolveAll()
        {
            int logStartIndex = Log.Count;

            bool changed;
            do
            {
                changed = NakedSingle();               // Trivial
                changed |= HiddenSingle();              // Simple
                if (!changed) changed |= LockedCandidates();   // Easy
                if (!changed) changed |= NakedSubsets();       // Moderate
                if (!changed) changed |= Fish(2);              // Clever (X-Wing)
                if (!changed) changed |= Skyscraper();         // Clever
                if (!changed) changed |= TwoStringKite();      // Clever
                if (!changed) changed |= EmptyRectangle();     // Clever
                if (!changed) changed |= SimpleColoring();     // Tricky
                if (!changed) changed |= RemotePairs();        // Tricky
                if (!changed) changed |= WWing();              // Tricky
                if (!changed) changed |= Fish(3);              // Hard (Swordfish)
                if (!changed) changed |= SashimiFinnedXWing(); // Hard
                if (!changed) changed |= XyWing();             // Hard
                if (!changed) changed |= Fish(4);              // Expert (Jerryfish)
                if (!changed) changed |= SashimiFinnedSwordfish(); // Expert
                if (!changed) changed |= XyzWing();            // Expert
                if (!changed)
                {
                    // Try raising the cap on the chain length from 3 to 10 one at a time, so that a
                    // shorter chain is preferred and found first whenever one is enough to solve it.
                    for (int maxLen = 3; maxLen <= 10 && !changed; maxLen++)
                        changed |= XyChain(maxLen);            // Expert
                }
                if (!changed) changed |= AlsXz();              // Genius
                if (!changed)
                {
                    // Longer chains have exponentially more combinations, so following the same idea
                    // as XyChain/ALS-XY-Chain, try raising the max node count from 3 to 10 one at a time (preferring shorter chains).
                    for (int maxNodes = 3; maxNodes <= 10 && !changed; maxNodes++)
                        changed |= GroupedXChain(maxNodes);    // Genius
                }
                if (!changed) changed |= AlsXyWing();          // Genius
                if (!changed)
                {
                    // An ALS chain's combinations grow rapidly the longer it gets, so following the
                    // same idea as XyChain, try raising the max ALS count from 3 to 6 one at a time (preferring shorter chains).
                    for (int maxAls = 3; maxAls <= 6 && !changed; maxAls++)
                        changed |= AlsXyChain(maxAls);          // Insane
                }
                if (!changed) changed |= Aic();                // Insane
                if (HasContradiction) break; // Once a contradiction is detected, further searching is pointless, so stop
            } while (changed && !IsSolved);

            var stepsThisRun = Log.Skip(logStartIndex).ToList();
            var usage = stepsThisRun
                .GroupBy(e => e.Technique)
                .ToDictionary(g => g.Key, g => g.Count());
            var difficulty = stepsThisRun.Count > 0
                ? stepsThisRun.Max(e => e.Tier)
                : Difficulty.Trivial;

            return new SolveResult
            {
                Solved = IsSolved,
                Difficulty = difficulty,
                TechniqueUsage = usage,
                HasContradiction = HasContradiction,
                ContradictionMessage = ContradictionMessage
            };
        }

        // ============================================================
        // Export / Import (formerly CommandButton13 / CommandButton14)
        // ============================================================

        public string ExportString()
        {
            var sb = new StringBuilder();
            for (int y = 1; y <= 9; y++)
                for (int x = 1; x <= 9; x++)
                    sb.Append(Board[x, y]);
            return sb.ToString();
        }

        public int[,] ParseImportString(string s)
        {
            var givens = new int[10, 10];
            if (s.Length != 81) return givens;
            for (int y = 1; y <= 9; y++)
                for (int x = 1; x <= 9; x++)
                    givens[x, y] = s[(y - 1) * 9 + (x - 1)] - '0';
            return givens;
        }
    }
}
