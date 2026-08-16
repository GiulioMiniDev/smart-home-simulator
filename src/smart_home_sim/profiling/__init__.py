"""Readable profiles of the resident a run actually produced.

The aggregate view of an execution trace: what the person does, when, how reliably and where —
published as a contract document, a standalone HTML page and a heatmap matrix.
"""

from smart_home_sim.profiling.builder import (
    DEFAULT_SLOT_MINUTES,
    build_profile,
    profile_from_trace,
    profile_from_trace_file,
    slot_labels,
)
from smart_home_sim.profiling.render import (
    heatmap_rows,
    render_profile_html,
    write_heatmap_csv,
)

__all__ = [
    "DEFAULT_SLOT_MINUTES",
    "build_profile",
    "heatmap_rows",
    "profile_from_trace",
    "profile_from_trace_file",
    "render_profile_html",
    "slot_labels",
    "write_heatmap_csv",
]
