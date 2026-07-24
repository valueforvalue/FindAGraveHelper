"""Events subpackage: SIEM-pipeable event translations."""
from scripts.events.ocsf import (
    OCSF_MAPPING,
    event_to_ocsf,
    sidecar_path_for,
    translate_audit_file,
)

__all__ = [
    "OCSF_MAPPING",
    "event_to_ocsf",
    "sidecar_path_for",
    "translate_audit_file",
]