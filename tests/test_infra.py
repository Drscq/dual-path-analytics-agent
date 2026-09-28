"""Tests for the scaffolding that is already implemented: config, db, data, fake LLM."""

from __future__ import annotations

import asyncio
import os
import subprocess

import pytest

from dpa import config, data, db
from dpa.llm import FakeLLM, NoMatchingRule, Rule

# --- config -------------------------------------------------------------------------------


def test_key_from_env_wins(monkeypatch):
    monkeypatch.setenv(config.KEY_NAME, "from-env")
    monkeypatch.setattr(config, "_read_keychain", lambda s: pytest.fail("keychain read"))
    assert config.load_api_key() == "from-env"


def test_key_falls_back_to_keychain(monkeypatch):
    monkeypatch.delenv(config.KEY_NAME, raising=False)
    monkeypatch.setattr(config, "_read_keychain", lambda s: "from-keychain")
    assert config.load_api_key() == "from-keychain"


def test_missing_key_explains_setup(monkeypatch):
    monkeypatch.delenv(config.KEY_NAME, raising=False)
    monkeypatch.setattr(config, "_read_keychain", lambda s: None)
    with pytest.raises(config.MissingApiKeyError, match="security add-generic-password"):
        config.load_api_key()


def test_keychain_miss_returns_none(monkeypatch):
    def fake_run(*a, **k):
        return subprocess.CompletedProcess(a, 44, stdout="", stderr="not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert config._read_keychain("nope") is None


def test_model_ids_overridable(monkeypatch):
    monkeypatch.setenv("DPA_FAST_MODEL", "f")
    monkeypatch.setenv("DPA_SLOW_MODEL", "s")
    assert config.Models.from_env() == config.Models("f", "s")


# --- db -----------------------------------------------------------------------------------


def test_execute_returns_columns_and_rows(conn):
    r = db.execute(conn, "SELECT country, count(*) AS n FROM users GROUP BY 1 ORDER BY 1")
    assert r.columns == ("country", "n")
    assert r.rows == (("CN", 1), ("US", 2))
    assert r.elapsed_ms >= 0


def test_schema_ddl_lists_every_table(conn):
    ddl = db.schema_ddl(conn)
    for t in ("users", "orders", "order_items"):
        assert f"CREATE TABLE {t}" in ddl
    assert "sale_price DOUBLE" in ddl


def test_connect_missing_file_is_actionable(tmp_path):
    with pytest.raises(FileNotFoundError, match="make data"):
        db.connect(tmp_path / "nope.duckdb")


# --- data ---------------------------------------------------------------------------------


def test_build_db_loads_csvs(tmp_path):
    (tmp_path / "a.csv").write_text("x,y\n1,foo\n2,bar\n")
    (tmp_path / "b.csv").write_text("z\n3.5\n")
    counts = data.build_db(tmp_path, tmp_path / "out.duckdb", tables=("a", "b"))
    assert counts == {"a": 2, "b": 1}
    with db.connect(tmp_path / "out.duckdb") as c:
        assert db.execute(c, "SELECT y FROM a ORDER BY x").rows == (("foo",), ("bar",))


def test_build_db_names_missing_csvs(tmp_path):
    with pytest.raises(FileNotFoundError, match="orders, users"):
        data.build_db(tmp_path, tmp_path / "out.duckdb", tables=("orders", "users"))


# --- fake llm -----------------------------------------------------------------------------


def test_fake_llm_first_matching_rule_and_records_calls():
    llm = FakeLLM([Rule("pro", model="p"), Rule("hello", contains="hi"), Rule("default")])
    r1 = asyncio.run(llm.generate(model="f", system="s", prompt="say hi"))
    r2 = asyncio.run(llm.generate(model="p", system="s", prompt="say hi", json_mode=True))
    assert (r1.text, r2.text) == ("hello", "pro")
    assert [c.model for c in llm.calls] == ["f", "p"]
    assert llm.calls[1].json_mode is True


def test_fake_llm_no_match_raises():
    with pytest.raises(NoMatchingRule):
        asyncio.run(FakeLLM([Rule("x", model="p")]).generate(model="f", system="", prompt=""))


def test_fake_llm_delay_is_observable():
    r = asyncio.run(FakeLLM([Rule("x", delay_s=0.05)]).generate(model="m", system="", prompt=""))
    assert r.latency_ms >= 45


# --- live (opt-in) ------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("DPA_LIVE") != "1", reason="set DPA_LIVE=1 to call Gemini")
def test_gemini_roundtrip():
    from dpa.llm import GeminiClient

    llm = GeminiClient(config.load_api_key())
    r = asyncio.run(llm.generate(model=config.Models.from_env().fast, system="Reply OK.",
                                 prompt="ping"))
    assert r.text and r.latency_ms > 0
