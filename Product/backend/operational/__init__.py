"""Typed operational companion contracts for the Gen 8 clinical pipeline.

Clinical logic remains in ``clinical_logic.json``.  This package handles
versioned operational intent only: capability resolution, episode lifecycle,
deployment-topology requirements, and external-effect plans.
"""

from .contracts import (
    OperationalValidationError,
    build_operational_package,
    project_lifecycle,
    resolve_capability,
    validate_lifecycle_definition,
)

__all__ = [
    "OperationalValidationError",
    "build_operational_package",
    "project_lifecycle",
    "resolve_capability",
    "validate_lifecycle_definition",
]
