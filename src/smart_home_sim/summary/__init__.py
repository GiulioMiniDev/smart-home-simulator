"""The dataset summary: one page that says what a generated run *is*.

The export publishes evidence; this publishes the reading of it. A floor plan with the sensors on
it, the resident's declared traits, the habit bands stated in words, the realized behaviour beside
them, and an index of every file in the export -- all in a single self-contained HTML document.
"""

from smart_home_sim.summary.document import (
    ROLE_PURPOSE,
    ScenarioFacts,
    SummaryInputs,
    render_summary_html,
)
from smart_home_sim.summary.plan import dwelling_region_ids, polygon_area, render_plan_svg

__all__ = [
    "ROLE_PURPOSE",
    "ScenarioFacts",
    "SummaryInputs",
    "dwelling_region_ids",
    "polygon_area",
    "render_plan_svg",
    "render_summary_html",
]
