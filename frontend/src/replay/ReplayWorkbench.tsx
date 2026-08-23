import { useResource } from "../hooks";
import type { HomeModel, ReplayEvent, ReplayResidentFrame, SensorModel } from "../types";
import { ReplayInspector } from "./ReplayInspector";
import { activeMovements, residentMovementAssociations, waypointAtOrBefore } from "./replay-positioning";
import { ReplayStage } from "./ReplayStage";
import { ReplayTimeline } from "./ReplayTimeline";
import { ReplayToolbar, ReplayTransport } from "./ReplayToolbar";
import { useReplayController } from "./useReplayController";

type ReplayModels = { homeModel?: HomeModel; sensorModel?: SensorModel };

function displayResident(residentId: string): string {
  return residentId.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function clock(value: string | undefined): string {
  const parsed = value ? new Date(value) : undefined;
  return !parsed || Number.isNaN(parsed.valueOf()) ? "Time unknown" : `${String(parsed.getUTCHours()).padStart(2, "0")}:${String(parsed.getUTCMinutes()).padStart(2, "0")}`;
}

function simulatedDate(value: string | undefined): string {
  const parsed = value ? new Date(value) : undefined;
  return !parsed || Number.isNaN(parsed.valueOf()) ? "Date unavailable" : parsed.toISOString().slice(0, 10);
}

function eventResident(
  controller: ReturnType<typeof useReplayController>,
  event: ReplayEvent | undefined,
): { resident?: ReplayResidentFrame; index?: number; movement?: ReplayEvent } {
  const residents = controller.frame?.residents ?? [];
  const at = controller.frame ? Date.parse(controller.frame.at) : Number.NaN;
  const active = activeMovements(controller.frame, controller.events);
  const associations = residentMovementAssociations(
    residents,
    active,
    Number.isFinite(at) ? at : undefined,
    controller.filters.visibilityMode,
  );
  const selectedResidentIndex = controller.filters.selectedResidentId
    ? residents.findIndex((resident) => resident.residentId === controller.filters.selectedResidentId)
    : -1;
  if (selectedResidentIndex >= 0) return { resident: residents[selectedResidentIndex], index: selectedResidentIndex };

  if (controller.filters.visibilityMode === "oracle" && event?.actorId) {
    const index = residents.findIndex((resident) => resident.residentId === event.actorId);
    if (index >= 0) return {
      resident: residents[index],
      index,
      movement: event.kind === "movement" && associations[index]?.eventId === event.eventId ? associations[index] : undefined,
    };
  }

  if (event?.kind === "movement") {
    const index = associations.findIndex((movement) => movement?.eventId === event.eventId);
    if (index >= 0) return { resident: residents[index], index, movement: associations[index] };
  }
  return {};
}

function sensorRegion(sensorModel: SensorModel | undefined, sensorId: string | null | undefined): string | undefined {
  if (!sensorId) return undefined;
  const sensor = sensorModel?.sensors.find((candidate) => candidate.sensorId === sensorId);
  return sensor && typeof sensor.regionId === "string" ? sensor.regionId : undefined;
}

function activityIsCurrentAt(event: ReplayEvent | undefined, at: number): boolean {
  if (event?.kind !== "activity" || !event.label || !Number.isFinite(at)) return false;
  const startsAt = Date.parse(event.at);
  if (!Number.isFinite(startsAt) || at < startsAt) return false;
  if (event.end !== undefined && event.end !== null) {
    const endsAt = Date.parse(event.end);
    return Number.isFinite(endsAt) && at <= endsAt;
  }
  // An omitted end is current only when the event contract explicitly calls it active.
  return event.status === "active";
}

function currentActivity(controller: ReturnType<typeof useReplayController>, selected: ReplayEvent | undefined): string {
  const at = controller.frame ? Date.parse(controller.frame.at) : Number.NaN;
  const activity = activityIsCurrentAt(selected, at)
    ? selected
    : controller.events?.items.find((event) => activityIsCurrentAt(event, at));
  return activity?.label || "Activity unavailable";
}

function captionFor(controller: ReturnType<typeof useReplayController>, sensorModel: SensorModel | undefined) {
  const event = controller.events?.items.find((item) => item.eventId === controller.selectedEventId);
  const linked = eventResident(controller, event);
  const eventAt = event?.at;
  const waypointRegion = linked.movement && eventAt
    ? waypointAtOrBefore(linked.movement, Date.parse(eventAt))?.regionId
    : undefined;
  return {
    title: event?.label || "Evidence label unavailable",
    kind: event?.kind || "Event kind unavailable",
    resident: linked.resident
      ? controller.filters.visibilityMode === "oracle" && linked.resident.residentId
        ? displayResident(linked.resident.residentId)
        : `Resident ${(linked.index ?? 0) + 1}`
      : "Resident unavailable",
    region: waypointRegion ?? linked.resident?.regionId ?? sensorRegion(sensorModel, event?.sensorId) ?? "Region unavailable",
    time: clock(eventAt),
  };
}

/** A single controller projects the same authoritative instant into plan, evidence and timeline. */
export function ReplayWorkbench({ runId, oracleAvailable = false }: { runId: string; oracleAvailable?: boolean }) {
  const controller = useReplayController(runId, { oracleAvailable });
  const models = useResource<ReplayModels>(`/runs/${encodeURIComponent(runId)}/models`);
  const analysis = controller.filters.detailMode === "analysis";
  const caption = captionFor(controller, models.data?.sensorModel);
  const selectedEvent = controller.events?.items.find((item) => item.eventId === controller.selectedEventId);
  const activity = currentActivity(controller, selectedEvent);
  const prepared =
    controller.status === "blocked" ||
    Boolean(controller.events) ||
    Boolean(controller.error) ||
    controller.evidenceIncomplete ||
    controller.evidenceLoading ||
    Boolean(controller.windowNotice);
  return <section className="replay-workbench" data-mode={analysis ? "analysis" : "presentation"}>
    {prepared ? <ReplayToolbar controller={controller} oracleAvailable={oracleAvailable} compact={!analysis} /> : <p className="replay-preparing" role="status">Preparing replay timeline…</p>}
    {models.error && <p className="replay-request-error" role="alert">Replay models unavailable: {models.error.message}</p>}
    {!analysis && controller.error && <p className="replay-request-error" role="alert">Replay window unavailable: {controller.error.message}</p>}
    {analysis ? <>
      <div className="replay-analysis-stage">
        <ReplayStage controller={controller} models={models.data ?? {}} />
        <ReplayInspector controller={controller} />
      </div>
      <ReplayTimeline controller={controller} sensorModel={models.data?.sensorModel} />
    </> : <div className="replay-presentation-stage">
      <div className="replay-presentation-summary" aria-label="Current replay state">
        <span><strong>Simulated date</strong> {simulatedDate(controller.frame?.at)}</span>
        <span><strong>Current time</strong> {clock(controller.frame?.at)}</span>
        <span><strong>Resident</strong> {caption.resident}</span>
        <span><strong>Current activity</strong> {activity}</span>
      </div>
      <ReplayStage controller={controller} models={models.data ?? {}} presentation />
      <section className="replay-caption" aria-live="polite" aria-atomic="true">
        <p className="eyebrow">Current evidence</p>
        <h2>{caption.title}</h2>
        <p>{caption.kind} · {caption.time}</p>
        <p>{caption.resident} · {caption.region}</p>
        <button type="button" className="button secondary" onClick={() => controller.updateFilters({ detailMode: "analysis" })}>Open evidence</button>
      </section>
      <ReplayTransport controller={controller} presentation />
    </div>}
  </section>;
}
