"""
dqt.common.config_loader
========================

YAML/JSON configuration loading and validation for DQT.

This module provides a single entry point --- ``load_config`` --- that reads a
YAML or JSON file from disk, validates it against the appropriate Pydantic
model, and returns the strongly-typed config object.  It also provides
convenience loaders for each specific config type.

Supported config types
----------------------

* :class:`~dqt.common.models.ConnectionConfig`
* :class:`~dqt.common.models.DQPipelineConfig`
* :class:`~dqt.common.models.RuleConfig` (single rule)
* ``list[RuleConfig]`` (rule file with a top-level ``rules`` list)

File format detection
---------------------

The loader infers format from the file extension:

* ``.yaml`` / ``.yml`` → PyYAML (``pip install pyyaml``)
* ``.json`` → standard-library ``json``

Environment variable expansion
-------------------------------

Before validation, all string values are scanned for ``${VAR_NAME}``
placeholders and replaced with the corresponding environment variable.  If the
variable is not set the placeholder is left unchanged so the Pydantic
validator can catch an invalid DSN.

Example::

    from dqt.common.config_loader import load_connection, load_pipeline, load_rules

    conn   = load_connection("config/connection.yaml")
    cfg    = load_pipeline("config/pipeline.yaml")
    rules  = load_rules("examples/rules/base_rules.yaml")
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from dqt.common.models import ConnectionConfig, DQPipelineConfig, RuleConfig

try:
    import yaml as _yaml

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

T = TypeVar("T", bound=BaseModel)

_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _expand_env(value: Any) -> Any:
    """Recursively expand ``${VAR}`` placeholders in strings within a nested
    structure (dict, list, or scalar).

    Unexpanded placeholders (env var not set) are left as-is so that
    downstream Pydantic validators can report meaningful errors.

    Args:
        value: Any Python object (dict, list, str, int, etc.).

    Returns:
        Same structure with all ``${VAR}`` occurrences replaced.

    Example::

        os.environ["DB_PASS"] = "secret"
        assert _expand_env("${DB_PASS}") == "secret"
        assert _expand_env({"dsn": "${DB_PASS}"}) == {"dsn": "secret"}
    """
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    return value


def _read_file(path: Path) -> dict[str, Any]:
    """Read and parse a YAML or JSON file into a raw Python dict.

    Args:
        path: Absolute or relative path to the file.

    Returns:
        Parsed dict (top-level must be a mapping).

    Raises:
        FileNotFoundError: If *path* does not exist.
        ImportError: If the file is YAML but PyYAML is not installed.
        ValueError: If parsing fails or the top-level is not a mapping.

    Example::

        data = _read_file(Path("config/connection.yaml"))
    """
    path = Path(path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw = path.read_text(encoding="utf-8")

    if path.suffix in (".yaml", ".yml"):
        if not _YAML_AVAILABLE:
            raise ImportError(
                "PyYAML is required to load YAML config files. Install it with: pip install pyyaml"
            )
        data = _yaml.safe_load(raw)
    else:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse JSON config at {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"Config file must contain a top-level mapping (got {type(data).__name__}): {path}"
        )
    return data


def _validate(model: type[T], data: dict[str, Any], source: Path) -> T:
    """Validate *data* against *model*, raising a clear error on failure.

    Args:
        model: Pydantic model class to validate against.
        data: Raw dict (after env expansion).
        source: Path used only for error messages.

    Returns:
        Validated model instance.

    Raises:
        ValueError: Wrapping the Pydantic ``ValidationError`` with file context.

    Example::

        conn = _validate(ConnectionConfig, data, Path("conn.yaml"))
    """
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ValueError(
            f"Validation failed for {model.__name__} loaded from {source}:\n{exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_connection(path: str | Path) -> ConnectionConfig:
    """Load and validate a :class:`~dqt.common.models.ConnectionConfig` from file.

    Supports YAML (``.yaml``/``.yml``) and JSON (``.json``) files.
    ``${ENV_VAR}`` placeholders in the DSN are expanded before validation.

    Args:
        path: Path to the config file.

    Returns:
        A validated :class:`~dqt.common.models.ConnectionConfig` instance.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If parsing or validation fails.

    Example::

        conn = load_connection("config/connection.yaml")
        print(conn.dsn)
    """
    p = Path(path)
    data = _expand_env(_read_file(p))
    return _validate(ConnectionConfig, data, p)


def load_pipeline(path: str | Path) -> DQPipelineConfig:
    """Load and validate a :class:`~dqt.common.models.DQPipelineConfig` from file.

    Supports YAML and JSON.  ``${ENV_VAR}`` placeholders are expanded.

    Args:
        path: Path to the config file.

    Returns:
        A validated :class:`~dqt.common.models.DQPipelineConfig` instance.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If parsing or validation fails.

    Example::

        cfg = load_pipeline("config/pipeline.yaml")
        print(cfg.include_schemas)
    """
    p = Path(path)
    data = _expand_env(_read_file(p))
    return _validate(DQPipelineConfig, data, p)


def load_rules(path: str | Path) -> list[RuleConfig]:
    """Load a list of :class:`~dqt.common.models.RuleConfig` objects from file.

    The file must contain a top-level ``rules`` key whose value is a list of
    rule mapping objects.  ``${ENV_VAR}`` placeholders are expanded.

    Args:
        path: Path to a YAML or JSON rule file.

    Returns:
        List of validated :class:`~dqt.common.models.RuleConfig` instances.
        Returns an empty list if the ``rules`` key is absent or empty.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If parsing or validation of any rule fails.

    Example::

        rules = load_rules("examples/rules/base_rules.yaml")
        for rule in rules:
            print(rule.name, rule.expression)
    """
    p = Path(path)
    data = _expand_env(_read_file(p))
    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list):
        raise ValueError(
            f"Rule file must have a top-level 'rules' list (got {type(raw_rules).__name__}): {p}"
        )
    results: list[RuleConfig] = []
    for i, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            raise ValueError(f"Rule #{i} in {p} must be a mapping, got {type(raw).__name__}.")
        results.append(_validate(RuleConfig, raw, p))
    return results


def load_rules_from_files(paths: list[str | Path]) -> list[RuleConfig]:
    """Load and merge rules from multiple files, later files overriding earlier ones.

    Rules with the same ``name`` in later files replace those from earlier files.
    The final list preserves insertion order (first-seen position) with
    overriding rules updated in place.

    Args:
        paths: Ordered list of YAML or JSON rule file paths.

    Returns:
        Merged list of :class:`~dqt.common.models.RuleConfig` instances.

    Example::

        rules = load_rules_from_files([
            "examples/rules/base_rules.yaml",
            "examples/rules/project_overrides.yaml",
        ])
    """
    merged: dict[str, RuleConfig] = {}
    for path in paths:
        for rule in load_rules(path):
            merged[rule.name] = rule
    return list(merged.values())


__all__ = [
    "load_connection",
    "load_pipeline",
    "load_rules",
    "load_rules_from_files",
]
