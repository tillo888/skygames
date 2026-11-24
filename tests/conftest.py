import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from skygames_engine import load_rules  # noqa: E402
from synth import heat_files  # noqa: E402


@pytest.fixture(scope="session")
def rules():
    return load_rules()


@pytest.fixture(scope="session")
def fs1_heat():
    return heat_files("fs1")


@pytest.fixture(scope="session")
def fs2_heat():
    return heat_files("fs2")
