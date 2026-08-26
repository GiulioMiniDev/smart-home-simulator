/**
 * The vocabulary editor: what the resident can do, and what the flat is made of.
 *
 * Written for a researcher, not a programmer. Every activity is shown as a list of things a person
 * does, in order, in a sentence — the call underneath is there to be edited, not to be read first.
 * Three things the old catalogs never said out loud are said on every step: which object in the
 * flat it will actually touch, what the sensors will record, and whether it has a length of its own
 * or absorbs the activity's time.
 */

import { useMemo, useState } from "react";
import { AlertTriangle, ArrowDown, ArrowRight, ArrowUp, Info, Plus, Trash2, Undo2 } from "lucide-react";
import { ConfirmAction, EmptyState, ErrorPanel, PageHeader, Skeleton } from "../components";
import * as draft from "./draft";
import { ActionsPanel, FurniturePanel, GapsPanel } from "./VocabularyPanels";
import {
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  stepBinding,
  stepCall,
  stepEvidence,
  stepPhrase,
  stepTiming,
} from "./phrasing";
import type { ProcessNode, VocabularyIntent, VocabularyPack } from "./types";
import { useVocabulary } from "./useVocabulary";
import "./vocabulary.css";

type Tab = "activities" | "actions" | "furniture" | "gaps";

const TAB_LABELS: Record<Tab, string> = {
  activities: "Activities",
  actions: "Actions",
  furniture: "Furniture",
  gaps: "What is missing",
};

export function VocabularyPage() {
  const session = useVocabulary();
  const [tab, setTab] = useState<Tab>("activities");
  const [selected, setSelected] = useState<string | undefined>(undefined);

  const gapCount = session.review?.report.gaps.length ?? 0;
  const labelSpaceMoved =
    session.openedLabelSpaceDigest !== undefined &&
    session.labelSpaceDigest !== undefined &&
    session.openedLabelSpaceDigest !== session.labelSpaceDigest;

  return (
    <div className="page vocabulary-page">
      <PageHeader
        eyebrow="Open vocabulary"
        title="What the resident can do"
        description="Every activity, action and piece of furniture the simulator knows about. Changes are saved as you make them and the next run uses them."
        actions={
          <div className="button-row">
            <SaveIndicator session={session} />
            <button
              className="button secondary"
              onClick={session.undo}
              disabled={!session.canUndo}
              title="Undo the last change"
            >
              <Undo2 size={15} /> Undo
            </button>
            <ConfirmAction
              label="Reset the vocabulary"
              title="Go back to the built-in vocabulary?"
              consequence="Every activity, action and object returns to the way the simulator ships. Runs already generated keep the vocabulary they were made with."
              disabled={!session.customised}
              onConfirm={() => void session.reset()}
            />
          </div>
        }
      />

      {session.error && <ErrorPanel message={session.error.message} onRetry={() => void session.reload()} />}
      {session.loading && !session.pack && <Skeleton lines={8} />}

      {session.pack && (
        <>
          <VocabularyStatus
            pack={session.pack}
            customised={session.customised}
            labelSpaceMoved={labelSpaceMoved}
          />

          <div className="tabs" role="tablist">
            {(Object.keys(TAB_LABELS) as Tab[]).map((item) => (
              <button
                key={item}
                role="tab"
                aria-selected={tab === item}
                onClick={() => setTab(item)}
              >
                {TAB_LABELS[item]}
                {item === "gaps" && gapCount > 0 && <span className="tab-count">{gapCount}</span>}
              </button>
            ))}
          </div>

          {tab === "activities" && (
            <ActivitiesPanel
              pack={session.pack}
              selected={selected}
              onSelect={setSelected}
              onEdit={session.edit}
            />
          )}
          {tab === "actions" && <ActionsPanel pack={session.pack} onEdit={session.edit} />}
          {tab === "furniture" && <FurniturePanel pack={session.pack} onEdit={session.edit} />}
          {tab === "gaps" && <GapsPanel report={session.review?.report} />}
        </>
      )}
    </div>
  );
}

function SaveIndicator({ session }: { session: ReturnType<typeof useVocabulary> }) {
  const { save } = session;
  if (save.status === "saving") return <span className="save-state is-working">Saving…</span>;
  if (save.status === "saved") return <span className="save-state is-done">Saved</span>;
  if (save.status === "conflict") {
    return (
      <button className="save-state is-bad" onClick={() => void session.reload()}>
        Changed in another window — reload
      </button>
    );
  }
  if (save.status === "error") return <span className="save-state is-bad">{save.message}</span>;
  return <span className="save-state">All changes saved automatically</span>;
}

function VocabularyStatus({
  pack,
  customised,
  labelSpaceMoved,
}: {
  pack: VocabularyPack;
  customised: boolean;
  labelSpaceMoved: boolean;
}) {
  return (
    <section className="vocab-status surface">
      <div>
        <span className="status">{customised ? "Edited" : "As shipped"}</span>
        <p>
          {pack.intents.length} activities · {pack.actions.length} actions ·{" "}
          {pack.entityTypes.length} kinds of furniture
        </p>
      </div>
      {labelSpaceMoved && (
        <p className="vocab-warning">
          <AlertTriangle size={15} aria-hidden="true" />
          <span>
            <strong>The ground-truth labels have changed in this session.</strong> Datasets
            generated before and after this point name different activities, so a score computed
            across both is not comparing like with like. Everything else — actions, furniture,
            timings — leaves the labels alone.
          </span>
        </p>
      )}
    </section>
  );
}

// --- activities --------------------------------------------------------------------------------

function ActivitiesPanel({
  pack,
  selected,
  onSelect,
  onEdit,
}: {
  pack: VocabularyPack;
  selected?: string;
  onSelect: (id: string) => void;
  onEdit: (pack: VocabularyPack) => void;
}) {
  const [query, setQuery] = useState("");
  const current = pack.intents.find((item) => item.intentId === selected) ?? pack.intents[0];

  const grouped = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const groups = new Map<string, VocabularyIntent[]>();
    for (const intent of pack.intents) {
      if (needle) {
        const hay = `${intent.intentId} ${intent.label} ${intent.defaultLocation}`.toLowerCase();
        if (!hay.includes(needle)) continue;
      }
      const bucket = groups.get(intent.category) ?? [];
      bucket.push(intent);
      groups.set(intent.category, bucket);
    }
    return [...groups.entries()].sort(
      (a, b) => CATEGORY_ORDER.indexOf(a[0]) - CATEGORY_ORDER.indexOf(b[0]),
    );
  }, [pack.intents, query]);

  return (
    <div className="vocab-board">
      <aside className="vocab-rail">
        <input
          className="catalogue-filter"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter activities…"
          aria-label="Filter activities"
        />
        <NewActivity pack={pack} onEdit={onEdit} onSelect={onSelect} />
        <div className="vocab-rail-scroll">
          {grouped.map(([category, intents]) => (
            <div className="vocab-group" key={category}>
              <p className="vocab-group-head">{CATEGORY_LABELS[category] ?? category}</p>
              {intents.map((intent) => (
                <button
                  key={intent.intentId}
                  className="vocab-pick"
                  aria-current={current?.intentId === intent.intentId}
                  onClick={() => onSelect(intent.intentId)}
                >
                  <span>{intent.label}</span>
                  <small>{draft.actionNodes(intent.processModel).length}</small>
                </button>
              ))}
            </div>
          ))}
          {grouped.length === 0 && <p className="vocab-empty">Nothing matches that.</p>}
        </div>
      </aside>

      {current ? (
        <ActivityDetail pack={pack} intent={current} onEdit={onEdit} onSelect={onSelect} />
      ) : (
        <EmptyState title="No activities in this vocabulary" icon={<Info size={22} />}>
          <p>Add one to describe something the resident does.</p>
        </EmptyState>
      )}
    </div>
  );
}

function NewActivity({
  pack,
  onEdit,
  onSelect,
}: {
  pack: VocabularyPack;
  onEdit: (pack: VocabularyPack) => void;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [category, setCategory] = useState("chores");
  const rooms = useMemo(
    () => [...new Set(pack.intents.map((item) => item.defaultLocation))].sort(),
    [pack.intents],
  );
  const [room, setRoom] = useState(rooms[0] ?? "living_room");

  if (!open) {
    return (
      <button className="button secondary vocab-add" onClick={() => setOpen(true)}>
        <Plus size={15} /> New activity
      </button>
    );
  }
  const create = () => {
    if (!label.trim()) return;
    const result = draft.addIntent(pack, { label: label.trim(), category, room });
    onEdit(result.pack);
    onSelect(result.intentId);
    setLabel("");
    setOpen(false);
  };
  return (
    <div className="vocab-new form-stack">
      <p className="vocab-note">
        A new activity is a new ground-truth label. Datasets made before it exists name a different
        set of activities than datasets made after.
      </p>
      <label>
        What is it called?
        <input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Water the plants" />
      </label>
      <label>
        What kind of thing is it?
        <select value={category} onChange={(event) => setCategory(event.target.value)}>
          {CATEGORY_ORDER.map((item) => (
            <option key={item} value={item}>{CATEGORY_LABELS[item] ?? item}</option>
          ))}
        </select>
      </label>
      <label>
        Where does it happen?
        <select value={room} onChange={(event) => setRoom(event.target.value)}>
          {rooms.map((item) => (
            <option key={item} value={item}>{item.replace(/_/g, " ")}</option>
          ))}
        </select>
      </label>
      <div className="button-row">
        <button className="button" onClick={create} disabled={!label.trim()}>Create</button>
        <button className="button secondary" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </div>
  );
}

function ActivityDetail({
  pack,
  intent,
  onEdit,
  onSelect,
}: {
  pack: VocabularyPack;
  intent: VocabularyIntent;
  onEdit: (pack: VocabularyPack) => void;
  onSelect: (id: string) => void;
}) {
  const steps = draft.actionNodes(intent.processModel);
  const linear = draft.isLinear(intent.processModel);
  const rooms = useMemo(
    () => [...new Set(pack.intents.map((item) => item.defaultLocation))].sort(),
    [pack.intents],
  );

  return (
    <section className="vocab-detail surface">
      <header className="vocab-detail-head">
        <div>
          <input
            className="vocab-title-input"
            value={intent.label}
            onChange={(event) => onEdit(draft.updateIntentMeta(pack, intent.intentId, { label: event.target.value }))}
            aria-label="Activity name"
          />
          <code className="vocab-id">{intent.intentId}</code>
        </div>
        <ConfirmAction
          label="Remove the activity"
          title={`Remove “${intent.label}”?`}
          consequence="Its steps go with it, and the ground-truth labels a new dataset carries will no longer include it. Datasets already generated keep it."
          onConfirm={() => {
            onEdit(draft.removeIntent(pack, intent.intentId));
            onSelect(pack.intents.find((item) => item.intentId !== intent.intentId)?.intentId ?? "");
          }}
        />
      </header>

      <div className="vocab-facts">
        <label>
          Happens in
          <select
            value={intent.defaultLocation}
            onChange={(event) => onEdit(draft.updateIntentMeta(pack, intent.intentId, { defaultLocation: event.target.value }))}
          >
            {rooms.map((item) => (
              <option key={item} value={item}>{item.replace(/_/g, " ")}</option>
            ))}
          </select>
        </label>
        <label>
          Kind
          <select
            value={intent.category}
            onChange={(event) => onEdit(draft.updateIntentMeta(pack, intent.intentId, { category: event.target.value }))}
          >
            {CATEGORY_ORDER.map((item) => (
              <option key={item} value={item}>{CATEGORY_LABELS[item] ?? item}</option>
            ))}
          </select>
        </label>
        <p className="vocab-mapping">
          {intent.externalMappings.casas_aruba ? (
            <>Matches <strong>{intent.externalMappings.casas_aruba}</strong> in CASAS Aruba.</>
          ) : (
            <>No equivalent in CASAS Aruba — this activity exists only here.</>
          )}
        </p>
      </div>

      {!linear && (
        <p className="vocab-warning">
          <AlertTriangle size={15} aria-hidden="true" />
          <span>
            This activity branches, so its steps are shown but cannot be reordered here. Flattening
            a branch would change what the activity means.
          </span>
        </p>
      )}

      <ol className="vocab-steps">
        {steps.map((node, index) => (
          <StepRow
            key={`${node.nodeId}-${index}`}
            pack={pack}
            intent={intent}
            node={node}
            index={index}
            total={steps.length}
            editable={linear}
            onEdit={onEdit}
          />
        ))}
      </ol>

      {linear && <AddStep pack={pack} intentId={intent.intentId} at={steps.length} onEdit={onEdit} />}
    </section>
  );
}

function StepRow({
  pack,
  intent,
  node,
  index,
  total,
  editable,
  onEdit,
}: {
  pack: VocabularyPack;
  intent: VocabularyIntent;
  node: ProcessNode;
  index: number;
  total: number;
  editable: boolean;
  onEdit: (pack: VocabularyPack) => void;
}) {
  const [open, setOpen] = useState(false);
  const action = pack.actions.find((item) => item.definition.actionType === node.actionType);
  const evidence = stepEvidence(pack, node);
  const binding = stepBinding(pack, node);
  const roles = useMemo(() => draft.knownRoles(pack), [pack]);

  return (
    <li className={`vocab-step ${evidence[0]?.kind === "presence" ? "is-unseen" : ""}`}>
      <span className="vocab-step-number">{index + 1}</span>
      <div className="vocab-step-body">
        <button className="vocab-step-phrase" onClick={() => setOpen(!open)} aria-expanded={open}>
          {stepPhrase(node)}
        </button>
        <div className="vocab-step-meta">
          <code>{stepCall(node)}</code>
          {binding.role && binding.types.length > 0 && (
            <span className="chip chip-object">{binding.types.join(" / ")}</span>
          )}
          {binding.role && binding.types.length === 0 && (
            <span className="chip chip-gap">nothing answers “{binding.role}”</span>
          )}
          {evidence.map((item) => (
            <span key={item.kind} className={`chip chip-${item.kind}`}>{item.label}</span>
          ))}
          <span className="vocab-step-timing">{stepTiming(action, node)}</span>
        </div>

        {open && (
          <div className="vocab-step-editor form-stack">
            {Object.entries(node.arguments).map(([name, argument]) => (
              <label key={name}>
                {name}
                {argument.source === "literal" ? (
                  <input
                    list={`roles-${intent.intentId}`}
                    value={String(argument.value ?? "")}
                    disabled={!editable}
                    onChange={(event) =>
                      onEdit(draft.setStepArgument(pack, intent.intentId, index, name, event.target.value))
                    }
                  />
                ) : (
                  <input value={`decided per activity (${argument.source})`} readOnly />
                )}
              </label>
            ))}
            {action?.gestureSeconds === null && (
              <label>
                Share of the activity’s time
                <input
                  type="number"
                  min={0.1}
                  step={0.1}
                  value={node.durationWeight ?? 1}
                  disabled={!editable}
                  onChange={(event) =>
                    onEdit(draft.setStepWeight(pack, intent.intentId, index, Number(event.target.value)))
                  }
                />
              </label>
            )}
            <datalist id={`roles-${intent.intentId}`}>
              {roles.map((role) => <option key={role} value={role} />)}
            </datalist>
          </div>
        )}
      </div>

      {editable && (
        <div className="vocab-step-controls">
          <button
            className="icon-button"
            aria-label="Move earlier"
            disabled={index === 0}
            onClick={() => onEdit(draft.moveStep(pack, intent.intentId, index, -1))}
          >
            <ArrowUp size={15} />
          </button>
          <button
            className="icon-button"
            aria-label="Move later"
            disabled={index === total - 1}
            onClick={() => onEdit(draft.moveStep(pack, intent.intentId, index, 1))}
          >
            <ArrowDown size={15} />
          </button>
          <button
            className="icon-button"
            aria-label="Remove this step"
            disabled={total <= 1}
            onClick={() => onEdit(draft.removeStep(pack, intent.intentId, index))}
          >
            <Trash2 size={15} />
          </button>
        </div>
      )}
    </li>
  );
}

function AddStep({
  pack,
  intentId,
  at,
  onEdit,
}: {
  pack: VocabularyPack;
  intentId: string;
  at: number;
  onEdit: (pack: VocabularyPack) => void;
}) {
  const [actionType, setActionType] = useState("");
  const sorted = useMemo(
    () => [...pack.actions].sort((a, b) => a.definition.actionType.localeCompare(b.definition.actionType)),
    [pack.actions],
  );
  return (
    <div className="vocab-add-step">
      <select value={actionType} onChange={(event) => setActionType(event.target.value)} aria-label="Action to add">
        <option value="">Add a step…</option>
        {sorted.map((item) => (
          <option key={item.definition.actionType} value={item.definition.actionType}>
            {item.definition.actionType}
          </option>
        ))}
      </select>
      <button
        className="button secondary"
        disabled={!actionType}
        onClick={() => {
          const action = pack.actions.find((item) => item.definition.actionType === actionType);
          if (action) onEdit(draft.insertStep(pack, intentId, at, action));
          setActionType("");
        }}
      >
        <ArrowRight size={15} /> Add to the end
      </button>
    </div>
  );
}
