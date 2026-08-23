import { useResource } from "../hooks";
import type { HomeModel, SensorModel } from "../types";
import { ReplayInspector } from "./ReplayInspector";
import { ReplayStage } from "./ReplayStage";
import { ReplayTimeline } from "./ReplayTimeline";
import { ReplayToolbar } from "./ReplayToolbar";
import { useReplayController } from "./useReplayController";

type ReplayModels = { homeModel?: HomeModel; sensorModel?: SensorModel };

/** A single controller projects the same authoritative instant into plan, evidence and timeline. */
export function ReplayWorkbench({ runId, oracleAvailable = false }: { runId: string; oracleAvailable?: boolean }) {
  const controller = useReplayController(runId, { oracleAvailable });
  const models = useResource<ReplayModels>(`/runs/${encodeURIComponent(runId)}/models`);
  const analysis = controller.filters.detailMode === "analysis";
  const prepared =
    controller.status === "blocked" ||
    Boolean(controller.events) ||
    Boolean(controller.error) ||
    controller.evidenceIncomplete ||
    Boolean(controller.windowNotice);
  return <section className="replay-workbench" data-mode={analysis ? "analysis" : "presentation"}>
    {prepared ? <ReplayToolbar controller={controller} oracleAvailable={oracleAvailable} /> : <p className="replay-preparing" role="status">Preparing replay timeline…</p>}
    {models.error && <p className="replay-request-error" role="alert">Replay models unavailable: {models.error.message}</p>}
    <div className="replay-analysis-stage">
      <ReplayStage controller={controller} models={models.data ?? {}} />
      {analysis && <ReplayInspector controller={controller} />}
    </div>
    <ReplayTimeline controller={controller} sensorModel={models.data?.sensorModel} />
  </section>;
}
