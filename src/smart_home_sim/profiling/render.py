"""Draw a resident profile: one self-contained HTML page and one heatmap matrix as CSV.

The page carries no script and no external reference, so it survives being emailed, committed
beside a thesis chapter or opened from a memory stick eight years from now. Its figures are inline
SVG for the same reason, and because a vector heatmap is the one that still reads when a reviewer
prints it.

Colour is deliberately thin: activity cells are `currentColor` at an opacity that encodes the
share, so the same markup is legible on a white page and a dark one. Only the rhythm strip uses
hues, because there the hue *is* the datum — which activity holds the slot — and nothing else can
carry it.
"""

from __future__ import annotations

import csv
import html
from collections.abc import Iterator, Sequence
from pathlib import Path

from smart_home_sim.domain.profile import BehaviourSlice, ResidentBehaviour, ResidentProfile

# Beyond this the rows stop being distinguishable and the page stops being a profile. The full
# matrix is always in the CSV and the JSON; the page shows the activities that fill the day.
MAX_ROWS = 24
CELL_WIDTH = 11.0
CELL_HEIGHT = 19.0
LABEL_WIDTH = 190.0
AXIS_HEIGHT = 22.0

# Twelve hues far enough apart to be told apart at 11 pixels wide.
HUES = (12, 200, 130, 45, 275, 170, 330, 95, 240, 25, 305, 60)


def _escape(value: str) -> str:
    return html.escape(str(value), quote=True)


def _readable(value: str) -> str:
    return value.replace("_", " ")


def _duration(minutes: float) -> str:
    total = int(round(minutes))
    return f"{total // 60}h {total % 60:02d}m" if total >= 60 else f"{total} min"


def _hour_ticks(slot_minutes: int, slot_count: int) -> Iterator[tuple[int, str]]:
    every = max(1, 120 // slot_minutes)
    for slot in range(0, slot_count, every):
        yield slot, f"{slot * slot_minutes // 60:02d}"


def _cells(shares: Sequence[float], row: int) -> str:
    """One heatmap row. Zero-valued cells are left out: the track behind them says the same thing
    in one rect instead of ninety-six."""
    parts = []
    for slot, share in enumerate(shares):
        if share <= 0:
            continue
        # A square root, not the raw share: at 15-minute slots most cells sit below 0.2, and a
        # linear ramp renders a real routine as an almost empty grid.
        opacity = round(min(max(share, 0.0), 1.0) ** 0.5, 4)
        parts.append(
            f'<rect x="{LABEL_WIDTH + slot * CELL_WIDTH:.1f}" y="{row * CELL_HEIGHT:.1f}" '
            f'width="{CELL_WIDTH:.1f}" height="{CELL_HEIGHT:.1f}" fill="currentColor" '
            f'opacity="{opacity}"><title>{share * 100:.1f}%</title></rect>'
        )
    return "".join(parts)


def _heatmap(
    rows: Sequence[tuple[str, Sequence[float]]], slot_minutes: int, slot_count: int
) -> str:
    """A share heatmap: rows against the clock, opacity as intensity."""
    if not rows:
        return '<p class="empty">Nothing measured in this slice.</p>'
    width = LABEL_WIDTH + slot_count * CELL_WIDTH
    height = AXIS_HEIGHT + len(rows) * CELL_HEIGHT
    parts = [
        f'<svg class="heatmap" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'role="img" preserveAspectRatio="xMinYMin meet">'
    ]
    for slot, label in _hour_ticks(slot_minutes, slot_count):
        x = LABEL_WIDTH + slot * CELL_WIDTH
        parts.append(f'<text class="tick" x="{x:.1f}" y="14">{label}</text>')
        parts.append(
            f'<line class="rule" x1="{x:.1f}" y1="{AXIS_HEIGHT}" x2="{x:.1f}" y2="{height:.0f}" />'
        )
    parts.append(f'<g transform="translate(0 {AXIS_HEIGHT})">')
    for index, (label, shares) in enumerate(rows):
        parts.append(
            f'<rect class="track" x="{LABEL_WIDTH}" y="{index * CELL_HEIGHT:.1f}" '
            f'width="{slot_count * CELL_WIDTH:.1f}" height="{CELL_HEIGHT:.1f}" />'
        )
        parts.append(
            f'<text class="row-label" x="{LABEL_WIDTH - 8:.0f}" '
            f'y="{index * CELL_HEIGHT + 13.5:.1f}">{_escape(label)}</text>'
        )
        parts.append(_cells(shares, index))
    parts.append("</g></svg>")
    return "".join(parts)


def _rhythm(slice_: BehaviourSlice, slot_minutes: int) -> str:
    """The day as one strip: which activity owns each slot, and how firmly.

    This is the figure a habit-segmentation experiment is really about. Hue names the dominant
    activity, opacity is the share of the slot it holds, and a pale run of cells is a stretch of
    the day with no owner — which is where the boundaries between bands tend to fall.
    """
    slots = slice_.slots
    order = {
        intent: index
        for index, intent in enumerate(item.intent for item in slice_.intents[:MAX_ROWS])
    }
    width = slot_count = len(slots)
    parts = [
        f'<svg class="rhythm" viewBox="0 0 {width * CELL_WIDTH:.0f} 62" role="img" '
        f'preserveAspectRatio="xMinYMin meet">'
    ]
    for index, item in enumerate(slots):
        x = index * CELL_WIDTH
        parts.append(
            f'<rect class="track" x="{x:.1f}" y="20" width="{CELL_WIDTH:.1f}" height="26"/>'
        )
        if item.dominant_intent is not None:
            hue = HUES[order.get(item.dominant_intent, len(order)) % len(HUES)]
            parts.append(
                f'<rect x="{x:.1f}" y="20" width="{CELL_WIDTH:.1f}" height="26" '
                f'fill="hsl({hue} 72% 48%)" opacity="{min(item.dominant_share, 1.0) ** 0.5:.3f}">'
                f"<title>{_escape(item.start)} · {_escape(_readable(item.dominant_intent))} · "
                f"{item.dominant_share * 100:.0f}% · {item.entropy_bits:.2f} bits</title></rect>"
            )
    for slot, label in _hour_ticks(slot_minutes, slot_count):
        parts.append(f'<text class="tick" x="{slot * CELL_WIDTH:.1f}" y="14">{label}</text>')
    parts.append("</svg>")
    legend = "".join(
        f'<li><span style="background:hsl({HUES[index % len(HUES)]} 72% 48%)"></span>'
        f"{_escape(_readable(intent))}</li>"
        for intent, index in sorted(order.items(), key=lambda item: item[1])[:12]
    )
    return "".join(parts) + f'<ul class="legend">{legend}</ul>'


def _intent_table(slice_: BehaviourSlice) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{_escape(_readable(item.intent))}</td>"
        f"<td>{item.occurrences}</td>"
        f"<td>{item.days_observed} / {slice_.day_count}</td>"
        f"<td>{_escape(item.typical_start or '—')}</td>"
        f"<td>{'—' if item.start_spread_minutes is None else f'±{item.start_spread_minutes:.0f}'}"
        "</td>"
        f"<td>{_duration(item.mean_duration_minutes)}</td>"
        f"<td>{_duration(item.total_minutes)}</td>"
        "</tr>"
        for item in slice_.intents[:MAX_ROWS]
    )
    return (
        "<table><thead><tr><th>Activity</th><th>Times</th><th>Days</th><th>Typical start</th>"
        "<th>Spread</th><th>Mean length</th><th>Total</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _slice_section(slice_: BehaviourSlice, profile: ResidentProfile) -> str:
    names = {"all": "Every day", "weekday": "Weekdays", "weekend": "Weekends"}
    if not slice_.day_count:
        return (
            f'<section class="slice"><h3>{names[slice_.day_type]}</h3>'
            '<p class="empty">The horizon contains no day of this kind.</p></section>'
        )
    slot_count = len(profile.slot_labels)
    activities = [
        (_readable(item.intent), item.occupancy_share) for item in slice_.intents[:MAX_ROWS]
    ]
    regions = [(_readable(item.region_id), item.occupancy_share) for item in slice_.regions[:12]]
    hidden = max(len(slice_.intents) - MAX_ROWS, 0)
    return (
        f'<section class="slice"><h3>{names[slice_.day_type]}</h3>'
        f'<p class="meta">{slice_.day_count} day(s) · {slice_.activity_count} activities · '
        f"{_duration(slice_.observed_minutes)} observed</p>"
        "<h4>Who owns each part of the day</h4>"
        f"{_rhythm(slice_, profile.slot_minutes)}"
        "<h4>Activities against the clock</h4>"
        f"{_heatmap(activities, profile.slot_minutes, slot_count)}"
        + (
            f'<p class="note">{hidden} rarer activity row(s) omitted from the figure; '
            "the CSV and the JSON carry them all.</p>"
            if hidden
            else ""
        )
        + "<h4>Where she is</h4>"
        f"{_heatmap(regions, profile.slot_minutes, slot_count)}"
        f"{_intent_table(slice_)}"
        "</section>"
    )


def _resident_section(resident: ResidentBehaviour, profile: ResidentProfile) -> str:
    narrative = "".join(f"<li>{_escape(line)}</li>" for line in resident.narrative)
    slices = "".join(_slice_section(item, profile) for item in resident.slices)
    dropped = (
        f" · {resident.dropped_activity_count} planned activity(ies) never ran"
        if resident.dropped_activity_count
        else ""
    )
    return (
        f'<article class="resident"><h2>{_escape(_readable(resident.resident_id))}</h2>'
        f'<p class="meta">{resident.activity_count} executed activities{dropped}</p>'
        f'<ul class="narrative">{narrative}</ul>{slices}</article>'
    )


STYLE = """
:root { color-scheme: light dark; --ink: #16181d; --paper: #ffffff; --muted: #6b7280;
  --line: #e4e6eb; --accent: #2f6f4f; --track: #f2f3f5; }
@media (prefers-color-scheme: dark) {
  :root { --ink: #e8eaee; --paper: #14161a; --muted: #9aa1ad; --line: #2a2e36;
    --accent: #74c69d; --track: #1d2026; } }
* { box-sizing: border-box; }
body { margin: 0; padding: 2.5rem 1.5rem 4rem; background: var(--paper); color: var(--ink);
  font: 15px/1.55 "Segoe UI", system-ui, sans-serif; }
main { max-width: 1180px; margin: 0 auto; }
h1 { font-size: 1.6rem; margin: 0 0 .3rem; }
h2 { font-size: 1.25rem; margin: 2.5rem 0 .2rem; }
h3 { font-size: 1.05rem; margin: 2rem 0 .2rem; }
h4 { font-size: .82rem; text-transform: uppercase; letter-spacing: .08em; color: var(--muted);
  margin: 1.4rem 0 .4rem; font-weight: 600; }
p.meta, p.note, .empty { color: var(--muted); font-size: .87rem; margin: .2rem 0 .6rem; }
header { border-bottom: 1px solid var(--line); padding-bottom: 1.2rem; }
header dl { display: flex; flex-wrap: wrap; gap: .35rem 2rem; margin: .8rem 0 0;
  font-size: .85rem; }
header dt { color: var(--muted); display: inline; margin-right: .4rem; }
header dd { display: inline; margin: 0; }
header div { min-width: 12rem; }
ul.narrative { list-style: none; padding: 0; margin: .8rem 0 0; }
ul.narrative li { border-left: 3px solid var(--accent); padding: .25rem 0 .25rem .7rem;
  margin-bottom: .35rem; }
svg.heatmap, svg.rhythm { width: 100%; height: auto; color: var(--accent); display: block; }
svg .track { fill: var(--track); }
svg .rule { stroke: var(--line); stroke-width: 1; }
svg text { font: 11px "Segoe UI", system-ui, sans-serif; fill: var(--muted); }
svg text.row-label { text-anchor: end; fill: var(--ink); }
ul.legend { list-style: none; display: flex; flex-wrap: wrap; gap: .3rem 1rem; padding: 0;
  margin: .5rem 0 0; font-size: .8rem; color: var(--muted); }
ul.legend span { display: inline-block; width: .7rem; height: .7rem; border-radius: 2px;
  margin-right: .35rem; vertical-align: -1px; }
table { border-collapse: collapse; width: 100%; margin-top: 1.2rem; font-size: .85rem; }
th, td { text-align: left; padding: .35rem .6rem; border-bottom: 1px solid var(--line); }
th { color: var(--muted); font-weight: 600; }
td:not(:first-child), th:not(:first-child) { text-align: right; }
footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--line);
  color: var(--muted); font-size: .8rem; }
code { font-family: ui-monospace, Consolas, monospace; font-size: .95em; }
"""


def resident_sections(profile: ResidentProfile) -> str:
    """The per-resident half of the page: narrative, rhythm, heatmaps and the activity table.

    Separate from the page around it because the dataset summary embeds these same figures under
    its own header. Two renderings of one profile that could drift apart would be two profiles.
    """
    return "".join(_resident_section(item, profile) for item in profile.residents) or (
        '<p class="empty">This trace records no resident behaviour.</p>'
    )


def render_profile_html(profile: ResidentProfile) -> str:
    """The whole profile as one standalone page."""
    residents = resident_sections(profile)
    title = f"Resident profile · {profile.trace_id}"
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_escape(title)}</title><style>{STYLE}</style></head><body><main>"
        "<header><h1>Resident profile</h1>"
        '<p class="meta">Realized behaviour, aggregated from the authoritative execution trace. '
        "Shares are measured against observed time, not against the calendar.</p><dl>"
        f"<div><dt>Horizon</dt><dd>{profile.start_date} → {profile.end_date} "
        f"({profile.day_count} days)</dd></div>"
        f"<div><dt>Slot</dt><dd>{profile.slot_minutes} min</dd></div>"
        f"<div><dt>Seed</dt><dd>{profile.seed}</dd></div>"
        f"<div><dt>Run</dt><dd><code>{_escape(profile.run_id or '—')}</code></dd></div>"
        f"<div><dt>Trace</dt><dd><code>{_escape(profile.trace_id)}</code></dd></div>"
        "</dl></header>"
        f"{residents}"
        f"<footer>Generated by {_escape(profile.provenance.generator_name or 'smart-home-sim')} "
        f"{_escape(profile.provenance.generator_version or '')} from trace digest "
        f"<code>{_escape(profile.source_trace_semantic_digest)}</code>.</footer>"
        "</main></body></html>\n"
    )


def heatmap_rows(profile: ResidentProfile) -> Iterator[list[object]]:
    """The matrices as long rows: one series per line, one column per slot.

    Wide rather than tidy, because the point of this file is to be plotted again elsewhere without
    a pivot: read it, filter to one `measure`, and the remaining columns are the heatmap.
    """
    yield ["residentId", "dayType", "measure", "series", *profile.slot_labels]
    for resident in profile.residents:
        for slice_ in resident.slices:
            for item in slice_.intents:
                yield [
                    resident.resident_id,
                    slice_.day_type,
                    "activity_share",
                    item.intent,
                    *item.occupancy_share,
                ]
                yield [
                    resident.resident_id,
                    slice_.day_type,
                    "activity_minutes",
                    item.intent,
                    *item.occupancy_minutes,
                ]
                yield [
                    resident.resident_id,
                    slice_.day_type,
                    "activity_starts",
                    item.intent,
                    *item.starts,
                ]
            for region in slice_.regions:
                yield [
                    resident.resident_id,
                    slice_.day_type,
                    "region_share",
                    region.region_id,
                    *region.occupancy_share,
                ]
            yield [
                resident.resident_id,
                slice_.day_type,
                "slot_entropy_bits",
                "__slot__",
                *[item.entropy_bits for item in slice_.slots],
            ]
            yield [
                resident.resident_id,
                slice_.day_type,
                "slot_labelled_share",
                "__slot__",
                *[item.labelled_share for item in slice_.slots],
            ]


def write_heatmap_csv(path: Path, profile: ResidentProfile) -> int:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        rows = 0
        for row in heatmap_rows(profile):
            writer.writerow(row)
            rows += 1
    return rows - 1
