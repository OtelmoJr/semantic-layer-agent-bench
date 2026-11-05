import pytest

from slab import config




def pytest_runtest_setup(item):
    if item.get_closest_marker("data") and not config.DB_PATH.exists():
        pytest.skip("needs the TPC-H database: run `make data`")
    if item.get_closest_marker("semantic") and not (config.DBT_DIR / "target" / "semantic_manifest.json").exists():
        pytest.skip("needs the dbt/MetricFlow manifest: run `make data`")
