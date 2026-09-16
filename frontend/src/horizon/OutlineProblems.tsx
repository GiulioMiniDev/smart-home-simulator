/**
 * What the outline cannot do as written, and the repairs a researcher can make before importing it.
 *
 * The findings come from the server — the same check the expander stops on — so this component
 * decides nothing about validity: it lists what was found, offers the repairs each finding admits,
 * and records the choices as amendments to the copy that is imported. A repair that works makes its
 * finding disappear on the next check; what was changed stays listed, with an undo, so the import
 * never differs from the file in a way the page does not say.
 *
 * Only repairs the finding itself makes safe are offered. A room is furnished only with a type the
 * vocabulary says provides what is missing, and an activity is moved only to a room that already
 * holds everything it needs.
 */

import { useState } from "react";
import { ArrowRightLeft, Check, ClipboardCopy, PackagePlus, Undo2, Wrench } from "lucide-react";
import { describeAmendment, newResourceId, type OutlineAmendment } from "./review";
import type { OutlineCheck, OutlineFinding, RoomLacksCapabilityDetails, RoomNotDeclaredDetails } from "./types";

export interface ProblemActions {
  check?: OutlineCheck;
  checking: boolean;
  /** Why the check could not run at all, when it could not. */
  failure?: string;
  amendments: OutlineAmendment[];
  /** Resource identifiers already in the imported copy, amendments included. */
  resourceIds: Set<string>;
  onAmend: (amendments: OutlineAmendment[]) => void;
  onUndo: (key: string) => void;
}

function words(value: string): string {
  return value.replace(/_/g, " ");
}

function Facts({ rows }: { rows: Array<[string, string]> }) {
  return (
    <dl className="vocab-review-facts">
      {rows.map(([term, detail]) => (
        <div key={term}><dt>{term}</dt><dd>{detail}</dd></div>
      ))}
    </dl>
  );
}

/** The message as the author would need it, for the one repair this page cannot make. */
function CopyForAuthor({ finding }: { finding: OutlineFinding }) {
  const [copied, setCopied] = useState(false);
  if (!navigator.clipboard) return null;
  return (
    <button
      className="button secondary"
      onClick={() => void navigator.clipboard.writeText(`${finding.message} (${finding.path})`).then(() => setCopied(true))}
    >
      <ClipboardCopy size={15} /> {copied ? "Copied" : "Copy for the author"}
    </button>
  );
}

function RoomLacksCapability({ finding, actions }: { finding: OutlineFinding; actions: ProblemActions }) {
  const details = finding.details as unknown as RoomLacksCapabilityDetails;
  const [mode, setMode] = useState<"closed" | "furnish" | "move">("closed");
  // One piece of furniture per missing capability, chosen from the types that provide it.
  const [chosen, setChosen] = useState<Record<string, string>>(
    Object.fromEntries(details.missingCapabilities.map((capability) => [capability, details.furnitureTypes[capability]?.[0] ?? ""])),
  );
  const [room, setRoom] = useState(details.roomsThatCanHostIt[0] ?? "");
  const unfurnishable = details.missingCapabilities.filter((capability) => !details.furnitureTypes[capability]?.length);

  const furnish = () => {
    const taken = new Set(actions.resourceIds);
    const types = [...new Set(Object.values(chosen).filter(Boolean))];
    actions.onAmend(types.map((resourceType) => {
      const resourceId = newResourceId(details.room, resourceType, taken);
      taken.add(resourceId);
      return { kind: "add_furniture", key: `add_furniture:${resourceId}`, resourceId, resourceType, room: details.room, reason: finding.message };
    }));
    setMode("closed");
  };
  const move = () => {
    actions.onAmend([{ kind: "move_activity", key: `move_activity:${details.recurringActivityId}`, recurringActivityId: details.recurringActivityId, from: details.room, room, reason: finding.message }]);
    setMode("closed");
  };

  return (
    <li className="vocab-review-item">
      <div className="vocab-review-head">
        <div className="vocab-review-summary">
          <div className="vocab-review-title">
            <span className="vocab-kind vocab-kind-room">Room</span>
            <strong>{details.label || words(details.recurringActivityId)}</strong>
            <code>{details.recurringActivityId}</code>
            <small>an activity sent to a room that has nothing it needs</small>
          </div>
          <Facts rows={[
            ["Where", words(details.room)],
            ["Who", details.residentIds.join(", ") || "not stated"],
            ["Missing", details.missingCapabilities.map(words).join(", ")],
            ["Effect", "the import stops: the expander refuses an activity in a room that cannot perform it"],
          ]} />
          <p className="vocab-review-advice advice-check">
            <strong>Advice:</strong> Add the furniture if the activity really happens here; move it if the author sent it to the wrong room.
          </p>
        </div>
        <div className="button-row vocab-review-actions">
          {!unfurnishable.length && <button className="button secondary" aria-expanded={mode === "furnish"} onClick={() => setMode(mode === "furnish" ? "closed" : "furnish")}><PackagePlus size={15} /> Add furniture here</button>}
          {!!details.roomsThatCanHostIt.length && <button className="button secondary" aria-expanded={mode === "move"} onClick={() => setMode(mode === "move" ? "closed" : "move")}><ArrowRightLeft size={15} /> Move the activity</button>}
          <CopyForAuthor finding={finding} />
        </div>
      </div>
      {mode === "furnish" && (
        <div className="vocab-review-form form-stack">
          {details.missingCapabilities.map((capability) => (
            <label key={capability}>
              Something for {words(capability)} in the {words(details.room)}
              <select value={chosen[capability] ?? ""} onChange={(event) => setChosen({ ...chosen, [capability]: event.target.value })}>
                {(details.furnitureTypes[capability] ?? []).map((kind) => <option key={kind} value={kind}>{words(kind)}</option>)}
              </select>
            </label>
          ))}
          <small>Only types the vocabulary says provide it are offered. Only the copy that is imported changes; the file on disk stays as the author wrote it.</small>
          <div className="button-row">
            <button className="button primary" onClick={furnish}>Add to the {words(details.room)}</button>
            <button className="button secondary" onClick={() => setMode("closed")}>Cancel</button>
          </div>
        </div>
      )}
      {mode === "move" && (
        <div className="vocab-review-form form-stack">
          <label>
            Move {details.recurringActivityId} to
            <select value={room} onChange={(event) => setRoom(event.target.value)}>
              {details.roomsThatCanHostIt.map((value) => <option key={value} value={value}>{words(value)}</option>)}
            </select>
          </label>
          <small>Only rooms that already hold everything the activity needs are offered.</small>
          <div className="button-row">
            <button className="button primary" disabled={!room} onClick={move}>Move it</button>
            <button className="button secondary" onClick={() => setMode("closed")}>Cancel</button>
          </div>
        </div>
      )}
    </li>
  );
}

function RoomNotDeclared({ finding, actions }: { finding: OutlineFinding; actions: ProblemActions }) {
  const details = finding.details as unknown as RoomNotDeclaredDetails;
  const [open, setOpen] = useState(false);
  const [room, setRoom] = useState(details.declaredRooms[0] ?? "");
  return (
    <li className="vocab-review-item">
      <div className="vocab-review-head">
        <div className="vocab-review-summary">
          <div className="vocab-review-title">
            <span className="vocab-kind vocab-kind-room">Room</span>
            <strong>{words(details.recurringActivityId)}</strong>
            <code>{details.recurringActivityId}</code>
            <small>an activity sent to a room the outline does not have</small>
          </div>
          <Facts rows={[
            ["Where", `${words(details.room)} — not a room of this outline`],
            ["Effect", "the import stops: the room would resolve to nothing"],
          ]} />
        </div>
        <div className="button-row vocab-review-actions">
          {!!details.declaredRooms.length && <button className="button secondary" aria-expanded={open} onClick={() => setOpen(!open)}><ArrowRightLeft size={15} /> Move the activity</button>}
          <CopyForAuthor finding={finding} />
        </div>
      </div>
      {open && (
        <div className="vocab-review-form form-stack">
          <label>
            Move {details.recurringActivityId} to
            <select value={room} onChange={(event) => setRoom(event.target.value)}>
              {details.declaredRooms.map((value) => <option key={value} value={value}>{words(value)}</option>)}
            </select>
          </label>
          <div className="button-row">
            <button
              className="button primary"
              disabled={!room}
              onClick={() => { actions.onAmend([{ kind: "move_activity", key: `move_activity:${details.recurringActivityId}`, recurringActivityId: details.recurringActivityId, from: details.room, room, reason: finding.message }]); setOpen(false); }}
            >
              Move it
            </button>
            <button className="button secondary" onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </div>
      )}
    </li>
  );
}

function OtherFinding({ finding }: { finding: OutlineFinding }) {
  return (
    <li className="vocab-review-item">
      <div className="vocab-review-head">
        <div className="vocab-review-summary">
          <div className="vocab-review-title"><strong>{finding.message}</strong><code>{finding.code}</code></div>
        </div>
        <div className="button-row vocab-review-actions"><CopyForAuthor finding={finding} /></div>
      </div>
    </li>
  );
}

export function OutlineProblems({ actions }: { actions?: ProblemActions }) {
  if (!actions) return null;
  const { check, checking, failure, amendments } = actions;
  const findings = check?.stage === "expansion" ? check.findings : [];
  if (!findings.length && !amendments.length && !failure && !checking) return null;
  return (
    <section className="horizon-section vocab-review outline-problems" aria-labelledby="outline-problems-title" aria-busy={checking}>
      <header>
        <Wrench size={18} />
        <div>
          <h3 id="outline-problems-title">What the outline cannot do — fix before importing</h3>
          <p>
            The server checked this file the way the import will. Each problem below stops the import; the repairs change only the copy that is imported, and every change is listed with an undo.
          </p>
        </div>
      </header>
      {checking && <p className="horizon-empty" role="status">Checking the outline…</p>}
      {failure && <p className="vocab-review-failure" role="alert">The outline could not be checked: {failure}</p>}
      {!!findings.length && (
        <div className="vocab-review-group">
          <strong>Problems · {findings.length}</strong>
          <ul>
            {findings.map((finding) => {
              if (finding.code === "ROOM_LACKS_CAPABILITY") return <RoomLacksCapability key={finding.path} finding={finding} actions={actions} />;
              if (finding.code === "ROOM_NOT_DECLARED") return <RoomNotDeclared key={finding.path} finding={finding} actions={actions} />;
              return <OtherFinding key={`${finding.code}-${finding.path}`} finding={finding} />;
            })}
          </ul>
        </div>
      )}
      {!checking && !failure && check?.stage === "expansion" && !findings.length && (
        <p className="vocab-review-done"><Check size={15} aria-hidden="true" /> With the changes below, the check finds nothing that stops the import.</p>
      )}
      {!!amendments.length && (
        <div className="vocab-review-group">
          <strong>Changes to this import · {amendments.length}</strong>
          <ul>
            {amendments.map((amendment) => (
              <li key={amendment.key} className="vocab-review-item">
                <p className="vocab-review-done">
                  <Check size={15} aria-hidden="true" />
                  {describeAmendment(amendment)}
                  <button className="button secondary" onClick={() => actions.onUndo(amendment.key)}><Undo2 size={14} /> Undo</button>
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
