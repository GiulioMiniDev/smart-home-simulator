/**
 * The horizon outline, read as a picture instead of as JSON.
 *
 * Whoever chooses the file has just pasted a case description into a chat window and saved what
 * came back. They are entitled to see what they are about to import without opening an editor:
 * where the day is carved, what is pinned by an employer and what is only a window, how the week
 * differs from itself, and which stretches of the months ahead behave differently.
 *
 * Three rules hold everywhere below. Nothing is drawn that is not also written in words, because
 * a bar on a track is not readable by everyone and not readable at all in a screen reader. Nothing
 * the model got wrong is hidden — an unplaceable band becomes a line under *What could not be
 * read*, never a silently missing bar. And nothing here decides anything: the server still judges
 * the outline, and the import button is exactly as available as it was before the preview existed.
 */

import { useRef, useState, type CSSProperties, type ReactNode } from "react";
import { flushSync } from "react-dom";
import { AlertTriangle, CalendarRange, Clock3, Download, ListTree, MapPin, Pin, Repeat, ShieldCheck, Sparkles, Upload, UserRound, Users } from "lucide-react";
import { downloadPreviewPage } from "./export";
import { KIND_PHRASE } from "./reading";
import type { ActivityView, BandRow, BandView, BehaviourView, CommitmentView, DayPiece, HorizonReading } from "./types";
import "./horizon.css";

const MINUTES_PER_DAY = 1440;
const HOUR_MARKS = [0, 3, 6, 9, 12, 15, 18, 21, 24];

function placement(piece: DayPiece): { left: string; width: string } {
  return {
    left: `${(piece.fromMinutes / MINUTES_PER_DAY) * 100}%`,
    width: `${((piece.toMinutes - piece.fromMinutes) / MINUTES_PER_DAY) * 100}%`,
  };
}

/** Bars carry no text of their own, so the sentence beside them is also their accessible name. */
function DayTrack({ pieces, tone, label, title }: { pieces: DayPiece[]; tone: string; label: string; title: string }) {
  return (
    <div className="horizon-track" role="img" aria-label={label}>
      {pieces.length === 0 && <span className="horizon-track-empty">not placed on the clock</span>}
      {pieces.map((piece, index) => (
        <i key={index} className={`horizon-bar tone-${tone}`} style={placement(piece)} title={title} />
      ))}
    </div>
  );
}

function HourAxis() {
  return (
    <div className="horizon-hours" aria-hidden="true">
      {HOUR_MARKS.map((hour) => (
        <span key={hour} style={{ left: `${(hour / 24) * 100}%` }}>{String(hour).padStart(2, "0")}</span>
      ))}
    </div>
  );
}

function BandSpine({ row, tones }: { row: BandRow; tones: Map<string, number> }) {
  return (
    <div className="horizon-track horizon-spine" role="img" aria-label={`${row.label}, in ${row.bands.length} band${row.bands.length === 1 ? "" : "s"}: ${row.bands.map((band) => `${band.label}, ${band.clock}`).join("; ")}`}>
      {row.bands.flatMap((band) => band.pieces.map((piece, pieceIndex) => (
        <i
          key={`${band.id}-${pieceIndex}`}
          className={`horizon-band tone-band-${(tones.get(band.id) ?? 0) % 5}`}
          style={placement(piece)}
          title={`${band.label} · ${band.clock}`}
        >
          <span>{band.label}</span>
        </i>
      )))}
    </div>
  );
}

function DayRow({ name, detail, children }: { name: string; detail: string; children: ReactNode }) {
  return (
    <div className="horizon-row">
      <div className="horizon-row-name"><strong>{name}</strong><small>{detail}</small></div>
      {children}
    </div>
  );
}

function DaySection({ bands, bandRows, commitments, activities }: { bands: BandView[]; bandRows: BandRow[]; commitments: CommitmentView[]; activities: ActivityView[] }) {
  // One colour per band across every spine it appears on, so the eye follows the same band from
  // the ordinary day to the Wednesday variation of it.
  const tones = new Map(bands.map((band, index) => [band.id, index]));
  return (
    <section className="horizon-section" aria-labelledby="horizon-day-title">
      <header><Clock3 size={18} /><div><h3 id="horizon-day-title">One day, from midnight to midnight</h3><p>The coloured spine is how the outline carves the day up. Solid bars underneath are fixed by someone other than the resident; the pale bars are windows, and the exact minute is drawn inside them when the days are computed.</p></div></header>
      <div className="horizon-day">
        <div className="horizon-row horizon-row-axis"><div /><HourAxis /></div>
        {!bandRows.length && <p className="horizon-empty">This outline does not carve the day into bands, so a segmentation algorithm has nothing here to be scored against.</p>}
        {bandRows.map((row) => (
          <DayRow key={row.key} name={row.key ? `The day ${row.label}` : "The shape of the day"} detail={`${row.bands.length} band${row.bands.length === 1 ? "" : "s"}`}>
            <BandSpine row={row} tones={tones} />
          </DayRow>
        ))}
        {commitments.map((commitment) => (
          <DayRow key={commitment.id} name={commitment.label} detail={commitment.sentence}>
            <DayTrack pieces={commitment.pieces} tone="fixed" label={`${commitment.label}: ${commitment.sentence}`} title={`Fixed: ${commitment.clock}`} />
          </DayRow>
        ))}
        {activities.map((activity) => (
          <DayRow key={activity.id} name={activity.label} detail={activity.sentence}>
            <DayTrack pieces={activity.pieces} tone={activity.kind} label={`${activity.label}: ${activity.sentence}`} title={`${KIND_PHRASE[activity.kind]} · ${activity.spread}`} />
          </DayRow>
        ))}
        {!activities.length && <p className="horizon-empty">No recurring activity is declared, so there is nothing to place inside the bands.</p>}
      </div>
      <ul className="horizon-legend">
        <li><i className="horizon-swatch tone-fixed" /> Fixed by someone else</li>
        <li><i className="horizon-swatch tone-anchor" /> Anchor</li>
        <li><i className="horizon-swatch tone-contextual" /> Contextual</li>
        <li><i className="horizon-swatch tone-optional" /> Optional</li>
        <li><i className="horizon-swatch tone-rare" /> Rare</li>
      </ul>
      {bands.some((band) => band.wraps) && <p className="horizon-note">A band shown in two pieces is one band crossing midnight — the night is the only one allowed to.</p>}
      {bandRows.length > 1 && <p className="horizon-note">Bands may be tied to particular days, so the day has more than one shape. Each spine above is one of them; the bars below it are the same on all of them.</p>}
    </section>
  );
}

function WeekSection({ reading }: { reading: HorizonReading }) {
  return (
    <section className="horizon-section" aria-labelledby="horizon-week-title">
      <header><CalendarRange size={18} /><div><h3 id="horizon-week-title">How the week differs from itself</h3><p>Only what is tied to particular days appears here. Everything else happens on all seven, and would say nothing about the shape of the week.</p></div></header>
      {reading.weekVaries ? (
        <div className="horizon-week">
          {reading.week.map((column) => (
            <div key={column.weekday} className={column.entries.length ? "" : "is-plain"}>
              <strong>{column.short}</strong>
              {column.entries.length
                ? <ul>{column.entries.map((entry, index) => <li key={index} className={`entry-${entry.kind}`}>{entry.label}</li>)}</ul>
                : <small>nothing tied to this day</small>}
            </div>
          ))}
        </div>
      ) : <p className="horizon-empty">Nothing in this outline is tied to a weekday: every day of the week has the same shape. That is worth a second look if the person works or studies.</p>}
    </section>
  );
}

function SpanSection({ reading }: { reading: HorizonReading }) {
  const lanes = Math.max(1, ...reading.phases.map((phase) => phase.lane + 1));
  const eventLanes = Math.max(1, ...reading.events.map((event) => event.lane + 1));
  return (
    <section className="horizon-section" aria-labelledby="horizon-span-title">
      <header><Repeat size={18} /><div><h3 id="horizon-span-title">The whole horizon, {reading.dayCount} days of it</h3><p>{reading.spanPhrase}. Stretches change a habit for a while; one-offs happen once somewhere inside their window, and the expander picks the day.</p></div></header>
      <div className="horizon-span">
        <div className="horizon-months" aria-hidden="true">
          {reading.monthTicks.map((tick, index) => (
            <span key={index} style={{ left: `${tick.fraction * 100}%` }}>{tick.label}{tick.year ? <b>{tick.year}</b> : null}</span>
          ))}
        </div>
        <div className="horizon-span-track" style={{ "--lanes": lanes } as CSSProperties} role="img" aria-label={reading.phases.length ? `${reading.phases.length} stretches across the horizon` : "No stretch changes any habit"}>
          {reading.monthTicks.map((tick, index) => <u key={index} style={{ left: `${tick.fraction * 100}%` }} />)}
          {reading.phases.map((phase) => (
            <i
              key={phase.id}
              className="horizon-phase"
              style={{ left: `${phase.fromFraction * 100}%`, width: `${Math.max(0.4, (phase.toFraction - phase.fromFraction) * 100)}%`, top: `${phase.lane * 26}px` }}
              title={`${phase.label} · ${phase.sentence}`}
            >
              <span>{phase.label}</span>
            </i>
          ))}
          {!reading.phases.length && <span className="horizon-track-empty">no stretch changes anything</span>}
        </div>
        <div className="horizon-span-track is-events" style={{ "--lanes": eventLanes } as CSSProperties} role="img" aria-label={reading.events.length ? `${reading.events.length} one-off events` : "No one-off event"}>
          {reading.monthTicks.map((tick, index) => <u key={index} style={{ left: `${tick.fraction * 100}%` }} />)}
          {reading.events.map((event) => (
            <i
              key={event.id}
              className="horizon-event"
              style={{ left: `${event.fromFraction * 100}%`, width: `${Math.max(0.6, (event.toFraction - event.fromFraction) * 100)}%`, top: `${event.lane * 24}px` }}
              title={`${event.label} · ${event.sentence}`}
            >
              <span>{event.label}</span>
            </i>
          ))}
          {!reading.events.length && <span className="horizon-track-empty">nothing one-off happens</span>}
        </div>
      </div>
      {!!reading.phases.length && <dl className="horizon-list">
        {reading.phases.map((phase) => (
          <div key={phase.id}>
            <dt>{phase.label}</dt>
            <dd>
              <span>{phase.sentence}</span>
              {phase.changes.length
                ? <ul>{phase.changes.map((change, index) => <li key={index}>{change}</li>)}</ul>
                : <small>changes no habit — only the label says anything.</small>}
              {phase.note && <small>{phase.note}</small>}
            </dd>
          </div>
        ))}
      </dl>}
      {!!reading.events.length && <dl className="horizon-list">
        {reading.events.map((event) => (
          <div key={event.id}>
            <dt>{event.label}</dt>
            <dd>
              <span>{event.sentence}</span>
              {!!event.displaces.length && <ul>{event.displaces.map((item, index) => <li key={index}>{item}</li>)}</ul>}
              {event.note && <small>{event.note}</small>}
            </dd>
          </div>
        ))}
      </dl>}
    </section>
  );
}

function BehaviourSection({ behaviour }: { behaviour: BehaviourView }) {
  return (
    <section className="horizon-section" aria-labelledby="horizon-behaviour-title">
      <header><ListTree size={18} /><div><h3 id="horizon-behaviour-title">How the actions are performed</h3><p>The other half of this file: {behaviour.processCount} process{behaviour.processCount === 1 ? "" : "es"}, each one the sequence of movements and touches that carries out an intent. It does not grow with the horizon — a year and a week need the same ones.</p></div></header>
      {behaviour.unimplemented.length ? (
        <div className="horizon-gaps" role="status">
          <strong><AlertTriangle size={16} aria-hidden="true" /> {behaviour.unimplemented.length} intent{behaviour.unimplemented.length === 1 ? "" : "s"} with nothing behind {behaviour.unimplemented.length === 1 ? "it" : "them"}</strong>
          <ul>{behaviour.unimplemented.map((intent) => <li key={intent}><code>{intent}</code></li>)}</ul>
          <small>The outline asks for {behaviour.unimplemented.length === 1 ? "this" : "these"}, and the package does not say how {behaviour.unimplemented.length === 1 ? "it is" : "they are"} performed. The import will refuse the file — after it has expanded the horizon into days, which takes minutes.</small>
        </div>
      ) : (
        <p className="horizon-empty">All {behaviour.namedIntents} intents this outline names have a process behind them. The resident&rsquo;s own rhythm emits others — sleeping and waking among them — which the outline never mentions and only the server can check.</p>
      )}
    </section>
  );
}

function PlaceSection({ reading }: { reading: HorizonReading }) {
  return (
    <section className="horizon-section" aria-labelledby="horizon-place-title">
      <header><MapPin size={18} /><div><h3 id="horizon-place-title">Where this life happens</h3><p>The rooms become the flat the simulator builds. Everywhere else is somewhere the resident travels to, so that being out of the house is a place and not an absence.</p></div></header>
      <div className="horizon-places">
        <div><strong>{reading.rooms.length} room{reading.rooms.length === 1 ? "" : "s"}</strong><ul>{reading.rooms.map((room) => <li key={room}>{room.replace(/_/g, " ")}</li>)}</ul></div>
        <div><strong>Elsewhere</strong>{reading.elsewhere.length ? <ul>{reading.elsewhere.map((place) => <li key={place} className="is-outside">{place.replace(/_/g, " ")}</li>)}</ul> : <small>the resident never leaves the flat</small>}</div>
        <div><strong><Users size={14} /> People</strong>{reading.people.length ? <ul>{reading.people.map((person) => <li key={person}>{person}</li>)}</ul> : <small>nobody else appears</small>}</div>
      </div>
    </section>
  );
}

export function HorizonPreview({ reading, fileName, onImport, busy, sourceFile }: {
  reading: HorizonReading;
  fileName: string;
  onImport: () => void;
  busy: boolean;
  /** Travels inside the exported page, so the picture and its input stay one artefact. */
  sourceFile?: File;
}) {
  const [open, setOpen] = useState(true);
  const sheet = useRef<HTMLElement>(null);
  const exportPage = async () => {
    const node = sheet.current;
    if (!node) return;
    // The export is the section as it stands, so a collapsed section would export as a header and
    // nothing else. Opened synchronously, before anything is read out of the document.
    if (!open) flushSync(() => setOpen(true));
    await downloadPreviewPage(node, {
      title: reading.title,
      fileName,
      theme: node.closest("[data-theme]")?.getAttribute("data-theme") === "dark" ? "dark" : "light",
      sourceFile,
    });
  };
  return (
    <section className="surface horizon-preview" aria-labelledby="horizon-preview-title" ref={sheet}>
      <div className="horizon-headline">
        <div>
          <p className="eyebrow"><Sparkles size={14} aria-hidden="true" /> Before you import · {fileName}</p>
          <h2 id="horizon-preview-title">{reading.title}</h2>
          <p>
            {reading.dayCount} days for <strong>{reading.residentId}</strong>, {reading.spanPhrase}, on {reading.timeZone} clocks.
            {reading.age !== undefined && ` Aged ${reading.age}.`}
            {reading.bedtime && ` Usually in bed around ${reading.bedtime}.`}
            {!!reading.health.length && ` Health noted: ${reading.health.join(", ")}.`}
          </p>
          <p className="horizon-provenance">
            <span><UserRound size={14} aria-hidden="true" /> {reading.authorPhrase}</span>
            <span className={reading.humanReviewed ? "is-checked" : "is-unchecked"}>
              <ShieldCheck size={14} aria-hidden="true" /> {reading.humanReviewed ? "The file says a person has read it" : "The file says nobody has read it yet"}
            </span>
          </p>
        </div>
        <div className="horizon-counts">
          <div><b>{reading.bands.length}</b><span>bands</span></div>
          <div><b>{reading.activities.length}</b><span>habits</span></div>
          <div><b>{reading.commitments.length}</b><span><Pin size={12} aria-hidden="true" /> fixed</span></div>
          <div><b>{reading.phases.length}</b><span>stretches</span></div>
          <div><b>{reading.events.length}</b><span>one-offs</span></div>
        </div>
      </div>
      {reading.note && <p className="horizon-note">{reading.note}</p>}
      <div className="horizon-toggle">
        <button className="button secondary" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide the detail" : "Read the whole outline"}</button>
        <button className="button secondary" onClick={() => void exportPage()}><Download size={16} /> Download this page</button>
        <button className="button primary" disabled={busy} onClick={onImport}><Upload size={16} /> Looks right — expand and import</button>
      </div>
      {open && <>
        <DaySection bands={reading.bands} bandRows={reading.bandRows} commitments={reading.commitments} activities={reading.activities} />
        <WeekSection reading={reading} />
        <SpanSection reading={reading} />
        {reading.behaviour && <BehaviourSection behaviour={reading.behaviour} />}
        <PlaceSection reading={reading} />
        {!!reading.bands.length && <section className="horizon-section" aria-labelledby="horizon-bands-title">
          <header><Clock3 size={18} /><div><h3 id="horizon-bands-title">What each band is meant to hold</h3><p>A band an algorithm is asked to recover from a sensor log has to be inhabited by something, and by something that differs from its neighbours.</p></div></header>
          <dl className="horizon-list">
            {reading.bands.map((band) => (
              <div key={band.id}>
                <dt>{band.label}</dt>
                <dd>
                  <span>{band.clock}, {band.weekdayPhrase}</span>
                  {band.activityLabels.length
                    ? <ul>{band.activityLabels.map((label, index) => <li key={index}>{label}</li>)}</ul>
                    : <small>nothing is assigned to it, so whatever happens to fall inside it is what a segmentation algorithm will find.</small>}
                  {band.note && <small>{band.note}</small>}
                </dd>
              </div>
            ))}
          </dl>
        </section>}
      </>}
      {!!reading.gaps.length && (
        <div className="horizon-gaps" role="status">
          <strong><AlertTriangle size={16} aria-hidden="true" /> What could not be read</strong>
          <ul>{reading.gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul>
          <small>The server decides whether the outline is valid; this list is only what the picture above could not place.</small>
        </div>
      )}
    </section>
  );
}
