import datetime as dt
import random
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from slab.comparator import compare

values = st.one_of(
    st.integers(-10**9, 10**9),
    st.floats(-1e9, 1e9, allow_nan=False, allow_infinity=False),
    st.text(max_size=8),
    st.dates(dt.date(1990, 1, 1), dt.date(2000, 12, 31)),
    st.none(),
)


@st.composite
def tables(draw):
    ncols = draw(st.integers(1, 4))
    nrows = draw(st.integers(0, 12))
    col_types = [draw(st.sampled_from(["int", "float", "text", "date", "any"])) for _ in range(ncols)]
    gen = {
        "int": st.integers(-10**6, 10**6),
        "float": st.floats(-1e6, 1e6, allow_nan=False, allow_infinity=False),
        "text": st.text(alphabet="abcXYZ", max_size=5),
        "date": st.dates(dt.date(1992, 1, 1), dt.date(1998, 12, 31)),
        "any": values,
    }
    rows = [tuple(draw(gen[t]) for t in col_types) for _ in range(nrows)]
    return [f"c{i}" for i in range(ncols)], rows


@settings(max_examples=300, deadline=None)
@given(tables(), st.randoms(use_true_random=False))
def test_row_permutation_is_irrelevant_when_unordered(tbl, rnd):
    cols, rows = tbl
    shuffled = list(rows)
    rnd.shuffle(shuffled)
    assert compare(cols, rows, cols, shuffled).correct


@settings(max_examples=300, deadline=None)
@given(tables(), st.randoms(use_true_random=False))
def test_column_permutation_and_renaming_is_irrelevant(tbl, rnd):
    cols, rows = tbl
    perm = list(range(len(cols)))
    rnd.shuffle(perm)
    pcols = [f"x{i}" for i in perm]
    prows = [tuple(r[i] for i in perm) for r in rows]
    assert compare(cols, rows, pcols, prows).correct


@settings(max_examples=200, deadline=None)
@given(st.lists(st.floats(1, 1e6, allow_nan=False), min_size=1, max_size=10))
def test_perturbation_beyond_tolerance_is_detected(xs):
    rows = [(i, x) for i, x in enumerate(xs)]
    bad = list(rows)
    bad[0] = (bad[0][0], bad[0][1] * 1.01)
    assert not compare(["k", "v"], rows, ["k", "v"], bad).correct


def test_tolerance_absorbs_decimal_vs_double():
    gold = [("BRAZIL", Decimal("12345678.91"))]
    pred = [("BRAZIL", 12345678.910000004)]
    assert compare(["n", "v"], gold, ["nation", "revenue"], pred).correct


def test_ordered_questions_require_order():
    gold = [("a", 3), ("b", 2), ("c", 1)]
    assert compare(["k", "v"], gold, ["k", "v"], gold, ordered=True).correct
    assert not compare(["k", "v"], gold, ["k", "v"], list(reversed(gold)), ordered=True).correct
    assert compare(["k", "v"], gold, ["k", "v"], list(reversed(gold)), ordered=False).correct


def test_extra_predicted_columns_are_tolerated_missing_are_not():
    gold = [("a", 1.0), ("b", 2.0)]
    pred = [("a", 1.0, 99), ("b", 2.0, 98)]
    assert compare(["k", "v"], gold, ["k", "v", "extra"], pred).correct
    assert not compare(["k", "v"], gold, ["k"], [("a",), ("b",)]).correct


def test_finer_grain_answer_is_wrong():
    gold = [("a", 3.0)]
    pred = [("a", 1.0), ("a", 2.0)]
    assert not compare(["k", "v"], gold, ["k", "v"], pred).correct


def test_year_integer_matches_january_first_date_both_ways():
    gold = [(dt.date(1995, 1, 1), 10.0), (dt.date(1996, 1, 1), 20.0)]
    pred = [(1995, 10.0), (1996, 20.0)]
    assert compare(["y", "v"], gold, ["y", "v"], pred).correct
    assert compare(["y", "v"], pred, ["y", "v"], gold).correct


def test_month_dates_do_not_match_years():
    gold = [(dt.date(1995, 3, 1), 10.0)]
    pred = [(1995, 10.0)]
    assert not compare(["m", "v"], gold, ["y", "v"], pred).correct


def test_midnight_timestamp_equals_date():
    gold = [(dt.date(1995, 3, 1), 1)]
    pred = [(dt.datetime(1995, 3, 1, 0, 0), 1)]
    assert compare(["m", "v"], gold, ["m", "v"], pred).correct


def test_null_equals_null_only():
    assert compare(["v"], [(None,)], ["v"], [(None,)]).correct
    assert not compare(["v"], [(None,)], ["v"], [(0,)]).correct


def test_empty_vs_nonempty():
    assert compare(["v"], [], ["v"], []).correct
    assert not compare(["v"], [], ["v"], [(1,)]).correct


def test_trailing_spaces_in_strings():
    assert compare(["v"], [("MAIL      ",)], ["v"], [("MAIL",)]).correct


def test_swapped_values_across_rows_are_wrong():
    gold = [("a", 1.0), ("b", 2.0)]
    pred = [("a", 2.0), ("b", 1.0)]
    assert not compare(["k", "v"], gold, ["k", "v"], pred).correct


def test_identical_columns_ambiguity_resolved():
    rnd = random.Random(0)
    rows = [(i, i, rnd.random()) for i in range(20)]
    pred = [(r[2], r[1], r[0]) for r in rows]
    assert compare(["a", "b", "c"], rows, ["x", "y", "z"], pred).correct
