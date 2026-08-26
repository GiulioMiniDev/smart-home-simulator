/**
 * The three panels beside the activities: actions, furniture and what is missing.
 *
 * Actions and furniture are the half of the vocabulary that can be extended freely — they change
 * how an activity is performed, not what it is called, so two datasets stay comparable across a
 * change here. That is why neither carries the warning the activity list does.
 */

import { useMemo, useState } from "react";
import { AlertTriangle, CircleCheck, Info, Pencil, Plus, Trash2 } from "lucide-react";
import { ConfirmAction, EmptyState } from "../components";
import { FurnitureSymbols, furnitureSymbol } from "./symbols";
import * as draft from "./draft";
import { actionSummary } from "./phrasing";
import type {
  VocabularyAction,
  VocabularyEntityType,
  VocabularyGapsReport,
  VocabularyPack,
} from "./types";

// --- actions -----------------------------------------------------------------------------------

export function ActionsPanel({
  pack,
  onEdit,
}: {
  pack: VocabularyPack;
  onEdit: (pack: VocabularyPack) => void;
}) {
  const sorted = useMemo(
    () => [...pack.actions].sort((a, b) => a.definition.actionType.localeCompare(b.definition.actionType)),
    [pack.actions],
  );
  return (
    <div className="vocab-single">
      <p className="vocab-lede">
        An activity is a sequence made only of these. A <strong>gesture</strong> has a length of its
        own — closing a door takes three seconds whether it happens during a five-minute breakfast
        or a two-hour dinner. Everything else <strong>fills the activity</strong>: it is what the
        activity is made of, and it absorbs whatever time the day allots.
      </p>
      <NewAction pack={pack} onEdit={onEdit} />
      <div className="vocab-table-scroll">
        <table className="vocab-table">
          <thead>
            <tr>
              <th>Action</th>
              <th>Reads as</th>
              <th>How long</th>
              <th>What the sensors get</th>
              <th>Used by</th>
              <th aria-label="Remove" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((action) => (
              <ActionRow key={action.definition.actionType} pack={pack} action={action} onEdit={onEdit} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ActionRow({
  pack,
  action,
  onEdit,
}: {
  pack: VocabularyPack;
  action: VocabularyAction;
  onEdit: (pack: VocabularyPack) => void;
}) {
  const [open, setOpen] = useState(false);
  const type = action.definition.actionType;
  const users = draft.actionUsers(pack, type);
  const elastic = action.gestureSeconds === null;

  const evidence = action.isTravel
    ? "motion all along the way"
    : action.observability.motionAtObject
      ? "motion at the object"
      : "nothing — only that she is in the room";

  return (
    <>
      <tr>
        <td><code>{type}</code></td>
        <td>{actionSummary(type)}</td>
        <td>
          {action.isTravel ? "as long as the walk" : elastic ? "fills the activity" : `${action.gestureSeconds}s`}
        </td>
        <td className={action.isTravel || action.observability.motionAtObject ? "" : "is-quiet"}>{evidence}</td>
        <td>{users.length === 0 ? <em>nothing</em> : `${users.length} activities`}</td>
        <td className="vocab-row-controls">
          <button className="icon-button" onClick={() => setOpen(!open)} aria-label={`Edit ${type}`} aria-expanded={open}>
            <Pencil size={15} />
          </button>
          <ConfirmAction
            compact
            label={`Remove ${type}`}
            title={`Remove “${type}”?`}
            consequence="No activity uses it, so nothing changes in what is generated."
            disabled={users.length > 0}
            onConfirm={() => onEdit(draft.removeAction(pack, type))}
          />
        </td>
      </tr>
      {open && (
        <tr className="vocab-row-editor">
          <td colSpan={6}>
            <div className="form-stack">
              <label>
                What it means
                <input
                  value={action.definition.description}
                  onChange={(event) =>
                    onEdit(
                      draft.updateAction(pack, type, {
                        definition: { ...action.definition, description: event.target.value },
                      }),
                    )
                  }
                />
              </label>
              <fieldset>
                <legend>How long does it take?</legend>
                <label className="check-field">
                  <input
                    type="radio"
                    name={`length-${type}`}
                    checked={elastic}
                    disabled={action.isTravel}
                    onChange={() => onEdit(draft.updateAction(pack, type, { gestureSeconds: null }))}
                  />
                  <span>
                    It fills the activity — this is what the activity is <em>made</em> of, like
                    cooking or sleeping.
                  </span>
                </label>
                <label className="check-field">
                  <input
                    type="radio"
                    name={`length-${type}`}
                    checked={!elastic}
                    disabled={action.isTravel}
                    onChange={() => onEdit(draft.updateAction(pack, type, { gestureSeconds: 3 }))}
                  />
                  <span>It is a quick gesture with a length of its own:</span>
                </label>
                {!elastic && (
                  <label>
                    Seconds
                    <input
                      type="number"
                      min={0}
                      step={0.5}
                      value={action.gestureSeconds ?? 0}
                      disabled={action.isTravel}
                      onChange={(event) =>
                        onEdit(draft.updateAction(pack, type, { gestureSeconds: Number(event.target.value) }))
                      }
                    />
                  </label>
                )}
                {action.isTravel && (
                  <p className="vocab-note">
                    This action is a walk, so its length is the path the planner lays out. It cannot
                    be given a fixed time.
                  </p>
                )}
              </fieldset>
              <label className="check-field">
                <input
                  type="checkbox"
                  checked={action.observability.motionAtObject}
                  onChange={(event) =>
                    onEdit(
                      draft.updateAction(pack, type, {
                        observability: { ...action.observability, motionAtObject: event.target.checked },
                      }),
                    )
                  }
                />
                <span>
                  The motion detector watching the object sees this.{" "}
                  <small>
                    Turn this off only for something a still body does — waiting, sleeping. An
                    action nothing sees leaves no trace in the dataset beyond the resident being in
                    the room.
                  </small>
                </span>
              </label>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function NewAction({ pack, onEdit }: { pack: VocabularyPack; onEdit: (pack: VocabularyPack) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [capability, setCapability] = useState("");
  const [fixed, setFixed] = useState(true);
  const [seconds, setSeconds] = useState(5);
  const capabilities = useMemo(() => draft.knownCapabilities(pack), [pack]);

  if (!open) {
    return (
      <button className="button secondary vocab-add" onClick={() => setOpen(true)}>
        <Plus size={15} /> New action
      </button>
    );
  }
  const identifier = draft.slug(name);
  const taken = pack.actions.some((item) => item.definition.actionType === identifier);
  return (
    <div className="vocab-new form-stack">
      <label>
        What does the resident do?
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="water plants" />
        {identifier && <small>Stored as <code>{identifier}</code>{taken && " — already taken"}</small>}
      </label>
      <label>
        Describe it in one line
        <input
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Pour water into a planter."
        />
      </label>
      <label>
        What does it need to be done to?
        <select value={capability} onChange={(event) => setCapability(event.target.value)}>
          <option value="">Nothing in particular</option>
          {capabilities.map((item) => (
            <option key={item} value={item}>{item.replace(/_/g, " ")}</option>
          ))}
        </select>
        <small>
          Furniture offering this is what the step will bind to. If nothing offers it, the step
          happens on open floor and no sensor on a fixture records it.
        </small>
      </label>
      <fieldset>
        <legend>How long does it take?</legend>
        <label className="check-field">
          <input type="radio" name="new-length" checked={fixed} onChange={() => setFixed(true)} />
          <span>A quick gesture — the same length wherever it happens</span>
        </label>
        {fixed && (
          <label>
            Seconds
            <input type="number" min={0} step={0.5} value={seconds} onChange={(event) => setSeconds(Number(event.target.value))} />
          </label>
        )}
        <label className="check-field">
          <input type="radio" name="new-length" checked={!fixed} onChange={() => setFixed(false)} />
          <span>It fills the activity — this is what the activity is made of</span>
        </label>
      </fieldset>
      <div className="button-row">
        <button
          className="button"
          disabled={!identifier || taken}
          onClick={() => {
            onEdit(
              draft.addAction(pack, {
                actionType: identifier,
                description,
                capability,
                gestureSeconds: fixed ? seconds : null,
                // A new action is something the resident does with her hands, so a detector sees
                // it. Anything that should be invisible is the exception, and the row above turns
                // it off explicitly.
                motionAtObject: true,
              }),
            );
            setName("");
            setDescription("");
            setOpen(false);
          }}
        >
          Create the action
        </button>
        <button className="button secondary" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </div>
  );
}

// --- furniture ---------------------------------------------------------------------------------

export function FurniturePanel({
  pack,
  onEdit,
}: {
  pack: VocabularyPack;
  onEdit: (pack: VocabularyPack) => void;
}) {
  const sorted = useMemo(
    () => [...pack.entityTypes].sort((a, b) => a.displayName.localeCompare(b.displayName)),
    [pack.entityTypes],
  );
  const [selected, setSelected] = useState<string | undefined>(undefined);
  const current = sorted.find((item) => item.entityType === selected) ?? sorted[0];

  return (
    <div className="vocab-board">
      <aside className="vocab-rail">
        <NewFurniture pack={pack} onEdit={onEdit} onSelect={setSelected} />
        <div className="vocab-rail-scroll">
          {sorted.map((item) => (
            <button
              key={item.entityType}
              className="vocab-pick vocab-pick-furniture"
              aria-current={current?.entityType === item.entityType}
              onClick={() => setSelected(item.entityType)}
            >
              <SymbolPreview entity={item} size={26} />
              <span>{item.displayName}</span>
              {item.contactInstrumented && <small title="Has a sensor on its door">door</small>}
            </button>
          ))}
        </div>
      </aside>
      {current ? (
        <FurnitureDetail pack={pack} entity={current} onEdit={onEdit} onSelect={setSelected} />
      ) : (
        <EmptyState title="No furniture in this vocabulary" icon={<Info size={22} />}>
          <p>Add a kind of object for activities to bind to.</p>
        </EmptyState>
      )}
    </div>
  );
}

/**
 * The glyph a type is drawn with, at any size.
 *
 * Three sources, in order: an SVG the researcher drew for this type, a bundled glyph named
 * explicitly, and the bundled glyph that matches the type's own name. A type with none is drawn as
 * a plain box, which is exactly what it looks like on the plan and in the replay.
 */
export function SymbolPreview({ entity, size = 48 }: { entity: VocabularyEntityType; size?: number }) {
  const bundled = entity.symbolId ?? furnitureSymbol(entity.entityType);
  return (
    <svg className="vocab-symbol" width={size} height={size} viewBox="-24 -24 48 48" aria-hidden="true">
      <FurnitureSymbols />
      {entity.symbolBody ? (
        <g dangerouslySetInnerHTML={{ __html: entity.symbolBody }} />
      ) : bundled ? (
        <use href={`#furn-${bundled}`} />
      ) : (
        <rect x="-15" y="-15" width="30" height="30" rx="3" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="4 3" />
      )}
    </svg>
  );
}

function FurnitureDetail({
  pack,
  entity,
  onEdit,
  onSelect,
}: {
  pack: VocabularyPack;
  entity: VocabularyEntityType;
  onEdit: (pack: VocabularyPack) => void;
  onSelect: (id: string) => void;
}) {
  const capabilities = useMemo(() => draft.knownCapabilities(pack), [pack]);
  const usedBy = useMemo(
    () =>
      pack.intents
        .filter((intent) =>
          intent.processModel.nodes.some((node) =>
            Object.values(node.arguments).some(
              (argument) =>
                argument.source === "literal" &&
                typeof argument.value === "string" &&
                (entity.roleAliases.includes(argument.value) || argument.value === entity.entityType),
            ),
          ),
        )
        .map((intent) => intent.label),
    [pack.intents, entity],
  );
  const drawn = entity.symbolBody || entity.symbolId || furnitureSymbol(entity.entityType);

  return (
    <section className="vocab-detail surface">
      <header className="vocab-detail-head">
        <div className="vocab-furniture-title">
          <SymbolPreview entity={entity} size={44} />
          <div>
            <input
              className="vocab-title-input"
              value={entity.displayName}
              onChange={(event) => onEdit(draft.updateEntityType(pack, entity.entityType, { displayName: event.target.value }))}
              aria-label="Furniture name"
            />
            <code className="vocab-id">{entity.entityType}</code>
          </div>
        </div>
        <ConfirmAction
          label="Remove this kind of furniture"
          title={`Remove “${entity.displayName}”?`}
          consequence={
            usedBy.length > 0
              ? `${usedBy.length} activities bind to it. They will fall back to the middle of the room.`
              : "No activity binds to it, so nothing changes in what is generated."
          }
          onConfirm={() => {
            onEdit(draft.removeEntityType(pack, entity.entityType));
            onSelect(pack.entityTypes.find((item) => item.entityType !== entity.entityType)?.entityType ?? "");
          }}
        />
      </header>

      <div className="vocab-columns">
        <div className="form-stack">
          <h3>What is it for?</h3>
          <p className="vocab-note">
            An activity asks for a capability and the simulator picks a piece of furniture that
            offers it. A type that offers nothing keeps <em>everything</em>, so it becomes a
            candidate for every activity.
          </p>
          <TokenEditor
            values={entity.capabilities}
            suggestions={capabilities}
            placeholder="food_preparation"
            onChange={(values) => onEdit(draft.updateEntityType(pack, entity.entityType, { capabilities: values }))}
          />

          <h3>What do activities call it?</h3>
          <p className="vocab-note">
            The names a step may use for it. <code>food_storage</code> is how a recipe refers to the
            fridge without knowing there is a fridge.
          </p>
          <TokenEditor
            values={entity.roleAliases}
            suggestions={draft.knownRoles(pack)}
            placeholder="food_storage"
            onChange={(values) => onEdit(draft.updateEntityType(pack, entity.entityType, { roleAliases: values }))}
          />

          <label className="check-field">
            <input
              type="checkbox"
              checked={entity.contactInstrumented}
              onChange={(event) =>
                onEdit(draft.updateEntityType(pack, entity.entityType, { contactInstrumented: event.target.checked }))
              }
            />
            <span>
              It has a sensor on its door.{" "}
              <small>
                Opening and closing it then appears in the dataset as its own event. Without this,
                opening it produces motion and nothing else.
              </small>
            </span>
          </label>

          <h3>Which activities use it</h3>
          {usedBy.length === 0 ? (
            <p className="vocab-note is-warning">
              <AlertTriangle size={14} /> Nothing binds to it. It will stand in the flat unused.
            </p>
          ) : (
            <ul className="vocab-usedby">{usedBy.map((label) => <li key={label}>{label}</li>)}</ul>
          )}
        </div>

        <div className="form-stack">
          <h3>How it is drawn</h3>
          <div className="vocab-symbol-stage">
            <SymbolPreview entity={entity} size={128} />
            <p className="vocab-note">
              {entity.symbolBody
                ? "Drawn with the shape below."
                : drawn
                  ? "Uses the drawing that ships with the app."
                  : "No drawing — it appears on the plan and in the replay as a dashed box."}
            </p>
          </div>
          <label>
            Shape
            <textarea
              rows={8}
              spellCheck={false}
              className="vocab-svg-input"
              value={entity.symbolBody ?? ""}
              placeholder={'<rect x="-15" y="-12" width="30" height="24" rx="3" fill="#fff" stroke="currentColor" stroke-width="2" />'}
              onChange={(event) =>
                onEdit(
                  draft.updateEntityType(pack, entity.entityType, {
                    symbolBody: event.target.value.trim() ? event.target.value : null,
                  }),
                )
              }
            />
            <small>
              SVG shapes drawn in a box from −24 to 24, scaled to the object's real footprint on the
              plan. Use <code>currentColor</code> for outlines so it follows the theme. Leave it
              empty to go back to the built-in drawing.
            </small>
          </label>
        </div>
      </div>
    </section>
  );
}

function NewFurniture({
  pack,
  onEdit,
  onSelect,
}: {
  pack: VocabularyPack;
  onEdit: (pack: VocabularyPack) => void;
  onSelect: (id: string) => void;
}) {
  const [name, setName] = useState("");
  return (
    <div className="vocab-new-inline">
      <input
        value={name}
        onChange={(event) => setName(event.target.value)}
        placeholder="Add a kind of furniture…"
        aria-label="New furniture name"
      />
      <button
        className="button secondary"
        aria-label="Add this kind of furniture"
        disabled={!draft.slug(name)}
        onClick={() => {
          const result = draft.addEntityType(pack, name.trim());
          onEdit(result.pack);
          onSelect(result.entityType);
          setName("");
        }}
      >
        <Plus size={15} />
      </button>
    </div>
  );
}

/** A list of short identifiers, added and removed one at a time. */
function TokenEditor({
  values,
  suggestions,
  placeholder,
  onChange,
}: {
  values: string[];
  suggestions: string[];
  placeholder: string;
  onChange: (values: string[]) => void;
}) {
  const [entry, setEntry] = useState("");
  const listId = `suggest-${placeholder}`;
  const add = () => {
    const value = draft.slug(entry);
    if (!value || values.includes(value)) return;
    onChange([...values, value].sort());
    setEntry("");
  };
  return (
    <div className="token-editor">
      <ul>
        {values.map((value) => (
          <li key={value}>
            <code>{value}</code>
            <button
              className="icon-button"
              aria-label={`Remove ${value}`}
              onClick={() => onChange(values.filter((item) => item !== value))}
            >
              <Trash2 size={13} />
            </button>
          </li>
        ))}
        {values.length === 0 && <li className="is-empty">none</li>}
      </ul>
      <div className="token-entry">
        <input
          list={listId}
          value={entry}
          placeholder={placeholder}
          onChange={(event) => setEntry(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              add();
            }
          }}
        />
        <button
          className="button secondary"
          aria-label={`Add ${placeholder === "food_preparation" ? "capability" : "name"}`}
          onClick={add}
          disabled={!draft.slug(entry)}
        >
          <Plus size={14} />
        </button>
        <datalist id={listId}>
          {suggestions.filter((item) => !values.includes(item)).map((item) => <option key={item} value={item} />)}
        </datalist>
      </div>
    </div>
  );
}

// --- gaps --------------------------------------------------------------------------------------

const SEVERITY_TITLES: Record<string, string> = {
  blocking: "Will stop a run",
  warning: "Will quietly make the dataset worse",
  note: "Worth knowing",
};

export function GapsPanel({ report }: { report?: VocabularyGapsReport }) {
  if (!report) return <EmptyState title="Checking the vocabulary…" icon={<Info size={22} />}><p>One moment.</p></EmptyState>;
  if (report.gaps.length === 0) {
    return (
      <EmptyState title="Nothing is missing" icon={<CircleCheck size={22} />}>
        <p>Every role binds to something, every action is used, and every object can be drawn.</p>
      </EmptyState>
    );
  }
  const groups = ["blocking", "warning", "note"].filter((severity) =>
    report.gaps.some((gap) => gap.severity === severity),
  );
  return (
    <div className="vocab-single">
      <p className="vocab-lede">
        None of these stop a run, unless marked otherwise. That is why they are worth reading: each
        one changes what ends up in the dataset without reporting anything.
      </p>
      {groups.map((severity) => (
        <section key={severity} className="vocab-gap-group">
          <h3>{SEVERITY_TITLES[severity]}</h3>
          <ul className="vocab-gap-list">
            {report.gaps
              .filter((gap) => gap.severity === severity)
              .map((gap) => (
                <li key={`${gap.code}-${gap.subject}`} className={`vocab-gap is-${severity}`}>
                  <div>
                    <strong>{gap.message}</strong>
                    {gap.consequence && <p>{gap.consequence}</p>}
                    {gap.details.usedBy && (
                      <p className="vocab-gap-detail">Used by: {gap.details.usedBy.join(", ")}</p>
                    )}
                    {gap.details.didYouMean && (
                      <p className="vocab-gap-detail">Did you mean: {gap.details.didYouMean.join(", ")}?</p>
                    )}
                  </div>
                  <code>{gap.code}</code>
                </li>
              ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
