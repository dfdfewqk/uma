"""Separate per-scenario rule plug-ins. A new scenario must register its own policy."""
from .island import IslandPostPatchPolicy

POLICIES = {IslandPostPatchPolicy.id: IslandPostPatchPolicy()}
SCENARIOS = {p.id: p.name for p in POLICIES.values()}
