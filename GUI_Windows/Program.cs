using System;
using System.Windows.Forms;

namespace SudokuSolver
{
    internal static class Program
    {
        [STAThread]
        static void Main()
        {
            ApplicationConfiguration.Initialize(); // For the .NET 6+ WinForms template
            Application.Run(new Form1());
        }
    }
}
