import { useResource } from "../hooks";
import type { HomeModel, SensorModel } from "../types";
import { ReplayInspector } from "./ReplayInspector";
import { ReplayStage } from "./ReplayStage";
import { ReplayTimeline } from "./ReplayTimeline";
import { ReplayToolbar, ReplayTransport } from "./ReplayToolbar";
import { useReplayController } from "./useReplayController";

type ReplayModels = { homeModel?: HomeModel; sensorModel?: SensorModel };

function displayResident(residentId: string | undefined, index: number, oracle: boolean): string {
  if (!oracle) return `Resident ${index + 1}`;
  return residentId?.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()) ?? "Resident identity unavailable";
}

function clock(value: string | undefined): string {
  const parsed = value ? new Date(value) : undefined;
  return !parsed || Number.isNaN(parsed.valueOf()) ? "Time unknown" : `${String(parsed.getUTCHours()).padStart(2, "0")}:${String(parsed.getUTCMinutes()).padStart(2, "0")}`;
}

function captionFor(controller: ReturnType<typeof useReplayController>) {
  const event = controller.events?.items.find((item) => item.eventId === controller.selectedEventId);
  const residents = controller.frame?.residents ?? [];
  const selectedResidentIndex = residents.findIndex((resident) => resident.residentId === controller.filters.selectedResidentId);
  const index = selectedResidentIndex >= 0 ? selectedResidentIndex : 0;
  const resident = residents[index];
  return {
    title: event?.label || "Evidence label unavailable",
    resident: displayResident(resident?.residentId, index, controller.filters.visibilityMode === "oracle"),
    region: resident?.regionId ?? "Region unknown",
    time: clock(controller.frame?.at),
  };
}

/** A single controller projects the same authoritative instant into plan, evidence and timeline. */
export function ReplayWorkbench({ runId, oracleAvailable = false }: { runId: string; oracleAvailable?: boolean }) {
  const controller = useReplayController(runId, { oracleAvailable });
  const models = useResource<ReplayModels>(`/runs/${encodeURIComponent(runId)}/models`);
  const analysis = controller.filters.detailMode === "analysis";
  const caption = captionFor(controller);
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
        <span><strong>Time</strong> {caption.time}</span><span><strong>Resident</strong> {caption.resident}</span><span><strong>Evidence</strong> {caption.title}</span>
      </div>
      <ReplayStage controller={controller} models={models.data ?? {}} presentation />
      <section className="replay-caption" aria-live="polite" aria-atomic="true">
        <p className="eyebrow">Current evidence</p>
        <h2>{caption.title}</h2>
        <p>{caption.resident} · {caption.region} · {caption.time}</p>
        <button type="button" className="button secondary" onClick={() => controller.updateFilters({ detailMode: "analysis" })}>Open evidence</button>
      </section>
      <ReplayTransport controller={controller} presentation />
    </div>}
  </section>;
}
