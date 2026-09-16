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
 *
 * A household is the same picture once per person, followed by what is true of the house rather
 * than of anyone in it. One resident is the case where that loop runs once and the household has
 * nothing to say, so the single-person page is unchanged.
 */

import { Fragment, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { flushSync } from "react-dom";
import { AlertTriangle, CalendarRange, Clock3, Download, ListTree, MapPin, Pin, Repeat, ShieldCheck, Sparkles, Upload, UserRound, Users } from "lucide-react";
import { downloadPreviewPage } from "./export";
import { KIND_PHRASE } from "./reading";
import type { ReviewActions } from "./review";
import { VocabularyReview } from "./VocabularyReview";
import { OutlineProblems, type ProblemActions } from "./OutlineProblems";
import type { VocabularyPack } from "../vocabulary/types";
import type { BandRow, BehaviourView, DayPiece, HorizonReading, HouseholdView, ResidentReading } from "./types";
import "./horizon.css";

const MINUTES_PER_DAY = 1440;
const HOUR_MARKS = [0, 3, 6, 9, 12, 15, 18, 21, 24];

/**
 * How the sections of one resident are titled.
 *
 * Alone, a resident needs no name on every heading. In a household the same headings repeat once
 * per person, and a heading that does not say whose day it is cannot be told from its neighbours by
 * anyone navigating a page by its headings. The ids differ too, because `aria-labelledby` resolves
 * by id and the first match would otherwise label every copy.
 */
interface Voice {
  id: string;
  title: (heading: string) => string;
  Heading: "h3" | "h4";
}

const ALONE: Voice = { id: "horizon", title: (heading) => heading, Heading: "h3" };

function voiceOf(resident: ResidentReading, index: number): Voice {
  return { id: `horizon-${index}`, title: (heading) => `${resident.name} · ${heading.charAt(0).toLowerCase()}${heading.slice(1)}`, Heading: "h4" };
}

function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

function joinNames(names: string[]): ReactNode {
  return names.map((name, index) => (
    <Fragment key={`${name}-${index}`}>
      {index > 0 && (index === names.length - 1 ? " and " : ", ")}
      <strong>{name}</strong>
    </Fragment>
  ));
}

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

function Legend() {
  return (
    <ul className="horizon-legend">
      <li><i className="horizon-swatch tone-fixed" /> Fixed by someone else</li>
      <li><i className="horizon-swatch tone-anchor" /> Anchor</li>
      <li><i className="horizon-swatch tone-contextual" /> Contextual</li>
      <li><i className="horizon-swatch tone-optional" /> Optional</li>
      <li><i className="horizon-swatch tone-rare" /> Rare</li>
    </ul>
  );
}

function DaySection({ resident, voice }: { resident: ResidentReading; voice: Voice }) {
  const { bands, bandRows, commitments, activities } = resident;
  const { Heading } = voice;
  // One colour per band across every spine it appears on, so the eye follows the same band from
  // the ordinary day to the Wednesday variation of it.
  const tones = new Map(bands.map((band, index) => [band.id, index]));
  return (
    <section className="horizon-section" aria-labelledby={`${voice.id}-day-title`}>
      <header><Clock3 size={18} /><div><Heading id={`${voice.id}-day-title`}>{voice.title("One day, from midnight to midnight")}</Heading><p>The coloured spine is how the outline carves the day up. Solid bars underneath are fixed by someone other than the resident; the pale bars are windows, and the exact minute is drawn inside them when the days are computed.</p></div></header>
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
      <Legend />
      {bands.some((band) => band.wraps) && <p className="horizon-note">A band shown in two pieces is one band crossing midnight — the night is the only one allowed to.</p>}
      {bandRows.length > 1 && <p className="horizon-note">Bands may be tied to particular days, so the day has more than one shape. Each spine above is one of them; the bars below it are the same on all of them.</p>}
    </section>
  );
}

function WeekSection({ resident, voice }: { resident: ResidentReading; voice: Voice }) {
  const { Heading } = voice;
  return (
    <section className="horizon-section" aria-labelledby={`${voice.id}-week-title`}>
      <header><CalendarRange size={18} /><div><Heading id={`${voice.id}-week-title`}>{voice.title("How the week differs from itself")}</Heading><p>Only what is tied to particular days appears here. Everything else happens on all seven, and would say nothing about the shape of the week.</p></div></header>
      {resident.weekVaries ? (
        <div className="horizon-week">
          {resident.week.map((column) => (
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

function SpanSection({ horizon, resident, voice }: { horizon: HorizonReading; resident: ResidentReading; voice: Voice }) {
  const { Heading } = voice;
  const lanes = Math.max(1, ...resident.phases.map((phase) => phase.lane + 1));
  const eventLanes = Math.max(1, ...resident.events.map((event) => event.lane + 1));
  return (
    <section className="horizon-section" aria-labelledby={`${voice.id}-span-title`}>
      <header><Repeat size={18} /><div><Heading id={`${voice.id}-span-title`}>{voice.title(`The whole horizon, ${horizon.dayCount} days of it`)}</Heading><p>{horizon.spanPhrase}. Stretches change a habit for a while; one-offs happen once somewhere inside their window, and the expander picks the day.</p></div></header>
      <div className="horizon-span">
        <div className="horizon-months" aria-hidden="true">
          {horizon.monthTicks.map((tick, index) => (
            <span key={index} style={{ left: `${tick.fraction * 100}%` }}>{tick.label}{tick.year ? <b>{tick.year}</b> : null}</span>
          ))}
        </div>
        <div className="horizon-span-track" style={{ "--lanes": lanes } as CSSProperties} role="img" aria-label={resident.phases.length ? `${resident.phases.length} stretches across the horizon` : "No stretch changes any habit"}>
          {horizon.monthTicks.map((tick, index) => <u key={index} style={{ left: `${tick.fraction * 100}%` }} />)}
          {resident.phases.map((phase) => (
            <i
              key={phase.id}
              className="horizon-phase"
              style={{ left: `${phase.fromFraction * 100}%`, width: `${Math.max(0.4, (phase.toFraction - phase.fromFraction) * 100)}%`, top: `${phase.lane * 26}px` }}
              title={`${phase.label} · ${phase.sentence}`}
            >
              <span>{phase.label}</span>
            </i>
          ))}
          {!resident.phases.length && <span className="horizon-track-empty">no stretch changes anything</span>}
        </div>
        <div className="horizon-span-track is-events" style={{ "--lanes": eventLanes } as CSSProperties} role="img" aria-label={resident.events.length ? `${resident.events.length} one-off events` : "No one-off event"}>
          {horizon.monthTicks.map((tick, index) => <u key={index} style={{ left: `${tick.fraction * 100}%` }} />)}
          {resident.events.map((event) => (
            <i
              key={event.id}
              className="horizon-event"
              style={{ left: `${event.fromFraction * 100}%`, width: `${Math.max(0.6, (event.toFraction - event.fromFraction) * 100)}%`, top: `${event.lane * 24}px` }}
              title={`${event.label} · ${event.sentence}`}
            >
              <span>{event.label}</span>
            </i>
          ))}
          {!resident.events.length && <span className="horizon-track-empty">nothing one-off happens</span>}
        </div>
      </div>
      {!!resident.phases.length && <dl className="horizon-list">
        {resident.phases.map((phase) => (
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
      {!!resident.events.length && <dl className="horizon-list">
        {resident.events.map((event) => (
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

function BandsSection({ resident, voice }: { resident: ResidentReading; voice: Voice }) {
  const { Heading } = voice;
  if (!resident.bands.length) return null;
  return (
    <section className="horizon-section" aria-labelledby={`${voice.id}-bands-title`}>
      <header><Clock3 size={18} /><div><Heading id={`${voice.id}-bands-title`}>{voice.title("What each band is meant to hold")}</Heading><p>A band an algorithm is asked to recover from a sensor log has to be inhabited by something, and by something that differs from its neighbours.</p></div></header>
      <dl className="horizon-list">
        {resident.bands.map((band) => (
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
    </section>
  );
}

function describePerson(resident: ResidentReading): string {
  return [
    resident.age !== undefined ? `Aged ${resident.age}.` : "",
    resident.bedtime ? `Usually in bed around ${resident.bedtime}.` : "",
    resident.health.length ? `Health noted: ${resident.health.join(", ")}.` : "",
  ].filter(Boolean).join(" ");
}

/** One person of a household: who they are, then the same four readings a lone resident gets. */
function ResidentBlock({ horizon, resident, index }: { horizon: HorizonReading; resident: ResidentReading; index: number }) {
  const voice = voiceOf(resident, index);
  const person = describePerson(resident);
  return (
    <section className="horizon-resident" aria-labelledby={`${voice.id}-title`}>
      <header>
        <UserRound size={18} aria-hidden="true" />
        <div>
          <h3 id={`${voice.id}-title`}>{resident.name}</h3>
          <p>
            {resident.name !== resident.residentId && <code>{resident.residentId}</code>}
            {plural(resident.bands.length, "band")} · {plural(resident.activities.length, "habit")} · {resident.commitments.length} fixed · {plural(resident.phases.length, "stretch", "stretches")} · {plural(resident.events.length, "one-off")}
            {person && <> · {person}</>}
          </p>
          {resident.note && <p className="horizon-note">{resident.note}</p>}
        </div>
      </header>
      <DaySection resident={resident} voice={voice} />
      <WeekSection resident={resident} voice={voice} />
      <SpanSection horizon={horizon} resident={resident} voice={voice} />
      <BandsSection resident={resident} voice={voice} />
    </section>
  );
}

function SentenceList({ items, empty }: { items: string[]; empty: string }) {
  return items.length
    ? <ul className="horizon-sentences">{items.map((item, index) => <li key={index}>{item}</li>)}</ul>
    : <p className="horizon-empty">{empty}</p>;
}

/**
 * What is true of the house rather than of anyone in it.
 *
 * Shared activities are drawn on the same 24-hour clock as each resident's own, because the one
 * question a reader has about them is whether that single window actually fits into everybody's
 * day — and the answer is a comparison with the spines above.
 */
function HouseholdSection({ household }: { household: HouseholdView }) {
  return (
    <section className="horizon-section" aria-labelledby="horizon-household-title">
      <header><Users size={18} /><div><h3 id="horizon-household-title">Living together</h3><p>What belongs to the household rather than to one person. A shared activity is declared once, with one window and its participants named, so the house has one dinner and not one per resident.</p></div></header>
      <div className="horizon-household-group">
        <strong>Who they are to each other</strong>
        <SentenceList items={household.relations} empty="No relation is declared, so every pair is treated as independent: nothing is shared that is not written below." />
      </div>
      <div className="horizon-household-group">
        <strong>Done together</strong>
        {household.joint.length ? <>
          <div className="horizon-day">
            <div className="horizon-row horizon-row-axis"><div /><HourAxis /></div>
            {household.joint.map((activity) => (
              <DayRow key={activity.id} name={activity.label} detail={`${activity.participants.join(", ")} · ${activity.sentence}`}>
                <DayTrack pieces={activity.pieces} tone={activity.kind} label={`${activity.label}, shared by ${activity.participants.join(", ")}: ${activity.sentence}`} title={`${KIND_PHRASE[activity.kind]} · ${activity.spread}`} />
              </DayRow>
            ))}
          </div>
          <dl className="horizon-list">
            {household.joint.map((activity) => (
              <div key={activity.id}>
                <dt>{activity.label}</dt>
                <dd>
                  <span>{activity.together}</span>
                  <ul>{activity.participants.map((name, index) => <li key={index}>{name}</li>)}</ul>
                  <small>{activity.fallback}.</small>
                  {activity.note && <small>{activity.note}</small>}
                </dd>
              </div>
            ))}
          </dl>
          <Legend />
        </> : <p className="horizon-empty">Nothing is declared as done together, so the residents only meet when their own windows happen to overlap.</p>}
      </div>
      <div className="horizon-household-group">
        <strong>Rooms and turns</strong>
        <SentenceList items={[...household.privacy, ...household.policies]} empty="No room is declared private and no rule decides who goes first." />
        <small>
          {household.sharedRooms.length
            ? `Declared shared: ${household.sharedRooms.join(", ")}. `
            : ""}
          A room holding a single sanitary fixture is private unless the outline names it as shared.
        </small>
      </div>
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
  const household = reading.residents.length > 1;
  return (
    <section className="horizon-section" aria-labelledby="horizon-place-title">
      <header><MapPin size={18} /><div><h3 id="horizon-place-title">Where this life happens</h3><p>The rooms become the flat the simulator builds. Everywhere else is somewhere {household ? "a resident" : "the resident"} travels to, so that being out of the house is a place and not an absence.</p></div></header>
      <div className="horizon-places">
        <div><strong>{reading.rooms.length} room{reading.rooms.length === 1 ? "" : "s"}</strong><ul>{reading.rooms.map((room) => <li key={room}>{room.replace(/_/g, " ")}</li>)}</ul></div>
        <div><strong>Elsewhere</strong>{reading.elsewhere.length ? <ul>{reading.elsewhere.map((place) => <li key={place} className="is-outside">{place.replace(/_/g, " ")}</li>)}</ul> : <small>{household ? "nobody here ever leaves the flat" : "the resident never leaves the flat"}</small>}</div>
        <div><strong><Users size={14} /> People</strong>{reading.people.length ? <ul>{reading.people.map((person) => <li key={person}>{person}</li>)}</ul> : <small>nobody else appears</small>}</div>
      </div>
    </section>
  );
}

function sum(residents: ResidentReading[], count: (resident: ResidentReading) => number): number {
  return residents.reduce((total, resident) => total + count(resident), 0);
}

export function HorizonPreview({ reading, fileName, onImport, busy, sourceFile, vocabulary, review, problems }: {
  reading: HorizonReading;
  /** The active vocabulary. Absent while it is loading, or if it failed — then nothing is called unknown. */
  vocabulary?: VocabularyPack;
  /** What the researcher can do about each addition. Absent, the review only lists them. */
  review?: ReviewActions;
  /** What the server says the outline cannot do, and the repairs made to the imported copy. */
  problems?: ProblemActions;
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
  const { residents, household } = reading;
  const alone = residents.length === 1 ? residents[0] : undefined;
  const livingTogether = !alone || household.relations.length + household.joint.length + household.policies.length + household.privacy.length + household.sharedRooms.length > 0;
  const person = alone ? describePerson(alone) : "";
  return (
    <section className="surface horizon-preview" aria-labelledby="horizon-preview-title" ref={sheet}>
      <div className="horizon-headline">
        <div>
          <p className="eyebrow"><Sparkles size={14} aria-hidden="true" /> Before you import · {fileName}</p>
          <h2 id="horizon-preview-title">{reading.title}</h2>
          <p>
            {alone
              ? <>{reading.dayCount} days for <strong>{alone.name}</strong></>
              : <>{reading.dayCount} days for a household of {residents.length} — {joinNames(residents.map((resident) => resident.name))}</>}
            , {reading.spanPhrase}, on {reading.timeZone} clocks.
            {person && ` ${person}`}
          </p>
          <p className="horizon-provenance">
            <span><UserRound size={14} aria-hidden="true" /> {reading.authorPhrase}</span>
            <span className={reading.humanReviewed ? "is-checked" : "is-unchecked"}>
              <ShieldCheck size={14} aria-hidden="true" /> {reading.humanReviewed ? "The file says a person has read it" : "The file says nobody has read it yet"}
            </span>
          </p>
        </div>
        <div className="horizon-counts">
          {!alone && <div><b>{residents.length}</b><span><Users size={12} aria-hidden="true" /> residents</span></div>}
          <div><b>{sum(residents, (resident) => resident.bands.length)}</b><span>bands</span></div>
          <div><b>{sum(residents, (resident) => resident.activities.length)}</b><span>habits</span></div>
          {!!household.joint.length && <div><b>{household.joint.length}</b><span>together</span></div>}
          <div><b>{sum(residents, (resident) => resident.commitments.length)}</b><span><Pin size={12} aria-hidden="true" /> fixed</span></div>
          <div><b>{sum(residents, (resident) => resident.phases.length)}</b><span>stretches</span></div>
          <div><b>{sum(residents, (resident) => resident.events.length)}</b><span>one-offs</span></div>
        </div>
      </div>
      {reading.note && <p className="horizon-note">{reading.note}</p>}
      {alone?.note && <p className="horizon-note">{alone.note}</p>}
      <VocabularyReview reading={reading} pack={vocabulary} actions={review} />
      <OutlineProblems actions={problems} />
      <div className="horizon-toggle">
        <button className="button secondary" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide the detail" : "Read the whole outline"}</button>
        <button className="button secondary" onClick={() => void exportPage()}><Download size={16} /> Download this page</button>
        <button className="button primary" disabled={busy} onClick={onImport}><Upload size={16} /> Looks right — expand and import</button>
      </div>
      {open && <>
        {alone ? <>
          <DaySection resident={alone} voice={ALONE} />
          <WeekSection resident={alone} voice={ALONE} />
          <SpanSection horizon={reading} resident={alone} voice={ALONE} />
        </> : residents.map((resident, index) => <ResidentBlock key={`${resident.residentId}-${index}`} horizon={reading} resident={resident} index={index} />)}
        {livingTogether && <HouseholdSection household={household} />}
        {reading.behaviour && <BehaviourSection behaviour={reading.behaviour} />}
        <PlaceSection reading={reading} />
        {alone && <BandsSection resident={alone} voice={ALONE} />}
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
