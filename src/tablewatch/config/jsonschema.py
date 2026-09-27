"""JSON Schemas for check files and `tablewatch.yml`.

Editors use these for completion and inline errors (VS Code's YAML
extension via `yaml.schemas`). The check-file schema is built from the
metric registry, so a new metric — or a new option on one — appears in the
editor without anyone editing a schema by hand.
"""

from __future__ import annotations

from typing import Any

from tablewatch.config.loader import COMMON_CHECK_KEYS
from tablewatch.config.project import ProjectConfig
from tablewatch.metrics.base import Metric, OptionType
from tablewatch.metrics.registry import all_metrics

DRAFT = "https://json-schema.org/draft/2020-12/schema"

_OPTION_SCHEMAS: dict[OptionType, dict[str, Any]] = {
    OptionType.STRING: {"type": "string", "minLength": 1},
    OptionType.NUMBER: {"type": "number"},
    OptionType.INTEGER: {"type": "integer", "minimum": 0},
    OptionType.VALUE_LIST: {
        "type": "array",
        "minItems": 1,
        "items": {"type": ["string", "number", "boolean"]},
    },
    OptionType.STRING_LIST: {
        "type": "array",
        "minItems": 1,
        "items": {"type": "string"},
    },
    OptionType.MAPPING: {"type": "object", "additionalProperties": {"type": "string"}},
}

_COMMON: dict[str, dict[str, Any]] = {
    "name": {"type": "string", "description": "Human-readable name shown in results."},
    "id": {
        "type": "string",
        "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]*$",
        "description": "Pin the check's identity so history survives edits.",
    },
    "warn": {
        "type": "string",
        "pattern": "^\\s*when\\b",
        "description": "e.g. 'when < 1000'",
    },
    "fail": {
        "type": "string",
        "pattern": "^\\s*when\\b",
        "description": "e.g. 'when = 0'",
    },
}
assert set(_COMMON) == set(COMMON_CHECK_KEYS)


def _starts_with_metric(name: str) -> str:
    return f"^\\s*{name}(?![A-Za-z0-9_])"


def _options_schema(metric: Metric) -> dict[str, Any]:
    properties = dict(_COMMON)
    if metric.scoped:
        properties["where"] = {
            "type": "string",
            "description": "SQL condition restricting the rows this check considers.",
        }
    for option, kind in metric.options.items():
        properties[option] = _OPTION_SCHEMAS[kind]
    return {
        "type": ["object", "null"],
        "description": metric.summary,
        "properties": properties,
        "additionalProperties": False,
    }


def check_file_schema() -> dict[str, Any]:
    metrics = all_metrics()
    names = "|".join(m.name for m in metrics)
    return {
        "$schema": DRAFT,
        "title": "tablewatch check file",
        "description": "One dataset and the checks that run against it.",
        "type": "object",
        "required": ["dataset", "checks"],
        "additionalProperties": False,
        "properties": {
            "dataset": {
                "type": "string",
                "description": "Table name, optionally schema.table.",
            },
            "datasource": {
                "type": "string",
                "description": "A datasource from tablewatch.yml.",
            },
            "filter": {
                "type": "string",
                "description": "SQL condition scoping every check.",
            },
            "owner": {"type": "string"},
            "tags": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ]
            },
            "checks": {
                "type": "array",
                "items": {
                    "oneOf": [
                        {
                            "type": "string",
                            "pattern": f"^\\s*({names})(?![A-Za-z0-9_])",
                            "description": "A check expression, e.g. 'row_count > 0'.",
                        },
                        {
                            "type": "object",
                            "minProperties": 1,
                            "maxProperties": 1,
                            "patternProperties": {
                                _starts_with_metric(m.name): {
                                    "$ref": f"#/$defs/{m.name}"
                                }
                                for m in metrics
                            },
                            "additionalProperties": False,
                        },
                    ]
                },
            },
        },
        "$defs": {m.name: _options_schema(m) for m in metrics},
    }


def project_schema() -> dict[str, Any]:
    schema = ProjectConfig.model_json_schema()
    schema["$schema"] = DRAFT
    schema["title"] = "tablewatch.yml"
    return schema
