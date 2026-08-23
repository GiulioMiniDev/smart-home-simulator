import { PlanCanvas } from "../components";
import { dwellingRegionIds } from "../editor";
import type { HomeModel, ReplayEvent, ReplayEventWindow, ReplayFilters, ReplayFrame, ReplayOverlay, ReplayVisibilityMode, SensorModel } from "../types";

export interface ReplayStageController {
  frame?: ReplayFrame;
  events?: ReplayEventWindow;
  selectedEventId?: string;
  filters: Pick<ReplayFilters, "selectedResidentId"> & Partial<Pick<ReplayFilters, "visibilityMode">>;
}

export interface ReplayStageModels {
  homeModel?: HomeModel;
  sensorModel?: SensorModel;
}

function displayLabel(residentId: string | undefined): string {
  if (!residentId) return "Resident identity unavailable";
  return residentId.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function selectedMovement(events: ReplayEventWindow | undefined, selectedEventId: string | undefined): ReplayEvent | undefined {
  const selected = events?.items.find((event) => event.eventId === selectedEventId);
  return selected?.kind === "movement" ? selected : undefined;
}

function timestamp(value: string | null | undefined): number | undefined {
  if (!value) return undefined;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function visibleMovement(frame: ReplayFrame | undefined, movement: ReplayEvent | undefined): ReplayEvent | undefined {
  if (!frame || !movement || movement.waypoints.length < 2) return undefined;
  const at = timestamp(frame.at);
  const startsAt = timestamp(movement.at);
  const endsAt = movement.end === null || movement.end === undefined
    ? timestamp(movement.waypoints.at(-1)?.at)
    : timestamp(movement.end);
  const usableWaypoints = movement.waypoints.every((waypoint) =>
    timestamp(waypoint.at) !== undefined
    && Number.isFinite(waypoint.position.x)
    && Number.isFinite(waypoint.position.y),
  );
  if (!usableWaypoints || at === undefined || startsAt === undefined || endsAt === undefined || endsAt < startsAt) return undefined;
  return startsAt <= at && at <= endsAt ? movement : undefined;
}

function replayOverlay(
  frame: ReplayFrame | undefined,
  movement: ReplayEvent | undefined,
  selectedResidentId: string | null | undefined,
  visibilityMode: ReplayVisibilityMode | undefined,
): ReplayOverlay {
  const isOracle = visibilityMode === "oracle";
  // Frame order is normally deterministic, but IDs make markers stay with people even if a
  // transport implementation changes its array ordering between adjacent instants.
  const residents = [...(frame?.residents ?? [])]
    .sort((left, right) => (left.residentId ?? "").localeCompare(right.residentId ?? ""))
    .map((resident, index) => ({
      residentId: resident.residentId ?? `unidentified-${index + 1}`,
      label: isOracle ? displayLabel(resident.residentId) : `Resident ${index + 1}`,
      marker: String(index + 1),
      regionId: resident.regionId ?? undefined,
      position: resident.position ?? undefined,
      executionState: resident.executionState,
    }));
  return {
    residents,
    activeRegionIds: [...new Set([
      ...residents.flatMap((resident) => resident.regionId ? [resident.regionId] : []),
      ...(movement?.waypoints.map((waypoint) => waypoint.regionId) ?? []),
    ])],
    activeSensorIds: [...new Set((frame?.sensorStates ?? []).filter((sensor) => sensor.changed).map((sensor) => sensor.sensorId))],
    trajectory: movement?.waypoints.map((waypoint) => waypoint.position) ?? [],
    selectedResidentId: isOracle ? selectedResidentId ?? undefined : undefined,
  };
}

function residentState(item: ReplayOverlay["residents"][number], visibilityMode: ReplayVisibilityMode | undefined): string {
  const position = item.position
    ? `Position ${item.position.x}, ${item.position.y}${item.regionId ? ` in ${item.regionId}` : ""}`
    : "Position unknown";
  const identity = visibilityMode === "oracle" ? "" : "Identity unavailable; ";
  return `${item.label}: ${identity}${position}; ${item.executionState}.`;
}

function selectedEventState(event: ReplayEvent | undefined) {
  if (!event) return <p>No event selected.</p>;
  return (
    <dl>
      <div><dt>Label</dt><dd>{event.label || "Event label unavailable"}</dd></div>
      <div><dt>Kind</dt><dd>{event.kind}</dd></div>
      <div><dt>Status</dt><dd>{event.status ?? "Status unavailable"}</dd></div>
      <div><dt>Time</dt><dd>{event.at}</dd></div>
    </dl>
  );
}

function waypointState(waypoint: ReplayEvent["waypoints"][number], index: number): string {
  return `Step ${index + 1}: ${waypoint.regionId}; coordinates ${String(waypoint.position.x)}, ${String(waypoint.position.y)}; ${waypoint.traversalMode}; ${waypoint.at}.`;
}

/** Spatial projection of the exact replay frame, paired with an equivalent screen-reader list. */
export function ReplayStage({ controller, models }: { controller: ReplayStageController; models: ReplayStageModels }) {
  const selected = controller.events?.items.find((event) => event.eventId === controller.selectedEventId);
  const movement = visibleMovement(controller.frame, selectedMovement(controller.events, controller.selectedEventId));
  const overlay = replayOverlay(controller.frame, movement, controller.filters.selectedResidentId, controller.filters.visibilityMode);
  const hasVisibleExternalTrajectory = !!models.homeModel
    && overlay.trajectory.length > 1
    && movement?.waypoints.some((waypoint) => !dwellingRegionIds(models.homeModel!).has(waypoint.regionId));

  return (
    <section className="replay-stage">
      {models.homeModel ? (
        <PlanCanvas
          home={models.homeModel}
          sensors={models.sensorModel}
          replayOverlay={overlay}
          showExternalPlaces={hasVisibleExternalTrajectory}
        />
      ) : <p role="status">Home model unavailable</p>}
      <section className="sr-only" aria-labelledby="replay-spatial-state-heading">
        <h2 id="replay-spatial-state-heading">Replay spatial state</h2>
        <section>
          <h3>Residents</h3>
          {overlay.residents.length ? <ol>{overlay.residents.map((resident) => <li key={resident.residentId}>{residentState(resident, controller.filters.visibilityMode)}</li>)}</ol> : <p>No residents in the replay frame.</p>}
        </section>
        <section>
          <h3>Active regions</h3>
          {overlay.activeRegionIds.length ? <ul>{overlay.activeRegionIds.map((regionId) => <li key={regionId}>{regionId}</li>)}</ul> : <p>No active regions.</p>}
        </section>
        <section>
          <h3>Changed sensors</h3>
          {overlay.activeSensorIds.length ? <ul>{overlay.activeSensorIds.map((sensorId) => <li key={sensorId}>{sensorId}</li>)}</ul> : <p>No changed sensors.</p>}
        </section>
        <section>
          <h3>Trajectory</h3>
          {movement ? <ol aria-label="Active trajectory waypoints">{movement.waypoints.map((waypoint, index) => <li key={`${waypoint.at}-${index}`}>{waypointState(waypoint, index)}</li>)}</ol> : <p>No active trajectory.</p>}
        </section>
        <section>
          <h3>Selected event</h3>
          {selectedEventState(selected)}
        </section>
      </section>
    </section>
  );
}
