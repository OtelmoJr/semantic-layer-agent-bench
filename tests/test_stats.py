import math

from slab.harness import stats


def rows(model, arm, outcomes):
    return [{"model_id": model, "arm": arm, "question_id": f"q{i}", "correct": c, "category": "simple"}
            for i, cs in enumerate(outcomes) for c in cs]


def test_mcnemar_exact_known_values():
    assert stats.mcnemar_exact(0, 0) == 1.0
    # b=0, c=6: two-sided exact p = 2 * 0.5^6
    assert math.isclose(stats.mcnemar_exact(0, 6), 2 * 0.5 ** 6)
    assert stats.mcnemar_exact(5, 5) == 1.0


def test_bootstrap_is_deterministic_and_brackets_mean():
    vals = [0, 1, 1, 0, 1, 1, 1, 0, 1, 1]
    lo1, hi1 = stats.bootstrap_ci(vals)
    lo2, hi2 = stats.bootstrap_ci(vals)
    assert (lo1, hi1) == (lo2, hi2)
    assert lo1 <= 0.7 <= hi1


def test_attempts_are_averaged_per_question():
    r = rows("m", "A", [[True, False, True], [False, False, False]])
    s = stats.arm_scores(r)[0]
    assert s.n_questions == 2
    assert math.isclose(s.ex, (2 / 3 + 0) / 2)
    assert s.pass_all == 0.0


def test_paired_test_counts_discordant_questions():
    a = rows("m", "A", [[False]] * 8 + [[True]] * 2)
    c = rows("m", "C", [[True]] * 8 + [[True]] * 2)
    t = stats.paired_test(a + c, "m", "A", "C")
    assert (t.x_only, t.y_only) == (0, 8)
    assert t.p_value < 0.01
    assert math.isclose(t.diff, 0.8)


def test_documentation_share():
    a = rows("m", "A", [[False]] * 10)
    b = rows("m", "B", [[True]] * 5 + [[False]] * 5)
    c = rows("m", "C", [[True]] * 10)
    point, lo, hi = stats.documentation_share(a + b + c, "m")
    assert math.isclose(point, 0.5)
    assert lo <= 0.5 <= hi
    assert stats.documentation_share(a + b + a_as_c(a), "m") is None


def a_as_c(a):
    return [dict(r, arm="C") for r in a]
