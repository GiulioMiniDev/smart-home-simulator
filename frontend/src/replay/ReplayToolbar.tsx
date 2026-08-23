import type { ReplayController } from "./useReplayController";

const SPEEDS = [0.25, 0.5, 1, 2, 4, 8, 16, 32];

export function ReplayToolbar({ controller }: { controller: ReplayController }) {
  const ready = controller.status === "ready";
  const analysis = controller.filters.detailMode === "analysis";
  const oracle = controller.filters.visibilityMode === "oracle";
  const status = controller.status === "blocked"
    ? controller.verification && !controller.verification.matches
      ? "Replay digest did not match"
      : controller.error?.message ?? "Replay unavailable"
    : controller.status === "verifying" ? "Verifying replay…" : "Replay verified";

  return <header className="replay-toolbar">
    <div className="replay-toolbar-group" role="group" aria-label="Replay view">
      <button type="button" aria-pressed={!analysis} onClick={() => controller.updateFilters({ detailMode: "presentation" })}>Presentation</button>
      <button type="button" aria-pressed={analysis} onClick={() => controller.updateFilters({ detailMode: "analysis" })}>Analysis</button>
    </div>
    <div className="replay-toolbar-group" role="group" aria-label="Replay transport">
      <button type="button" aria-label="Previous event" disabled={!ready} onClick={() => controller.step(-1)}>Previous</button>
      <button type="button" disabled={!ready} onClick={() => controller.playing ? controller.pause() : controller.play()}>{controller.playing ? "Pause" : "Play"}</button>
      <button type="button" aria-label="Next event" disabled={!ready} onClick={() => controller.step(1)}>Next</button>
    </div>
    <label className="replay-speed">Speed
      <select aria-label="Playback speed" disabled={!ready} value={controller.filters.speed} onChange={(event) => controller.updateFilters({ speed: Number(event.target.value) })}>
        {SPEEDS.map((speed) => <option key={speed} value={speed}>{speed}×</option>)}
      </select>
    </label>
    <div className="replay-toolbar-group" role="group" aria-label="Evidence visibility">
      <button type="button" aria-pressed={!oracle} disabled={!ready} onClick={() => controller.updateFilters({ visibilityMode: "observable" })}>Observable</button>
      <button type="button" aria-pressed={oracle} disabled={!ready} onClick={() => controller.updateFilters({ visibilityMode: "oracle" })}>Oracle</button>
    </div>
    <output className={`replay-verification ${ready ? "is-verified" : ""}`} aria-live="polite">{status}</output>
  </header>;
}
