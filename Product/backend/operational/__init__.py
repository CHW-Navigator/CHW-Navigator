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
from .topology import (
    assert_persona_isolation,
    assert_topology_valid,
    build_topology_lock,
    resolve_topology_relation,
    resolve_topology_relation_for_user,
    simulate_topology_access,
    validate_topology_requirements_against_package,
    validate_topology_package,
)

__all__ = [
    "OperationalValidationError",
    "build_operational_package",
    "project_lifecycle",
    "resolve_capability",
    "validate_lifecycle_definition",
    "assert_persona_isolation",
    "assert_topology_valid",
    "build_topology_lock",
    "resolve_topology_relation",
    "resolve_topology_relation_for_user",
    "simulate_topology_access",
    "validate_topology_requirements_against_package",
    "validate_topology_package",
]
