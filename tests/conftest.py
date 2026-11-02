import pytest

from cdp_migration import synthetic
from cdp_migration.evaluation import make_ctx


@pytest.fixture
def records():
    return synthetic.make_toolkit(seed=5)


@pytest.fixture
def ctx(records, tmp_path):
    return make_ctx(records, out_dir=tmp_path / "out")
