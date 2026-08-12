using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Windows.Forms;

namespace SudokuSolver
{
    public class Form1 : Form
    {
        private readonly SudokuEngine _engine = new SudokuEngine();
        private readonly SudokuCellControl[,] _cells = new SudokuCellControl[10, 10]; // Uses indices 1-9
        private readonly bool[,] _givenMask = new bool[10, 10]; // Whether this cell was a given at the time of Initialize

        private ListBox _logBox;
        private TextBox _importExportBox;
        private Label _difficultyLabel;
        private CheckBox _showCandidatesCheck;

        // ---- Step replay (forward/back) ----
        private Button _btnHistoryFirst;
        private Button _btnHistoryPrev;
        private Button _btnHistoryNext;
        private Button _btnHistoryLast;
        private Label _stepPositionLabel;

        /// <summary>Which snapshot index of _engine.History is currently shown on
        /// screen. -1 means "there is no history yet (before Initialize)".</summary>
        private int _historyCursor = -1;

        /// <summary>
        /// The _engine.History index that corresponds to _logBox.Items[i] (always
        /// kept the same length as _logBox.Items). Lines with no corresponding
        /// snapshot (e.g. the "(No change)" line, or the auto-solve technique-usage
        /// summary lines) are set to -1.
        ///
        /// Converting through this list -- which tracks the actual correspondence
        /// per line instead of assuming a fixed offset -- keeps the log and the
        /// step-replay in sync regardless of whether a given line has a
        /// corresponding snapshot.
        /// </summary>
        private readonly List<int> _logBoxHistoryIndex = new List<int>();

        /// <summary>Guard flag that prevents an infinite loop when synchronizing the log selection and the replay position with each other.</summary>
        private bool _suppressLogSelection;

        // ---- Grid layout constants (accounting for the margin used by the row/column labels) ----
        private const int CellSize = 46;
        private const int RowLabelWidth = 22;   // Width reserved for the row-number (1-9) labels on the left of the board
        private const int ColLabelHeight = 20;  // Height reserved for the column-name (A-I) labels above the board
        private const int GridOriginX = 20 + RowLabelWidth;
        private const int GridOriginY = 20 + ColLabelHeight;

        public Form1()
        {
            Text = "Sudoku Solver (ported from VBA)";
            Width = 1180;
            Height = 800;
            StartPosition = FormStartPosition.CenterScreen;

            BuildGridLabels();
            BuildGrid();
            BuildButtons();
            BuildHistoryPanel();
            BuildLogPanel();
            UpdateNavButtonsEnabled();
        }

        // ------------------------------------------------------------
        // Minimum form size constraint + log window resizing
        //
        // Previously the form could be shrunk indefinitely, ignoring the size of
        // the controls actually placed on it, so the following two things were
        // added:
        // 1. At OnLoad, compute the size that exactly fits all currently placed
        //    controls, and fix that as MinimumSize (so the window can never be
        //    shrunk smaller than the visible controls).
        // 2. The processing-log ListBox uses Anchor (Top+Bottom+Left+Right) so
        //    that stretching the window vertically grows its height along with it
        //    (set in BuildLogPanel). When shrinking, OnResize also guarantees the
        //    height never drops below "at least 10 visible lines".
        // ------------------------------------------------------------

        /// <summary>The number of lines kept as the lower bound the log window is never shrunk below.</summary>
        private const int LogBoxMinVisibleLines = 10;

        protected override void OnLoad(EventArgs e)
        {
            base.OnLoad(e);

            int maxRight = 0, maxBottom = 0;
            foreach (Control c in Controls)
            {
                maxRight = Math.Max(maxRight, c.Right);
                maxBottom = Math.Max(maxBottom, c.Bottom);
            }
            var requiredClientSize = new Size(maxRight + 20, maxBottom + 20);
            MinimumSize = SizeFromClientSize(requiredClientSize);
        }

        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);

            if (_logBox != null)
            {
                int minHeight = TextRenderer.MeasureText("A", _logBox.Font).Height * LogBoxMinVisibleLines + 8;
                if (_logBox.Height < minHeight)
                    _logBox.Height = minHeight;
            }
        }

        // ------------------------------------------------------------
        // Board legend: show column names A,B,C... across the top, and row
        // numbers 1,2,3... down the left
        // ------------------------------------------------------------
        private void BuildGridLabels()
        {
            for (int x = 1; x <= 9; x++)
            {
                var colLabel = new Label
                {
                    Text = ((char)('A' + x - 1)).ToString(),
                    Left = GridOriginX + (x - 1) * CellSize,
                    Top = 20,
                    Width = CellSize,
                    Height = ColLabelHeight,
                    TextAlign = ContentAlignment.MiddleCenter,
                    Font = new Font("Segoe UI", 9.5F, FontStyle.Bold),
                };
                Controls.Add(colLabel);
            }

            for (int y = 1; y <= 9; y++)
            {
                var rowLabel = new Label
                {
                    Text = y.ToString(),
                    Left = 20,
                    Top = GridOriginY + (y - 1) * CellSize,
                    Width = RowLabelWidth,
                    Height = CellSize,
                    TextAlign = ContentAlignment.MiddleCenter,
                    Font = new Font("Segoe UI", 9.5F, FontStyle.Bold),
                };
                Controls.Add(rowLabel);
            }
        }

        // ------------------------------------------------------------
        // Generate the 9x9 grid
        // There is no gap between boxes (cells are packed together); instead,
        // box boundaries (columns 3,6 on the right edge / rows 3,6 on the
        // bottom edge) are drawn with a thick line to show the separation.
        // ------------------------------------------------------------
        private void BuildGrid()
        {
            for (int x = 1; x <= 9; x++)
            {
                for (int y = 1; y <= 9; y++)
                {
                    var cell = new SudokuCellControl
                    {
                        Width = CellSize,
                        Height = CellSize,
                        Left = GridOriginX + (x - 1) * CellSize,
                        Top = GridOriginY + (y - 1) * CellSize,
                        BoldRightBorder = (x == 3 || x == 6),
                        BoldBottomBorder = (y == 3 || y == 6),
                    };
                    cell.ValueChanged += (s, e) => OnCellEditedManually();
                    Controls.Add(cell);
                    _cells[x, y] = cell;
                }
            }
        }

        // ------------------------------------------------------------
        // Control buttons (arranged in 3 columns: techniques in col1/col2,
        // overall controls grouped in col3.
        // Technique buttons are ordered from easiest to hardest: top-to-bottom
        // in col1, then top-to-bottom in col2.
        // ------------------------------------------------------------
        private void BuildButtons()
        {
            // col1/col2: technique button columns. col3: overall controls column (auto-solve, clear board, etc.).
            int col1X = 470, col2X = 670, col3X = 880;
            int btnW = 190, btnH = 30, gap = 6;
            int col1Y = 20, col2Y = 20, col3Y = 20;

            AddButton("Initialize", col1X, ref col1Y, btnW, btnH, gap, OnInitialize);
            AddButton("Naked Single", col1X, ref col1Y, btnW, btnH, gap, (s, e) => RunTechnique(_engine.NakedSingle));
            AddButton("Hidden Single", col1X, ref col1Y, btnW, btnH, gap, (s, e) => RunTechnique(_engine.HiddenSingle));
            AddButton("Locked Candidates", col1X, ref col1Y, btnW, btnH, gap, (s, e) => RunTechnique(_engine.LockedCandidates));
            AddButton("Naked/Hidden Subsets", col1X, ref col1Y, btnW, btnH, gap, (s, e) => RunTechnique(() => _engine.NakedSubsets()));
            AddButton("X-Wing", col1X, ref col1Y, btnW, btnH, gap, (s, e) => RunTechnique(() => _engine.Fish(2)));
            AddButton("Skyscraper", col1X, ref col1Y, btnW, btnH, gap, (s, e) => RunTechnique(_engine.Skyscraper));
            AddButton("2 String Kite", col1X, ref col1Y, btnW, btnH, gap, (s, e) => RunTechnique(_engine.TwoStringKite));
            AddButton("Empty Rectangle", col1X, ref col1Y, btnW, btnH, gap, (s, e) => RunTechnique(_engine.EmptyRectangle));
            AddButton("Simple Coloring (replaces X-Chain)", col1X, ref col1Y, btnW, btnH, gap, (s, e) => RunTechnique(_engine.SimpleColoring));
            AddButton("Remote Pairs", col1X, ref col1Y, btnW, btnH, gap, (s, e) => RunTechnique(_engine.RemotePairs));
            AddButton("W-Wing", col1X, ref col1Y, btnW, btnH, gap, (s, e) => RunTechnique(_engine.WWing));

            // col2 (2nd technique column): continues from col1, stacked top-to-bottom from easiest to hardest
            AddButton("Swordfish", col2X, ref col2Y, btnW, btnH, gap, (s, e) => RunTechnique(() => _engine.Fish(3)));
            AddButton("Sashimi/Finned X-Wing", col2X, ref col2Y, btnW, btnH, gap, (s, e) => RunTechnique(_engine.SashimiFinnedXWing));
            AddButton("XY-Wing", col2X, ref col2Y, btnW, btnH, gap, (s, e) => RunTechnique(_engine.XyWing));
            AddButton("Jerryfish", col2X, ref col2Y, btnW, btnH, gap, (s, e) => RunTechnique(() => _engine.Fish(4)));
            AddButton("Sashimi/Finned Swordfish", col2X, ref col2Y, btnW, btnH, gap, (s, e) => RunTechnique(_engine.SashimiFinnedSwordfish));
            AddButton("XYZ-Wing", col2X, ref col2Y, btnW, btnH, gap, (s, e) => RunTechnique(_engine.XyzWing));
            AddButton("XY-Chain", col2X, ref col2Y, btnW, btnH, gap, (s, e) => RunTechnique(() => _engine.XyChain()));
            AddButton("ALS-XZ", col2X, ref col2Y, btnW, btnH, gap, (s, e) => RunTechnique(_engine.AlsXz));
            AddButton("Grouped X-Chain", col2X, ref col2Y, btnW, btnH, gap, (s, e) => RunTechnique(() => _engine.GroupedXChain()));
            AddButton("ALS-XY-Wing", col2X, ref col2Y, btnW, btnH, gap, (s, e) => RunTechnique(_engine.AlsXyWing));
            AddButton("AIC", col2X, ref col2Y, btnW, btnH, gap, (s, e) => RunTechnique(_engine.Aic));
            AddButton("ALS-XY-Chain", col2X, ref col2Y, btnW, btnH, gap, (s, e) => RunTechnique(() => _engine.AlsXyChain()));

            // col3 (overall controls column)
            AddButton("Auto-Solve + Rate Difficulty", col3X, ref col3Y, btnW, btnH, gap, OnAutoSolve);
            AddButton("Clear Board", col3X, ref col3Y, btnW, btnH, gap, OnClearBoard);
            AddButton("Clear Log", col3X, ref col3Y, btnW, btnH, gap, (s, e) => { _logBox.Items.Clear(); _logBoxHistoryIndex.Clear(); });

            _showCandidatesCheck = new CheckBox
            {
                Text = "Show candidate digits",
                Left = col3X,
                Top = col3Y,
                Width = btnW,
                Checked = true,
            };
            _showCandidatesCheck.CheckedChanged += (s, e) => RefreshBoard();
            Controls.Add(_showCandidatesCheck);
            col3Y += 26;

            _difficultyLabel = new Label
            {
                Left = col3X,
                Top = col3Y,
                Width = btnW,
                Height = 40,
                Text = "Difficulty: (not yet determined)",
                Font = new Font("Segoe UI", 10F, FontStyle.Bold),
            };
            Controls.Add(_difficultyLabel);
            col3Y += 46;

            AddButton("Export (to 81-character string)", col3X, ref col3Y, btnW, btnH, gap, OnExport);
            AddButton("Import (from 81-character string)", col3X, ref col3Y, btnW, btnH, gap, OnImport);

            _importExportBox = new TextBox
            {
                Left = col3X,
                Top = col3Y,
                Width = btnW,
                Height = 50,
                Multiline = true,
            };
            // Select all text when focused (WinForms otherwise clears the selection
            // right after a click, so this is deferred by one tick via
            // BeginInvoke).
            _importExportBox.Enter += (s, e) =>
                _importExportBox.BeginInvoke(new MethodInvoker(() => _importExportBox.SelectAll()));
            Controls.Add(_importExportBox);
        }

        private void AddButton(string text, int left, ref int top, int width, int height, int gap, EventHandler onClick)
        {
            var b = new Button { Text = text, Left = left, Top = top, Width = width, Height = height, Font = new Font("Segoe UI", 8.5F) };
            b.Click += onClick;
            Controls.Add(b);
            top += height + gap;
        }

        // ------------------------------------------------------------
        // Step-replay panel (shows how the board changed step by step,
        // forward/back). Placed below the grid, above the log panel.
        // ------------------------------------------------------------
        private void BuildHistoryPanel()
        {
            int top = 498;
            int left = 20;
            int h = 30;

            _btnHistoryFirst = new Button { Text = "|◀ First", Left = left, Top = top, Width = 85, Height = h };
            _btnHistoryFirst.Click += (s, e) => ShowHistoryFrame(0);
            Controls.Add(_btnHistoryFirst);

            _btnHistoryPrev = new Button { Text = "◀ Back 1 step", Left = left + 90, Top = top, Width = 105, Height = h };
            _btnHistoryPrev.Click += (s, e) => ShowHistoryFrame(_historyCursor - 1);
            Controls.Add(_btnHistoryPrev);

            _stepPositionLabel = new Label
            {
                Left = left + 200,
                Top = top + 5,
                Width = 320,
                Height = 20,
                TextAlign = ContentAlignment.MiddleCenter,
                Text = "Step: - / -",
                Font = new Font("Segoe UI", 9F, FontStyle.Bold),
            };
            Controls.Add(_stepPositionLabel);

            _btnHistoryNext = new Button { Text = "Forward 1 step ▶", Left = left + 525, Top = top, Width = 105, Height = h };
            _btnHistoryNext.Click += (s, e) => ShowHistoryFrame(_historyCursor + 1);
            Controls.Add(_btnHistoryNext);

            _btnHistoryLast = new Button { Text = "Latest ▶|", Left = left + 635, Top = top, Width = 85, Height = h };
            _btnHistoryLast.Click += (s, e) => ShowHistoryFrame(_engine.History.Count - 1);
            Controls.Add(_btnHistoryLast);
        }

        private void BuildLogPanel()
        {
            var label = new Label
            {
                Text = "Processing log (step number, difficulty, and details. Click a line to show the board at that point, with the target cell highlighted in yellow. Related cells that were noted as reasoning are shown in pale blue (dark blue for AIC)):",
                Left = 20,
                Top = 536,
                Width = 830,
                Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right,
            };
            Controls.Add(label);

            _logBox = new ListBox
            {
                Left = 20,
                Top = 559,
                Width = 830,
                Height = 192,
                Font = new Font("Consolas", 9F),
                HorizontalScrollbar = true,
                // Make this grow taller when the window is stretched vertically.
                // (Top is fixed, and Bottom is pinned to a fixed distance from the
                //  form's bottom edge, so the height grows by exactly however much
                //  the form grows. The minimum of 10 visible lines is separately
                //  enforced in OnResize.)
                Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right,
            };
            _logBox.SelectedIndexChanged += OnLogSelectionChanged;
            Controls.Add(_logBox);
        }

        // ------------------------------------------------------------
        // Event handlers
        // ------------------------------------------------------------

        /// <summary>Handles the case where the user clicks a cell and types a digit
        /// before Initialize has been run yet. At this point candidates haven't
        /// been computed yet, so this simply does nothing (the values get read in
        /// once the Initialize button is pressed).</summary>
        private void OnCellEditedManually()
        {
            // Does nothing: the Value of each _cells entry is read when the Initialize button is pressed.
        }

        private void OnInitialize(object sender, EventArgs e)
        {
            var givens = new int[10, 10];
            for (int x = 1; x <= 9; x++)
            {
                for (int y = 1; y <= 9; y++)
                {
                    int v = _cells[x, y].Value;
                    givens[x, y] = v;
                    _givenMask[x, y] = v != 0;
                }
            }
            _contradictionAlerted = false;
            _engine.Initialize(givens);
            _difficultyLabel.Text = "Difficulty: (not yet determined)";
            FlushLog();
            RefreshBoard();
            ShowContradictionAlertIfAny();
        }

        /// <summary>If a contradiction is found on the board (either the givens
        /// themselves contain a duplicate, or a cell ran out of candidates while
        /// solving), shows a popup warning. To avoid showing the same
        /// contradiction repeatedly, it is only shown once until Initialize() is
        /// run again.</summary>
        private bool _contradictionAlerted;

        private void ShowContradictionAlertIfAny()
        {
            if (!_engine.HasContradiction || _contradictionAlerted) return;
            _contradictionAlerted = true;
            MessageBox.Show(this, _engine.ContradictionMessage, "The board has a contradiction",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }

        private void RunTechnique(Func<bool> technique)
        {
            bool changed = technique();
            FlushLog();
            RefreshBoard();
            if (!changed)
                AddNonHistoryLogLine("      (No change)");
            ShowContradictionAlertIfAny();
        }

        private void OnAutoSolve(object sender, EventArgs e)
        {
            var result = _engine.SolveAll();
            FlushLog();
            RefreshBoard();

            string status = result.Solved ? "Solved" : "Got this far using the implemented techniques";
            _difficultyLabel.Text = $"Difficulty: {result.Difficulty}\n({status})";

            if (result.TechniqueUsage.Count > 0)
            {
                AddNonHistoryLogLine("---- Breakdown of techniques used ----");
                foreach (var kv in result.TechniqueUsage.OrderByDescending(kv => kv.Value))
                    AddNonHistoryLogLine($"      {kv.Key} : {kv.Value} time(s)");
            }
            if (_logBox.Items.Count > 0)
                _logBox.TopIndex = _logBox.Items.Count - 1;
            ShowContradictionAlertIfAny();
        }

        private void OnClearBoard(object sender, EventArgs e)
        {
            ClearBoardAndLog();
        }

        /// <summary>Clears everything on the board (values, candidates,
        /// highlights) as well as the log and history. Called in common by both
        /// the "Clear Board" button and the Import button (which clears before
        /// loading).</summary>
        private void ClearBoardAndLog()
        {
            for (int x = 1; x <= 9; x++)
                for (int y = 1; y <= 9; y++)
                {
                    _cells[x, y].SetValue(0, isGiven: true);
                    _cells[x, y].SetCandidates(null);
                    _cells[x, y].SetHighlighted(false);
                    _cells[x, y].SetCauseHighlighted(false);
                    _cells[x, y].SetAicHighlighted(false);
                    _givenMask[x, y] = false;
                }
            _logBox.Items.Clear();
            _logBoxHistoryIndex.Clear();
            _engine.AcknowledgeFlushedLog(); // Resets the internal _snapshotCursor along with Log.Clear()
            _engine.History.Clear();
            _historyCursor = -1;
            _contradictionAlerted = false;
            _difficultyLabel.Text = "Difficulty: (not yet determined)";
            _stepPositionLabel.Text = "Step: - / -";
            UpdateNavButtonsEnabled();
        }

        private void OnExport(object sender, EventArgs e)
        {
            _importExportBox.Text = _engine.ExportString();
        }

        /// <summary>
        /// Import button: first fully clears the board and log, then loads the
        /// entered 81-character string, and immediately runs Initialize
        /// (including candidate computation) right after.
        /// (Previously this only set the digits into the cells, and Initialize
        /// had to be run separately by pressing its own button.)
        /// </summary>
        private void OnImport(object sender, EventArgs e)
        {
            var givens = _engine.ParseImportString(_importExportBox.Text.Trim());

            ClearBoardAndLog();

            for (int x = 1; x <= 9; x++)
                for (int y = 1; y <= 9; y++)
                    _cells[x, y].SetValue(givens[x, y], isGiven: true);

            OnInitialize(sender, e);
        }

        // ------------------------------------------------------------
        // Step replay: draws the board/candidates for the given history index as-is
        // ------------------------------------------------------------

        /// <summary>
        /// Displays the snapshot from _engine.History[index] on the board. index
        /// is automatically clamped into the valid range. After a technique
        /// button or auto-solve, the latest (last) snapshot is always passed in,
        /// which keeps the familiar behavior of "the result appears on the board
        /// immediately". The single cell that step acted on (snap.X, snap.Y) is
        /// highlighted with a pale yellow background and orange border.
        /// </summary>
        private void ShowHistoryFrame(int index)
        {
            if (_engine.History.Count == 0)
            {
                _historyCursor = -1;
                _stepPositionLabel.Text = "Step: - / -";
                UpdateNavButtonsEnabled();
                return;
            }

            index = Math.Max(0, Math.Min(index, _engine.History.Count - 1));
            _historyCursor = index;

            var snap = _engine.History[index];
            bool showCandidates = _showCandidatesCheck == null || _showCandidatesCheck.Checked;

            for (int x = 1; x <= 9; x++)
            {
                for (int y = 1; y <= 9; y++)
                {
                    int v = snap.Board[x, y];
                    var cell = _cells[x, y];

                    if (v != 0)
                    {
                        cell.SetValue(v, isGiven: _givenMask[x, y]);
                    }
                    else
                    {
                        cell.SetValue(0, isGiven: true);
                        cell.SetCandidates(showCandidates
                            ? SudokuEngine.GetCandidateFlags(snap.Board, snap.Notes, x, y)
                            : null);
                    }

                    // When snap.X/Y is 0 (a line that doesn't target a specific
                    // cell, such as the initial setup or "Solved!"), it never
                    // matches any cell, so all cell highlighting is automatically
                    // cleared.
                    cell.SetHighlighted(x == snap.X && y == snap.Y);

                    // For eliminations derived from a relationship between
                    // multiple cells, as in XY-Chain/W-Wing/XY-Wing/Fish/Remote
                    // Pairs, the group of cells that justified it
                    // (snap.CauseCells) is shown in pale blue.
                    // AIC alone tends to have long chains of reasoning cells that
                    // are easily confused with other techniques', so it gets its
                    // own darker blue.
                    bool isCause = false;
                    for (int i = 0; i < snap.CauseCells.Count; i++)
                        if (snap.CauseCells[i].x == x && snap.CauseCells[i].y == y) { isCause = true; break; }

                    bool isAic = snap.Technique == "Aic";
                    cell.SetAicHighlighted(isAic && isCause);
                    cell.SetCauseHighlighted(!isAic && isCause);
                }
            }

            _stepPositionLabel.Text = $"Step: {index + 1} / {_engine.History.Count}   [{snap.Message}]";

            // Also highlight the log selection to match the step currently
            // shown. Instead of a fixed offset (index-1), find and select the
            // line in _logBoxHistoryIndex whose value actually equals history
            // index==index (this stays correct even when "No change" or summary
            // lines are interspersed).
            _suppressLogSelection = true;
            try
            {
                int logIndex = _logBoxHistoryIndex.IndexOf(index);
                if (logIndex >= 0)
                    _logBox.SelectedIndex = logIndex;
                else
                    _logBox.ClearSelected();
            }
            finally
            {
                _suppressLogSelection = false;
            }

            UpdateNavButtonsEnabled();
        }

        private void OnLogSelectionChanged(object sender, EventArgs e)
        {
            if (_suppressLogSelection) return;
            int logIndex = _logBox.SelectedIndex;
            if (logIndex < 0 || logIndex >= _logBoxHistoryIndex.Count) return;

            // Lines with no corresponding snapshot in _engine.History -- such as
            // "No change" or OnAutoSolve's technique-usage summary lines -- are
            // -1 in _logBoxHistoryIndex, so the click is simply ignored (nothing
            // happens).
            int historyIndex = _logBoxHistoryIndex[logIndex];
            if (historyIndex < 0 || historyIndex >= _engine.History.Count) return;

            ShowHistoryFrame(historyIndex);
        }

        private void UpdateNavButtonsEnabled()
        {
            bool hasHistory = _engine.History.Count > 0;
            _btnHistoryFirst.Enabled = hasHistory && _historyCursor > 0;
            _btnHistoryPrev.Enabled = hasHistory && _historyCursor > 0;
            _btnHistoryNext.Enabled = hasHistory && _historyCursor < _engine.History.Count - 1;
            _btnHistoryLast.Enabled = hasHistory && _historyCursor < _engine.History.Count - 1;
        }

        // ------------------------------------------------------------
        // Redraw: placed digits are drawn large, and candidate digits are
        // drawn small when a cell isn't fixed yet. Internally this is unified
        // to always "show the latest frame of the history"
        // (because the latest state should always be shown right after a
        // technique is applied).
        // ------------------------------------------------------------
        private void RefreshBoard()
        {
            ShowHistoryFrame(_engine.History.Count - 1);
        }

        /// <summary>
        /// Flushes the lines accumulated in _engine.Log into the log display.
        /// Since _engine.Log[k] always has exactly one corresponding snapshot in
        /// _engine.History (AddLog + FlushSnapshots run together as a pair every
        /// time Place()/Eliminate() is called), the correspondence at this point
        /// is simply a consecutive run: "however many lines of _engine.Log are
        /// being flushed now, that many History indices starting right after the
        /// number flushed so far (= the current history count)". Recording this
        /// in _logBoxHistoryIndex keeps the log-line-to-step correspondence
        /// intact even when lines with no corresponding entry -- like "(No
        /// change)" or a summary line -- get interspersed later.
        ///
        /// [Important] The 1-to-1 correspondence above only holds when
        /// _engine.Log is always cleared via
        /// <see cref="SudokuEngine.AcknowledgeFlushedLog"/>. See the comment on
        /// AcknowledgeFlushedLog() for details.
        /// </summary>
        private void FlushLog()
        {
            // By this point, _engine.History already has the snapshots
            // corresponding to each line of _engine.Log about to be flushed
            // (pushed inside Place/Eliminate).
            // So the "history index of the first entry" is (History.Count - Log.Count).
            int historyIndex = _engine.History.Count - _engine.Log.Count;
            foreach (var entry in _engine.Log)
            {
                _logBox.Items.Add(entry.ToString());
                _logBoxHistoryIndex.Add(historyIndex);
                historyIndex++;
            }
            _engine.AcknowledgeFlushedLog(); // Resets the internal _snapshotCursor along with Log.Clear()
            if (_logBox.Items.Count > 0)
                _logBox.TopIndex = _logBox.Items.Count - 1;
        }

        /// <summary>
        /// Adds a line to the log display that has no corresponding snapshot in
        /// _engine.History at all, such as "(No change)" or the auto-solve
        /// technique-usage summary. Always adds a paired -1 to
        /// _logBoxHistoryIndex too, so _logBox.Items and _logBoxHistoryIndex
        /// always stay the same length.
        /// </summary>
        private void AddNonHistoryLogLine(string text)
        {
            _logBox.Items.Add(text);
            _logBoxHistoryIndex.Add(-1);
        }
    }
}
