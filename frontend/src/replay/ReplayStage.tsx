import { PlanCanvas } from "../components";
import { dwellingRegionIds } from "../editor";
import type { HomeModel, ReplayEvent, ReplayEventWindow, ReplayFilters, ReplayFrame, ReplayOverlay, SensorModel } from "../types";

export interface ReplayStageController {
  frame?: ReplayFrame;
  events?: ReplayEventWindow;
  selectedEventId?: string;
  filters: Pick<ReplayFilters, "selectedResidentId">;
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

function replayOverlay(frame: ReplayFrame | undefined, movement: ReplayEvent | undefined, selectedResidentId: string | null | undefined): ReplayOverlay {
  // Frame order is normally deterministic, but IDs make markers stay with people even if a
  // transport implementation changes its array ordering between adjacent instants.
  const residents = [...(frame?.residents ?? [])]
    .sort((left, right) => (left.residentId ?? "").localeCompare(right.residentId ?? ""))
    .map((resident, index) => ({
      residentId: resident.residentId ?? `unidentified-${index + 1}`,
      label: displayLabel(resident.residentId),
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
    selectedResidentId: selectedResidentId ?? undefined,
  };
}

function residentState(item: ReplayOverlay["residents"][number]): string {
  const position = item.position
    ? `Position ${item.position.x}, ${item.position.y}${item.regionId ? ` in ${item.regionId}` : ""}`
    : "Position unknown";
  return `${item.label}: ${position}; ${item.executionState}.`;
}

/** Spatial projection of the exact replay frame, paired with an equivalent screen-reader list. */
export function ReplayStage({ controller, models }: { controller: ReplayStageController; models: ReplayStageModels }) {
  const movement = selectedMovement(controller.events, controller.selectedEventId);
  const overlay = replayOverlay(controller.frame, movement, controller.filters.selectedResidentId);
  const hasVisibleExternalTrajectory = !!models.homeModel
    && overlay.trajectory.length > 1
    && movement?.waypoints.some((waypoint) => !dwellingRegionIds(models.homeModel!).has(waypoint.regionId));

  return (
    <section className="replay-stage" aria-label="Replay spatial state">
      {models.homeModel ? (
        <PlanCanvas
          home={models.homeModel}
          sensors={models.sensorModel}
          replayOverlay={overlay}
          showExternalPlaces={hasVisibleExternalTrajectory}
        />
      ) : <p role="status">Home model unavailable</p>}
      <ol className="sr-only" aria-label="Replay resident states">
        {overlay.residents.map((resident) => <li key={resident.residentId}>{residentState(resident)}</li>)}
      </ol>
    </section>
  );
}
