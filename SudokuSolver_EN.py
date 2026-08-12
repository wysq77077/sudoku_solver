#!/usr/bin/env python3

from __future__ import annotations

import argparse
import itertools
import sys
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

Cell = Tuple[int, int]  # (x, y) 1-9, 1-9


# ============================================================
# Enum types (correspond to the C# CellState / Unit / Difficulty)
# ============================================================

class CellState(IntEnum):
    """Candidate state for each (value, x, y). Keeps exactly the same values as the C# CellState."""
    OPEN = 0                 # Still alive as a candidate
    PLACED = 1               # This value has been placed in this cell
    ELIMINATED = 2           # Eliminated by a row/col/box conflict (auto-removed due to a placed cell)

    LOCKED_CANDIDATE = 3     # Easy: eliminated by Locked Candidates (Pointing/Claiming)
    NAKED_SUBSET = 4         # Moderate: eliminated by Naked/Hidden Pair through Quad

    X_WING = 5               # Clever: eliminated by Fish (size 2)
    SKYSCRAPER = 6           # Clever: eliminated by Skyscraper
    TWO_STRING_KITE = 7      # Clever: eliminated by 2 String Kite
    EMPTY_RECTANGLE = 8      # Clever: eliminated by Empty Rectangle

    COLORING = 9             # Tricky: eliminated/placed by Simple Coloring
    REMOTE_PAIR = 10         # Tricky: eliminated by Remote Pair
    W_WING = 11              # Tricky: eliminated by W-Wing

    SWORDFISH = 12           # Hard: eliminated by Fish (size 3)
    SASHIMI_FINNED_X_WING = 13  # Hard: eliminated by Sashimi/Finned X-Wing
    XY_WING = 14             # Hard: eliminated by XY-Wing

    JERRYFISH = 15           # Expert: eliminated by Fish (size 4)
    SASHIMI_FINNED_SWORDFISH = 16  # Expert: eliminated by Sashimi/Finned Swordfish
    XYZ_WING = 17            # Expert: eliminated by XYZ-Wing
    XY_CHAIN = 18            # Expert: eliminated by XY-Chain

    ALS_XZ = 19              # Genius: eliminated by the ALS-XZ technique
    GROUPED_X_CHAIN = 20     # Genius: eliminated by Grouped X-Chain/Grouped X-Cycle
    ALS_XY_WING = 21         # Genius: eliminated by the ALS-XY-Wing technique

    AIC = 22                 # Insane: eliminated/placed by AIC (Alternating Inference Chain)
    ALS_XY_CHAIN = 23        # Insane: eliminated by ALS-XY-Chain


def is_free(state: CellState) -> bool:
    return state == CellState.OPEN


class Unit(IntEnum):
    ROW = 0
    COL = 1
    BOX = 2


class Difficulty(IntEnum):
    """Difficulty rank of a technique. Larger numbers mean harder (same ordering as the C# version)."""
    TRIVIAL = 0   # Naked Single
    SIMPLE = 1    # Hidden Single
    EASY = 2      # Locked Candidates
    MODERATE = 3  # Naked Subset
    CLEVER = 4    # X-Wing, Skyscraper, 2 String Kite, Empty Rectangle
    TRICKY = 5    # Simple Coloring, Remote Pair, W-Wing
    HARD = 6      # Swordfish, Sashimi/Finned X-Wing, XY-Wing
    EXPERT = 7    # Jerryfish, Sashimi/Finned Swordfish, XYZ-Wing, XY-Chain
    GENIUS = 8    # ALS-XZ, ALS-XY-Wing
    INSANE = 9    # AIC, ALS-XY-Chain


STATE_TIER: Dict[CellState, Difficulty] = {
    CellState.LOCKED_CANDIDATE: Difficulty.EASY,
    CellState.NAKED_SUBSET: Difficulty.MODERATE,
    CellState.X_WING: Difficulty.CLEVER,
    CellState.SKYSCRAPER: Difficulty.CLEVER,
    CellState.TWO_STRING_KITE: Difficulty.CLEVER,
    CellState.EMPTY_RECTANGLE: Difficulty.CLEVER,
    CellState.COLORING: Difficulty.TRICKY,
    CellState.REMOTE_PAIR: Difficulty.TRICKY,
    CellState.W_WING: Difficulty.TRICKY,
    CellState.SWORDFISH: Difficulty.HARD,
    CellState.SASHIMI_FINNED_X_WING: Difficulty.HARD,
    CellState.XY_WING: Difficulty.HARD,
    CellState.JERRYFISH: Difficulty.EXPERT,
    CellState.SASHIMI_FINNED_SWORDFISH: Difficulty.EXPERT,
    CellState.XYZ_WING: Difficulty.EXPERT,
    CellState.XY_CHAIN: Difficulty.EXPERT,
    CellState.ALS_XZ: Difficulty.GENIUS,
    CellState.GROUPED_X_CHAIN: Difficulty.GENIUS,
    CellState.ALS_XY_WING: Difficulty.GENIUS,
    CellState.AIC: Difficulty.INSANE,
    CellState.ALS_XY_CHAIN: Difficulty.INSANE,
}

# Display names that exactly match the C# CellState enum member names (PascalCase).
# Used for the technique field in the log (roughly the C# version's reason.ToString()) and for
# the keys of SolveResult.TechniqueUsage, to keep them the same strings as the C# version
# (the Python enum member names use ordinary Python SCREAMING_SNAKE_CASE, so they would not match as-is).
STATE_TECHNIQUE_NAME: Dict[CellState, str] = {
    CellState.LOCKED_CANDIDATE: "LockedCandidate",
    CellState.NAKED_SUBSET: "NakedSubset",
    CellState.X_WING: "XWing",
    CellState.SKYSCRAPER: "Skyscraper",
    CellState.TWO_STRING_KITE: "TwoStringKite",
    CellState.EMPTY_RECTANGLE: "EmptyRectangle",
    CellState.COLORING: "Coloring",
    CellState.REMOTE_PAIR: "RemotePair",
    CellState.W_WING: "WWing",
    CellState.SWORDFISH: "Swordfish",
    CellState.SASHIMI_FINNED_X_WING: "SashimiFinnedXWing",
    CellState.XY_WING: "XyWing",
    CellState.JERRYFISH: "Jerryfish",
    CellState.SASHIMI_FINNED_SWORDFISH: "SashimiFinnedSwordfish",
    CellState.XYZ_WING: "XyzWing",
    CellState.XY_CHAIN: "XyChain",
    CellState.ALS_XZ: "AlsXz",
    CellState.GROUPED_X_CHAIN: "GroupedXChain",
    CellState.ALS_XY_WING: "AlsXyWing",
    CellState.AIC: "Aic",
    CellState.ALS_XY_CHAIN: "AlsXyChain",
}


# ============================================================
# Board geometry (computed and cached once at module level.
# Equivalent to the C# version's static constructor)
# ============================================================

def _compute_cells_of(unit: Unit, index: int) -> List[Cell]:
    if unit == Unit.ROW:
        return [(x, index) for x in range(1, 10)]
    if unit == Unit.COL:
        return [(index, y) for y in range(1, 10)]
    # BOX
    bx = ((index - 1) % 3) * 3 + 1
    by = ((index - 1) // 3) * 3 + 1
    return [(bx + dx, by + dy) for dx in range(3) for dy in range(3)]


def _compute_box_index(x: int, y: int) -> int:
    return ((y - 1) // 3) * 3 + ((x - 1) // 3) + 1


UNIT_CELLS: Dict[Tuple[Unit, int], List[Cell]] = {
    (unit, idx): _compute_cells_of(unit, idx)
    for unit in (Unit.ROW, Unit.COL, Unit.BOX)
    for idx in range(1, 10)
}

BOX_INDEX: Dict[Cell, int] = {
    (x, y): _compute_box_index(x, y) for x in range(1, 10) for y in range(1, 10)
}

_PEERS: Dict[Cell, List[Cell]] = {}
for _x in range(1, 10):
    for _y in range(1, 10):
        _set: Set[Cell] = set()
        for c in UNIT_CELLS[(Unit.ROW, _y)]:
            if c[0] != _x:
                _set.add(c)
        for c in UNIT_CELLS[(Unit.COL, _x)]:
            if c[1] != _y:
                _set.add(c)
        for c in UNIT_CELLS[(Unit.BOX, BOX_INDEX[(_x, _y)])]:
            if c != (_x, _y):
                _set.add(c)
        _PEERS[(_x, _y)] = list(_set)


def cells_of(unit: Unit, index: int) -> List[Cell]:
    return UNIT_CELLS[(unit, index)]


def box_index(x: int, y: int) -> int:
    return BOX_INDEX[(x, y)]


def peers(x: int, y: int) -> List[Cell]:
    return _PEERS[(x, y)]


def sees(x1: int, y1: int, x2: int, y2: int) -> bool:
    if x1 == x2 and y1 == y2:
        return False
    if x1 == x2 or y1 == y2:
        return True
    return box_index(x1, y1) == box_index(x2, y2)


def col_letter(x: int) -> str:
    return chr(ord('A') + x - 1)


def unit_name(u: Unit) -> str:
    if u == Unit.ROW:
        return "Horizontal"
    if u == Unit.COL:
        return "Vertical"
    return "Block"


def mask_digits(mask: int) -> List[int]:
    return list(_MASK_DIGITS_TABLE[mask])


# For every bitmask from 0 to 1023, precompute a
# table of "which digits are set". mask_digits() is called extremely often by every technique,
# so this turns it into an O(1) table lookup instead of checking 9 bits each time.
_MASK_DIGITS_TABLE: List[Tuple[int, ...]] = [
    tuple(d for d in range(1, 10) if m & (1 << d)) for m in range(1024)
]


# ============================================================
# Data structures (correspond to the C# LogEntry / SolveResult / AlsCandidate)
# ============================================================

@dataclass
class LogEntry:
    step: int
    message: str
    technique: str
    tier: Difficulty

    def __str__(self) -> str:
        tier_name = self.tier.name.capitalize()
        return f"[{self.step:>3}] ({tier_name:<8}) {self.message}"


@dataclass
class SolveResult:
    solved: bool
    difficulty: Difficulty
    technique_usage: Dict[str, int] = field(default_factory=dict)
    has_contradiction: bool = False
    contradiction_message: Optional[str] = None


@dataclass
class AlsCandidate:
    house: Unit
    house_index: int
    size: int
    mask: int
    cells: List[Cell]
    cell_masks: List[int]
    cells_set: FrozenSet[Cell] = field(default_factory=frozenset)
    cells_by_digit: Dict[int, List[Cell]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Cell-set intersection tests (_als_shares_cell / _find_rcc_digits) are
        # called millions of times during searches such as ALS-XY-Chain, so instead of rebuilding a
        # set every time, it is converted to a frozenset once here and cached (for O(1) intersection tests).
        if not self.cells_set:
            self.cells_set = frozenset(self.cells)
        # The "list of cells holding digit d" is also called frequently from _find_rcc_digits etc.,
        # so instead of rebuilding the list every time (_cells_with_digit), it is
        # sorted by digit and cached once here.
        if not self.cells_by_digit:
            by_digit: Dict[int, List[Cell]] = {}
            for cell, m in zip(self.cells, self.cell_masks):
                for d in mask_digits(m):
                    by_digit.setdefault(d, []).append(cell)
            self.cells_by_digit = by_digit


EMPTY_INT_LIST: List[int] = []
EMPTY_CELL_LIST: List[Cell] = []
FULL_CANDIDATE_MASK = sum(1 << d for d in range(1, 10))  # state where digits 1-9 are all open


@dataclass
class GNode:
    """A Grouped X-Chain node = for a single digit, the set of 1-3 candidate cells
    lined up vertically or horizontally within one box."""
    cells: List[Cell]  # sorted in ascending order
    digit: int
    cell_set: FrozenSet[Cell]

    def __str__(self) -> str:
        if len(self.cells) == 1:
            x, y = self.cells[0]
            return f"{col_letter(x)}{y}"
        return "[" + "".join(f"{col_letter(x)}{y}" for x, y in self.cells) + "]"


def _make_gnode(cells: List[Cell], digit: int) -> GNode:
    sorted_cells = sorted(cells)
    return GNode(cells=sorted_cells, digit=digit, cell_set=frozenset(sorted_cells))


@dataclass
class GStrongLink:
    a: GNode
    b: GNode
    house_unit: Unit
    house_index: int


def _houses_containing_node(node: GNode) -> List[Tuple[Unit, int]]:
    """Enumerates every house (row/col/box) that fully contains the node.
    A single-cell node can match all three. A multi-cell node (a line-shaped set) only
    matches the row or column its line runs along, plus the containing box."""
    houses: List[Tuple[Unit, int]] = []
    first = node.cells[0]
    if all(c[1] == first[1] for c in node.cells):
        houses.append((Unit.ROW, first[1]))
    if all(c[0] == first[0] for c in node.cells):
        houses.append((Unit.COL, first[0]))
    box = box_index(first[0], first[1])
    if all(box_index(c[0], c[1]) == box for c in node.cells):
        houses.append((Unit.BOX, box))
    return houses


def _find_weak_link_house(a: GNode, b: GNode, exclude1: Tuple[Unit, int],
                           exclude2: Tuple[Unit, int]) -> Optional[Tuple[Unit, int]]:
    """Checks whether a weak link exists between two nodes in a house different from
    either of the two given houses (the houses of the immediately preceding/following strong link), and returns that house if so.

    [Important] A weak link requires more than just "some cell of each node sees some cell of the other."
    A multi-cell node (e.g. [D5,E5]) only carries the undetermined information that "this digit
    goes in either D or E," so if only part of the node's cells belong to house H
    (e.g. only D5 belongs to column 4, not E5), the conclusion for house H ("this node OR
    the other node must go in H") does not hold. That conclusion for house H is only valid
    when all of the node's cells are contained in house H. For this reason, the houses that
    can be treated as a weak link are restricted to "houses that fully contain each of the two nodes"
    (for a single-cell node, the row/column/box it belongs to automatically "fully contains" it).
    """
    houses_a = _houses_containing_node(a)
    houses_b = set(_houses_containing_node(b))
    for house in houses_a:
        if house == exclude1 or house == exclude2:
            continue
        if house in houses_b:
            return house
    return None


# ============================================================
# Main body
# ============================================================

class SudokuEngine:
    """A direct port of the logic from the VBA-derived C# version's SudokuEngine.cs.
    Does not depend on the UI (WinForms/GUI) at all. Coordinates are x=column (1-9), y=row (1-9), 1-based.
    History (replaying the board move by move) is not implemented since it is unnecessary for the CLI version.
    """

    def __init__(self) -> None:
        self.board: List[List[int]] = [[0] * 10 for _ in range(10)]
        self.notes: List[List[List[CellState]]] = [
            [[CellState.OPEN] * 10 for _ in range(10)] for _ in range(10)
        ]
        # A cache holding the "current candidate bitmask" for each cell (x, y).
        # A speedup that turns _candidate_mask() from O(9) into O(1) (kept as a plain Python
        # nested list. Using a NumPy array instead was confirmed to be slower, since the
        # per-element access overhead ends up larger than with a plain list,
        # so it is deliberately kept as a list).
        self._mask_cache: List[List[int]] = [[0] * 10 for _ in range(10)]
        self.log: List[LogEntry] = []
        self.has_contradiction: bool = False
        self.contradiction_message: Optional[str] = None
        self._step_counter: int = 0

    # ------------------------------------------------------------
    # Initialization and placement handling
    # ------------------------------------------------------------

    @property
    def is_solved(self) -> bool:
        for x in range(1, 10):
            for y in range(1, 10):
                if self.board[x][y] == 0:
                    return False
        return True

    def _record_contradiction(self, message: str) -> None:
        if self.has_contradiction:
            return  # Only record the first one found
        self.has_contradiction = True
        self.contradiction_message = message
        self._add_log(f"[Contradiction detected] {message}", "Contradiction", Difficulty.TRIVIAL)

    def _validate_givens(self, givens: List[List[int]]) -> None:
        for unit in (Unit.ROW, Unit.COL, Unit.BOX):
            for idx in range(1, 10):
                seen: Dict[int, Cell] = {}
                for (x, y) in cells_of(unit, idx):
                    v = givens[x][y]
                    if v == 0:
                        continue
                    if v in seen:
                        ox, oy = seen[v]
                        self._record_contradiction(
                            f"Digit {v} is duplicated in {unit_name(unit)}"
                            f" (cells: {col_letter(ox)}{oy} and {col_letter(x)}{y})")
                        return
                    seen[v] = (x, y)

    def _check_contradiction(self) -> None:
        if self.has_contradiction:
            return
        for x in range(1, 10):
            for y in range(1, 10):
                if self.board[x][y] != 0:
                    continue
                if self._candidate_mask(x, y) == 0:
                    self._record_contradiction(
                        f"{col_letter(x)}{y} has no digit left that can be placed (the board is contradictory)")
                    return

    def initialize(self, givens: List[List[int]]) -> None:
        """givens is a [10][10] int list (1-indexed, 0 = empty)."""
        self.log.clear()
        self._step_counter = 0
        self.has_contradiction = False
        self.contradiction_message = None
        self.board = [[0] * 10 for _ in range(10)]
        self.notes = [[[CellState.OPEN] * 10 for _ in range(10)] for _ in range(10)]
        self._mask_cache = [[FULL_CANDIDATE_MASK] * 10 for _ in range(10)]
        for row in self._mask_cache:
            row[0] = 0
        self._mask_cache[0] = [0] * 10

        self._validate_givens(givens)

        for x in range(1, 10):
            for y in range(1, 10):
                v = givens[x][y]
                if v != 0:
                    self.board[x][y] = v
                    self.notes[v][x][y] = CellState.PLACED

        self._delete_candidate()

    def _delete_candidate(self) -> None:
        placed_count = 0
        mask_cache = self._mask_cache
        for x in range(1, 10):
            for y in range(1, 10):
                v = self.board[x][y]
                if v == 0:
                    continue
                placed_count += 1

                for (px, py) in peers(x, y):
                    if self.notes[v][px][py] == CellState.OPEN:
                        self.notes[v][px][py] = CellState.ELIMINATED
                        mask_cache[px][py] &= ~(1 << v)

                for t in range(1, 10):
                    if self.notes[t][x][y] == CellState.OPEN:
                        self.notes[t][x][y] = CellState.ELIMINATED

                self.notes[v][x][y] = CellState.PLACED
                mask_cache[x][y] = 0

        if placed_count == 81:
            self._add_log("Solved!", "Result", Difficulty.TRIVIAL)

        self._check_contradiction()

    def _add_log(self, message: str, technique: str, tier: Difficulty) -> None:
        self._step_counter += 1
        self.log.append(LogEntry(self._step_counter, message, technique, tier))

    def _place(self, x: int, y: int, v: int, technique: str, tier: Difficulty,
               detail: Optional[str] = None) -> None:
        self.board[x][y] = v
        self.notes[v][x][y] = CellState.PLACED
        message = (f"{col_letter(x)}{y} <{v}> {technique}" if detail is None
                   else f"{col_letter(x)}{y} <{v}> {technique} ({detail})")
        self._add_log(message, technique, tier)
        self._delete_candidate()

    def _eliminate(self, digit: int, x: int, y: int, reason: CellState, message: str) -> bool:
        if self.notes[digit][x][y] != CellState.OPEN:
            return False
        self.notes[digit][x][y] = reason
        self._mask_cache[x][y] &= ~(1 << digit)
        tier = STATE_TIER.get(reason, Difficulty.MODERATE)
        technique_name = STATE_TECHNIQUE_NAME.get(reason, reason.name)
        self._add_log(message, technique_name, tier)
        return True

    # ------------------------------------------------------------
    # Candidate helpers
    # ------------------------------------------------------------

    def get_candidate_flags(self, x: int, y: int) -> List[bool]:
        flags = [False] * 10
        if self.board[x][y] != 0:
            return flags
        mask = self._mask_cache[x][y]
        for d in range(1, 10):
            flags[d] = bool(mask & (1 << d))
        return flags

    def _candidate_mask(self, x: int, y: int) -> int:
        if self.board[x][y] != 0:
            return 0
        return self._mask_cache[x][y]

    def _collect_bivalue_cells(self) -> List[Tuple[int, int, int]]:
        result = []
        for x in range(1, 10):
            for y in range(1, 10):
                mask = self._candidate_mask(x, y)
                if mask.bit_count() == 2:
                    result.append((x, y, mask))
        return result

    # ------------------------------------------------------------
    # Technique 1: Naked Single
    # ------------------------------------------------------------

    def naked_single(self) -> bool:
        changed = False
        for x in range(1, 10):
            for y in range(1, 10):
                if self.board[x][y] != 0:
                    continue
                mask = self._candidate_mask(x, y)
                if mask.bit_count() == 1:
                    self._place(x, y, mask_digits(mask)[0], "Naked Single", Difficulty.TRIVIAL)
                    changed = True
        return changed

    # ------------------------------------------------------------
    # Technique 2: Hidden Single
    # ------------------------------------------------------------

    def hidden_single(self) -> bool:
        changed = False
        for unit in (Unit.BOX, Unit.ROW, Unit.COL):
            for idx in range(1, 10):
                for m in range(1, 10):
                    open_cells = [c for c in cells_of(unit, idx) if is_free(self.notes[m][c[0]][c[1]])]
                    if len(open_cells) == 1:
                        x, y = open_cells[0]
                        self._place(x, y, m, f"Hidden Single <{unit_name(unit)}>", Difficulty.SIMPLE)
                        changed = True
        return changed

    # ------------------------------------------------------------
    # Technique 3: Locked Candidates (Pointing / Claiming)
    # ------------------------------------------------------------

    def locked_candidates(self) -> bool:
        changed = False
        for m in range(1, 10):
            changed |= self._pointing_in_box(m)
            changed |= self._claiming_in_line(m, Unit.ROW)
            changed |= self._claiming_in_line(m, Unit.COL)
        return changed

    def _pointing_in_box(self, m: int) -> bool:
        changed = False
        for b in range(1, 10):
            cells = [c for c in cells_of(Unit.BOX, b) if is_free(self.notes[m][c[0]][c[1]])]
            if not cells:
                continue

            if len({c[1] for c in cells}) == 1:
                y = cells[0][1]
                for (x2, y2) in cells_of(Unit.ROW, y):
                    if box_index(x2, y2) != b and is_free(self.notes[m][x2][y2]):
                        changed |= self._eliminate(
                            m, x2, y2, CellState.LOCKED_CANDIDATE,
                            f"{col_letter(x2)}{y2}  Locked Candidate (Pointing, Row) <{m}>")
            if len({c[0] for c in cells}) == 1:
                x = cells[0][0]
                for (x2, y2) in cells_of(Unit.COL, x):
                    if box_index(x2, y2) != b and is_free(self.notes[m][x2][y2]):
                        changed |= self._eliminate(
                            m, x2, y2, CellState.LOCKED_CANDIDATE,
                            f"{col_letter(x2)}{y2}  Locked Candidate (Pointing, Col) <{m}>")
        return changed

    def _claiming_in_line(self, m: int, line_unit: Unit) -> bool:
        changed = False
        for idx in range(1, 10):
            cells = [c for c in cells_of(line_unit, idx) if is_free(self.notes[m][c[0]][c[1]])]
            if not cells:
                continue

            box = box_index(cells[0][0], cells[0][1])
            if not all(box_index(c[0], c[1]) == box for c in cells):
                continue

            for (x2, y2) in cells_of(Unit.BOX, box):
                in_same_line = (y2 == idx) if line_unit == Unit.ROW else (x2 == idx)
                if not in_same_line and is_free(self.notes[m][x2][y2]):
                    changed |= self._eliminate(
                        m, x2, y2, CellState.LOCKED_CANDIDATE,
                        f"{col_letter(x2)}{y2}  Locked Candidate (Claiming, {unit_name(line_unit)}) <{m}>")
        return changed

    # ------------------------------------------------------------
    # Technique 4: Naked Subsets (Naked Pair through Quad; simultaneously also acts as Hidden Subset)
    # ------------------------------------------------------------

    def naked_subsets(self, max_size: int = 5) -> bool:
        changed = False
        for unit in (Unit.ROW, Unit.COL, Unit.BOX):
            for idx in range(1, 10):
                changed |= self._naked_subsets_in_group(unit, idx, max_size)
        return changed

    def _naked_subsets_in_group(self, unit: Unit, idx: int, max_size: int) -> bool:
        cells = []
        for (x, y) in cells_of(unit, idx):
            if self.board[x][y] != 0:
                continue
            mask = self._candidate_mask(x, y)
            if mask != 0:
                cells.append((x, y, mask))

        changed = False
        n = len(cells)
        upper = min(max_size, n - 1)
        for size in range(2, upper + 1):
            for combo in itertools.combinations(cells, size):
                union_mask = 0
                for c in combo:
                    union_mask |= c[2]
                if union_mask.bit_count() != size:
                    continue

                hidden_size = n - size
                if hidden_size < size:
                    label = f"Hidden Subset(size {hidden_size}, {unit_name(unit)})"
                else:
                    label = f"Naked Subset(size {size}, {unit_name(unit)})"

                in_subset = {(c[0], c[1]) for c in combo}
                for (x, y, mask) in cells:
                    if (x, y) in in_subset:
                        continue
                    to_remove = mask & union_mask
                    for d in mask_digits(to_remove):
                        changed |= self._eliminate(
                            d, x, y, CellState.NAKED_SUBSET,
                            f"{col_letter(x)}{y}  {label} removes <{d}>")
        return changed

    # ------------------------------------------------------------
    # Technique 5: Fish = X-Wing(2) / Swordfish(3) / Jerryfish(4)
    # ------------------------------------------------------------

    @staticmethod
    def _fish_state(size: int) -> CellState:
        return {2: CellState.X_WING, 3: CellState.SWORDFISH, 4: CellState.JERRYFISH}[size]

    @staticmethod
    def _fish_name(size: int) -> str:
        return {2: "X-Wing", 3: "Swordfish", 4: "Jerryfish"}[size]

    def fish(self, size: int) -> bool:
        changed = False
        changed |= self._fish_direction(size, base_is_row=True)
        changed |= self._fish_direction(size, base_is_row=False)
        return changed

    def _fish_direction(self, size: int, base_is_row: bool) -> bool:
        changed = False
        base_unit = Unit.ROW if base_is_row else Unit.COL

        for m in range(1, 10):
            line_mask = [0] * 10
            for i in range(1, 10):
                mask = 0
                for (x, y) in cells_of(base_unit, i):
                    cover = x if base_is_row else y
                    if is_free(self.notes[m][x][y]):
                        mask |= (1 << cover)
                line_mask[i] = mask

            candidate_lines = [i for i in range(1, 10)
                               if line_mask[i] != 0 and 2 <= line_mask[i].bit_count() <= size]

            for lines in itertools.combinations(candidate_lines, size):
                union_mask = 0
                for l in lines:
                    union_mask |= line_mask[l]
                if union_mask.bit_count() != size:
                    continue

                for cover in mask_digits(union_mask):
                    for line in range(1, 10):
                        if line in lines:
                            continue
                        x = cover if base_is_row else line
                        y = line if base_is_row else cover
                        if is_free(self.notes[m][x][y]):
                            direction = "Horizontal" if base_is_row else "Vertical"
                            changed |= self._eliminate(
                                m, x, y, self._fish_state(size),
                                f"{col_letter(x)}{y}  {self._fish_name(size)} ({direction}) removes <{m}>")
        return changed

    # ------------------------------------------------------------
    # Technique: Sashimi/Finned X-Wing
    # ------------------------------------------------------------

    def sashimi_finned_x_wing(self) -> bool:
        changed = False
        changed |= self._sashimi_finned_x_wing_direction(base_is_row=True)
        changed |= self._sashimi_finned_x_wing_direction(base_is_row=False)
        return changed

    def _sashimi_finned_x_wing_direction(self, base_is_row: bool) -> bool:
        changed = False
        base_unit = Unit.ROW if base_is_row else Unit.COL

        for d in range(1, 10):
            for r1 in range(1, 10):
                cr1 = []
                for (x, y) in cells_of(base_unit, r1):
                    if is_free(self.notes[d][x][y]):
                        cr1.append(x if base_is_row else y)
                if len(cr1) != 2:
                    continue

                for (ca, cb) in ((cr1[0], cr1[1]), (cr1[1], cr1[0])):
                    for r2 in range(1, 10):
                        if r2 == r1:
                            continue

                        others = []
                        for (x, y) in cells_of(base_unit, r2):
                            cover = x if base_is_row else y
                            if cover == ca:
                                continue
                            if is_free(self.notes[d][x][y]):
                                others.append(cover)
                        if not others:
                            continue

                        box = box_index(cb, r2) if base_is_row else box_index(r2, cb)
                        confined = all(
                            (box_index(cover, r2) if base_is_row else box_index(r2, cover)) == box
                            for cover in others)
                        if not confined:
                            continue

                        kind = "Finned" if cb in others else "Sashimi"

                        for (x, y) in cells_of(Unit.BOX, box):
                            cover = x if base_is_row else y
                            line = y if base_is_row else x
                            if cover != cb:
                                continue
                            if line == r1 or line == r2:
                                continue
                            if is_free(self.notes[d][x][y]):
                                changed |= self._eliminate(
                                    d, x, y, CellState.SASHIMI_FINNED_X_WING,
                                    f"{col_letter(x)}{y}  {kind} X-Wing removes <{d}>")
        return changed

    # ------------------------------------------------------------
    # Technique: Sashimi/Finned Swordfish
    #
    # A generalization of Swordfish (size 3). Even when the union of cells (cover coordinates)
    # where the digit can be placed across 3 base lines (rows or columns) does not fit exactly
    # into a covering set K of 3 columns (or 3 rows), if every candidate sticking out of K
    # (the fins) fits within a single box, then within that box, candidates on the row(s)/column(s)
    # of K passing through that box, other than the base lines, can be eliminated.
    #
    # [Detection algorithm]
    # - Choose 3 base lines and the 3 covering lines (K)
    # - Among the cells on each base line where the digit can be placed, collect the cells not in K (= fins)
    # - If the total number of fins is 3 or more, it does not hold
    # - If there are 0 fins, it's a normal Swordfish (already handled by fish(3), so out of scope here)
    # - Holds only when there is 1 fin, or 2 fins that both fit within the same box
    #
    # [Determining Sashimi/Finned (general definition)]
    # Among the base lines that produced a fin, if even one line itself has
    # no candidate on the K side (i.e. the fin alone stands in for that row/column's role), it's Sashimi;
    # otherwise (i.e. the line that produced the fin still has a candidate on the K side too, so the fin is purely extra), it's Finned.
    # ------------------------------------------------------------

    def sashimi_finned_swordfish(self) -> bool:
        changed = False
        changed |= self._sashimi_finned_swordfish_direction(base_is_row=True)
        changed |= self._sashimi_finned_swordfish_direction(base_is_row=False)
        return changed

    def _sashimi_finned_swordfish_direction(self, base_is_row: bool) -> bool:
        changed = False
        base_unit = Unit.ROW if base_is_row else Unit.COL

        for d in range(1, 10):
            line_candidates: Dict[int, List[int]] = {}
            for i in range(1, 10):
                lst = []
                for (x, y) in cells_of(base_unit, i):
                    cover = x if base_is_row else y
                    if is_free(self.notes[d][x][y]):
                        lst.append(cover)
                line_candidates[i] = lst

            non_empty_lines = [i for i in range(1, 10) if line_candidates[i]]

            for line_combo in itertools.combinations(non_empty_lines, 3):
                lines = list(line_combo)
                cand_sets = [line_candidates[l] for l in lines]

                total_union: Set[int] = set()
                for s in cand_sets:
                    total_union.update(s)

                if len(total_union) <= 3:
                    continue  # No fins (already handled by the normal fish(3))

                total_union_list = sorted(total_union)

                for k_combo in itertools.combinations(total_union_list, 3):
                    k = set(k_combo)

                    # Collect the actual coordinates of the fins (candidates not in K), and which base line each fin came from
                    fin_cells: List[Cell] = []
                    lines_with_fin: Set[int] = set()
                    for li, line in enumerate(lines):
                        for cover in cand_sets[li]:
                            if cover in k:
                                continue
                            fin_cells.append((cover, line) if base_is_row else (line, cover))
                            lines_with_fin.add(li)

                    if len(fin_cells) == 0:
                        continue  # No fins (already handled by the normal fish(3))
                    if len(fin_cells) > 2:
                        continue  # 3 or more fins does not hold

                    fin_boxes = {box_index(c[0], c[1]) for c in fin_cells}
                    if len(fin_boxes) != 1:
                        continue  # Fins must fit within a single box
                    box = next(iter(fin_boxes))

                    # Determine Sashimi/Finned: if any of the lines that produced a fin
                    # has no candidate on the K side at all, it's Sashimi; if all of them do, it's Finned
                    is_sashimi = any(not any(cov in k for cov in cand_sets[li]) for li in lines_with_fin)
                    kind = "Sashimi" if is_sashimi else "Finned"

                    # Within the fin's box, from the column(s)/row(s) of K passing through that box,
                    # eliminate candidates on rows/columns other than the base lines
                    for cover in k:
                        passes_through_box = any(
                            (c[0] if base_is_row else c[1]) == cover for c in cells_of(Unit.BOX, box))
                        if not passes_through_box:
                            continue

                        for (x, y) in cells_of(Unit.BOX, box):
                            c2 = x if base_is_row else y
                            line2 = y if base_is_row else x
                            if c2 != cover:
                                continue
                            if line2 in lines:
                                continue
                            if not is_free(self.notes[d][x][y]):
                                continue
                            direction = "Horizontal" if base_is_row else "Vertical"
                            changed |= self._eliminate(
                                d, x, y, CellState.SASHIMI_FINNED_SWORDFISH,
                                f"{col_letter(x)}{y}  {kind} Swordfish ({direction}) removes <{d}>")
        return changed

    # ------------------------------------------------------------
    # Technique: 2 String Kite
    # ------------------------------------------------------------

    def two_string_kite(self) -> bool:
        changed = False
        for num in range(1, 10):
            for row in range(1, 10):
                row_cells = [x for x in range(1, 10) if is_free(self.notes[num][x][row])]
                if len(row_cells) != 2:
                    continue
                ax, bx = row_cells[0], row_cells[1]

                for col in range(1, 10):
                    col_cells = [y for y in range(1, 10) if is_free(self.notes[num][col][y])]
                    if len(col_cells) != 2:
                        continue
                    cy, dy = col_cells[0], col_cells[1]

                    if col == ax or col == bx or row == cy or row == dy:
                        continue

                    changed |= self._try_two_string_kite(num, ax, row, bx, col, cy, dy)
                    changed |= self._try_two_string_kite(num, ax, row, bx, col, dy, cy)
                    changed |= self._try_two_string_kite(num, bx, row, ax, col, cy, dy)
                    changed |= self._try_two_string_kite(num, bx, row, ax, col, dy, cy)
        return changed

    def _try_two_string_kite(self, num: int, row_end_x: int, row: int, other_row_end_x: int,
                              col: int, col_end_y: int, other_col_end_y: int) -> bool:
        if box_index(row_end_x, row) != box_index(col, col_end_y):
            return False
        tx, ty = other_row_end_x, other_col_end_y
        if not is_free(self.notes[num][tx][ty]):
            return False
        return self._eliminate(num, tx, ty, CellState.TWO_STRING_KITE,
                                f"{col_letter(tx)}{ty}  2 String Kite removes <{num}>")

    # ------------------------------------------------------------
    # Technique: Skyscraper
    # ------------------------------------------------------------

    def skyscraper(self) -> bool:
        changed = False
        for digit in range(1, 10):
            changed |= self._skyscraper_direction(digit, base_is_row=True)
            changed |= self._skyscraper_direction(digit, base_is_row=False)
        return changed

    def _skyscraper_direction(self, digit: int, base_is_row: bool) -> bool:
        changed = False
        base_unit = Unit.ROW if base_is_row else Unit.COL

        for base_idx in range(1, 10):
            covers = []
            for (x, y) in cells_of(base_unit, base_idx):
                if is_free(self.notes[digit][x][y]):
                    covers.append(x if base_is_row else y)
            if len(covers) != 2:
                continue
            c1, c2 = covers[0], covers[1]

            t1 = self._find_lone_candidate(digit, c1, base_idx, base_is_row)
            if t1 == 0:
                continue
            t2 = self._find_lone_candidate(digit, c2, base_idx, base_is_row)
            if t2 == 0 or t1 == t2:
                continue

            ax, ay = (c1, t1) if base_is_row else (t1, c1)
            bx, by = (c2, t2) if base_is_row else (t2, c2)
            changed |= self._eliminate_skyscraper(digit, ax, ay, bx, by)
        return changed

    def _find_lone_candidate(self, digit: int, cover: int, base_idx: int, base_is_row: bool) -> int:
        count = 0
        target = 0
        for i in range(1, 10):
            if i == base_idx:
                continue
            x, y = (cover, i) if base_is_row else (i, cover)
            if is_free(self.notes[digit][x][y]):
                count += 1
                target = i
        return target if count == 1 else 0

    def _eliminate_skyscraper(self, digit: int, ax: int, ay: int, bx: int, by: int) -> bool:
        changed = False
        for (x, y) in common_peers_of([(ax, ay), (bx, by)]):
            if is_free(self.notes[digit][x][y]):
                changed |= self._eliminate(digit, x, y, CellState.SKYSCRAPER,
                                            f"{col_letter(x)}{y}  Skyscraper removes <{digit}>")
        return changed

    # ------------------------------------------------------------
    # Empty Rectangle
    #
    # Within a single box B, if the cells where a digit can be placed fit entirely on
    # "one row R" and "one column C" (with at least one cell on each) -- an empty rectangle --
    # then if one end of a strong link outside B (a row/column with only 2 candidate cells) lies on R or C,
    # the digit can be eliminated from the cell where the other end A's row/column meets C/R.
    # ------------------------------------------------------------

    def empty_rectangle(self) -> bool:
        changed = False
        for digit in range(1, 10):
            for box in range(1, 10):
                changed |= self._empty_rectangle_in_box(digit, box)
        return changed

    def _empty_rectangle_in_box(self, digit: int, box: int) -> bool:
        box_cells = cells_of(Unit.BOX, box)
        candidates = [c for c in box_cells if is_free(self.notes[digit][c[0]][c[1]])]
        if len(candidates) < 2:
            return False

        box_rows = sorted({c[1] for c in box_cells})
        box_cols = sorted({c[0] for c in box_cells})

        changed = False
        for r in (r for r in box_rows if any(c[1] == r for c in candidates)):
            for c in (c for c in box_cols if any(cc[0] == c for cc in candidates)):
                # Whether all cells fit "on row R or column C"
                if not all(cell[0] == c or cell[1] == r for cell in candidates):
                    continue
                # If either the vertical arm or the horizontal arm has no cells, it's just a straight line
                # (equivalent to Locked Candidates) rather than a true empty rectangle, so exclude it.
                has_row_arm = any(cell[1] == r and cell[0] != c for cell in candidates)
                has_col_arm = any(cell[0] == c and cell[1] != r for cell in candidates)
                if not has_row_arm or not has_col_arm:
                    continue

                changed |= self._search_empty_rectangle_links(digit, box, r, c, box_rows, box_cols, candidates)
        return changed

    def _search_empty_rectangle_links(self, digit: int, box: int, r: int, c: int,
                                       box_rows: List[int], box_cols: List[int],
                                       candidates: List[Cell]) -> bool:
        changed = False

        # 4a) Strong link on an external column C'. If one end lies on row R, eliminate at the intersection of the other end A's row and C.
        for c_prime in range(1, 10):
            if c_prime in box_cols:
                continue  # Exclude the box's own columns (external columns only)

            link_cells = [cell for cell in cells_of(Unit.COL, c_prime) if is_free(self.notes[digit][cell[0]][cell[1]])]
            if len(link_cells) != 2:
                continue

            on_row_matches = [cell for cell in link_cells if cell[1] == r]
            if len(on_row_matches) != 1:
                continue  # No match, or (theoretically impossible but) both matching, is excluded
            a = link_cells[1] if link_cells[0] == on_row_matches[0] else link_cells[0]

            tx, ty = c, a[1]
            if box_index(tx, ty) == box:
                continue  # Exclude when the target is inside the box itself (the proof does not hold)
            if not is_free(self.notes[digit][tx][ty]):
                continue

            changed |= self._eliminate(
                digit, tx, ty, CellState.EMPTY_RECTANGLE,
                f"{col_letter(tx)}{ty}  Empty Rectangle (Block {box}, R={r}, C={col_letter(c)}, "
                f"strong link on external column {col_letter(c_prime)}) removes <{digit}>")

        # 4b) Strong link on an external row R'. If one end lies on column C, eliminate at the intersection of the other end A's column and R.
        for r_prime in range(1, 10):
            if r_prime in box_rows:
                continue  # Exclude the box's own rows (external rows only)

            link_cells = [cell for cell in cells_of(Unit.ROW, r_prime) if is_free(self.notes[digit][cell[0]][cell[1]])]
            if len(link_cells) != 2:
                continue

            on_col_matches = [cell for cell in link_cells if cell[0] == c]
            if len(on_col_matches) != 1:
                continue  # No match, or (theoretically impossible but) both matching, is excluded
            a = link_cells[1] if link_cells[0] == on_col_matches[0] else link_cells[0]

            tx, ty = a[0], r
            if box_index(tx, ty) == box:
                continue  # Exclude when the target is inside the box itself (the proof does not hold)
            if not is_free(self.notes[digit][tx][ty]):
                continue

            changed |= self._eliminate(
                digit, tx, ty, CellState.EMPTY_RECTANGLE,
                f"{col_letter(tx)}{ty}  Empty Rectangle (Block {box}, R={r}, C={col_letter(c)}, "
                f"strong link on external row {r_prime}) removes <{digit}>")
        return changed

    # ------------------------------------------------------------
    # Technique 6: XY-Wing
    # ------------------------------------------------------------

    def xy_wing(self) -> bool:
        changed = False
        bivalue = self._collect_bivalue_cells()

        for pivot in bivalue:
            px, py, pmask = pivot
            pivot_digits = mask_digits(pmask)
            wings = [c for c in bivalue if sees(px, py, c[0], c[1])]

            for i in range(len(wings)):
                for j in range(i + 1, len(wings)):
                    w1 = wings[i]
                    w2 = wings[j]

                    common1 = [d for d in pivot_digits if d in mask_digits(w1[2])]
                    common2 = [d for d in pivot_digits if d in mask_digits(w2[2])]
                    if len(common1) != 1 or len(common2) != 1 or common1[0] == common2[0]:
                        continue

                    w1_digits = mask_digits(w1[2])
                    w2_digits = mask_digits(w2[2])
                    wing_shared = [d for d in w1_digits if d in w2_digits]
                    if len(wing_shared) != 1:
                        continue
                    c = wing_shared[0]
                    if c in pivot_digits:
                        continue

                    targets = common_peers_of([(w1[0], w1[1]), (w2[0], w2[1])])
                    targets.discard((px, py))
                    for (x, y) in targets:
                        if is_free(self.notes[c][x][y]):
                            changed |= self._eliminate(c, x, y, CellState.XY_WING,
                                                        f"{col_letter(x)}{y}  XY-Wing removes <{c}>")
        return changed

    # ------------------------------------------------------------
    # Technique: XYZ-Wing
    # ------------------------------------------------------------

    def xyz_wing(self) -> bool:
        changed = False
        for ax in range(1, 10):
            for ay in range(1, 10):
                pivot_mask = self._candidate_mask(ax, ay)
                if pivot_mask.bit_count() != 3:
                    continue

                pincers_row_col = []
                for bx in range(1, 10):
                    if bx == ax:
                        continue
                    m = self._candidate_mask(bx, ay)
                    if m.bit_count() == 2 and (m & ~pivot_mask) == 0:
                        pincers_row_col.append((bx, ay, m))
                for by in range(1, 10):
                    if by == ay:
                        continue
                    m = self._candidate_mask(ax, by)
                    if m.bit_count() == 2 and (m & ~pivot_mask) == 0:
                        pincers_row_col.append((ax, by, m))
                if not pincers_row_col:
                    continue

                pincers_box = []
                for (cx, cy) in cells_of(Unit.BOX, box_index(ax, ay)):
                    if cx == ax and cy == ay:
                        continue
                    m = self._candidate_mask(cx, cy)
                    if m.bit_count() == 2 and (m & ~pivot_mask) == 0:
                        pincers_box.append((cx, cy, m))
                if not pincers_box:
                    continue

                for b in pincers_row_col:
                    for c in pincers_box:
                        if b[0] == c[0] and b[1] == c[1]:
                            continue
                        shared_mask = b[2] & c[2]
                        if shared_mask.bit_count() != 1:
                            continue
                        target_digit = mask_digits(shared_mask)[0]

                        cause_cells = [(ax, ay), (b[0], b[1]), (c[0], c[1])]
                        for (x, y) in common_peers_of(cause_cells):
                            if is_free(self.notes[target_digit][x][y]):
                                changed |= self._eliminate(
                                    target_digit, x, y, CellState.XYZ_WING,
                                    f"{col_letter(x)}{y}  XYZ-Wing removes <{target_digit}>")
        return changed

    # ------------------------------------------------------------
    # Technique 7: Remote Pairs
    # ------------------------------------------------------------

    def remote_pairs(self) -> bool:
        changed = False
        by_pair: Dict[int, List[Cell]] = {}
        for (x, y, mask) in self._collect_bivalue_cells():
            by_pair.setdefault(mask, []).append((x, y))

        for mask, cells in by_pair.items():
            if len(cells) < 4:
                continue
            digits = mask_digits(mask)

            adjacency = _build_adjacency(cells, lambda a, b: sees(a[0], a[1], b[0], b[1]))
            colors, components = _color_graph(adjacency, len(cells))

            for comp in components:
                for a in range(len(comp)):
                    for b in range(a + 1, len(comp)):
                        i, j = comp[a], comp[b]
                        if colors[i] == colors[j]:
                            continue
                        if j in adjacency[i]:
                            continue

                        for (x, y) in common_peers_of([cells[i], cells[j]]):
                            for d in digits:
                                if is_free(self.notes[d][x][y]):
                                    changed |= self._eliminate(
                                        d, x, y, CellState.REMOTE_PAIR,
                                        f"{col_letter(x)}{y}  Remote Pair removes <{d}>")
        return changed

    # ------------------------------------------------------------
    # Technique 8: Simple Coloring
    # ------------------------------------------------------------

    def simple_coloring(self) -> bool:
        changed = False
        for m in range(1, 10):
            cells = []
            for x in range(1, 10):
                for y in range(1, 10):
                    if is_free(self.notes[m][x][y]):
                        cells.append((x, y))
            n = len(cells)
            if n < 2:
                continue

            index = {c: i for i, c in enumerate(cells)}
            adjacency: List[List[int]] = [[] for _ in range(n)]

            for unit in (Unit.ROW, Unit.COL, Unit.BOX):
                for idx in range(1, 10):
                    in_unit = [c for c in cells_of(unit, idx) if is_free(self.notes[m][c[0]][c[1]])]
                    if len(in_unit) != 2:
                        continue
                    a = index[in_unit[0]]
                    b = index[in_unit[1]]
                    if b not in adjacency[a]:
                        adjacency[a].append(b)
                        adjacency[b].append(a)

            colors, components = _color_graph(adjacency, n)

            for comp in components:
                if len(comp) < 2:
                    continue

                contradicting_color = _find_contradicting_color(comp, cells, colors)
                if contradicting_color != -1:
                    for i in comp:
                        if colors[i] == contradicting_color:
                            continue
                        x, y = cells[i]
                        if self.board[x][y] == 0:
                            self._place(x, y, m, "Simple Coloring (Color Wrap)", Difficulty.CLEVER)
                            changed = True
                    continue

                comp_set = set(comp)
                for x in range(1, 10):
                    for y in range(1, 10):
                        if not is_free(self.notes[m][x][y]):
                            continue
                        self_idx = index.get((x, y))
                        if self_idx is not None and self_idx in comp_set:
                            continue

                        sees_color0 = any(colors[i] == 0 and sees(x, y, cells[i][0], cells[i][1]) for i in comp)
                        sees_color1 = any(colors[i] == 1 and sees(x, y, cells[i][0], cells[i][1]) for i in comp)
                        if sees_color0 and sees_color1:
                            changed |= self._eliminate(m, x, y, CellState.COLORING,
                                                        f"{col_letter(x)}{y}  Simple Coloring removes <{m}>")
        return changed

    # ------------------------------------------------------------
    # Technique 9: XY-Chain
    # ------------------------------------------------------------

    def xy_chain(self, max_length: int = 10 ** 9) -> bool:
        changed = False
        bivalue = [(x, y, mask_digits(mask)[0], mask_digits(mask)[1])
                   for (x, y, mask) in self._collect_bivalue_cells()]

        total = len(bivalue)
        if total < 3:
            return False

        adjacency: List[List[int]] = [[] for _ in range(total)]
        for i in range(total):
            for j in range(i + 1, total):
                a = bivalue[i]
                b = bivalue[j]
                if not sees(a[0], a[1], b[0], b[1]):
                    continue
                if a[2] == b[2] or a[2] == b[3] or a[3] == b[2] or a[3] == b[3]:
                    adjacency[i].append(j)
                    adjacency[j].append(i)

        for start in range(total):
            if not adjacency[start]:
                continue
            start_cell = bivalue[start]

            visited1 = [False] * total
            visited1[start] = True
            changed |= self._find_xy_chain(start, start, start_cell[2], start_cell[3], 1,
                                            bivalue, adjacency, visited1, [start], max_length)

            visited2 = [False] * total
            visited2[start] = True
            changed |= self._find_xy_chain(start, start, start_cell[3], start_cell[2], 1,
                                            bivalue, adjacency, visited2, [start], max_length)
        return changed

    def _find_xy_chain(self, start_idx: int, current_idx: int, lock_digit: int, start_unused_digit: int,
                        length: int, cells: List[Tuple[int, int, int, int]], adjacency: List[List[int]],
                        visited: List[bool], path: List[int], max_length: int) -> bool:
        if length >= max_length:
            return False

        changed = False
        start = cells[start_idx]

        for next_idx in adjacency[current_idx]:
            if visited[next_idx]:
                continue
            nxt = cells[next_idx]
            if nxt[2] != lock_digit and nxt[3] != lock_digit:
                continue

            next_lock = nxt[3] if nxt[2] == lock_digit else nxt[2]

            if length >= 3 and next_lock == start_unused_digit and sees(start[0], start[1], nxt[0], nxt[1]):
                full_chain = [(cells[idx][0], cells[idx][1]) for idx in path]
                full_chain.append((nxt[0], nxt[1]))
                return self._apply_xy_chain_elimination(start[0], start[1], nxt[0], nxt[1], next_lock)

            visited[next_idx] = True
            path.append(next_idx)
            changed |= self._find_xy_chain(start_idx, next_idx, next_lock, start_unused_digit,
                                            length + 1, cells, adjacency, visited, path, max_length)
            path.pop()
            visited[next_idx] = False
        return changed

    def _apply_xy_chain_elimination(self, sx: int, sy: int, ex: int, ey: int, digit: int) -> bool:
        changed = False
        for (x, y) in common_peers_of([(sx, sy), (ex, ey)]):
            if is_free(self.notes[digit][x][y]):
                changed |= self._eliminate(digit, x, y, CellState.XY_CHAIN,
                                            f"{col_letter(x)}{y}  XY-Chain removes <{digit}>")
        return changed

    # ------------------------------------------------------------
    # Technique 9 (continued): W-Wing
    # ------------------------------------------------------------

    def w_wing(self) -> bool:
        changed = False
        bivalue = self._collect_bivalue_cells()

        for i in range(len(bivalue)):
            for j in range(i + 1, len(bivalue)):
                c1 = bivalue[i]
                c2 = bivalue[j]
                if c1[2] != c2[2]:
                    continue
                if sees(c1[0], c1[1], c2[0], c2[1]):
                    continue

                digits = mask_digits(c1[2])
                d1, d2 = digits[0], digits[1]

                for (link_digit, erase_digit) in ((d1, d2), (d2, d1)):
                    if not self._has_w_wing_link(link_digit, c1[0], c1[1], c2[0], c2[1]):
                        continue

                    for (x, y) in common_peers_of([(c1[0], c1[1]), (c2[0], c2[1])]):
                        if is_free(self.notes[erase_digit][x][y]):
                            changed |= self._eliminate(
                                erase_digit, x, y, CellState.W_WING,
                                f"{col_letter(x)}{y}  W-Wing removes <{erase_digit}>")
        return changed

    def _has_w_wing_link(self, digit: int, x1: int, y1: int, x2: int, y2: int) -> bool:
        for unit in (Unit.ROW, Unit.COL, Unit.BOX):
            for idx in range(1, 10):
                cells = [c for c in cells_of(unit, idx) if self.notes[digit][c[0]][c[1]] == CellState.OPEN]
                if len(cells) != 2:
                    continue
                (rx1, ry1), (rx2, ry2) = cells[0], cells[1]

                match_a = sees(rx1, ry1, x1, y1) and sees(rx2, ry2, x2, y2)
                match_b = sees(rx1, ry1, x2, y2) and sees(rx2, ry2, x1, y1)
                if match_a or match_b:
                    return True
        return False

    # ------------------------------------------------------------
    # Common helpers related to ALS (Almost Locked Set)
    # ------------------------------------------------------------

    def _find_als_in_group(self, group: List[Cell]) -> Iterable[Tuple[List[Cell], int]]:
        open_cells = [c for c in group if self.board[c[0]][c[1]] == 0]
        m = len(open_cells)
        for q in range(1, m):
            for combo in itertools.combinations(open_cells, q):
                mask = 0
                for c in combo:
                    mask |= self._candidate_mask(c[0], c[1])
                if mask.bit_count() == q + 1:
                    yield list(combo), mask

    def _collect_als(self) -> List[AlsCandidate]:
        found: List[AlsCandidate] = []
        for unit in (Unit.ROW, Unit.COL, Unit.BOX):
            for idx in range(1, 10):
                group = cells_of(unit, idx)
                for (cells, mask) in self._find_als_in_group(group):
                    found.append(AlsCandidate(
                        house=unit,
                        house_index=idx,
                        size=len(cells),
                        mask=mask,
                        cells=cells,
                        cell_masks=[self._candidate_mask(c[0], c[1]) for c in cells],
                    ))

        seen: Set[FrozenSet[Cell]] = set()
        result: List[AlsCandidate] = []
        for als in found:
            key = als.cells_set
            if key not in seen:
                seen.add(key)
                result.append(als)
        return result

    @staticmethod
    def _all_in_one_house(cells: Sequence[Cell]) -> bool:
        n = len(cells)
        if n == 0:
            return False
        if n == 1:
            return True
        first_x, first_y = cells[0]
        same_row = same_col = same_box = True
        first_box = BOX_INDEX[(first_x, first_y)]
        for (x, y) in cells[1:]:
            if same_row and y != first_y:
                same_row = False
            if same_col and x != first_x:
                same_col = False
            if same_box and BOX_INDEX[(x, y)] != first_box:
                same_box = False
            if not (same_row or same_col or same_box):
                return False  # Can exit early once all 3 possibilities are confirmed false
        return True

    @staticmethod
    def _cells_with_digit(als: AlsCandidate, digit: int) -> List[Cell]:
        return als.cells_by_digit.get(digit, EMPTY_CELL_LIST)

    def _find_rcc_digits(self, a: AlsCandidate, b: AlsCandidate) -> List[int]:
        result: List[int] = []
        if a.cells_set & b.cells_set:
            return result  # Excluded if the cells overlap

        common = a.mask & b.mask
        for z in mask_digits(common):
            z_cells = self._cells_with_digit(a, z) + self._cells_with_digit(b, z)
            if self._all_in_one_house(z_cells):
                result.append(z)
        return result

    # ------------------------------------------------------------
    # ALS-XZ
    # ------------------------------------------------------------

    def als_xz(self) -> bool:
        als_list = self._collect_als()
        changed = False
        s = len(als_list)

        for i in range(s):
            a = als_list[i]
            for j in range(i + 1, s):
                b = als_list[j]

                common = a.mask & b.mask
                if common.bit_count() < 2:
                    continue

                rcc_digits = self._find_rcc_digits(a, b)
                if not rcc_digits:
                    continue

                common_digits = mask_digits(common)

                for z in rcc_digits:
                    for x_digit in common_digits:
                        if x_digit == z:
                            continue

                        x_cells = self._cells_with_digit(a, x_digit) + self._cells_with_digit(b, x_digit)
                        if not x_cells:
                            continue

                        common_peers = common_peers_of(x_cells)
                        if not common_peers:
                            continue

                        for (tx, ty) in common_peers:
                            if self.board[tx][ty] != 0:
                                continue
                            if self.notes[x_digit][tx][ty] != CellState.OPEN:
                                continue
                            changed |= self._eliminate(
                                x_digit, tx, ty, CellState.ALS_XZ,
                                f"{col_letter(tx)}{ty}  ALS-XZ (RCC<{z}>, "
                                f"ALS {unit_name(a.house)}{a.house_index}+{unit_name(b.house)}{b.house_index}) "
                                f"removes <{x_digit}>")
        return changed

    # ------------------------------------------------------------
    # Grouped X-Chain / Grouped X-Cycle
    #
    # The same algorithm as the C# version (including fixes for 2 bugs that were found there).
    # - Strong link: a relationship where, within a house, the "nodes" for that digit are limited to exactly two
    # - Node: a set of 1-3 candidate cells lined up in a single column or row within one box
    #   (for row/column houses, the segment within each box that the house spans automatically becomes one node.
    #    for box houses, among the box's 3 rows and 3 columns, find two disjoint lines that together
    #    cover all the candidate cells exactly, and if found, those two lines become the two nodes)
    # - Weak link: a relationship where a common house exists that fully contains each of the two nodes
    #   (it is not enough for only part of a node's cells to belong to the house; for details see
    #   the comment on _find_weak_link_house())
    #
    # Starting from a strong link, the chain is extended alternately as strong link -> weak link -> strong link -> ...,
    # and the digit is removed from cells seen simultaneously by the nodes at both ends of the chain (a normal chain).
    # If the chain loops back to the starting node, it becomes a Grouped X-Cycle, and in each house
    # that one of the loop's weak links belongs to, the digit can be removed from every other cell not part of the loop.
    #
    # As soon as any elimination succeeds, the search stops with no further exploration.
    # From the auto-solver, this is called while raising the maximum number of nodes
    # allowed in the chain from 3 up to 10, one at a time.
    # ------------------------------------------------------------

    def grouped_x_chain(self, max_nodes: int = 10 ** 9) -> bool:
        for digit in range(1, 10):
            strong_links = self._collect_grouped_strong_links(digit)
            if not strong_links:
                continue

            for link in strong_links:
                for start, next_node in ((link.a, link.b), (link.b, link.a)):
                    path: List[GNode] = [start, next_node]
                    used_cells: Set[Cell] = set(start.cells)
                    used_cells.update(next_node.cells)
                    weak_houses: List[Tuple[Unit, int]] = []
                    first_house = (link.house_unit, link.house_index)
                    if self._explore_grouped_chain(digit, path, used_cells, weak_houses,
                                                    first_house, first_house, strong_links,
                                                    max(2, max_nodes)):
                        return True  # Stop the whole search as soon as the first elimination is found (per the user's instruction)
        return False

    def _explore_grouped_chain(self, digit: int, path: List[GNode], used_cells: Set[Cell],
                                weak_houses: List[Tuple[Unit, int]], last_strong_house: Tuple[Unit, int],
                                first_strong_house: Tuple[Unit, int], strong_links: List["GStrongLink"],
                                max_nodes: int) -> bool:
        """
        A recursive search that extends the chain from the node at the end of path, alternating
        weak link -> strong link. last_strong_house: the house of the immediately preceding
        strong link (the next weak link must differ from this). first_strong_house: the house
        of the chain's first strong link (when looping back to the start as a cycle, that weak
        link must also differ from this). used_cells: the accumulated cells of every node used

        so far in the chain.
        [Important] Forbidding node reuse cannot rely only on whether the nodes themselves match
        (the same cell set). E.g., if a single-cell node {E5} is used on the path and later a
        2-cell node {D5,E5} (which includes E5) from a different box house is connected as a
        "different node", the truth value of cell E5 ends up being handled twice, separately, in
        the chain, breaking the logic -- so this uses the same cell-level check as ALS-XY-Chain: don't reuse a node overlapping any cell already used on the path.
        """
        current = path[-1]
        start = path[0]

        # 1) Cycle check: with 2 or more strong links already used, can we get back to the start node via a weak link?
        if len(path) >= 4:
            cycle_house = _find_weak_link_house(current, start, last_strong_house, first_strong_house)
            if cycle_house is not None:
                weak_houses.append(cycle_house)
                cycle_found = self._try_apply_grouped_x_cycle(digit, path, weak_houses)
                weak_houses.pop()
                if cycle_found:
                    return True

        if len(path) >= max_nodes:
            return False  # Do not extend the chain any further

        # 2) Normal chain: look for whether we can connect to another strong link via a weak link
        for link in strong_links:
            for near_end, far_end in ((link.a, link.b), (link.b, link.a)):
                # Don't use a node that overlaps even one cell already used on the path (returning to the start is already handled above as a cycle)
                if (near_end.cell_set & used_cells) or (far_end.cell_set & used_cells):
                    continue

                link_house = (link.house_unit, link.house_index)
                weak_house = _find_weak_link_house(current, near_end, last_strong_house, link_house)
                if weak_house is None:
                    continue

                path.append(near_end)
                path.append(far_end)
                used_cells.update(near_end.cells)
                used_cells.update(far_end.cells)
                weak_houses.append(weak_house)

                found = self._try_apply_grouped_chain_elimination(digit, start, far_end, path)
                if not found:
                    found = self._explore_grouped_chain(digit, path, used_cells, weak_houses, link_house,
                                                          first_strong_house, strong_links, max_nodes)

                weak_houses.pop()
                used_cells.difference_update(far_end.cells)
                used_cells.difference_update(near_end.cells)
                path.pop()
                path.pop()

                if found:
                    return True
        return False

    def _try_apply_grouped_chain_elimination(self, digit: int, start: GNode, end: GNode,
                                              path: List[GNode]) -> bool:
        """Attempts elimination for a normal chain (start and end are different nodes).
        Removes the digit from cells seen simultaneously by both end nodes (the intersection
        of their respective common_peers_of results), excluding cells that make up the chain itself."""
        peers_of_start = common_peers_of(start.cells)
        if not peers_of_start:
            return False
        peers_of_end = common_peers_of(end.cells)
        if not peers_of_end:
            return False

        chain_cells: Set[Cell] = set()
        for n in path:
            chain_cells.update(n.cells)

        desc = "-".join(str(n) for n in path)

        changed = False
        for (tx, ty) in peers_of_start:
            if (tx, ty) not in peers_of_end:
                continue
            if (tx, ty) in chain_cells:  # Don't target cells that are part of the chain itself
                continue
            if self.board[tx][ty] != 0:
                continue
            if self.notes[digit][tx][ty] != CellState.OPEN:
                continue
            changed |= self._eliminate(digit, tx, ty, CellState.GROUPED_X_CHAIN,
                                        f"{col_letter(tx)}{ty}  Grouped X-Chain ({desc}) removes <{digit}>")
        return changed

    def _try_apply_grouped_x_cycle(self, digit: int, path: List[GNode],
                                    weak_houses: List[Tuple[Unit, int]]) -> bool:
        """Attempts elimination for a Grouped X-Cycle (loop). In each house that one of the
        loop's weak links belongs to, removes the digit from every other cell not part of the loop (nodes)."""
        cycle_cells: Set[Cell] = set()
        for n in path:
            cycle_cells.update(n.cells)

        desc = "-".join(str(n) for n in path) + "-(loop)"

        changed = False
        for (house_unit, house_idx) in weak_houses:
            for (x, y) in cells_of(house_unit, house_idx):
                if (x, y) in cycle_cells:
                    continue
                if self.board[x][y] != 0:
                    continue
                if self.notes[digit][x][y] != CellState.OPEN:
                    continue
                changed |= self._eliminate(digit, x, y, CellState.GROUPED_X_CHAIN,
                                            f"{col_letter(x)}{y}  Grouped X-Cycle ({desc}) removes <{digit}>")
        return changed

    def _collect_grouped_strong_links(self, digit: int) -> List["GStrongLink"]:
        """Collects all grouped strong links for the given digit from across the entire board."""
        links: List[GStrongLink] = []
        for unit in (Unit.ROW, Unit.COL, Unit.BOX):
            for idx in range(1, 10):
                nodes = self._find_grouped_nodes(unit, idx, digit)
                if len(nodes) == 2:
                    links.append(GStrongLink(a=nodes[0], b=nodes[1], house_unit=unit, house_index=idx))
        return links

    def _find_grouped_nodes(self, unit: Unit, idx: int, digit: int) -> List[GNode]:
        """Finds the list of nodes (1-3 cell line-shaped sets) for the given house and digit."""
        cells = [c for c in cells_of(unit, idx) if is_free(self.notes[digit][c[0]][c[1]])]
        if not cells:
            return []

        if unit != Unit.BOX:
            # Row/column house: splitting by box directly gives the cells lined up along this house's direction
            groups: Dict[int, List[Cell]] = {}
            for c in cells:
                groups.setdefault(box_index(c[0], c[1]), []).append(c)
            return [_make_gnode(g, digit) for g in groups.values()]

        # Box house: among the box's 3 rows and 3 columns, list only the rows/columns that have candidate cells as "line candidates",
        # then look for a pair of two that covers all candidate cells exactly, with no overlap.
        ys = sorted({c[1] for c in cells})
        xs = sorted({c[0] for c in cells})
        row_lines = [[c for c in cells if c[1] == y] for y in ys]
        col_lines = [[c for c in cells if c[0] == x] for x in xs]
        line_candidates = row_lines + col_lines

        for i in range(len(line_candidates)):
            for j in range(i + 1, len(line_candidates)):
                l1, l2 = line_candidates[i], line_candidates[j]
                if any(c in l2 for c in l1):
                    continue  # The intersection cell must not be a candidate
                if len(l1) + len(l2) != len(cells):
                    continue  # Check whether it covers exactly, with nothing missing or extra
                return [_make_gnode(l1, digit), _make_gnode(l2, digit)]
        return []  # If it can't be split into 2 nodes, this box has no strong link

    # ------------------------------------------------------------
    # ALS-XY-Wing
    # ------------------------------------------------------------

    def als_xy_wing(self) -> bool:
        als_list = self._collect_als()
        s = len(als_list)
        changed = False

        rcc_cache: Dict[Tuple[int, int], List[int]] = {}
        for i in range(s):
            for j in range(i + 1, s):
                digits = self._find_rcc_digits(als_list[i], als_list[j])
                if digits:
                    rcc_cache[(i, j)] = digits

        def get_rcc(i: int, j: int) -> List[int]:
            key = (i, j) if i < j else (j, i)
            return rcc_cache.get(key, EMPTY_INT_LIST)

        for di in range(s):
            d = als_list[di]
            for ei in range(s):
                if ei == di:
                    continue
                rcc_de = get_rcc(di, ei)
                if not rcc_de:
                    continue
                e = als_list[ei]

                for fi in range(ei + 1, s):
                    if fi == di:
                        continue
                    rcc_df = get_rcc(di, fi)
                    if not rcc_df:
                        continue
                    f = als_list[fi]

                    if e.cells_set & f.cells_set:
                        continue

                    for x1 in rcc_de:
                        for x2 in rcc_df:
                            if x1 == x2:
                                continue

                            common_ef = e.mask & f.mask
                            for w in mask_digits(common_ef):
                                if w == x1 or w == x2:
                                    continue

                                w_cells = self._cells_with_digit(e, w) + self._cells_with_digit(f, w)
                                if not w_cells:
                                    continue

                                common_peers = common_peers_of(w_cells)
                                if not common_peers:
                                    continue

                                for (tx, ty) in common_peers:
                                    if self.board[tx][ty] != 0:
                                        continue
                                    if self.notes[w][tx][ty] != CellState.OPEN:
                                        continue
                                    changed |= self._eliminate(
                                        w, tx, ty, CellState.ALS_XY_WING,
                                        f"{col_letter(tx)}{ty}  ALS-XY-Wing "
                                        f"(D={unit_name(d.house)}{d.house_index}, RCC<{x1}>/<{x2}>) removes <{w}>")
        return changed

    # ------------------------------------------------------------
    # ALS-XY-Chain
    # ------------------------------------------------------------

    def als_xy_chain(self, max_als_count: int = 10 ** 9) -> bool:
        als_list = self._collect_als()
        s = len(als_list)
        if s < 3:
            return False

        rcc_cache: Dict[Tuple[int, int], List[int]] = {}
        for i in range(s):
            for j in range(i + 1, s):
                digits = self._find_rcc_digits(als_list[i], als_list[j])
                if digits:
                    rcc_cache[(i, j)] = digits

        def get_rcc(i: int, j: int) -> List[int]:
            key = (i, j) if i < j else (j, i)
            return rcc_cache.get(key, EMPTY_INT_LIST)

        changed = False
        for start in range(s):
            visited = [False] * s
            visited[start] = True
            used_cells: Set[Cell] = set(als_list[start].cells)
            changed |= self._extend_als_chain(start, start, -1, [], [start], als_list, get_rcc,
                                               visited, max(3, max_als_count), used_cells)
        return changed

    def _extend_als_chain(self, start_idx: int, current_idx: int, last_digit: int,
                           used_digits: List[int], path: List[int], als_list: List[AlsCandidate],
                           get_rcc: Callable[[int, int], List[int]], visited: List[bool],
                           max_als_count: int, used_cells: Set[Cell]) -> bool:
        if len(path) >= max_als_count:
            return False

        changed = False
        a = als_list[start_idx]

        for next_idx in range(len(als_list)):
            if visited[next_idx]:
                continue
            candidate = als_list[next_idx]

            # Whether it shares no cells with any ALS already on the path (replaced with an
            # O(1) intersection test against the accumulated used_cells, consolidating what used to be a
            # per-path-length loop of _als_shares_cell() calls into a single set operation).
            if candidate.cells_set & used_cells:
                continue

            rcc_digits = get_rcc(current_idx, next_idx)
            if not rcc_digits:
                continue

            for rcc in rcc_digits:
                if rcc == last_digit:
                    continue

                path.append(next_idx)
                visited[next_idx] = True
                used_digits.append(rcc)
                used_cells |= candidate.cells_set

                if len(path) >= 3:
                    common_mask = a.mask & candidate.mask
                    for z in mask_digits(common_mask):
                        if z in used_digits:
                            continue
                        changed |= self._try_apply_als_xy_chain_elimination(
                            a, candidate, z, als_list, path, used_digits)

                changed |= self._extend_als_chain(start_idx, next_idx, rcc, used_digits, path,
                                                   als_list, get_rcc, visited, max_als_count, used_cells)

                used_cells -= candidate.cells_set
                used_digits.pop()
                visited[next_idx] = False
                path.pop()
        return changed

    def _try_apply_als_xy_chain_elimination(self, a: AlsCandidate, g: AlsCandidate, z: int,
                                             als_list: List[AlsCandidate], path: List[int],
                                             used_digits: List[int]) -> bool:
        z_cells = self._cells_with_digit(a, z) + self._cells_with_digit(g, z)
        if not z_cells:
            return False

        common_peers = common_peers_of(z_cells)
        if not common_peers:
            return False

        chain_cell_set: Set[Cell] = set()
        for idx in path:
            chain_cell_set.update(als_list[idx].cells)
        chain_desc = _build_als_chain_description(path, used_digits, als_list)

        changed = False
        for (tx, ty) in common_peers:
            if (tx, ty) in chain_cell_set:
                continue
            if self.board[tx][ty] != 0:
                continue
            if self.notes[z][tx][ty] != CellState.OPEN:
                continue
            changed |= self._eliminate(z, tx, ty, CellState.ALS_XY_CHAIN,
                                        f"{col_letter(tx)}{ty}  ALS-XY-Chain ({chain_desc}) removes <{z}>")
        return changed

    # ------------------------------------------------------------
    # AIC (Alternating Inference Chain)
    # ------------------------------------------------------------

    def _collect_aic_strong_links(self) -> List[Tuple[AicNode, AicNode]]:
        links: List[Tuple[AicNode, AicNode]] = []
        seen: Set[Tuple[AicNode, AicNode]] = set()

        def add_link(a: AicNode, b: AicNode) -> None:
            key = (a, b) if a <= b else (b, a)
            if key not in seen:
                seen.add(key)
                links.append(key)

        for unit in (Unit.ROW, Unit.COL, Unit.BOX):
            for idx in range(1, 10):
                for z in range(1, 10):
                    found = []
                    for (x, y) in cells_of(unit, idx):
                        if is_free(self.notes[z][x][y]):
                            found.append((x, y))
                            if len(found) > 2:
                                break
                    if len(found) == 2:
                        add_link(AicNode(found[0][0], found[0][1], z), AicNode(found[1][0], found[1][1], z))

        for (x, y, mask) in self._collect_bivalue_cells():
            digits = mask_digits(mask)
            add_link(AicNode(x, y, digits[0]), AicNode(x, y, digits[1]))

        return links

    @staticmethod
    def _build_aic_adjacency(links: List[Tuple[AicNode, AicNode]]) -> Dict[AicNode, List[AicNode]]:
        adjacency: Dict[AicNode, List[AicNode]] = {}

        def add(frm: AicNode, to: AicNode) -> None:
            adjacency.setdefault(frm, []).append(to)

        for (a, b) in links:
            add(a, b)
            add(b, a)
        return adjacency

    def aic(self) -> bool:
        strong_links = self._collect_aic_strong_links()
        if not strong_links:
            return False
        adjacency = self._build_aic_adjacency(strong_links)

        for max_strong in range(2, 6):
            for (link_a, link_b) in strong_links:
                for (start, anchor_other) in ((link_a, link_b), (link_b, link_a)):
                    path = [start]
                    visited = {start, anchor_other}
                    if self._explore_aic(path, visited, "weak", 0, max_strong, adjacency, anchor_other):
                        return True
        return False

    def _explore_aic(self, path: List[AicNode], visited: Set[AicNode], next_type: str,
                      strong_count: int, max_strong: int, adjacency: Dict[AicNode, List[AicNode]],
                      anchor_other: AicNode) -> bool:
        current = path[-1]
        prev = path[-2] if len(path) >= 2 else None

        if next_type == "weak":
            mask = self._candidate_mask(current.x, current.y)
            for d in mask_digits(mask):
                if d == current.digit:
                    continue
                nxt = AicNode(current.x, current.y, d)
                if prev is not None and nxt == prev:
                    continue
                if self._try_aic_advance(path, visited, nxt, "weak", strong_count, max_strong,
                                          adjacency, anchor_other):
                    return True

            for unit in (Unit.ROW, Unit.COL, Unit.BOX):
                if unit == Unit.ROW:
                    idx = current.y
                elif unit == Unit.COL:
                    idx = current.x
                else:
                    idx = box_index(current.x, current.y)
                for (x, y) in cells_of(unit, idx):
                    if x == current.x and y == current.y:
                        continue
                    if not is_free(self.notes[current.digit][x][y]):
                        continue
                    nxt = AicNode(x, y, current.digit)
                    if prev is not None and nxt == prev:
                        continue
                    if self._try_aic_advance(path, visited, nxt, "weak", strong_count, max_strong,
                                              adjacency, anchor_other):
                        return True
        else:  # strong
            if strong_count >= max_strong:
                return False
            for nxt in adjacency.get(current, []):
                if prev is not None and nxt == prev:
                    continue
                if self._try_aic_advance(path, visited, nxt, "strong", strong_count, max_strong,
                                          adjacency, anchor_other):
                    return True
        return False

    def _try_aic_advance(self, path: List[AicNode], visited: Set[AicNode], nxt: AicNode,
                          arrived_via: str, strong_count: int, max_strong: int,
                          adjacency: Dict[AicNode, List[AicNode]], anchor_other: AicNode) -> bool:
        start = path[0]
        new_strong_count = strong_count + (1 if arrived_via == "strong" else 0)

        if nxt == start:
            if arrived_via == "weak":
                return self._try_apply_aic_self_contradiction_delete(start, path)
            return self._try_apply_aic_continuous_nice_loop(path)

        if nxt in visited:
            return False

        if (arrived_via == "strong" and nxt.digit == anchor_other.digit
                and not (nxt.x == anchor_other.x and nxt.y == anchor_other.y)
                and sees(nxt.x, nxt.y, anchor_other.x, anchor_other.y)):
            if self._try_apply_aic_normal(anchor_other, nxt, path):
                return True

        path.append(nxt)
        visited.add(nxt)
        next_type = "strong" if arrived_via == "weak" else "weak"
        found = self._explore_aic(path, visited, next_type, new_strong_count, max_strong, adjacency, anchor_other)
        if not found:
            path.pop()
            visited.discard(nxt)
        return found

    @staticmethod
    def _aic_chain_cells(path: List[AicNode], tail: Optional[AicNode] = None,
                          head: Optional[AicNode] = None) -> List[Cell]:
        cells: List[Cell] = []
        if head is not None:
            cells.append((head.x, head.y))
        cells.extend((n.x, n.y) for n in path)
        if tail is not None:
            cells.append((tail.x, tail.y))
        return cells

    @staticmethod
    def _aic_chain_desc(path: List[AicNode], tail: Optional[AicNode] = None,
                         head: Optional[AicNode] = None) -> str:
        nodes = []
        if head is not None:
            nodes.append(head)
        nodes.extend(path)
        if tail is not None:
            nodes.append(tail)
        return "-".join(str(n) for n in nodes)

    def _try_apply_aic_normal(self, reference: AicNode, end: AicNode, path: List[AicNode]) -> bool:
        path_cells = set(self._aic_chain_cells(path, end, reference))

        targets = [t for t in common_peers_of([(reference.x, reference.y), (end.x, end.y)])
                   if t not in path_cells and is_free(self.notes[reference.digit][t[0]][t[1]])]
        if not targets:
            return False

        desc = self._aic_chain_desc(path, end, reference)
        changed = False
        for (x, y) in targets:
            changed |= self._eliminate(reference.digit, x, y, CellState.AIC,
                                        f"{col_letter(x)}{y}  AIC ({desc}) removes <{reference.digit}>")
        return changed

    def _try_apply_aic_continuous_nice_loop(self, path: List[AicNode]) -> bool:
        n = len(path)
        path_cells = {(p.x, p.y) for p in path}

        digits_in_loop_by_cell: Dict[Cell, Set[int]] = {}
        for node in path:
            cell = (node.x, node.y)
            digits_in_loop_by_cell.setdefault(cell, set()).add(node.digit)

        desc = self._aic_chain_desc(path, path[0])
        changed = False

        for i in range(n):
            link_index = i + 1
            if link_index % 2 == 0:
                continue  # Even index = strong link, so skip

            p = path[i]
            q = path[(i + 1) % n]

            if p.x == q.x and p.y == q.y:
                in_loop = digits_in_loop_by_cell[(p.x, p.y)]
                mask = self._candidate_mask(p.x, p.y)
                for d in mask_digits(mask):
                    if d in in_loop:
                        continue
                    changed |= self._eliminate(d, p.x, p.y, CellState.AIC,
                                                f"{col_letter(p.x)}{p.y}  AIC Nice Loop ({desc}) removes <{d}>")
            else:
                digit = p.digit
                for (x, y) in common_peers_of([(p.x, p.y), (q.x, q.y)]):
                    if (x, y) in path_cells:
                        continue
                    if not is_free(self.notes[digit][x][y]):
                        continue
                    changed |= self._eliminate(digit, x, y, CellState.AIC,
                                                f"{col_letter(x)}{y}  AIC Nice Loop ({desc}) removes <{digit}>")
        return changed

    def _try_apply_aic_self_contradiction_delete(self, start: AicNode, path: List[AicNode]) -> bool:
        if not is_free(self.notes[start.digit][start.x][start.y]):
            return False
        desc = self._aic_chain_desc(path)
        return self._eliminate(start.digit, start.x, start.y, CellState.AIC,
                                f"{col_letter(start.x)}{start.y}  AIC ({desc}) removes <{start.digit}> "
                                f"(self-contradiction)")

    # ------------------------------------------------------------
    # Auto-solve
    # ------------------------------------------------------------

    def solve_all(self) -> SolveResult:
        log_start_index = len(self.log)

        changed = True
        while changed and not self.is_solved:
            changed = self.naked_single()               # Trivial
            changed |= self.hidden_single()              # Simple
            if not changed:
                changed |= self.locked_candidates()       # Easy
            if not changed:
                changed |= self.naked_subsets()           # Moderate
            if not changed:
                changed |= self.fish(2)                   # Clever (X-Wing)
            if not changed:
                changed |= self.skyscraper()              # Clever
            if not changed:
                changed |= self.two_string_kite()         # Clever
            if not changed:
                changed |= self.empty_rectangle()         # Clever
            if not changed:
                changed |= self.simple_coloring()         # Tricky
            if not changed:
                changed |= self.remote_pairs()            # Tricky
            if not changed:
                changed |= self.w_wing()                  # Tricky
            if not changed:
                changed |= self.fish(3)                   # Hard (Swordfish)
            if not changed:
                changed |= self.sashimi_finned_x_wing()   # Hard
            if not changed:
                changed |= self.xy_wing()                 # Hard
            if not changed:
                changed |= self.fish(4)                   # Expert (Jerryfish)
            if not changed:
                changed |= self.sashimi_finned_swordfish()  # Expert
            if not changed:
                changed |= self.xyz_wing()                # Expert
            if not changed:
                for max_len in range(3, 11):
                    changed |= self.xy_chain(max_len)     # Expert
                    if changed:
                        break
            if not changed:
                changed |= self.als_xz()                  # Genius
            if not changed:
                # Since longer chains mean more combinations, following the same idea as XyChain/ALS-XY-Chain,
                # try raising the max node count from 3 to 10 one at a time (preferring shorter chains).
                for max_nodes in range(3, 11):
                    changed |= self.grouped_x_chain(max_nodes)  # Genius
                    if changed:
                        break
            if not changed:
                changed |= self.als_xy_wing()              # Genius
            if not changed:
                for max_als in range(3, 7):
                    changed |= self.als_xy_chain(max_als)  # Insane
                    if changed:
                        break
            if not changed:
                changed |= self.aic()                      # Insane
            if self.has_contradiction:
                break

        steps_this_run = self.log[log_start_index:]
        usage: Dict[str, int] = {}
        for e in steps_this_run:
            usage[e.technique] = usage.get(e.technique, 0) + 1
        difficulty = max((e.tier for e in steps_this_run), default=Difficulty.TRIVIAL)

        return SolveResult(
            solved=self.is_solved,
            difficulty=difficulty,
            technique_usage=usage,
            has_contradiction=self.has_contradiction,
            contradiction_message=self.contradiction_message,
        )

    # ------------------------------------------------------------
    # Export / Import
    # ------------------------------------------------------------

    def export_string(self) -> str:
        chars = []
        for y in range(1, 10):
            for x in range(1, 10):
                chars.append(str(self.board[x][y]))
        return "".join(chars)

    @staticmethod
    def parse_import_string(s: str) -> List[List[int]]:
        givens = [[0] * 10 for _ in range(10)]
        if len(s) != 81:
            return givens
        for y in range(1, 10):
            for x in range(1, 10):
                ch = s[(y - 1) * 9 + (x - 1)]
                givens[x][y] = int(ch)
        return givens


# ============================================================
# Node for AIC (corresponds to the C# AicNode. Treated as a lightweight value type via tuple inheritance)
# ============================================================

class AicNode(Tuple[int, int, int]):
    """An AIC node = (cell, digit). Treated as a 3-tuple (x, y, digit)."""

    def __new__(cls, x: int, y: int, digit: int):
        return super().__new__(cls, (x, y, digit))

    @property
    def x(self) -> int:
        return self[0]

    @property
    def y(self) -> int:
        return self[1]

    @property
    def digit(self) -> int:
        return self[2]

    def __str__(self) -> str:
        return f"{col_letter(self.x)}{self.y}<{self.digit}>"


# ============================================================
# Free-function helpers (called in common from multiple techniques)
# ============================================================

def common_peers_of(cells: Sequence[Cell]) -> Set[Cell]:
    """Finds the cells seen in common by all the given cells (excluding themselves)."""
    result: Optional[Set[Cell]] = None
    for c in cells:
        p = set(peers(c[0], c[1]))
        result = p if result is None else (result & p)
    return result if result is not None else set()


def _build_adjacency(items: List[Cell], are_linked: Callable[[Cell, Cell], bool]) -> List[List[int]]:
    n = len(items)
    adjacency: List[List[int]] = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if are_linked(items[i], items[j]):
                adjacency[i].append(j)
                adjacency[j].append(i)
    return adjacency


def _color_graph(adjacency: List[List[int]], n: int) -> Tuple[List[int], List[List[int]]]:
    """Splits the graph into connected components and alternately 2-colors within each component. Isolated points are not included in any component."""
    colors = [-1] * n
    components: List[List[int]] = []

    for start in range(n):
        if colors[start] != -1 or not adjacency[start]:
            continue

        comp = [start]
        colors[start] = 0
        queue = [start]
        head = 0
        while head < len(queue):
            cur = queue[head]
            head += 1
            for nxt in adjacency[cur]:
                if colors[nxt] != -1:
                    continue
                colors[nxt] = 1 - colors[cur]
                queue.append(nxt)
                comp.append(nxt)
        components.append(comp)
    return colors, components


def _find_contradicting_color(comp: List[int], cells: List[Cell], colors: List[int]) -> int:
    bad0 = bad1 = False
    for a in range(len(comp)):
        for b in range(a + 1, len(comp)):
            i, j = comp[a], comp[b]
            if colors[i] != colors[j]:
                continue
            x1, y1 = cells[i]
            x2, y2 = cells[j]
            if not sees(x1, y1, x2, y2):
                continue
            if colors[i] == 0:
                bad0 = True
            else:
                bad1 = True
    if bad0 and not bad1:
        return 0
    if bad1 and not bad0:
        return 1
    return -1


def _als_shares_cell(a: AlsCandidate, b: AlsCandidate) -> bool:
    return bool(a.cells_set & b.cells_set)


def _build_als_chain_description(path: List[int], used_digits: List[int], als_list: List[AlsCandidate]) -> str:
    parts = []
    for i, idx in enumerate(path):
        als = als_list[idx]
        parts.append(f"{unit_name(als.house)}{als.house_index}")
        if i < len(used_digits):
            parts.append(f"-<{used_digits[i]}>-")
    return "".join(parts)


# ============================================================
# CLI
# ============================================================

def _format_board(board: List[List[int]]) -> str:
    """Formats a 9x9 board as text, laid out in a table bordered by lines every 3x3 block.
    Column labels (A-I) are shown at the top, row labels (1-9) in the leftmost column. Unplaced cells are shown as a single blank space.

    Example layout:
          A B C   D E F   G H I
        +-------+-------+-------+
      1 | 4 . . | . . . | 2 . . |
      2 | . . 1 | . 9 . | . . 3 |
      3 | 2 . 4 | 3 . . | . 5 . |
        +-------+-------+-------+
        ...

    The row label plus separator "Y |" is 3 characters, the cell area is 9 cells plus 8
    separators = 17 characters, and the final border "|" is 1 character, for a total of
    3+17+1=21 characters that is kept consistent throughout (the header row and border rows are also built to the same 21-character width, so columns never drift out of alignment).
    """

    def block_row(cells: Sequence[str], block_sep: str) -> str:
        # cells: a list of 9 single-character strings. Only every 3rd boundary uses block_sep; otherwise a half-width space is used as the separator.
        out = []
        for i, c in enumerate(cells):
            out.append(c)
            if i < 8:
                out.append(block_sep if (i + 1) % 3 == 0 else " ")
        return "".join(out)

    def hline() -> str:
        parts = []
        for i in range(9):
            parts.append("-")
            if i < 8:
                parts.append("+" if (i + 1) % 3 == 0 else "-")
        return "  +" + "".join(parts) + "+"

    lines = []
    lines.append("   " + block_row(list("ABCDEFGHI"), " ") + " ")
    lines.append(hline())
    for y in range(1, 10):
        row_cells = [str(board[x][y]) if board[x][y] != 0 else " " for x in range(1, 10)]
        lines.append(f"{y} |" + block_row(row_cells, "|") + "|")
        if y % 3 == 0:
            lines.append(hline())
    return "\n".join(lines)


def _read_puzzle_string(raw: str) -> str:
    """Strips whitespace/newlines (not counted among the 81 characters) and replaces '.' with '0'."""
    cleaned = "".join(ch for ch in raw if not ch.isspace())
    cleaned = cleaned.replace(".", "0")
    return cleaned


def _solve_and_print_one(puzzle_str: str, show_answer_board: bool, quiet_log: bool) -> int:
    """Solves one puzzle and prints the result. If the puzzle string is malformed, prints
    a message to stderr and returns 1 (the caller uses this to decide whether to abort)."""
    if len(puzzle_str) != 81 or not all(ch.isdigit() for ch in puzzle_str):
        print(f"[Error] The puzzle must be an 81-character digit string (0 or '.' for blanks)"
              f" (received length: {len(puzzle_str)})", file=sys.stderr)
        return 1

    engine = SudokuEngine()
    givens = SudokuEngine.parse_import_string(puzzle_str)
    engine.initialize(givens)
    result = engine.solve_all()

    answer = engine.export_string()

    print(f"[Answer] {answer}")
    print(f"[Solved] {result.solved}")
    print(f"[Difficulty] {result.difficulty.name.capitalize()}")
    if result.has_contradiction:
        print(f"[Contradiction] {result.contradiction_message}")

    if show_answer_board:
        print()
        print(_format_board(engine.board))

    if not quiet_log:
        print()
        for entry in engine.log:
            print(str(entry))

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="SudokuSolver.py",
        description="A CLI tool that analyzes and auto-solves Sudoku puzzles and rates their difficulty.",
        add_help=False,  # To make both -h/-H work, register help manually instead of using the auto-added one
    )
    parser.add_argument("-h", "-H", "--help", action="help",
                         help="Show this help message and exit")
    parser.add_argument("-s", "-S", dest="quiet_log", action="store_true",
                         help="Don't print the solving log (only print answer/solved/difficulty)")
    parser.add_argument("-a", "-A", dest="show_answer_board", action="store_true",
                         help="Print the answer as a 9x9 text board (printed before the log)")
    parser.add_argument("puzzle", nargs="?", default=None,
                         help="An 81-character digit string (0 or '.' for blanks). If omitted, "
                              "reads one puzzle per line continuously from standard input")

    args = parser.parse_args(argv)

    if args.puzzle is not None:
        # If a puzzle is given directly on the command line: solve just that one puzzle and exit, as before.
        puzzle_str = _read_puzzle_string(args.puzzle)
        return _solve_and_print_one(puzzle_str, args.show_answer_board, args.quiet_log)

    # If the puzzle is omitted: read from standard input, one puzzle per line, for as many
    # lines as there are. Since the for-loop iterates lazily one line at a time, there is no
    # read-ahead -- the next line is only read once the current puzzle has been solved and printed.
    # Blank lines are skipped, but if a line is read that isn't a valid 81-character digit
    # string, processing aborts at that point (the expected behavior when non-puzzle text gets mixed in).
    for raw_line in sys.stdin:
        cleaned = _read_puzzle_string(raw_line)
        if cleaned == "":
            continue  # Skip blank lines
        exit_code = _solve_and_print_one(cleaned, args.show_answer_board, args.quiet_log)
        if exit_code != 0:
            return exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
