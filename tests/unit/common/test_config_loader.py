"""
Unit tests for dqt.common.config_loader.

Tests cover:
- YAML and JSON loading for ConnectionConfig, DQPipelineConfig, RuleConfig.
- Environment variable expansion.
- Validation error propagation.
- load_rules_from_files merging behaviour.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from dqt.common.config_loader import (
    load_connection,
    load_pipeline,
    load_rules,
    load_rules_from_files,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_yaml(tmp_path: Path):
    """Helper that writes YAML content to a temp file and returns its path."""

    def _write(filename: str, content: str) -> Path:
        p = tmp_path / filename
        p.write_text(textwrap.dedent(content), encoding="utf-8")
        return p

    return _write


@pytest.fixture
def tmp_json(tmp_path: Path):
    """Helper that writes JSON content to a temp file and returns its path."""

    def _write(filename: str, data: dict) -> Path:
        p = tmp_path / filename
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    return _write


# ---------------------------------------------------------------------------
# ConnectionConfig
# ---------------------------------------------------------------------------


class TestLoadConnection:
    def test_yaml_valid(self, tmp_yaml):
        p = tmp_yaml(
            "conn.yaml",
            """
            id: pg-test
            dsn: postgresql://user:pass@localhost/testdb
            read_only: true
        """,
        )
        conn = load_connection(p)
        assert conn.id == "pg-test"
        assert "testdb" in conn.dsn
        assert conn.read_only is True

    def test_json_valid(self, tmp_json):
        p = tmp_json("conn.json", {"id": "sqlite-dev", "dsn": "sqlite:///dev.db"})
        conn = load_connection(p)
        assert conn.id == "sqlite-dev"

    def test_env_expansion(self, tmp_yaml, monkeypatch):
        monkeypatch.setenv("TEST_DSN", "sqlite:///expanded.db")
        p = tmp_yaml(
            "conn.yaml",
            """
            id: test
            dsn: "${TEST_DSN}"
        """,
        )
        conn = load_connection(p)
        assert conn.dsn == "sqlite:///expanded.db"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_connection(tmp_path / "nonexistent.yaml")

    def test_invalid_validation_raises(self, tmp_yaml):
        p = tmp_yaml(
            "bad_conn.yaml",
            """
            id: ""
            dsn: sqlite:///dev.db
        """,
        )
        with pytest.raises(ValueError, match="Validation failed"):
            load_connection(p)

    def test_blank_dsn_raises(self, tmp_yaml):
        p = tmp_yaml(
            "blank_dsn.yaml",
            """
            id: test
            dsn: "   "
        """,
        )
        with pytest.raises(ValueError, match="Validation failed"):
            load_connection(p)


# ---------------------------------------------------------------------------
# DQPipelineConfig
# ---------------------------------------------------------------------------


class TestLoadPipeline:
    def test_yaml_minimal(self, tmp_yaml):
        p = tmp_yaml(
            "pipeline.yaml",
            """
            connection_id: pg-test
        """,
        )
        cfg = load_pipeline(p)
        assert cfg.connection_id == "pg-test"
        assert cfg.include_schemas is None

    def test_yaml_full(self, tmp_yaml):
        p = tmp_yaml(
            "pipeline_full.yaml",
            """
            connection_id: pg-test
            include_schemas: [public, staging]
            exclude_tables: [audit_log]
            metric_thresholds:
              completeness: 0.95
              validity: 0.99
            rule_files:
              - examples/rules/base_rules.yaml
        """,
        )
        cfg = load_pipeline(p)
        assert cfg.include_schemas == ["public", "staging"]
        assert cfg.exclude_tables == ["audit_log"]
        assert cfg.metric_thresholds["completeness"] == 0.95
        assert len(cfg.rule_files) == 1

    def test_overlap_validation(self, tmp_yaml):
        p = tmp_yaml(
            "overlap.yaml",
            """
            connection_id: test
            include_schemas: [public]
            exclude_schemas: [public]
        """,
        )
        with pytest.raises(ValueError, match="Validation failed"):
            load_pipeline(p)

    def test_threshold_out_of_range(self, tmp_yaml):
        p = tmp_yaml(
            "bad_thresh.yaml",
            """
            connection_id: test
            metric_thresholds:
              completeness: 1.5
        """,
        )
        with pytest.raises(ValueError, match="Validation failed"):
            load_pipeline(p)


# ---------------------------------------------------------------------------
# RuleConfig
# ---------------------------------------------------------------------------


class TestLoadRules:
    def test_yaml_valid(self, tmp_yaml):
        p = tmp_yaml(
            "rules.yaml",
            """
            rules:
              - name: not_null_email
                dimension: completeness
                severity: error
                scope:
                  column_pattern: email
                expression: NOT NULL
        """,
        )
        rules = load_rules(p)
        assert len(rules) == 1
        assert rules[0].name == "not_null_email"
        assert rules[0].expression == "NOT NULL"

    def test_json_valid(self, tmp_json):
        p = tmp_json(
            "rules.json",
            {
                "rules": [
                    {
                        "name": "unique_id",
                        "dimension": "uniqueness",
                        "severity": "critical",
                        "scope": {"column_pattern": "id"},
                        "expression": "UNIQUE",
                    }
                ]
            },
        )
        rules = load_rules(p)
        assert rules[0].expression == "UNIQUE"

    def test_empty_rules_key(self, tmp_yaml):
        p = tmp_yaml("empty.yaml", "rules: []")
        assert load_rules(p) == []

    def test_missing_rules_key_returns_empty(self, tmp_yaml):
        p = tmp_yaml("no_rules.yaml", "connection_id: test")
        assert load_rules(p) == []

    def test_invalid_rule_name_with_space(self, tmp_yaml):
        p = tmp_yaml(
            "bad_name.yaml",
            """
            rules:
              - name: "bad name"
                dimension: completeness
                severity: error
                scope: {}
                expression: NOT NULL
        """,
        )
        with pytest.raises(ValueError, match="Validation failed"):
            load_rules(p)

    def test_invalid_severity(self, tmp_yaml):
        p = tmp_yaml(
            "bad_sev.yaml",
            """
            rules:
              - name: some_rule
                dimension: completeness
                severity: ultra_critical
                scope: {}
                expression: NOT NULL
        """,
        )
        with pytest.raises(ValueError, match="Validation failed"):
            load_rules(p)


class TestLoadRulesFromFiles:
    def test_merge_override(self, tmp_yaml):
        p1 = tmp_yaml(
            "r1.yaml",
            """
            rules:
              - name: check_a
                dimension: completeness
                severity: warning
                scope: {}
                expression: NOT NULL
        """,
        )
        p2 = tmp_yaml(
            "r2.yaml",
            """
            rules:
              - name: check_a
                dimension: completeness
                severity: critical
                scope: {}
                expression: NOT NULL
        """,
        )
        merged = load_rules_from_files([p1, p2])
        assert len(merged) == 1
        assert merged[0].severity == "critical"  # p2 wins

    def test_merge_additive(self, tmp_yaml):
        p1 = tmp_yaml(
            "r1b.yaml",
            """
            rules:
              - name: rule_one
                dimension: completeness
                severity: warning
                scope: {}
                expression: NOT NULL
        """,
        )
        p2 = tmp_yaml(
            "r2b.yaml",
            """
            rules:
              - name: rule_two
                dimension: uniqueness
                severity: error
                scope: {}
                expression: UNIQUE
        """,
        )
        merged = load_rules_from_files([p1, p2])
        assert len(merged) == 2
