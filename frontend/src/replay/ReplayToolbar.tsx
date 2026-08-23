import type { ReplayController } from "./useReplayController";

const SPEEDS = [0.25, 0.5, 1, 2, 4, 8, 16, 32];

function keyboardAction(action: () => void) {
  return (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); action(); }
  };
}

function CopyDigest({ label, digest }: { label: string; digest?: string | null }) {
  if (!digest) return <dd>Not available</dd>;
  return <dd><code>{digest}</code><button type="button" className="replay-copy-digest" aria-label={`Copy ${label}`} onClick={() => void navigator.clipboard?.writeText(digest)}>Copy</button></dd>;
}

export function ReplayToolbar({ controller, oracleAvailable = false }: { controller: ReplayController; oracleAvailable?: boolean }) {
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
      <button type="button" aria-label="Previous event" disabled={!ready} onClick={() => controller.step(-1)} onKeyDown={keyboardAction(() => controller.step(-1))}>Previous</button>
      <button type="button" disabled={!ready} onClick={() => controller.playing ? controller.pause() : controller.play()} onKeyDown={keyboardAction(() => controller.playing ? controller.pause() : controller.play())}>{controller.playing ? "Pause" : "Play"}</button>
      <button type="button" aria-label="Next event" disabled={!ready} onClick={() => controller.step(1)} onKeyDown={keyboardAction(() => controller.step(1))}>Next</button>
    </div>
    <label className="replay-speed">Speed
      <select aria-label="Playback speed" disabled={!ready} value={controller.filters.speed} onChange={(event) => controller.updateFilters({ speed: Number(event.target.value) })}>
        {SPEEDS.map((speed) => <option key={speed} value={speed}>{speed}×</option>)}
      </select>
    </label>
    <div className="replay-toolbar-group" role="group" aria-label="Evidence visibility">
      <button type="button" aria-pressed={!oracle} disabled={!ready} onClick={() => controller.updateFilters({ visibilityMode: "observable" })}>Observable</button>
      <button type="button" aria-pressed={oracle} disabled={!ready || !oracleAvailable} aria-describedby={!oracleAvailable ? "oracle-unavailable" : undefined} onClick={() => controller.updateFilters({ visibilityMode: "oracle" })}>Oracle</button>
    </div>
    <output className={`replay-verification ${ready ? "is-verified" : ""}`} aria-live="polite">{status}</output>
    {!oracleAvailable && <p id="oracle-unavailable" className="replay-oracle-unavailable">Oracle mapping unavailable for this run; observable evidence remains available.</p>}
    {controller.status === "blocked" && controller.verification && !controller.verification.matches && <dl className="replay-digest-details" aria-label="Semantic digest verification details">
      <div><dt>Expected semantic digest</dt><CopyDigest label="expected semantic digest" digest={controller.verification.expectedSemanticDigest} /></div>
      <div><dt>Actual semantic digest</dt><CopyDigest label="actual semantic digest" digest={controller.verification.actualSemanticDigest} /></div>
    </dl>}
  </header>;
}
