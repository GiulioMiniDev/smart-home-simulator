"""Versioned input and report contracts."""

from smart_home_sim.domain.models import Scenario
from smart_home_sim.domain.report import ValidationIssue, ValidationReport

__all__ = ["Scenario", "ValidationIssue", "ValidationReport"]
