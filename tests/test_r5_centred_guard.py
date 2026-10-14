"""Release 5 (``centred_ratings``): a static guard on the engine's source.

Under the switch a rating is shifted once, where it enters the pitch
(``physics_sim.centred_ratings``), and a formula that subtracts a centre
itself compares against 50. Three mistakes break that silently, and each
has happened or nearly happened:

* a model reads a centre directly, so its rating is centred twice;
* a rating is shifted by the wrong centre (the plain ACT mean instead of
  the usage centre, the Release 4 terms' centre for a shifted rating);
* a term reads a RAW rating against a literal 50 -- neither shifted nor
  centred -- as the pickoff did.

This walks the syntax tree of ``physics_sim`` and fails on any of them. It
is a guard on how the source is written, not a proof:
``test_what_the_guard_cannot_see`` lists what gets past it.
"""

from __future__ import annotations

import ast
import re
import shutil
from pathlib import Path

import pytest

from physics_sim.centred_ratings import CENTRED_RATING_KEYS, MODEL_CENTER_KEYS
from physics_sim.config import DEFAULT_TUNING

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "physics_sim"

# Every centre the switch has a say in: the ones the shift reads and the
# ones a model names for a shifted rating.
COVERED_KEYS = CENTRED_RATING_KEYS | set(MODEL_CENTER_KEYS)
# The helpers that shift a raw rating: they take the centre it is shifted
# by (a pitcher's usage centre, never his plain ACT mean).
SHIFT_CALLS = {"source_shift", "_league_relative", "league_relative", "tired"}
# The Release 4 readers centre a RAW rating themselves on the plain ACT
# mean (``_pickoff_rating`` is the pickoff's, under the switch). Of the
# covered centres they may be given only the two they read today.
R4_CALLS = {"_centred_rating", "_clipped_battery", "_pickoff_rating"}
R4_COVERED_KEYS = {"pitcher_control_center", "pitcher_arm_center"}
# Every other place a covered key may appear: (module, function, key).
OTHER_KEY_USES = {
    # The Contact hit edge: the raw rating against the league's own centre.
    ("engine.py", "_contact_babip_edge", "hitter_contact_center"),
}

# A player's rating attribute -> the centre it is shifted by.
SHIFTED_ATTRIBUTES = {
    "contact": "hitter_contact_center",
    "power": "hitter_power_center",
    "eye": "hitter_eye_center",
    "control": "pitcher_control_usage_center",
    "movement": "pitcher_movement_usage_center",
    "arm": "pitcher_arm_usage_center",  # a pitcher's (see _is_rating_read)
    "repertoire": "pitcher_grade_usage_center",
}
# Raw reads of those attributes in engine.py that are right as they are:
# (function, expression).
RAW_READS = {
    # The Contact hit edge reads the raw rating against the real centre.
    ("_contact_babip_edge", "batter.contact"),
    # The repertoire is tested for emptiness; its grades are shifted one by
    # one in the comprehension below it.
    ("_pitcher_context", "pitcher.repertoire"),
    # Release 6a: the manager's view of an arm (pitcher_score_model 1)
    # shifts each grade in the comprehension that reads it, then averages.
    ("_pitcher_stuff_score", "pitcher.repertoire"),
    # PitchResult.contact: whether the swing met the ball, not a rating.
    ("play_half_inning", "res.contact"),
}
# A raw pitcher rating may be handed on under these keyword names: the
# functions that take them are checked by RAW_PARAMETERS.
RAW_KEYWORDS = {"pitcher_control", "pitcher_arm"}
# Parameters that carry a raw pitcher rating. A function that does
# arithmetic or a comparison on one must first pass it to a Release 4
# reader -- except:
RAW_PARAMETERS = {"pitcher_arm", "pitcher_control", "pitcher_hold", "pitcher_movement"}
RAW_PARAMETER_USES = {
    # The lead a runner takes: hold against an absolute threshold. Hold is
    # not a shifted rating; left absolute (docs/future_work.md).
    ("_lead_level", "pitcher_hold"),
}


# A string that is a tuning key naming a centre, or a piece one could be
# built from ("_center", "pitcher_{}_center", "hitter_%s_center").
_KEY_PIECE = re.compile(r"[A-Za-z0-9_{}%]*center[A-Za-z0-9_{}%]*")


def _parse(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = {
        child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }
    return tree, parents


def _function(node, parents) -> str:
    while node is not None and not isinstance(
        node, (ast.FunctionDef, ast.AsyncFunctionDef)
    ):
        node = parents.get(node)
    return getattr(node, "name", "")


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return getattr(func, "id", "")


def _is_docstring(node, parents) -> bool:
    return isinstance(parents.get(node), ast.Expr)


def _in_dunder_all(node, parents) -> bool:
    while node is not None:
        if isinstance(node, ast.Assign):
            return any(getattr(t, "id", "") == "__all__" for t in node.targets)
        node = parents.get(node)
    return False


def _key_problems(package: Path) -> list[str]:
    """Every wrong use of a rating-centre key in the package."""
    problems = []
    seen = set()
    for path in sorted(package.glob("*.py")):
        tree, parents = _parse(path)
        module = path.name
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            text = node.value
            # A key or a piece of one: no spaces (prose is not a key).
            if not _KEY_PIECE.fullmatch(text) or _is_docstring(node, parents):
                continue
            if _in_dunder_all(node, parents):
                continue
            function = _function(node, parents)
            where = f"{module}:{node.lineno} {function} {text!r}"
            if text not in DEFAULT_TUNING:
                # A piece of a key (an f-string, a concatenation, a format):
                # a centre read this walk could not follow.
                problems.append(f"{where}: not a registered key (a built key?)")
                continue
            if not text.endswith("_center"):
                continue  # spray_center_band_deg, platoon_vl_center_enabled
            seen.add(text)
            parent = parents[node]
            how = "other"
            if isinstance(parent, ast.Call) and node in parent.args:
                how = "call:" + _call_name(parent)
            elif isinstance(parent, ast.Dict):
                how = "dict key" if node in parent.keys else "dict value"
            elif isinstance(parent, ast.Set):
                how = "set"
            call = how.removeprefix("call:")
            if module == "physics.py":
                # The pitch kernel reads EVERY centre through the accessor,
                # covered or not, and never a shift (usage) centre.
                if how != "call:rating_center":
                    problems.append(f"{where}: read without rating_center ({how})")
                elif text in CENTRED_RATING_KEYS and text not in MODEL_CENTER_KEYS:
                    problems.append(f"{where}: a model names a shift centre")
                continue
            if text not in COVERED_KEYS:
                continue
            if module == "config.py":
                ok = how == "dict key"
            elif module == "centred_ratings.py":
                ok = how in {"dict key", "dict value", "set"}
            elif call in SHIFT_CALLS:
                ok = text in CENTRED_RATING_KEYS
            elif call in R4_CALLS:
                ok = text in R4_COVERED_KEYS
            else:
                ok = (module, function, text) in OTHER_KEY_USES
            if not ok:
                problems.append(f"{where}: {how}")
    missing = COVERED_KEYS - seen
    if missing:
        problems.append(f"covered keys never named: {sorted(missing)}")
    return problems


def _is_rating_read(node: ast.Attribute) -> bool:
    if node.attr not in SHIFTED_ATTRIBUTES or not isinstance(node.ctx, ast.Load):
        return False
    # ``arm`` is also every fielder's throwing arm; a pitcher's is the one
    # that sets velocity. Told apart by what it is read off.
    return node.attr != "arm" or "pitcher" in ast.unparse(node.value)


def _raw_read_problems(package: Path) -> list[str]:
    """Every read of a shifted rating in engine.py that is not shifted, not
    handed to a checked function and not listed in ``RAW_READS``; and every
    function that computes on a raw pitcher-rating parameter without a
    Release 4 reader."""
    tree, parents = _parse(package / "engine.py")
    problems = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and _is_rating_read(node)):
            continue
        function = _function(node, parents)
        text = ast.unparse(node)
        where = f"engine.py:{node.lineno} {function} {text}"
        parent = parents[node]
        if isinstance(parent, ast.Call) and parent.args and parent.args[0] is node:
            if _call_name(parent) in SHIFT_CALLS:
                keys = [
                    arg.value
                    for arg in parent.args[1:]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                ]
                if keys and keys[0] != SHIFTED_ATTRIBUTES[node.attr]:
                    problems.append(f"{where}: shifted by {keys[0]}")
                continue
        if isinstance(parent, ast.keyword) and parent.arg in RAW_KEYWORDS:
            continue
        if (function, text) in RAW_READS:
            continue
        problems.append(f"{where}: a raw rating read outside the shift helpers")
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        names = {arg.arg for arg in fn.args.args + fn.args.kwonlyargs}
        for name in sorted(names & RAW_PARAMETERS):
            computed = read = False
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Name) and node.id == name):
                    continue
                if not isinstance(node.ctx, ast.Load):
                    continue
                parent = parents[node]
                if isinstance(parent, (ast.BinOp, ast.Compare, ast.UnaryOp)):
                    computed = True
                elif (
                    isinstance(parent, ast.Call)
                    and parent.args
                    and parent.args[0] is node
                    and _call_name(parent) in R4_CALLS
                ):
                    read = True
            if computed and not read and (fn.name, name) not in RAW_PARAMETER_USES:
                problems.append(
                    f"engine.py:{fn.lineno} {fn.name}: computes on the raw "
                    f"{name} without a Release 4 reader"
                )
    return problems


def _problems(package: Path = PACKAGE) -> list[str]:
    return _key_problems(package) + _raw_read_problems(package)


def test_the_engine_reads_centres_and_ratings_only_through_the_helpers():
    """A new ``*_center`` read that does not go through
    ``centred_ratings.rating_center`` (or a shift helper), or a new raw read
    of a shifted rating, fails here: under the switch it would centre a
    rating a second time, or not at all."""
    assert _problems() == []


def test_the_allow_lists_name_things_that_exist():
    # An allow-list entry for code that is gone hides the next mistake.
    tree, parents = _parse(PACKAGE / "engine.py")
    reads = {
        (_function(node, parents), ast.unparse(node))
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and _is_rating_read(node)
    }
    assert RAW_READS <= reads
    functions = {
        fn.name: {arg.arg for arg in fn.args.args + fn.args.kwonlyargs}
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef)
    }
    for function, name in RAW_PARAMETER_USES:
        assert name in functions[function]
    for _module, function, _key in OTHER_KEY_USES:
        assert function in functions


VIOLATIONS = {
    # --- a centre read outside the accessor --------------------------------
    "a model subtracts a covered centre itself": (
        "physics.py",
        'def f(t, x):\n    return x - t.get("hitter_power_center")\n',
    ),
    "any direct centre read in the pitch kernel": (
        "physics.py",
        'def f(t):\n    return t.get("catcher_arm_center", 50.0)\n',
    ),
    "a model names a usage centre": (
        "physics.py",
        "def f(tuning, x):\n"
        '    return x - rating_center(tuning, "pitcher_control_usage_center")\n',
    ),
    "a direct read of a plain covered centre in the engine": (
        "engine.py",
        'def f(t, x):\n    return x - t.get("pitcher_grade_center")\n',
    ),
    "a direct read of a usage centre in the engine": (
        "engine.py",
        'def f(t, x):\n    return x - t.get("pitcher_arm_usage_center")\n',
    ),
    "a Release 4 reader on a rating the switch shifts": (
        "engine.py",
        'def f(t, x):\n    return _centred_rating(x, "pitcher_movement_center", t)\n',
    ),
    "a Release 4 reader on a usage centre": (
        "engine.py",
        'def f(t, x):\n    return _centred_rating(x, "pitcher_arm_usage_center", t)\n',
    ),
    "a shift by the plain ACT mean": (
        "engine.py",
        'def f(t, x):\n    return _league_relative(x, "pitcher_control_center", t)\n',
    ),
    "a covered key held in another module": (
        "fielding.py",
        'KEY = "hitter_eye_center"\n',
    ),
    # --- a key the walk cannot follow ---------------------------------------
    "an f-string key": (
        "engine.py",
        'def f(t, name):\n    return t.get(f"pitcher_{name}_usage_center", 50.0)\n',
    ),
    "a concatenated key": (
        "engine.py",
        'def f(t):\n    return t.get("pitcher_arm" + "_center", 50.0)\n',
    ),
    "a formatted key": (
        "engine.py",
        'def f(t, name):\n    return t.get("hitter_%s_center" % name, 50.0)\n',
    ),
    "a str.format key": (
        "fielding.py",
        'def f(t, name):\n    return t.get("pitcher_{}_center".format(name), 50.0)\n',
    ),
    # --- a raw rating against a literal --------------------------------------
    "a raw pitcher rating against 50 (the pickoff, as it was)": (
        "engine.py",
        "def f(pitcher):\n    return (pitcher.arm - 50.0) / 320.0\n",
    ),
    "a raw hitter rating against a threshold": (
        "engine.py",
        "def f(batter):\n    return batter.power >= 60.0\n",
    ),
    "a raw rating copied to a local first": (
        "engine.py",
        "def f(pitcher_state):\n"
        "    control = pitcher_state.pitcher.control\n"
        "    return 1.0 + (50.0 - control) / 200.0\n",
    ),
    "a raw pitcher-rating parameter computed on": (
        "engine.py",
        "def f(*, pitcher_arm, tuning):\n    return (pitcher_arm - 50.0) / 320.0\n",
    ),
    "a rating shifted by another rating's centre": (
        "engine.py",
        "def f(pitcher, tuning):\n"
        "    return _league_relative(\n"
        '        pitcher.control, "pitcher_arm_usage_center", tuning\n'
        "    )\n",
    ),
    "a pitch grade read raw": (
        "engine.py",
        'def f(pitcher):\n    return pitcher.repertoire.get("fb", 50.0) - 50.0\n',
    ),
}


@pytest.mark.parametrize("name", sorted(VIOLATIONS))
def test_the_guard_catches(tmp_path, name):
    module, added = VIOLATIONS[name]
    package = tmp_path / "physics_sim"
    package.mkdir()
    for path in PACKAGE.glob("*.py"):
        shutil.copy(path, package / path.name)
    assert _problems(package) == []
    with (package / module).open("a", encoding="utf-8") as fh:
        fh.write("\n\n" + added)
    assert _problems(package), name


# What it does not catch. Each of these is appended to a copy of the engine
# and the guard stays silent; they are here so that nobody takes the guard
# for more than it is.
BLIND_SPOTS = {
    "a key with no 'center' in any literal": (
        "engine.py",
        'def f(t):\n    return t.get("pitcher_arm_usage_" + "cen" + "ter", 50.0)\n',
    ),
    "a key that arrives in a variable": (
        "engine.py",
        "def f(t, key):\n    return t.get(key, 50.0)\n",
    ),
    "a rating read by name": (
        "engine.py",
        'def f(pitcher):\n    return getattr(pitcher, "arm") - 50.0\n',
    ),
    "a raw rating under a parameter name the guard does not list": (
        "engine.py",
        "def f(*, arm_rating):\n    return (arm_rating - 50.0) / 320.0\n",
    ),
    "a raw rating read in another module": (
        "fielding.py",
        "def f(pitcher):\n    return (pitcher.control - 50.0) / 200.0\n",
    ),
    "the kernel reading an input the engine never shifted": (
        "physics.py",
        'def f(pitcher):\n    return pitcher.get("stamina", 50.0) - 50.0\n',
    ),
    "a reader called after the raw use": (
        "engine.py",
        "def f(*, pitcher_hold, tuning):\n"
        "    early = (pitcher_hold - 50.0) / 140.0\n"
        "    pitcher_hold = _centred_rating(\n"
        '        pitcher_hold, "pitcher_hold_center", tuning\n'
        "    )\n"
        "    return early + pitcher_hold\n",
    ),
}


@pytest.mark.parametrize("name", sorted(BLIND_SPOTS))
def test_what_the_guard_cannot_see(tmp_path, name):
    """Documented limits. The invariance tests
    (tests/test_r5_centred_ratings.py) are what catches these: a term that
    reads a rating the wrong way makes a shifted league play a different
    game."""
    module, added = BLIND_SPOTS[name]
    package = tmp_path / "physics_sim"
    package.mkdir()
    for path in PACKAGE.glob("*.py"):
        shutil.copy(path, package / path.name)
    with (package / module).open("a", encoding="utf-8") as fh:
        fh.write("\n\n" + added)
    assert _problems(package) == []
