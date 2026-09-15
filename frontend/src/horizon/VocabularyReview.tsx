/**
 * What the outline brings that the vocabulary does not have, and the researcher's answer to each.
 *
 * An external author may propose furniture and activities the prompt's vocabulary lacks, and may
 * also simply use them. Neither is silently accepted: an object whose type the vocabulary says
 * nothing about offers every capability, so it can be picked for any action in its room, and an
 * activity the vocabulary does not name stops the import, because it would be a new label in the
 * dataset. This is where the researcher decides — add it to the vocabulary with what it is for,
 * import the object as a type that already exists, remove it, or leave it.
 *
 * Every entry says what kind of thing it is, where it is, what it is for and what the review
 * recommends, because a bare identifier did not: `exercise_surface · proposed` asked for a decision
 * without saying it was a piece of furniture placed outdoors, where nothing is ever furnished.
 *
 * Actions and capabilities are never offered here. They are what the simulator executes and what
 * the sensors record; a proposal combines them, it does not invent them.
 */

import { useMemo, useState, type ReactNode } from "react";
import { AlertTriangle, BookPlus, Check, Replace, Trash2, Undo2 } from "lucide-react";
import { knownCapabilities } from "../vocabulary/draft";
import { CATEGORY_LABELS, CATEGORY_ORDER } from "../vocabulary/phrasing";
import type { VocabularyPack } from "../vocabulary/types";
import {
  REMOVED,
  activityAdvice,
  furnitureAdvice,
  intentFromProposal,
  reviewItems,
  type ActivityItem,
  type Advice,
  type FurnitureItem,
  type ReviewActions,
} from "./review";
import type { HorizonReading } from "./types";

function words(value: string): string {
  return value.replace(/_/g, " ");
}

function Facts({ rows }: { rows: Array<[string, ReactNode]> }) {
  return (
    <dl className="vocab-review-facts">
      {rows.map(([term, detail]) => (
        <div key={term}><dt>{term}</dt><dd>{detail}</dd></div>
      ))}
    </dl>
  );
}

function AdviceLine({ advice }: { advice: Advice }) {
  return <p className={`vocab-review-advice advice-${advice.tone}`}><strong>Advice:</strong> {advice.text}</p>;
}

function Title({ kind, name, identifier, origin }: { kind: "Object" | "Activity"; name: string; identifier: string; origin: string }) {
  return (
    <div className="vocab-review-title">
      <span className={`vocab-kind vocab-kind-${kind.toLowerCase()}`}>{kind}</span>
      <strong>{name}</strong>
      <code>{identifier}</code>
      <small>{origin}</small>
    </div>
  );
}

function FurnitureRow({ item, pack, reading, actions }: { item: FurnitureItem; pack: VocabularyPack; reading: HorizonReading; actions?: ReviewActions }) {
  const [mode, setMode] = useState<"closed" | "add" | "substitute">("closed");
  const [name, setName] = useState(item.proposal?.displayName ?? words(item.entityType));
  const [chosen, setChosen] = useState<string[]>(item.proposal?.capabilities ?? []);
  const [contact, setContact] = useState(item.proposal?.contactInstrumented ?? false);
  const [drawing, setDrawing] = useState("");
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string>();
  const capabilities = useMemo(() => knownCapabilities(pack), [pack]);
  const invented = chosen.filter((value) => !capabilities.includes(value));
  const decision = actions ? actions.substitutions[item.entityType] : undefined;
  const candidates = pack.entityTypes.filter((entity) => entity.capabilities.length).sort((a, b) => a.displayName.localeCompare(b.displayName));
  const advice = furnitureAdvice(item, capabilities);

  const add = async () => {
    if (!actions) return;
    setBusy(true); setFailure(undefined);
    try {
      await actions.onAddFurniture({
        entityType: item.entityType,
        displayName: name.trim() || item.entityType,
        capabilities: chosen,
        roleAliases: [],
        contactInstrumented: contact,
        symbolId: null,
        symbolBody: drawing.trim() ? drawing : null,
      });
    } catch (reason) {
      setFailure(reason instanceof Error ? reason.message : String(reason));
      setBusy(false);
    }
  };

  const where = item.rooms.length
    ? item.rooms.map((place) => reading.rooms.includes(place) ? words(place) : `${words(place)} — outside the home`).join(", ")
    : "no object in the home has this type";
  const purpose = item.proposal?.capabilities.length
    ? item.proposal.capabilities.map(words).join(", ")
    : item.declaredEmpty ? "the vocabulary has this type but says nothing it is for" : "not stated";

  return (
    <li className="vocab-review-item">
      <div className="vocab-review-head">
        <div className="vocab-review-summary">
          <Title
            kind="Object"
            name={item.proposal?.displayName ?? words(item.entityType)}
            identifier={item.entityType}
            origin={item.proposal ? "a new type of furniture the author proposes" : "a type of furniture the author used without proposing it"}
          />
          <Facts rows={[
            ["Where", where],
            ["For", purpose],
            ...(item.proposal?.rationale ? [["Why", `“${item.proposal.rationale}”`] as [string, ReactNode]] : []),
          ]} />
          {decision === undefined && <AdviceLine advice={advice} />}
        </div>
        {actions && (decision !== undefined ? (
          <p className="vocab-review-done">
            <Check size={15} aria-hidden="true" />
            {decision === REMOVED ? "Removed from this import" : <>Imported as <code>{decision}</code></>}
            <button className="button secondary" onClick={() => actions.onSubstitute(item.entityType, undefined)}><Undo2 size={14} /> Undo</button>
          </p>
        ) : (
          <div className="button-row vocab-review-actions">
            <button className="button secondary" aria-expanded={mode === "add"} onClick={() => setMode(mode === "add" ? "closed" : "add")}><BookPlus size={15} /> Add to the vocabulary</button>
            {!!item.rooms.length && <button className="button secondary" aria-expanded={mode === "substitute"} onClick={() => setMode(mode === "substitute" ? "closed" : "substitute")}><Replace size={15} /> Use a known type instead</button>}
            {!!item.rooms.length && <button className="button secondary" onClick={() => { actions.onSubstitute(item.entityType, REMOVED); setMode("closed"); }}><Trash2 size={15} /> Remove from this import</button>}
          </div>
        ))}
      </div>
      {actions && decision === undefined && mode === "add" && (
        <div className="vocab-review-form form-stack">
          <label>Name<input value={name} onChange={(event) => setName(event.target.value)} /></label>
          <fieldset>
            <legend>What it is for</legend>
            <div className="vocab-review-capabilities">
              {[...capabilities, ...invented].map((value) => (
                <label key={value} className="check-field">
                  <input
                    type="checkbox"
                    checked={chosen.includes(value)}
                    onChange={(event) => setChosen(event.target.checked ? [...chosen, value] : chosen.filter((item) => item !== value))}
                  />
                  <span>{words(value)}{invented.includes(value) && <small> — no action asks for this, so it binds nothing</small>}</span>
                </label>
              ))}
            </div>
            <small>Only what an action needs from an object. Leave everything unticked and the type stays as permissive as it is now.</small>
          </fieldset>
          <label className="check-field">
            <input type="checkbox" checked={contact} onChange={(event) => setContact(event.target.checked)} />
            <span>It has a door or a lid a contact sensor would be fitted to.</span>
          </label>
          <label>
            Drawing (optional)
            <textarea rows={4} spellCheck={false} className="vocab-svg-input" value={drawing} onChange={(event) => setDrawing(event.target.value)} placeholder={'<rect x="-18" y="-8" width="36" height="16" rx="3" fill="none" stroke="currentColor" stroke-width="2" />'} />
            <small>SVG shapes in a box from −24 to 24, as on the Furniture page. Empty draws a dashed box; the drawing can be added there later.</small>
          </label>
          {failure && <p className="vocab-review-failure" role="alert">{failure}</p>}
          <div className="button-row">
            <button className="button primary" disabled={busy || !chosen.length} onClick={() => void add()}>Add “{name.trim() || item.entityType}”</button>
            <button className="button secondary" onClick={() => setMode("closed")}>Cancel</button>
          </div>
        </div>
      )}
      {actions && decision === undefined && mode === "substitute" && (
        <div className="vocab-review-form form-stack">
          <label>
            Import every <code>{item.entityType}</code> in this file as
            <select value={target} onChange={(event) => setTarget(event.target.value)}>
              <option value="">Choose a type…</option>
              {candidates.map((entity) => <option key={entity.entityType} value={entity.entityType}>{entity.displayName}</option>)}
            </select>
          </label>
          <small>Only the copy that is imported changes; the file on disk stays as the author wrote it.</small>
          <div className="button-row">
            <button className="button primary" disabled={!target} onClick={() => { actions.onSubstitute(item.entityType, target); setMode("closed"); }}>Use this type</button>
            <button className="button secondary" onClick={() => setMode("closed")}>Cancel</button>
          </div>
        </div>
      )}
    </li>
  );
}

function ActivityRow({ item, pack, actions }: { item: ActivityItem; pack: VocabularyPack; actions?: ReviewActions }) {
  const rooms = useMemo(() => [...new Set(pack.intents.map((intent) => intent.defaultLocation))].sort(), [pack.intents]);
  const proposedRoom = item.proposal?.defaultLocation;
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState(item.proposal?.label ?? words(item.intentId));
  const [category, setCategory] = useState(item.proposal && CATEGORY_ORDER.includes(item.proposal.category) ? item.proposal.category : "leisure");
  const [location, setLocation] = useState(proposedRoom && rooms.includes(proposedRoom) ? proposedRoom : rooms.includes("living_room") ? "living_room" : rooms[0] ?? "");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string>();
  const steps = (item.model?.nodes ?? []).filter((node) => node.kind === "action").length;

  const add = async () => {
    if (!actions || !item.model) return;
    setBusy(true); setFailure(undefined);
    try {
      await actions.onAddActivity(intentFromProposal(item.intentId, { label: label.trim() || item.intentId, category, room: location, description: item.proposal?.description ?? "" }, item.model));
    } catch (reason) {
      setFailure(reason instanceof Error ? reason.message : String(reason));
      setBusy(false);
    }
  };

  return (
    <li className="vocab-review-item">
      <div className="vocab-review-head">
        <div className="vocab-review-summary">
          <Title
            kind="Activity"
            name={item.proposal?.label ?? words(item.intentId)}
            identifier={item.intentId}
            origin={item.proposal ? "a new activity label the author proposes" : "an activity label the author used without proposing it"}
          />
          <Facts rows={[
            ["Where", item.proposal ? words(item.proposal.defaultLocation) : "not stated"],
            ["How", item.model ? `the file's own process, in ${steps} step${steps === 1 ? "" : "s"}` : "the file gives no process for it"],
            ["Effect", "the import stops until it is in the vocabulary: it would be a new label in the dataset"],
            ...(item.proposal?.rationale ? [["Why", `“${item.proposal.rationale}”`] as [string, ReactNode]] : []),
          ]} />
          <AdviceLine advice={activityAdvice(item)} />
        </div>
        {actions && item.model && (
          <div className="button-row vocab-review-actions">
            <button className="button secondary" aria-expanded={open} onClick={() => setOpen(!open)}><BookPlus size={15} /> Add to the vocabulary</button>
          </div>
        )}
      </div>
      {actions && item.model && open && (
        <div className="vocab-review-form form-stack">
          <label>Name<input value={label} onChange={(event) => setLabel(event.target.value)} /></label>
          <label>
            Kind of activity
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              {CATEGORY_ORDER.map((value) => <option key={value} value={value}>{CATEGORY_LABELS[value] ?? value}</option>)}
            </select>
          </label>
          <label>
            Where it usually happens
            <select value={location} onChange={(event) => setLocation(event.target.value)}>
              {rooms.map((value) => <option key={value} value={value}>{words(value)}</option>)}
            </select>
            {proposedRoom && !rooms.includes(proposedRoom) && (
              <small>The author proposed the {words(proposedRoom)}, which no activity in the vocabulary uses. Every outline must declare the rooms the vocabulary's activities happen in, so only those are offered.</small>
            )}
          </label>
          {failure && <p className="vocab-review-failure" role="alert">{failure}</p>}
          <div className="button-row">
            <button className="button primary" disabled={busy || !location} onClick={() => void add()}>Add “{label.trim() || item.intentId}”</button>
            <button className="button secondary" onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </div>
      )}
    </li>
  );
}

export function VocabularyReview({ reading, pack, actions }: { reading: HorizonReading; pack?: VocabularyPack; actions?: ReviewActions }) {
  if (!pack) return null;
  const { furniture, activities } = reviewItems(reading, pack);
  if (!furniture.length && !activities.length) return null;
  return (
    <section className="horizon-section vocab-review" aria-labelledby="vocab-review-title">
      <header>
        <AlertTriangle size={18} />
        <div>
          <h3 id="vocab-review-title">Additions to the vocabulary — review before importing</h3>
          <p>
            This outline uses things the simulator's vocabulary does not have yet. An <strong>object</strong> is a type of furniture: until you say what it is for, any action in its room may use it. An <strong>activity</strong> is an activity label: the import stops until it exists.
            Nothing is added on its own; each entry below says what it is and what we recommend.
          </p>
        </div>
      </header>
      {!!furniture.length && (
        <div className="vocab-review-group">
          <strong>Objects (types of furniture) · {furniture.length}</strong>
          <ul>{furniture.map((item) => <FurnitureRow key={item.entityType} item={item} pack={pack} reading={reading} actions={actions} />)}</ul>
        </div>
      )}
      {!!activities.length && (
        <div className="vocab-review-group">
          <strong>Activities (activity labels) · {activities.length}</strong>
          <ul>{activities.map((item) => <ActivityRow key={item.intentId} item={item} pack={pack} actions={actions} />)}</ul>
        </div>
      )}
    </section>
  );
}
