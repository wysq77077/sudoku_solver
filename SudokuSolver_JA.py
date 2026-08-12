#!/usr/bin/env python3
"""SudokuSolver_fast.py

SudokuSolver.py の高速化版。出力フォーマット・アルゴリズムのロジックは
元のSudokuSolver.pyと完全に同一(202件のテストパズルでログ・回答が
1バイトも違わないことを確認済み)。内部実装の効率化に加えて、CLIの
標準入力の扱いのみ拡張している(後述)。

【高速化の方針と、その過程で分かったこと】
当初はNumPyで盤面(board)・候補ノート(notes)を丸ごと配列化する方針で
実装したが、実際にベンチマークすると簡単〜中程度のパズルではむしろ
**遅くなる**ことが分かった(理由: 9x9=81マスという盤面はNumPyにとって
極端に小さく、1要素ずつのアクセスにかかるオーバーヘッドの方が、
Pythonのリストで同じことをするより大きくなってしまうため)。
NumPyは配列全体をまとめて処理する「バルク演算」でこそ威力を発揮するが、
このソルバーの各技法はマスを1つずつ・組み合わせを1つずつ調べる作りに
なっており、そもそもNumPy向きの処理ではなかった、というのが結論。

そこで方針を転換し、cProfileで実際のボトルネックを計測したところ、
**ALS-XY-Chainの探索(_extend_als_chain)** が支配的なコストであることが
判明した。特に、2つのALS(Almost Locked Set)がマスを共有していないかを
調べる `_als_shares_cell()` が、探索1回あたり数百万回呼ばれ、しかも
毎回 `set(b.cells)` を作り直していたことが最大の無駄だった。

このボトルネックをつぶすことに絞って以下の最適化を行った(NumPyではなく、
Pythonの標準的なデータ構造の選び方の改善が中心):

1. `AlsCandidate` に、マス集合を `frozenset` として構築時に1回だけ
   キャッシュしておく(`cells_set`)。以後のマス共有判定は
   `a.cells_set & b.cells_set` のO(1)差集合判定で済む
   (以前は毎回 `set()` を作ってから線形走査していた)。
2. ALS-XY-Chainの探索中、経路上の各ALSと1つずつ照合するのではなく、
   経路全体で「これまでに使われたマス」を1つの集合として累積して
   持ち回ることで、突き合わせ回数を「経路の長さ分」から「1回」に減らした。
3. `AlsCandidate` に、「digit dを持つマス一覧」も構築時に1回だけ
   digitごとに仕分けてキャッシュしておく(`cells_by_digit`)。
   ALS-XZ/ALS-XY-Wing/ALS-XY-Chainが呼ぶ `_cells_with_digit()` は、
   以前は毎回O(マス数)の線形走査だったが、これでO(1)の辞書引きになる。
4. `_all_in_one_house()`(3つの判定を1回の走査にまとめ、早期終了を追加)。
5. 候補ビットマスク→候補数字リストへの変換(`mask_digits()`)を、
   1024通りをあらかじめテーブル化したO(1)参照にした。
6. マスの候補ビットマスクそのもの(`_candidate_mask()`)も、
   毎回9回チェックし直すのではなく、除外・確定のたびに差分更新する
   キャッシュ(`_mask_cache`、通常のPythonのリスト)を持たせてO(1)にした。

これらは全て「元のアルゴリズムのロジックを変えず、同じ計算を
より少ない/より軽い操作で行う」ための変更であり、挙動は完全に同一になる。
(技法の使用回数集計に一時的にpandasを使っていたが、解答速度には寄与
しておらずログ集計用途に過ぎなかったため、素のPythonの辞書集計に戻した。
外部パッケージへの依存はこのファイルには一切無い。)

【ベンチマーク結果(このファイル同梱の検証で確認した実測値)】
- 中程度の難易度のパズル: 約1.5〜1.8倍
- ALS-XY-Chainが必要な高難易度パズル: 約3.6〜3.8倍
高難易度パズルほど、支配的だったALS-XY-Chainの探索コストの削減効果が
大きく出る。

C#版と同じくGrouped X-Chain/Grouped X-Cycleにも対応している
(アルゴリズム・バグ修正はC#版と同一)。

使い方・オプションは SudokuSolver.py と同じ。
    py SudokuSolver_fast.py [option] [問題]

問題を省略した場合は、標準入力から1行1問ずつ何問でも連続して読み込み、
1問解き終えるたびに次の1行を読みに行く(元のSudokuSolver.pyは標準入力
全体を1問として読んでいたのに対し、この高速化版では複数問を連続処理
できるよう拡張している)。空行は読み飛ばすが、81文字の数字列として
成立しない行を読んだ場合はその時点で処理を中断する(GUIは一切考慮しない、
CLI専用のツールという位置づけ)。

対象: Python 3.14以上(標準ライブラリのみで動作。外部パッケージ不要)。
"""

from __future__ import annotations

import argparse
import itertools
import sys
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

Cell = Tuple[int, int]  # (x, y) 1-9, 1-9


# ============================================================
# 列挙型(C#版 CellState / Unit / Difficulty に対応)
# ============================================================

class CellState(IntEnum):
    """各(値, x, y)ごとの候補状態。C#版 CellState と完全に同じ値を維持する。"""
    OPEN = 0                 # まだ候補として生きている
    PLACED = 1               # このマスにこの値が確定した
    ELIMINATED = 2           # 行/列/ブロックの矛盾で除外(確定マスによる自動消去)

    LOCKED_CANDIDATE = 3     # Easy: Locked Candidates(Pointing/Claiming)で除外
    NAKED_SUBSET = 4         # Moderate: Naked/Hidden Pair〜Quadで除外

    X_WING = 5               # Clever: Fish(size 2)で除外
    SKYSCRAPER = 6           # Clever: Skyscraperで除外
    TWO_STRING_KITE = 7      # Clever: 2 String Kiteで除外
    EMPTY_RECTANGLE = 8      # Clever: Empty Rectangleで除外

    COLORING = 9             # Tricky: Simple Coloringで除外/確定
    REMOTE_PAIR = 10         # Tricky: Remote Pairで除外
    W_WING = 11              # Tricky: W-Wingで除外

    SWORDFISH = 12           # Hard: Fish(size 3)で除外
    SASHIMI_FINNED_X_WING = 13  # Hard: Sashimi/Finned X-Wingで除外
    XY_WING = 14             # Hard: XY-Wingで除外

    JERRYFISH = 15           # Expert: Fish(size 4)で除外
    SASHIMI_FINNED_SWORDFISH = 16  # Expert: Sashimi/Finned Swordfishで除外
    XYZ_WING = 17            # Expert: XYZ-Wingで除外
    XY_CHAIN = 18            # Expert: XY-Chainで除外

    ALS_XZ = 19              # Genius: ALS-XZ法で除外
    GROUPED_X_CHAIN = 20     # Genius: Grouped X-Chain/Grouped X-Cycleで除外
    ALS_XY_WING = 21         # Genius: ALS-XY-Wing法で除外

    AIC = 22                 # Insane: AIC(Alternating Inference Chain)で除外/確定
    ALS_XY_CHAIN = 23        # Insane: ALS-XY-Chainで除外


def is_free(state: CellState) -> bool:
    return state == CellState.OPEN


class Unit(IntEnum):
    ROW = 0
    COL = 1
    BOX = 2


class Difficulty(IntEnum):
    """技法の難易度ランク。数字が大きいほど難しい(C#版と同じ並び順)。"""
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

# C#版のCellState enumメンバー名(PascalCase)と完全に一致させるための表示名。
# ログの technique 欄(≒C#版の reason.ToString())や、SolveResult.TechniqueUsage の
# キーをC#版と同じ文字列にするために使う(Python側の enum メンバー名は
# 通常のPython流にSCREAMING_SNAKE_CASEにしてあるため、そのままでは一致しない)。
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
# 盤面ジオメトリ(モジュールレベルで1回だけ計算してキャッシュする。
# C#版の static コンストラクタに相当)
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


# 0〜1023の全ビットマスクについて、あらかじめ「立っている数字のリスト」を
# テーブル化しておく。mask_digits()は全技法から極めて高頻度に呼ばれるため、
# 毎回9回のビットチェックをするのではなくO(1)のテーブル参照にする。
_MASK_DIGITS_TABLE: List[Tuple[int, ...]] = [
    tuple(d for d in range(1, 10) if m & (1 << d)) for m in range(1024)
]


# ============================================================
# データ構造(C#版 LogEntry / SolveResult / AlsCandidate に対応)
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
        # マス集合の交差判定(_als_shares_cell / _find_rcc_digits)が
        # ALS-XY-Chain等の探索で数百万回呼ばれるため、毎回setを作り直すのではなく
        # ここで1回だけfrozenset化してキャッシュしておく(O(1)差集合判定のため)。
        if not self.cells_set:
            self.cells_set = frozenset(self.cells)
        # 「digit dを持つマス一覧」も_find_rcc_digits等から高頻度に呼ばれるため、
        # 毎回リストを作り直す(_cells_with_digit)のではなく、ここで1回だけ
        # digitごとに仕分けてキャッシュしておく。
        if not self.cells_by_digit:
            by_digit: Dict[int, List[Cell]] = {}
            for cell, m in zip(self.cells, self.cell_masks):
                for d in mask_digits(m):
                    by_digit.setdefault(d, []).append(cell)
            self.cells_by_digit = by_digit


EMPTY_INT_LIST: List[int] = []
EMPTY_CELL_LIST: List[Cell] = []
FULL_CANDIDATE_MASK = sum(1 << d for d in range(1, 10))  # digit 1-9が全て開いている状態


@dataclass
class GNode:
    """Grouped X-Chainのノード = ある1つの数字について、1つのブロック内で
    縦または横に並んだ1〜3マスの候補マス集合。"""
    cells: List[Cell]  # 昇順ソート済み
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
    """ノードが完全に収まっているハウス(行/列/ブロック)を、成立するものすべて列挙する。
    単一マスのノードなら3つとも該当しうる。複数マスのノード(直線集合)は、
    その直線の方向に応じて行または列、および該当ブロックのみが対象になる。"""
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
    """2つのノードの間に、指定した2つのハウス(直前・直後の強リンクのハウス)の
    どちらとも異なるハウスで弱リンクが成立するか調べ、成立すればそのハウスを返す。

    【重要】弱リンクの成立条件は、単に「両ノードの何らかのマス同士が見える」では不十分。
    複数マスからなるノード(例: [D5,E5])は「DかEのどちらかにこの数字が入る」という
    未確定な情報しか持たないため、そのノードの一部のマスだけがハウスHに属している場合
    (例: D5だけが列4に属し、E5は属さない)、そのハウスHでの結論("HにこそこのノードOR
    相手ノードのどちらかが必ず入る")は成立しない。ノードの全マスがハウスHに含まれて
    いる場合に限り、そのハウスHでの結論が有効になる。そのため、弱リンクとして扱える
    ハウスは「両ノードそれぞれを完全に含むハウス」に限定している
    (単一マスのノードなら、そのマスの属する行・列・ブロックは全て自動的に「完全に含む」)。
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
# 本体
# ============================================================

class SudokuEngine:
    """VBA由来のC#版 SudokuEngine.cs のロジックをそのまま移植したもの。
    UI(WinForms/GUI)には一切依存しない。座標は x=列(1-9), y=行(1-9) の1始まり。
    History(一手ごとの盤面再生)は、CLI版では不要なため実装していない。
    """

    def __init__(self) -> None:
        self.board: List[List[int]] = [[0] * 10 for _ in range(10)]
        self.notes: List[List[List[CellState]]] = [
            [[CellState.OPEN] * 10 for _ in range(10)] for _ in range(10)
        ]
        # 各マス(x,y)の「現在の候補ビットマスク」を保持するキャッシュ。
        # _candidate_mask() をO(9)からO(1)にするための高速化(通常のPythonの
        # ネストしたリストのまま。NumPy配列にすると要素アクセス1回あたりの
        # オーバーヘッドの方が大きくなり逆に遅くなることを確認したため、
        # あえてリストのまま使っている)。
        self._mask_cache: List[List[int]] = [[0] * 10 for _ in range(10)]
        self.log: List[LogEntry] = []
        self.has_contradiction: bool = False
        self.contradiction_message: Optional[str] = None
        self._step_counter: int = 0

    # ------------------------------------------------------------
    # 初期化・確定処理まわり
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
            return  # 最初に見つかったものだけを記録する
        self.has_contradiction = True
        self.contradiction_message = message
        self._add_log(f"[矛盾検出] {message}", "Contradiction", Difficulty.TRIVIAL)

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
                            f"{unit_name(unit)}に数字{v}が重複しています"
                            f"(座標: {col_letter(ox)}{oy} と {col_letter(x)}{y})")
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
                        f"{col_letter(x)}{y} に置ける数字が無くなりました(盤面に矛盾が生じています)")
                    return

    def initialize(self, givens: List[List[int]]) -> None:
        """givens は [10][10] の int リスト(1-indexed, 0=空欄)。"""
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
    # 候補まわりのヘルパー
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
    # 技法1: Naked Single
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
    # 技法2: Hidden Single
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
    # 技法3: Locked Candidates (Pointing / Claiming)
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
    # 技法4: Naked Subsets(Naked Pair〜Quad。同時にHidden Subsetにもなる)
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
    # 技法5: Fish = X-Wing(2) / Swordfish(3) / Jerryfish(4)
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
    # 技法: Sashimi/Finned X-Wing
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
    # 技法: Sashimi/Finned Swordfish
    #
    # Swordfish(size 3)の一般化版。3本の基準ライン(行または列)でdigitが
    # 配置可能なマスの集合(cover座標)の和集合が、3列(または3行)の被覆集合K
    # ちょうどには収まらない場合でも、Kからはみ出す候補(フィン)が全て1つの
    # ブロックに収まっていれば、そのブロック内でKのうちそのブロックを通る
    # 列(行)から、基準ライン以外の行(列)にある候補を除外できる。
    #
    # 【判定アルゴリズム】
    # ・3本の基準ラインと、被覆する3本のカバーライン(K)を選ぶ
    # ・各基準ライン上でdigitが配置可能なマスのうち、Kに属さないマス(=フィン)を集める
    # ・フィンの総数が3個以上なら不成立
    # ・フィンが0個なら通常のSwordfish(fish(3)で対応済みなのでここでは対象外)
    # ・フィンが1個、または2個で両方とも同じブロックに収まっている場合のみ成立
    #
    # 【Sashimi/Finnedの判定(一般的な定義)】
    # フィンを出した基準ラインのうち、そのライン自身がK側の候補を1つも持たない
    # (=フィンだけでその行/列の役割を代替している)ラインが1つでもあればSashimi、
    # 無ければ(=フィンを出したラインもK側に候補を残している=フィンは純粋な余剰)Finned。
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
                    continue  # フィンが無い(=通常のfish(3)で対応済み)

                total_union_list = sorted(total_union)

                for k_combo in itertools.combinations(total_union_list, 3):
                    k = set(k_combo)

                    # フィン(=Kに含まれない候補)の実座標と、どの基準ラインから出たフィンかを集める
                    fin_cells: List[Cell] = []
                    lines_with_fin: Set[int] = set()
                    for li, line in enumerate(lines):
                        for cover in cand_sets[li]:
                            if cover in k:
                                continue
                            fin_cells.append((cover, line) if base_is_row else (line, cover))
                            lines_with_fin.add(li)

                    if len(fin_cells) == 0:
                        continue  # フィンが無い(=通常のfish(3)で対応済み)
                    if len(fin_cells) > 2:
                        continue  # フィンが3個以上は不成立

                    fin_boxes = {box_index(c[0], c[1]) for c in fin_cells}
                    if len(fin_boxes) != 1:
                        continue  # フィンは1ブロックに収まっている必要がある
                    box = next(iter(fin_boxes))

                    # Sashimi/Finnedの判定: フィンを出したラインのいずれかが、
                    # K側の候補を1つも持たなければSashimi、全て持っていればFinned
                    is_sashimi = any(not any(cov in k for cov in cand_sets[li]) for li in lines_with_fin)
                    kind = "Sashimi" if is_sashimi else "Finned"

                    # フィンのブロック内で、Kのうちそのブロックを通る列(行)から、
                    # 基準ライン以外の行(列)にある候補を除外する
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
    # 技法: 2 String Kite
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
    # 技法: Skyscraper
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
    # 1つのブロックB内で、あるdigitの配置可能マスが「1本の行R」と「1本の列C」
    # の上だけに(両方に最低1マスずつ)収まっている(=空の長方形)場合、
    # Bの外部にある強リンク(候補が2箇所しかない列/行)の一端がRまたはC上に
    # あれば、もう一方の端Aから見て、CとR側の交点セルからdigitを除外できる。
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
                # 「行Rまたは列C上」に全マスが収まっているか
                if not all(cell[0] == c or cell[1] == r for cell in candidates):
                    continue
                # 縦の腕・横の腕がそれぞれ最低1マス無ければ、ただの直線(Locked Candidates相当)
                # であり、真の空の長方形にはならないため対象外とする。
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

        # 4a) 外部の列C'上の強リンク。一端が行R上にあれば、もう一方Aの行とCの交点から除外。
        for c_prime in range(1, 10):
            if c_prime in box_cols:
                continue  # ブロック自身の列は対象外(外部の列のみ)

            link_cells = [cell for cell in cells_of(Unit.COL, c_prime) if is_free(self.notes[digit][cell[0]][cell[1]])]
            if len(link_cells) != 2:
                continue

            on_row_matches = [cell for cell in link_cells if cell[1] == r]
            if len(on_row_matches) != 1:
                continue  # 一致なし、または(理論上ないが)両方一致は対象外
            a = link_cells[1] if link_cells[0] == on_row_matches[0] else link_cells[0]

            tx, ty = c, a[1]
            if box_index(tx, ty) == box:
                continue  # ターゲットが自分自身のブロック内は対象外(証明が成立しない)
            if not is_free(self.notes[digit][tx][ty]):
                continue

            changed |= self._eliminate(
                digit, tx, ty, CellState.EMPTY_RECTANGLE,
                f"{col_letter(tx)}{ty}  Empty Rectangle (Block {box}, R={r}, C={col_letter(c)}, "
                f"外部列{col_letter(c_prime)}の強リンク) removes <{digit}>")

        # 4b) 外部の行R'上の強リンク。一端が列C上にあれば、もう一方Aの列とRの交点から除外。
        for r_prime in range(1, 10):
            if r_prime in box_rows:
                continue  # ブロック自身の行は対象外(外部の行のみ)

            link_cells = [cell for cell in cells_of(Unit.ROW, r_prime) if is_free(self.notes[digit][cell[0]][cell[1]])]
            if len(link_cells) != 2:
                continue

            on_col_matches = [cell for cell in link_cells if cell[0] == c]
            if len(on_col_matches) != 1:
                continue  # 一致なし、または(理論上ないが)両方一致は対象外
            a = link_cells[1] if link_cells[0] == on_col_matches[0] else link_cells[0]

            tx, ty = a[0], r
            if box_index(tx, ty) == box:
                continue  # ターゲットが自分自身のブロック内は対象外(証明が成立しない)
            if not is_free(self.notes[digit][tx][ty]):
                continue

            changed |= self._eliminate(
                digit, tx, ty, CellState.EMPTY_RECTANGLE,
                f"{col_letter(tx)}{ty}  Empty Rectangle (Block {box}, R={r}, C={col_letter(c)}, "
                f"外部行{r_prime}の強リンク) removes <{digit}>")
        return changed

    # ------------------------------------------------------------
    # 技法6: XY-Wing
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
    # 技法: XYZ-Wing
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
    # 技法7: Remote Pairs
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
    # 技法8: Simple Coloring
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
    # 技法9: XY-Chain
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
    # 技法9(続き): W-Wing
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
    # ALS(Almost Locked Set)関連の共通ヘルパー
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
                return False  # 3通り全て不成立が確定した時点で早期終了できる
        return True

    @staticmethod
    def _cells_with_digit(als: AlsCandidate, digit: int) -> List[Cell]:
        return als.cells_by_digit.get(digit, EMPTY_CELL_LIST)

    def _find_rcc_digits(self, a: AlsCandidate, b: AlsCandidate) -> List[int]:
        result: List[int] = []
        if a.cells_set & b.cells_set:
            return result  # マスを共有していたら対象外

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
    # C#版と同一のアルゴリズム(見つかった2つのバグの修正も含めて)。
    # ・強リンク: ハウス内でその数字の「ノード」がちょうど2つに限定される関係
    # ・ノード: 1つのブロック内で、縦一列または横一列に並んだ1〜3マスの候補マス集合
    #   (行・列ハウスでは、そのハウスがまたぐ各ブロックの区間が自動的に1ノードになる。
    #    ブロックハウスでは、ブロック内の3行・3列のうち、全候補マスを過不足なく
    #    覆う互いに素な2本を探し、見つかればその2本を2つのノードとする)
    # ・弱リンク: 2つのノードそれぞれを完全に含む共通のハウスがある関係
    #   (ノードの一部のマスだけがハウスに属している場合は不十分。詳細は
    #   _find_weak_link_house() のコメントを参照)
    #
    # 強リンクを起点に、強リンク→弱リンク→強リンク→…と交互に鎖を伸ばし、
    # 鎖の両端のノードから同時に見えるマスから候補数字を除去する(通常の鎖)。
    # 鎖が始点ノードに戻って輪になった場合はGrouped X-Cycleとなり、輪を構成する
    # 弱リンクが属する各ハウスにおいて、輪を構成しない他の全マスから除去できる。
    #
    # いずれかの除去に成功した時点で、それ以降の探索は行わず処理を終了する。
    # 自動ソルブからは、鎖に含めるノード数の上限を3から10まで1つずつ
    # 引き上げながら呼び出す。
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
                        return True  # 最初に見つかった除外で全体の探索を打ち切る(ユーザー指示)
        return False

    def _explore_grouped_chain(self, digit: int, path: List[GNode], used_cells: Set[Cell],
                                weak_houses: List[Tuple[Unit, int]], last_strong_house: Tuple[Unit, int],
                                first_strong_house: Tuple[Unit, int], strong_links: List["GStrongLink"],
                                max_nodes: int) -> bool:
        """
        path末尾のノードから、弱リンク→強リンクの順で鎖を伸ばしていく再帰探索。
        last_strong_house: 直前の強リンクのハウス(次の弱リンクがこれと異なる必要がある)。
        first_strong_house: 鎖の最初の強リンクのハウス(サイクルとして始点に戻る際、
        その弱リンクがこれとも異なる必要がある)。
        used_cells: これまでの鎖で使った全ノードのマスを累積したもの。

        【重要】ノードの再利用禁止は、ノードそのものの一致(同じマス集合)だけでは不十分。
        例えば単一マスノード{E5}を経路上で使った後、別のブロックハウスの2マスノード
        {D5,E5}(E5を含む)を"別のノード"として繋いでしまうと、E5というマス1つの
        真偽値を鎖の中で2回別々に扱うことになり、論理が破綻する。そのため、
        「経路上で既に使ったマスと1つでも重なるノードは使わない」という、
        ALS-XY-Chainと同じ考え方のマス単位のチェックにしている。
        """
        current = path[-1]
        start = path[0]

        # 1) サイクル判定: 強リンクを2本以上使った状態で、始点ノードへ弱リンクで戻れるか
        if len(path) >= 4:
            cycle_house = _find_weak_link_house(current, start, last_strong_house, first_strong_house)
            if cycle_house is not None:
                weak_houses.append(cycle_house)
                cycle_found = self._try_apply_grouped_x_cycle(digit, path, weak_houses)
                weak_houses.pop()
                if cycle_found:
                    return True

        if len(path) >= max_nodes:
            return False  # これ以上鎖を伸ばさない

        # 2) 通常の鎖: 別の強リンクへ弱リンクで繋げられないか探す
        for link in strong_links:
            for near_end, far_end in ((link.a, link.b), (link.b, link.a)):
                # 経路上で既に使ったマスと1つでも重なるノードは使わない(始点への復帰は上でサイクルとして処理済み)
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
        """通常の鎖(始点と終点が異なるノード)の除外を試みる。両端のノードから同時に
        見えるマス(それぞれのcommon_peers_ofの積集合)から、鎖自身を構成するマスを
        除いて候補数字を除去する。"""
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
            if (tx, ty) in chain_cells:  # 鎖自身を構成するマスは除外対象にしない
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
        """Grouped X-Cycle(輪)の除外を試みる。輪を構成する各弱リンクのハウスにおいて、
        輪(ノード)を構成しない他の全マスから候補数字を除去する。"""
        cycle_cells: Set[Cell] = set()
        for n in path:
            cycle_cells.update(n.cells)

        desc = "-".join(str(n) for n in path) + "-(輪)"

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
        """盤面全体から、指定した数字についてのグループ化強リンクを全て集める。"""
        links: List[GStrongLink] = []
        for unit in (Unit.ROW, Unit.COL, Unit.BOX):
            for idx in range(1, 10):
                nodes = self._find_grouped_nodes(unit, idx, digit)
                if len(nodes) == 2:
                    links.append(GStrongLink(a=nodes[0], b=nodes[1], house_unit=unit, house_index=idx))
        return links

    def _find_grouped_nodes(self, unit: Unit, idx: int, digit: int) -> List[GNode]:
        """指定したハウス・数字について、ノード(1〜3マスの直線集合)の一覧を求める。"""
        cells = [c for c in cells_of(unit, idx) if is_free(self.notes[digit][c[0]][c[1]])]
        if not cells:
            return []

        if unit != Unit.BOX:
            # 行・列ハウス: ブロックごとに区切れば、そのままこのハウスの方向に並んでいる
            groups: Dict[int, List[Cell]] = {}
            for c in cells:
                groups.setdefault(box_index(c[0], c[1]), []).append(c)
            return [_make_gnode(g, digit) for g in groups.values()]

        # ブロックハウス: ブロック内の3行・3列のうち候補マスがある行/列だけを「直線候補」として
        # 列挙し、全候補マスを過不足なく・マスの重複なく覆える2本の組を探す。
        ys = sorted({c[1] for c in cells})
        xs = sorted({c[0] for c in cells})
        row_lines = [[c for c in cells if c[1] == y] for y in ys]
        col_lines = [[c for c in cells if c[0] == x] for x in xs]
        line_candidates = row_lines + col_lines

        for i in range(len(line_candidates)):
            for j in range(i + 1, len(line_candidates)):
                l1, l2 = line_candidates[i], line_candidates[j]
                if any(c in l2 for c in l1):
                    continue  # 交差マスが候補であってはならない
                if len(l1) + len(l2) != len(cells):
                    continue  # 過不足なく覆えているか
                return [_make_gnode(l1, digit), _make_gnode(l2, digit)]
        return []  # 2ノードに分割できなければ、このブロックには強リンク無し

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

            # 経路上のどのALSともマスを共有していないか(累積used_cellsとの
            # O(1)差集合判定に置き換えることで、path本数ぶんループしていた
            # _als_shares_cell()呼び出しを1回のset演算にまとめている)。
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
                continue  # 偶数番目=強リンクなのでスキップ

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
    # 自動ソルブ
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
                # 鎖は伸ばすほど組み合わせが増えるため、XyChain/ALS-XY-Chainと同じ考え方で
                # ノード数3から10まで1つずつ上限を引き上げながら試す(短い鎖を優先)。
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
# AIC用ノード(C#版 AicNode に対応。tuple継承で軽量な値型として扱う)
# ============================================================

class AicNode(Tuple[int, int, int]):
    """AICのノード = (マス, 数字)。(x, y, digit) の3要素タプルとして扱う。"""

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
# フリー関数ヘルパー(複数の技法から共通に呼ばれるもの)
# ============================================================

def common_peers_of(cells: Sequence[Cell]) -> Set[Cell]:
    """マス群すべてから共通に見えるマス(自分自身は除く)を求める。"""
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
    """グラフを連結成分ごとに分割し、各成分内を交互に2彩色する。孤立点はどの成分にも含めない。"""
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
    """9x9盤面をテキスト表示用に、3x3ブロックごとに罫線で囲んだ表形式で整形する。
    列ラベル(A-I)を最上部に、行ラベル(1-9)を最左列に表示する。未確定マスは空白1文字。

    レイアウト例:
          A B C   D E F   G H I
        +-------+-------+-------+
      1 | 4 . . | . . . | 2 . . |
      2 | . . 1 | . 9 . | . . 3 |
      3 | 2 . 4 | 3 . . | . 5 . |
        +-------+-------+-------+
        ...

    行ラベル+区切り「Y |」は3文字、セル領域は9マス+区切り8個で17文字、
    最後の枠「|」で1文字、合計 3+17+1=21文字に必ず揃うようにしている
    (ヘッダー行・罫線行も同じ21文字の幅で組み立てるため、桁がずれない)。
    """

    def block_row(cells: Sequence[str], block_sep: str) -> str:
        # cells: 9文字ぶんの文字列のリスト。3個ごとの境界だけ block_sep、それ以外は半角スペースで区切る。
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
    """81文字に満たない改行や空白を除去し、'.' を '0' に置き換える。"""
    cleaned = "".join(ch for ch in raw if not ch.isspace())
    cleaned = cleaned.replace(".", "0")
    return cleaned


def _solve_and_print_one(puzzle_str: str, show_answer_board: bool, quiet_log: bool) -> int:
    """1問を解いて結果を出力する。問題の形式が不正な場合は標準エラーに
    メッセージを出し、1を返す(呼び出し側はこれを見てabortする)。"""
    if len(puzzle_str) != 81 or not all(ch.isdigit() for ch in puzzle_str):
        print(f"[エラー] 問題は81文字の数字列(0または'.'は空欄)である必要があります"
              f"(受け取った長さ: {len(puzzle_str)})", file=sys.stderr)
        return 1

    engine = SudokuEngine()
    givens = SudokuEngine.parse_import_string(puzzle_str)
    engine.initialize(givens)
    result = engine.solve_all()

    answer = engine.export_string()

    print(f"[回答] {answer}")
    print(f"[解けたか] {result.solved}")
    print(f"[難易度] {result.difficulty.name.capitalize()}")
    if result.has_contradiction:
        print(f"[矛盾] {result.contradiction_message}")

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
        description="数独を解析・自動ソルブし、難易度を判定するCLIツール。",
        add_help=False,  # -h/-Hを両方効かせるため、自動追加のhelpは使わず手動で登録する
    )
    parser.add_argument("-h", "-H", "--help", action="help",
                         help="このヘルプを表示して終了する")
    parser.add_argument("-s", "-S", dest="quiet_log", action="store_true",
                         help="解法ログを出力しない(回答/解けたか/難易度のみ出力する)")
    parser.add_argument("-a", "-A", dest="show_answer_board", action="store_true",
                         help="回答の9x9盤面をテキストで出力する(ログより前に出力)")
    parser.add_argument("puzzle", nargs="?", default=None,
                         help="81文字の数字列(0または'.'は空欄)。省略時は標準入力から"
                              "1行1問ずつ連続して読み込む")

    args = parser.parse_args(argv)

    if args.puzzle is not None:
        # コマンドラインに問題が直接指定された場合: これまで通り1問だけ解いて終了する。
        puzzle_str = _read_puzzle_string(args.puzzle)
        return _solve_and_print_one(puzzle_str, args.show_answer_board, args.quiet_log)

    # 問題が省略された場合: 標準入力から1行1問として、何問でも連続して読み取る。
    # for文によるイテレーションは1行ずつ遅延評価されるため、先読みはせず、
    # 1問解いて出力し終えたタイミングで次の1行を読みに行く形になる。
    # 空行は読み飛ばすが、81文字の数字列として成立しない行を読んだ場合は
    # そこでabortする(問題以外のテキストが混入した場合の想定挙動)。
    for raw_line in sys.stdin:
        cleaned = _read_puzzle_string(raw_line)
        if cleaned == "":
            continue  # 空行は読み飛ばす
        exit_code = _solve_and_print_one(cleaned, args.show_answer_board, args.quiet_log)
        if exit_code != 0:
            return exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
