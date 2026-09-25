"""Resolved checks: what a YAML check becomes once it has been parsed,
validated, given its inherited defaults, and assigned a stable identity."""

from __future__ import annotations

from tablewatch.checks.model import Check, Dataset, Outcome

__all__ = ["Check", "Dataset", "Outcome"]
