"""One page that says what a generated dataset is: the flat, the sensors, the person, the answers.

An export publishes the evidence a run produced -- a sensor log, an oracle, a diary, a profile --
and every one of those files answers a question the reader has to already know to ask. What it has
never published is the thing a person opens first: a page that says which flat this is, where the
sensors were put, who lives there and what her days are supposed to look like. Without it
`pir_kitchen` is a string, the habit bands are rows in a CSV, and the home model never leaves the
workspace at all.

This document is that page, and it is deliberately *one file*: HTML with inline SVG, no script and
no external reference, so it survives being emailed, committed beside a thesis chapter or opened
from a memory stick in eight years. It states nothing of its own -- every number in it is read from
an artifact of the run -- and it carries no clock reading, so the same run and the same request
rebuild the same bytes.

It states the ground truth in the open, bands, dominant activities and all. That is the point: the
reader of this page is the person who commissioned the dataset, and a summary that withheld the
answer sheet would be a summary of somebody else's problem. The blind view of the same run is the
export beside it, whose observable log carries no labels at all.
"""

from __future__ import annotations

import html
import re
from collections.abc import Container, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from smart_home_sim.domain.application import ExportManifestFile
from smart_home_sim.domain.environment import HomeModel
from smart_home_sim.domain.profile import ResidentProfile
from smart_home_sim.domain.sensors import SensorModel
from smart_home_sim.profiling.render import STYLE as PROFILE_STYLE
from smart_home_sim.profiling.render import resident_sections
from smart_home_sim.summary.plan import (
    PLAN_STYLE,
    SERVICE_ENTITY_TYPE,
    polygon_area,
    render_plan_svg,
    sensor_region_ids,
)

# Composition rows beyond this stop being a mix and start being a tail; the exported ground truth
# carries every one of them.
MAX_COMPOSITION_ROWS = 8
# Hues for the composition bars, far enough apart to be told apart in a stripe a few pixels tall.
# The same ramp the profile page uses for its rhythm strip, assigned once per activity across every
# band so that one activity keeps one colour down the page.
HUES = (12, 200, 130, 45, 275, 170, 330, 95, 240, 25, 305, 60)

# What each exported role is *for*, in the words a reader needs to decide whether to open it.
ROLE_PURPOSE: dict[str, str] = {
    "observable": "What a physical sensor field would have recorded. No identity, no activity "
    "label, no admission of noise: this is the input side of any experiment.",
    "oracle": "The causal link from each reading back to the resident and the activity that "
    "caused it. The answer key for the sensor log, kept in a separate file on purpose.",
    "activities": "Every activity the simulator actually executed, planned and actual times "
    "included. The realized diary.",
    "actions": "The atomic steps inside those activities, with the entity each one touched.",
    "movements": "Where the resident went and when she arrived. Presence, not activity.",
    "state_transitions": "Every change of a world fact: doors, appliances, lights, containers.",
    "resources": "Claims and releases of the things that can only be used by one person at once.",
    "runtime_events": "The disturbances the run injected, and what each of them displaced.",
    "plan_deviations": "Where execution departed from the compiled plan, and by how much.",
    "final_state": "The world as the horizon left it.",
    "habit_ground_truth": "The declared habit bands with the activity mix each one holds. The "
    "target a segmentation algorithm is scored against.",
    "resident_profile": "The realized behaviour aggregated onto the clock: document, page and "
    "heatmap matrix.",
    "summary": "This page.",
}

SUMMARY_STYLE = """
:root { --plan-paper: #ffffff; --plan-grid: #eef0f4; --plan-room: #f6f7f9;
  --plan-wall: #2a2d33; --plan-ink: #2a2d33; --plan-furniture: #cbd8d4; --plan-tint: #dcefed;
  --plan-warm: #fff4df; --sensor-contact: #b4632a; --sensor-temperature: #3a63b8;
  --card: #fbfcfd; }
@media (prefers-color-scheme: dark) {
  :root { --plan-paper: #171a1f; --plan-grid: #22262d; --plan-room: #1d2126;
    --plan-wall: #c9cfd8; --plan-ink: #dfe3ea; --plan-furniture: #38474a; --plan-tint: #24393c;
    --plan-warm: #3b3524; --sensor-contact: #e0965d; --sensor-temperature: #7fa6f0;
    --card: #191c21; } }
h2 { border-top: 1px solid var(--line); padding-top: 1.6rem; }
h2:first-of-type { border-top: none; }
section > p:first-of-type { max-width: 62ch; }
ul.legend.plan-key { margin-top: .2rem; }
ul.legend.plan-key span.pir { background: var(--accent); }
ul.legend.plan-key span.contact { background: var(--sensor-contact); }
ul.legend.plan-key span.temperature { background: var(--sensor-temperature); }
ul.legend.plan-key span.furniture { background: var(--plan-furniture); }
.metrics { display: flex; flex-wrap: wrap; gap: .6rem; margin: 1rem 0 0; padding: 0;
  list-style: none; }
.metrics li { flex: 1 1 8rem; border: 1px solid var(--line); border-radius: 6px;
  background: var(--card); padding: .55rem .7rem; }
.metrics strong { display: block; font-size: 1.35rem; line-height: 1.2; }
.metrics span { color: var(--muted); font-size: .78rem; text-transform: uppercase;
  letter-spacing: .06em; }
.band { border: 1px solid var(--line); border-radius: 6px; background: var(--card);
  padding: .9rem 1rem; margin: .9rem 0; }
.band h4 { margin-top: 0; }
.band .window { font-size: 1.05rem; font-weight: 600; }
.band .says { margin: .5rem 0 .2rem; max-width: 72ch; }
.bar { display: flex; height: .8rem; border-radius: 3px; overflow: hidden; margin: .6rem 0 .35rem;
  background: var(--track); }
.bar span { display: block; height: 100%; }
.bar span.rest { background: repeating-linear-gradient(135deg, var(--track), var(--track) 3px,
  var(--line) 3px, var(--line) 6px); }
dl.persona { margin: .6rem 0 0; }
dl.persona div { display: flex; gap: .8rem; border-bottom: 1px solid var(--line);
  padding: .28rem 0; }
dl.persona dt { color: var(--muted); flex: 0 0 16rem; }
dl.persona dd { margin: 0; }
dl.persona dl { margin: 0; }
dl.persona dl div { border: none; padding: .1rem 0; }
dl.persona dl dt { flex-basis: 13rem; }
td.wrap, th.wrap { text-align: left; }
td.numeric, th.numeric { text-align: right; font-variant-numeric: tabular-nums; }
"""


@dataclass(frozen=True)
class ScenarioFacts:
    """The handful of scenario fields a reader needs, read without materializing the days.

    A five month scenario is four megabytes of day plans, none of which belongs on this page, so
    the export streams out the few keys that do rather than validating the whole document.
    """

    title: str | None = None
    language: str | None = None
    time_zone: str | None = None
    residents: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class SummaryInputs:
    """Everything the page states, gathered from the run's own artifacts.

    The identifier of the export is deliberately not among them. It is a fresh uuid on every
    publication, so printing it on the page would make two rebuilds of the same request differ by
    bytes -- and rebuilding a deleted export byte for byte is the promise the whole export makes.
    The manifest sitting beside the page carries that identifier.
    """

    run_id: str
    seed: int
    trace_digest: str
    profile: ResidentProfile
    files: Sequence[ExportManifestFile]
    home: HomeModel | None = None
    sensors: SensorModel | None = None
    scenario: ScenarioFacts | None = None
    # The habit ground truth exactly as the scenario carries it. A payload rather than a validated
    # model: this page must render for every run in the workspace, including ones written against
    # an earlier version of that contract, and a summary that refuses to build is worse than one
    # that says a field is missing.
    habits: Mapping[str, Any] | None = None
    # Per-sensor counters from the projection report, by sensor identifier.
    sensor_stats: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    include_start: datetime | None = None
    include_end: datetime | None = None


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _readable(value: str) -> str:
    """`walkingSpeedMetersPerSecond` and `walking_speed` both read as words, not as code."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value).replace("_", " ")
    return spaced[:1].upper() + spaced[1:].lower() if spaced else spaced


def _plain(value: str) -> str:
    return value.replace("_", " ")


def _count(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def _duration(minutes: float) -> str:
    total = int(round(minutes))
    if total >= 1440:
        return f"{total // 1440}d {total % 1440 // 60}h"
    return f"{total // 60}h {total % 60:02d}m" if total >= 60 else f"{total} min"


def _percent(share: float) -> str:
    return f"{share * 100:.1f}%"


def _bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "kB", "MB"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _rows(
    header: Sequence[str], rows: Iterable[Sequence[str]], numeric: Container[int] = ()
) -> str:
    """A table whose columns say which of them hold numbers.

    Right-alignment is for quantities. Applied to a column of room names or of sentences it reads
    as a layout accident, which is what a single "everything after the first column" rule produces.
    """
    head = "".join(
        f'<th class="{"numeric" if index in numeric else "wrap"}">{_escape(name)}</th>'
        for index, name in enumerate(header)
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td class="{"numeric" if index in numeric else "wrap"}">{cell}</td>'
            for index, cell in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _definition(pairs: Iterable[tuple[str, str]]) -> str:
    return (
        "<dl>"
        + "".join(f"<div><dt>{_escape(name)}</dt><dd>{value}</dd></div>" for name, value in pairs)
        + "</dl>"
    )


# --- the home ---------------------------------------------------------------------------------


def _home_section(inputs: SummaryInputs) -> str:
    home = inputs.home
    if home is None:
        return (
            '<section><h2>The home</h2><p class="empty">This run carries no home model, so the '
            "flat cannot be drawn. Sensor identifiers in the log have no place attached to "
            "them.</p></section>"
        )
    sensors = inputs.sensors
    entity_region = {item.entity_id: item.region_id for item in home.entities}
    by_region: dict[str, list[str]] = {}
    for sensor in sensors.sensors if sensors else []:
        for region_id in sensor_region_ids(sensor, entity_region):
            by_region.setdefault(region_id, []).append(sensor.sensor_id)
    furniture: dict[str, list[str]] = {}
    for entity in home.entities:
        if entity.entity_type != SERVICE_ENTITY_TYPE:
            furniture.setdefault(entity.region_id, []).append(_plain(entity.entity_type))

    rooms = [item for item in home.regions if item.kind == "room"]
    table = _rows(
        ("Room", "Area", "Furniture", "Sensors"),
        (
            (
                _escape(_plain(room.region_id)),
                f"{polygon_area(room.boundary.vertices):.1f} m²",
                _escape(", ".join(sorted(furniture.get(room.region_id, []))) or "—"),
                _escape(", ".join(sorted(by_region.get(room.region_id, []))) or "—"),
            )
            for room in sorted(rooms, key=lambda item: -polygon_area(item.boundary.vertices))
        ),
        numeric=(1,),
    )
    elsewhere = sorted(item.region_id for item in home.regions if item.kind != "room")
    beyond = (
        f'<p class="note">The resident also leaves the flat: the scenario places '
        f"{len(elsewhere)} region(s) outside it — "
        f"{_escape(', '.join(_plain(x) for x in elsewhere))}"
        ". They are part of the world and of the log, and are left off the drawing because at "
        "kilometres away they would leave the dwelling unreadable in a corner.</p>"
        if elsewhere
        else ""
    )
    legend = (
        '<ul class="legend plan-key">'
        '<li><span class="pir"></span>motion (PIR), dashed outline is its field of view</li>'
        '<li><span class="contact"></span>contact, on a door or a cupboard</li>'
        '<li><span class="temperature"></span>temperature, one per room</li>'
        '<li><span class="furniture"></span>furniture footprint the resident walks around</li>'
        "</ul>"
    )
    return (
        f'<section><h2>The home</h2><p class="meta">'
        f"<code>{_escape(home.home_id)}</code> {_escape(home.home_version)} · "
        f"{len(rooms)} rooms · {len(home.entities)} entities · "
        f"{len(home.obstacles)} furniture footprints · "
        f"{sum(polygon_area(item.boundary.vertices) for item in rooms):.1f} m² of floor</p>"
        "<p>The drawing is derived from the same geometry the path planner routes through: rooms "
        "as the materializer tiled them, doors on the walls they actually cross, furniture at the "
        "extent the resident has to walk around, and the sensors where they were deployed.</p>"
        f"{render_plan_svg(home, sensors)}{legend}{table}{beyond}</section>"
    )


# --- the sensors ------------------------------------------------------------------------------


def _sensor_watches(sensor: Any) -> str:
    if sensor.sensor_type == "contact":
        trigger = f"on {sensor.action_trigger}" if sensor.action_types else ""
        fact = f"fact <code>{_escape(sensor.fact)}</code>" if sensor.fact else ""
        return " · ".join(
            part for part in (f"<code>{_escape(sensor.entity_id)}</code>", fact, trigger) if part
        )
    if sensor.sensor_type == "temperature":
        # What actually moves the reading: a thermometer with no sources is a flat line, and the
        # deltas are the only thing in the model that says a shower is visible in the bathroom.
        sources = ", ".join(
            f"{_plain(item.entity_id)} {item.delta_celsius:+.1f} °C" for item in sensor.sources
        )
        return f"{sensor.baseline_celsius:.1f} °C baseline · {_escape(sources)}"
    return "presence in " + _escape(", ".join(_plain(item) for item in sensor.region_ids))


def _sensor_tuning(sensor: Any) -> str:
    if sensor.sensor_type == "pir":
        return f"holds {sensor.hold_milliseconds / 1000:.0f} s"
    if sensor.sensor_type == "contact":
        return f"pulses {sensor.pulse_milliseconds / 1000:.1f} s"
    interval = min(item.sample_interval_seconds for item in sensor.sources)
    return f"samples every {interval / 60:.0f} min, {sensor.reporting_mode}"


def _sensor_section(inputs: SummaryInputs) -> str:
    sensors = inputs.sensors
    if sensors is None:
        return (
            '<section><h2>The sensor field</h2><p class="empty">This run carries no sensor '
            "model.</p></section>"
        )
    entities = inputs.home.entities if inputs.home else []
    entity_region = {item.entity_id: item.region_id for item in entities}
    stats = inputs.sensor_stats
    rows = []
    for sensor in sorted(sensors.sensors, key=lambda item: item.sensor_id):
        counters = stats.get(sensor.sensor_id, {})
        observed = counters.get("observationCount")
        candidates = counters.get("candidateCount") or 0
        lost = sum(
            int(counters.get(name, 0) or 0)
            for name in ("dropoutCount", "falseNegativeCount", "failureSuppressedCount")
        )
        invented = int(counters.get("falsePositiveCount", 0) or 0)
        rows.append(
            (
                f"<code>{_escape(sensor.sensor_id)}</code>",
                _escape(sensor.sensor_type),
                _escape(
                    ", ".join(_plain(x) for x in sensor_region_ids(sensor, entity_region)) or "—"
                ),
                _sensor_watches(sensor),
                _escape(_sensor_tuning(sensor)),
                _count(observed) if observed is not None else "—",
                f"{lost / candidates:.2%}" if candidates else "—",
                _count(invented) if counters else "—",
            )
        )
    table = _rows(
        ("Sensor", "Type", "Where", "What it watches", "Tuning", "Readings", "Lost", "Invented"),
        rows,
        numeric=(5, 6, 7),
    )
    note = (
        '<p class="note">Loss is dropout, missed detection and declared outage together, as a '
        "share of the events the sensor could have reported; invented readings are false "
        "positives. These are stated per sensor and never per reading: the exported log carries "
        "no column admitting which of its own readings are unreliable, because no real sensor log "
        "does. Declaring the rate is what a dataset owes its reader; labelling the rows would hand "
        "over part of the answer.</p>"
        if stats
        else '<p class="note">This run publishes no projection counters, so only the declared '
        "configuration of each sensor is shown.</p>"
    )
    return (
        f'<section><h2>The sensor field</h2><p class="meta">'
        f"<code>{_escape(sensors.sensor_model_id)}</code> "
        f"{_escape(sensors.sensor_model_version)} · "
        f"{len(sensors.sensors)} sensors</p>"
        "<p>Every reading in the observable log comes from one of these, and carries nothing but "
        "the sensor's own identifier, a timestamp and a value.</p>"
        f"{table}{note}</section>"
    )


# --- the resident -----------------------------------------------------------------------------


def _persona_value(value: Any) -> str:
    if isinstance(value, dict):
        return _persona_list(value)
    if isinstance(value, list):
        return _escape(", ".join(_plain(str(item)) for item in value)) or "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return _escape(_plain(str(value)))


def _persona_list(profile: Mapping[str, Any]) -> str:
    return (
        "<dl>"
        + "".join(
            f"<div><dt>{_escape(_readable(name))}</dt><dd>{_persona_value(value)}</dd></div>"
            for name, value in profile.items()
        )
        + "</dl>"
    )


def _resident_section_declared(inputs: SummaryInputs) -> str:
    scenario = inputs.scenario
    residents = scenario.residents if scenario else []
    described = [item for item in residents if item.get("profile")]
    if not described:
        # Outline-first horizons keep the persona in the outline, which the application never
        # receives: the run holds the days the persona produced and not the persona itself. Saying
        # so is better than an empty section that reads as a resident with no traits.
        source = (
            "This horizon was expanded from an outline, and the outline is not part of the run: "
            "the scenario carries the days it produced, not the person it described. What the "
            "resident is like has to be read from the bands and the behaviour below."
            if inputs.habits
            else "The scenario declares no traits for this resident."
        )
        names = ", ".join(
            _escape(item.get("displayName") or item.get("residentId", "")) for item in residents
        )
        return (
            f'<section><h2>The resident</h2><p class="meta">{names or "—"}</p>'
            f'<p class="empty">{source}</p></section>'
        )
    people = "".join(
        f"<h3>{_escape(item.get('displayName') or _plain(item.get('residentId', 'resident')))}</h3>"
        f'<p class="meta"><code>{_escape(item.get("residentId", ""))}</code></p>'
        f'<dl class="persona">{_persona_list(item.get("profile", {}))[4:-5]}</dl>'
        for item in described
    )
    return (
        "<section><h2>The resident</h2>"
        "<p>Declared by the scenario before anything ran. These traits are inputs to the "
        "generator, not measurements of it: what the simulation made of them is the realized "
        "behaviour further down.</p>"
        f"{people}</section>"
    )


# --- the declared habit bands -----------------------------------------------------------------


def _hue_by_intent(bands: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """One colour per activity for the whole section, not one per position in each bar.

    Colouring by rank inside a band paints the largest slice of every band the same red, which
    reads as the same activity holding all of them. Ranking the activities once, across every band,
    is what makes the bars comparable: `sleep` is one colour wherever it turns up.
    """
    minutes: dict[str, float] = {}
    for band in bands:
        for item in band.get("composition") or []:
            intent = str(item.get("intent", ""))
            minutes[intent] = minutes.get(intent, 0.0) + float(item.get("minutes", 0.0))
    order = sorted(minutes, key=lambda intent: (-minutes[intent], intent))
    return {intent: HUES[index % len(HUES)] for index, intent in enumerate(order)}


def _composition_bar(
    composition: Sequence[Mapping[str, Any]], unaccounted: float, hues: Mapping[str, int]
) -> str:
    parts = []
    for item in composition[:MAX_COMPOSITION_ROWS]:
        share = float(item.get("share", 0.0))
        if share <= 0:
            continue
        hue = hues.get(str(item.get("intent", "")), HUES[0])
        parts.append(
            f'<span style="width:{share * 100:.2f}%;background:hsl({hue} 72% 48%)" '
            f'title="{_escape(_plain(str(item.get("intent", ""))))} {_percent(share)}"></span>'
        )
    rest = max(
        0.0,
        1.0
        - sum(float(item.get("share", 0.0)) for item in composition[:MAX_COMPOSITION_ROWS])
        - unaccounted,
    )
    if rest > 0:
        parts.append(f'<span style="width:{rest * 100:.2f}%;background:var(--line)"></span>')
    if unaccounted > 0:
        parts.append(f'<span class="rest" style="width:{unaccounted * 100:.2f}%"></span>')
    return f'<div class="bar">{"".join(parts)}</div>'


def _band_says(band: Mapping[str, Any]) -> str:
    """The band in one sentence, because a table of shares is not an answer anyone reads first."""
    label = _escape(band.get("label", band.get("habitId", "band")))
    window = f"{_escape(band.get('windowStart', ''))}–{_escape(band.get('windowEnd', ''))}"
    weekdays = band.get("weekdays") or []
    days = (
        f"on {_escape(', '.join(_plain(str(day)) for day in weekdays))}"
        if weekdays
        else "every day"
    )
    applies = f"{_count(band.get('dayCount', 0))} day(s)"
    unnamed = (
        f"{_percent(float(band.get('unaccountedShare', 0.0)))} of the band is time the outline "
        "named nothing for."
    )
    dominant = band.get("dominantIntent")
    if not dominant:
        return (
            f"<strong>{label}</strong> runs {window} {days}, over {applies}, and no single "
            "activity holds it on most days — which is itself the finding, and the reason no "
            f"boundary is claimed for it. {unnamed}"
        )

    share = next(
        (
            float(item.get("share", 0.0))
            for item in band.get("composition") or []
            if str(item.get("intent", "")) == str(dominant)
        ),
        0.0,
    )
    held = (
        f"<b>{_escape(_plain(str(dominant)))}</b>, which accounts for {_percent(share)} of the "
        "time inside it"
    )
    start, end = band.get("effectiveStart"), band.get("effectiveEnd")
    # The declared window is where the planner was *allowed* to put the band; the effective one is
    # where its dominant activity reliably lands. A band whose activity holds no stretch on most
    # days has no second answer to give, and inventing one would be the wrong kind of helpful.
    boundary = (
        f" and actually runs {_escape(start)}–{_escape(end)}, covering "
        f"{_percent(float(band.get('effectiveShare', 0.0)))} of the declared window"
        if start and end
        else ", though no stretch of the band is held on most days, so the behaviour supports no "
        "boundary narrower than the window itself"
    )
    return (
        f"<strong>{label}</strong> runs {window} {days}, over {applies}. It is held by "
        f"{held}{boundary}. {unnamed}"
    )


def _band_card(band: Mapping[str, Any], hues: Mapping[str, int]) -> str:
    composition = list(band.get("composition") or [])
    unaccounted = float(band.get("unaccountedShare", 0.0))
    hidden = max(len(composition) - MAX_COMPOSITION_ROWS, 0)
    table = _rows(
        ("Activity", "Share", "Time in band"),
        (
            (
                _escape(_plain(str(item.get("intent", "")))),
                _percent(float(item.get("share", 0.0))),
                _duration(float(item.get("minutes", 0.0))),
            )
            for item in composition[:MAX_COMPOSITION_ROWS]
        ),
        numeric=(1, 2),
    )
    splits = "".join(
        f'<p class="meta">{_escape(_plain(str(item.get("dayType", ""))))}: '
        f"{_count(item.get('dayCount', 0))} day(s), "
        + ", ".join(
            f"{_escape(_plain(str(part.get('intent', ''))))} "
            f"{_percent(float(part.get('share', 0)))}"
            for part in list(item.get("composition") or [])[:4]
        )
        + f", {_percent(float(item.get('unaccountedShare', 0.0)))} unnamed</p>"
        for item in (band.get("dayTypes") or [])
    )
    crosses = ' <span class="meta">(crosses midnight)</span>' if band.get("crossesMidnight") else ""
    return (
        f'<article class="band"><p class="window">'
        f"{_escape(band.get('windowStart', ''))} → {_escape(band.get('windowEnd', ''))}{crosses}"
        f'</p><p class="says">{_band_says(band)}</p>'
        f"{_composition_bar(composition, unaccounted, hues)}{table}"
        + (
            f'<p class="note">{hidden} rarer activity row(s) omitted here; the exported ground '
            "truth carries them all.</p>"
            if hidden
            else ""
        )
        + splits
        + "</article>"
    )


def _habits_section(inputs: SummaryInputs) -> str:
    habits = inputs.habits
    bands = list((habits or {}).get("habits") or [])
    if not bands:
        return (
            '<section><h2>The declared habits</h2><p class="empty">This run declares no habit '
            "bands. They exist only for horizons expanded from an outline; for every other run the "
            "shape of the day has to be read out of the realized behaviour below, where a run of "
            "low-entropy slots is where a band sits.</p></section>"
        )
    windowed = (
        '<p class="note">This export is cut to a window, but the bands below are measured over '
        "the whole horizon: they are what the plan declared, not what the exported slice "
        "contains.</p>"
        if inputs.include_start or inputs.include_end
        else ""
    )
    hues = _hue_by_intent(bands)
    cards = "".join(_band_card(band, hues) for band in bands)
    return (
        '<section><h2>The declared habits</h2><p class="meta">'
        f"{len(bands)} band(s) · outline "
        f"<code>{_escape((habits or {}).get('outlineId', '—'))}</code>"
        f" · {_escape((habits or {}).get('startDate', ''))} → "
        f"{_escape((habits or {}).get('endDate', ''))}</p>"
        "<p>A habit here is a band of the day, in the sense the smart-home literature uses the "
        "word: a stretch of hours in which a recognisable process runs. This is what a "
        "segmentation algorithm is asked to recover from the sensor log alone, stated in the open "
        "because the reader of this page is the person who commissioned the dataset. The shares "
        "are what the generated plan actually put inside each band, not what its window "
        "allowed.</p>"
        f"{windowed}{cards}</section>"
    )


# --- what the export contains -------------------------------------------------------------------


def _files_section(inputs: SummaryInputs) -> str:
    """One line per role, not per file.

    A role asked for in three formats is one dataset written three ways: repeating its description
    beside `.jsonl`, `.csv` and `.xes` turns a thirteen line index into a thirty-nine line one that
    says the same thing three times. The digests are not repeated here either — `manifest.json` is
    the integrity record, and this page says where it is.
    """
    by_role: dict[str, list[ExportManifestFile]] = {}
    for item in inputs.files:
        by_role.setdefault(item.role, []).append(item)
    rows = []
    for role in sorted(by_role):
        items = sorted(by_role[role], key=lambda entry: entry.relative_path)
        names = ", ".join(
            f"<code>{_escape(item.relative_path.split('/')[-1])}</code>" for item in items
        )
        rows.append(
            (
                _escape(_plain(role)),
                names,
                _escape(ROLE_PURPOSE.get(role, "")),
                _count(max(item.record_count for item in items)),
                _bytes(sum(item.size_bytes for item in items)),
            )
        )
    return (
        "<section><h2>What this export contains</h2>"
        "<p>Every file is listed in <code>manifest.json</code> with its full digest, and the "
        "export verifies against it. This page is published beside them and is not itself "
        "evidence: everything it states is read from the run's own artifacts.</p>"
        + _rows(("Role", "Files", "What it is", "Records", "Size"), rows, numeric=(3, 4))
        + "</section>"
    )


# --- the page ---------------------------------------------------------------------------------


def _metrics(inputs: SummaryInputs) -> str:
    profile = inputs.profile
    home = inputs.home
    observations = sum(
        item.record_count
        for item in inputs.files
        if item.role == "observable" and item.format.value == "jsonl"
    ) or max(
        (item.record_count for item in inputs.files if item.role == "observable"),
        default=0,
    )
    activities = sum(item.activity_count for item in profile.residents)
    bands = len(list((inputs.habits or {}).get("habits") or []))
    items = [
        (f"{profile.day_count}", "days"),
        (_count(activities), "activities run"),
        (str(len([x for x in home.regions if x.kind == "room"])) if home else "—", "rooms"),
        (str(len(inputs.sensors.sensors)) if inputs.sensors else "—", "sensors"),
        (_count(observations) if observations else "—", "readings exported"),
        (str(bands) if bands else "—", "habit bands"),
    ]
    return (
        '<ul class="metrics">'
        + "".join(
            f"<li><strong>{value}</strong><span>{label}</span></li>" for value, label in items
        )
        + "</ul>"
    )


def render_summary_html(inputs: SummaryInputs) -> str:
    """The whole dataset as one page."""
    profile = inputs.profile
    scenario = inputs.scenario
    resident_names = ", ".join(
        str(item.get("displayName") or _plain(str(item.get("residentId", ""))))
        for item in (scenario.residents if scenario else [])
    ) or ", ".join(_plain(item.resident_id) for item in profile.residents)
    title = (scenario.title if scenario and scenario.title else None) or (
        f"Dataset summary · {inputs.run_id}"
    )
    window = (
        f"{inputs.include_start.isoformat()} → {inputs.include_end.isoformat()}"
        if inputs.include_start and inputs.include_end
        else "the whole run"
    )
    header = _definition(
        (
            ("Home", f"<code>{_escape(inputs.home.home_id)}</code>" if inputs.home else "—"),
            ("Resident", _escape(resident_names or "—")),
            (
                "Horizon",
                f"{profile.start_date} → {profile.end_date} ({profile.day_count} days)",
            ),
            ("Time zone", _escape(scenario.time_zone if scenario else "—")),
            ("Written in", _escape((scenario.language if scenario else None) or "—")),
            ("Seed", str(inputs.seed)),
            ("Covers", _escape(window)),
            ("Run", f"<code>{_escape(inputs.run_id)}</code>"),
        )
    )
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_escape(title)}</title>"
        f"<style>{PROFILE_STYLE}{PLAN_STYLE}{SUMMARY_STYLE}</style></head><body><main>"
        f"<header><h1>{_escape(title)}</h1>"
        '<p class="meta">One synthetic resident, the flat she lives in, the sensors that watched '
        "her and the routine she was given. Everything here is read from the artifacts of a "
        "single run.</p>"
        f"{header}{_metrics(inputs)}</header>"
        f"{_home_section(inputs)}"
        f"{_sensor_section(inputs)}"
        f"{_resident_section_declared(inputs)}"
        f"{_habits_section(inputs)}"
        "<section><h2>The behaviour that actually happened</h2>"
        "<p>Aggregated from the execution trace and nothing else, so it describes the resident "
        "deviations, failures and dropped activities included — the same run the sensor log beside "
        "it was projected from. Comparing it to the declared bands above is an evaluation someone "
        "performs; neither document makes that claim about the other.</p>"
        f"{resident_sections(profile)}</section>"
        f"{_files_section(inputs)}"
        f"<footer>Generated by {_escape(profile.provenance.generator_name or 'smart-home-sim')} "
        f"{_escape(profile.provenance.generator_version or '')} from trace digest "
        f"<code>{_escape(inputs.trace_digest)}</code>. No clock reading is recorded here: the same "
        "run and the same request rebuild the same page.</footer>"
        "</main></body></html>\n"
    )
