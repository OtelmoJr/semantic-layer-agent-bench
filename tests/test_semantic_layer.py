import pytest
import yaml

from slab import config

pytestmark = [pytest.mark.data, pytest.mark.semantic]


@pytest.fixture(scope="module")
def engine():
    from slab.semantic.engine import SemanticEngine
    return SemanticEngine()


def test_semantic_layer_matches_glossary_verbatim(engine):
    """Arm B and arm C must receive the same business definitions."""
    glossary = {m["name"]: m["description"] for m in yaml.safe_load(config.GLOSSARY_PATH.read_text())["metrics"]}
    exposed = {m["name"]: m["description"] for m in engine.list_metrics()}
    assert exposed == glossary


def test_internal_metrics_hidden(engine):
    from slab.semantic.engine import INTERNAL_METRICS, MetricQuery, SemanticQueryError
    names = {m["name"] for m in engine.list_metrics()}
    assert not names & INTERNAL_METRICS
    with pytest.raises(SemanticQueryError):
        engine.compile(MetricQuery(metrics=("late_lines",)))


def test_compiled_sql_only_touches_semantic_models(engine):
    from slab.semantic.engine import SEMANTIC_POLICY, MetricQuery
    from slab.sqlguard import validate
    sql = engine.compile(MetricQuery(metrics=("net_revenue", "return_rate"),
                                     group_by=("customer__region", "supplier__nation", "metric_time__year")))
    validate(sql, SEMANTIC_POLICY)


def test_unknown_metric_is_a_clean_error(engine):
    from slab.semantic.engine import MetricQuery, SemanticQueryError
    with pytest.raises(SemanticQueryError, match="metric"):
        engine.compile(MetricQuery(metrics=("profit",)))


def test_parity_all_in_coverage_questions():
    from slab.parity import run
    assert run() == []
