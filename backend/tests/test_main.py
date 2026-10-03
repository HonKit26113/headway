"""Tests for main.py startup (CONTRACT.md Phase E hardening M1).

main.py loads transit data in a FastAPI `lifespan` handler (no deprecated on_event); startup
with missing data reports fallback and never crashes. No network; backend/data is only read.
"""
from __future__ import annotations

import importlib
import warnings
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service import transit

REAL_DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(autouse=True)
def fresh_transit():
    transit.reset()
    yield
    transit.reset()


def _import_main():
    import main
    return main


def test_startup_with_empty_data_dir_reports_fallback(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(transit, "DATA_DIR", empty)
    transit.reset()
    main = _import_main()
    with TestClient(main.app):
        st = transit.data_status()
        assert st["fallback"] is True
        assert st["gtfs_loaded"] is False
        assert st["stops"] == 0


def test_startup_calls_transit_load(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(transit, "DATA_DIR", empty)
    calls = []
    real_load = transit.load

    def spy(*a, **k):
        calls.append((a, k))
        return real_load(*a, **k)

    monkeypatch.setattr(transit, "load", spy)
    main = _import_main()
    with TestClient(main.app):
        assert len(calls) == 1


def test_startup_with_missing_data_dir_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(transit, "DATA_DIR", tmp_path / "does_not_exist")
    main = _import_main()
    with TestClient(main.app):
        assert transit.data_status()["fallback"] is True


def test_no_on_event_deprecation_warning(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(transit, "DATA_DIR", empty)
    import main
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        main = importlib.reload(main)
        with TestClient(main.app):
            pass
    bad = [w for w in caught
           if issubclass(w.category, DeprecationWarning) and "on_event" in str(w.message)]
    assert bad == [], [str(w.message) for w in bad]


def test_no_on_event_handlers_registered():
    main = _import_main()
    assert list(main.app.router.on_startup) == []
    assert list(main.app.router.on_shutdown) == []


def test_startup_raises_no_deprecation_as_error(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr(transit, "DATA_DIR", empty)
    import main
    with warnings.catch_warnings():
        warnings.filterwarnings("error", message=".*on_event.*", category=DeprecationWarning)
        main = importlib.reload(main)
        with TestClient(main.app):
            assert transit.data_status()["fallback"] is True


@pytest.mark.real
@pytest.mark.skipif(not (REAL_DATA / "manifest.json").exists(),
                    reason="backend/data/manifest.json missing")
def test_startup_loads_real_data():
    main = _import_main()
    with TestClient(main.app):
        st = transit.data_status()
        assert st["gtfs_loaded"] is True
        assert st["fallback"] is False
        assert st["stops"] >= 8000
