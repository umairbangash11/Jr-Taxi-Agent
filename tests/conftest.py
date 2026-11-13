"""Shared pytest wiring.

Folders named ``phase-1`` are not importable packages, so the repo root (for ``shared``) and each
phase folder are put on ``sys.path`` here.
"""

import os
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PHASE_1 = os.path.join(REPO_ROOT, "phase-1")

for path in (PHASE_1, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)


@pytest.fixture
def sample_path():
    return os.path.join(REPO_ROOT, "samples", "saft_sample.xml")


@pytest.fixture
def out_path(tmp_path):
    return str(tmp_path / "saft_data.json")
