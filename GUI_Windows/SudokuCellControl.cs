using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace SudokuSolver
{
    /// <summary>
    /// A custom control that draws a single Sudoku cell.
    ///
    /// - If the value is fixed, draws a large digit in the center
    ///   (an original "given" digit is drawn in black; a digit placed by the
    ///   solver is drawn in green)
    /// - If the value isn't fixed yet, draws the candidate digits (1-9) that
    ///   haven't been eliminated yet as small digits in a 3x3 grid
    ///   (i.e. "pencil marks")
    /// - While this cell is the current target in the step-replay log, it is
    ///   highlighted with a pale yellow background and an orange border
    ///   (IsHighlighted)
    /// - Cells on the right/bottom edge of a 3x3 box are drawn with a thicker
    ///   border, so the box boundaries stay visible even when the cells are
    ///   packed together with no gap
    ///
    /// This draws directly on a Control rather than using a TextBox because a
    /// TextBox can't represent "up to nine small digits inside one cell".
    /// Key input (1-9, Backspace/Delete) is handled by this control itself.
    /// </summary>
    public class SudokuCellControl : Control
    {
        public int Value { get; private set; }
        public bool IsGiven { get; private set; } = true;

        /// <summary>The font size of the candidate digits (pencil marks), given as a
        /// multiplier of the cell's height. Originally 0.13f, then 0.19f, then
        /// enlarged further to 0.24f for readability. Adjust this value further
        /// if needed (roughly 0.13-0.28 is a realistic range).</summary>
        public static float CandidateFontScale { get; set; } = 0.24f;

        /// <summary>The color used to draw candidate digits. Kept a bit dark so it
        /// stays readable even after being enlarged.</summary>
        private static readonly Brush CandidateBrush = new SolidBrush(Color.DimGray);

        /// <summary>Whether this is "the cell the current log line is acting on" in
        /// the step-replay log. While true, the background is pale yellow and the
        /// border is orange, to make it stand out.</summary>
        public bool IsHighlighted { get; private set; }

        /// <summary>Whether this cell was one of the cells that justified the current
        /// elimination (the highlighted-in-yellow cell), in the step-replay log.
        /// Used to show, in pale blue, the group of cells that a technique such as
        /// XY-Chain/W-Wing/XY-Wing/Fish/Remote Pairs used as the "reasoning" behind a
        /// single elimination it derived from a relationship between multiple cells.
        /// This is not expected to be true at the same time as IsHighlighted
        /// (yellow); the priority order used in OnPaint is
        /// "yellow > dark blue (AIC) > pale blue > normal".</summary>
        public bool IsCauseHighlighted { get; private set; }

        /// <summary>A dedicated highlight indicating an AIC reasoning cell. Uses a
        /// darker blue (a cornflower-blue tone) so it's clearly distinguishable from
        /// the pale blue used for other techniques' reasoning cells
        /// (IsCauseHighlighted). AIC chains tend to get long, so this was given its
        /// own color to avoid confusion with other techniques' reasoning cells.</summary>
        public bool IsAicHighlighted { get; private set; }

        /// <summary>True if this cell is on the right edge of a 3x3 box (x=3,6). Its
        /// border is drawn thicker.</summary>
        public bool BoldRightBorder { get; set; }

        /// <summary>True if this cell is on the bottom edge of a 3x3 box (y=3,6). Its
        /// border is drawn thicker.</summary>
        public bool BoldBottomBorder { get; set; }

        private readonly bool[] _candidates = new bool[10];

        public event EventHandler ValueChanged;

        public SudokuCellControl()
        {
            SetStyle(ControlStyles.UserPaint
                     | ControlStyles.AllPaintingInWmPaint
                     | ControlStyles.OptimizedDoubleBuffer
                     | ControlStyles.ResizeRedraw
                     | ControlStyles.Selectable, true);
            TabStop = true;
            Cursor = Cursors.Hand;
        }

        /// <summary>Sets the fixed value. If isGiven=true it is shown in black, as an
        /// "originally entered digit". If false, it is shown in green, as "a digit
        /// the solver placed".</summary>
        public void SetValue(int value, bool isGiven)
        {
            Value = value;
            IsGiven = isGiven;
            if (value != 0)
                Array.Clear(_candidates, 0, _candidates.Length);
            Invalidate();
        }

        /// <summary>Updates the candidate digits (pencil marks). flags has length 10 and uses index 1-9.</summary>
        public void SetCandidates(bool[] flags)
        {
            for (int d = 1; d <= 9; d++)
                _candidates[d] = flags != null && flags[d];
            Invalidate();
        }

        /// <summary>Toggles whether this cell is highlighted as the target of the current step-replay log line.</summary>
        public void SetHighlighted(bool value)
        {
            if (IsHighlighted == value) return;
            IsHighlighted = value;
            Invalidate();
        }

        /// <summary>Toggles whether this cell is highlighted as part of the "reasoning" behind the current step's elimination.</summary>
        public void SetCauseHighlighted(bool value)
        {
            if (IsCauseHighlighted == value) return;
            IsCauseHighlighted = value;
            Invalidate();
        }

        /// <summary>Toggles whether this cell is highlighted as an AIC reasoning cell.</summary>
        public void SetAicHighlighted(bool value)
        {
            if (IsAicHighlighted == value) return;
            IsAicHighlighted = value;
            Invalidate();
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            var g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;

            Color background;
            Color borderColor;
            int borderWidth;

            if (Focused)
            {
                background = Color.FromArgb(255, 250, 205); // Pale lemon color (has keyboard focus)
                borderColor = Color.RoyalBlue;
                borderWidth = 2;
            }
            else if (IsHighlighted)
            {
                background = Color.FromArgb(255, 241, 118);  // Pale yellow (this cell is the log's current focus)
                borderColor = Color.DarkOrange;
                borderWidth = 2;
            }
            else if (IsAicHighlighted)
            {
                background = Color.FromArgb(150, 190, 255);  // Slightly darker blue (AIC only, to distinguish from other techniques' pale blue)
                borderColor = Color.DodgerBlue;
                borderWidth = 2;
            }
            else if (IsCauseHighlighted)
            {
                background = Color.FromArgb(197, 225, 255);  // Pale blue (a cell highlighted as the reasoning behind this elimination)
                borderColor = Color.SteelBlue;
                borderWidth = 2;
            }
            else
            {
                background = Color.White;
                borderColor = Color.Black;
                borderWidth = 1;
            }

            using (var bg = new SolidBrush(background))
                g.FillRectangle(bg, ClientRectangle);

            if (Value != 0)
            {
                DrawBigDigit(g);
            }
            else
            {
                DrawCandidates(g);
            }

            using (var border = new Pen(borderColor, borderWidth))
                g.DrawRectangle(border, 0, 0, Width - 1, Height - 1);

            // Draw the 3x3 box borders thicker, to keep them visible now that the gap between cells has been removed.
            if (BoldRightBorder || BoldBottomBorder)
            {
                using var boldPen = new Pen(Color.Black, 3);
                if (BoldRightBorder)
                    g.DrawLine(boldPen, Width - 1, 0, Width - 1, Height);
                if (BoldBottomBorder)
                    g.DrawLine(boldPen, 0, Height - 1, Width, Height - 1);
            }
        }

        private void DrawBigDigit(Graphics g)
        {
            string text = Value.ToString();
            using var font = new Font("Segoe UI", Height * 0.5f, FontStyle.Bold, GraphicsUnit.Pixel);
            var color = IsGiven ? Color.Black : Color.SeaGreen;
            var size = g.MeasureString(text, font);
            using var brush = new SolidBrush(color);
            g.DrawString(text, font, brush,
                (Width - size.Width) / 2f, (Height - size.Height) / 2f);
        }

        private void DrawCandidates(Graphics g)
        {
            float cellW = Width / 3f;
            float cellH = Height / 3f;
            // Font size for the candidate digits (pencil marks). Previously Height * 0.13f, which was too small, so it was enlarged.
            using var font = new Font("Segoe UI", Height * CandidateFontScale, FontStyle.Regular, GraphicsUnit.Pixel);

            for (int d = 1; d <= 9; d++)
            {
                if (!_candidates[d]) continue;
                int row = (d - 1) / 3;
                int col = (d - 1) % 3;
                string text = d.ToString();
                var size = g.MeasureString(text, font);
                float x = col * cellW + (cellW - size.Width) / 2f;
                float y = row * cellH + (cellH - size.Height) / 2f;
                g.DrawString(text, font, CandidateBrush, x, y);
            }
        }

        // ---- Key input (handled by this control itself, without a TextBox: 1-9 and Backspace/Delete) ----

        protected override bool IsInputKey(Keys keyData) => true;

        protected override void OnKeyPress(KeyPressEventArgs e)
        {
            base.OnKeyPress(e);
            if (e.KeyChar >= '1' && e.KeyChar <= '9')
            {
                SetValue(e.KeyChar - '0', isGiven: true);
                ValueChanged?.Invoke(this, EventArgs.Empty);
            }
            e.Handled = true;
        }

        protected override void OnKeyDown(KeyEventArgs e)
        {
            base.OnKeyDown(e);
            if (e.KeyCode == Keys.Back || e.KeyCode == Keys.Delete)
            {
                SetValue(0, isGiven: true);
                ValueChanged?.Invoke(this, EventArgs.Empty);
            }
        }

        protected override void OnMouseDown(MouseEventArgs e)
        {
            base.OnMouseDown(e);
            Focus();
        }

        protected override void OnGotFocus(EventArgs e) { base.OnGotFocus(e); Invalidate(); }
        protected override void OnLostFocus(EventArgs e) { base.OnLostFocus(e); Invalidate(); }
    }
}
