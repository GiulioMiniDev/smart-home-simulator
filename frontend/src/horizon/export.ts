/**
 * The horizon preview as one file you can keep.
 *
 * Same doctrine as the resident profile page it sits beside: no script, no external reference, so
 * it survives being emailed, committed beside a thesis chapter or opened from a memory stick eight
 * years from now. The difference is when it can be made — this one is drawn before anything is
 * imported, so a horizon the server would refuse can still be exported, looked at and argued about
 * without expanding a single day.
 *
 * The page is not re-rendered from the reading. It is the rendered section itself, lifted out of
 * the document with the stylesheet that drew it, because a second renderer for the same picture is
 * a second picture waiting to disagree with the first. The two controls that only mean something
 * inside the application — the toggle and the import button — are the only things removed.
 *
 * The file it was drawn from travels with it, collapsed. That is what makes the export answer a
 * question on its own: this is what the model wrote, and this is what it looks like.
 */

/** Long enough that a large page has started downloading before the URL stops resolving. */
const RELEASE_DOWNLOAD_AFTER_MS = 60_000;

function escapeHtml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/**
 * Every rule the application drew this page with, minus anything that reaches off the page.
 *
 * `@font-face` and any rule carrying a `url(` would leave the exported file pointing at assets
 * that exist only while the workspace is running — a broken reference in the one artefact whose
 * whole point is not to have any. The font stacks keep their fallbacks, so the page still reads.
 */
export function collectStyles(doc: Document): string {
  const parts: string[] = [];
  for (const sheet of Array.from(doc.styleSheets)) {
    let rules: CSSRule[];
    try {
      rules = Array.from(sheet.cssRules);
    } catch {
      // A stylesheet from another origin. It cannot have styled this page's own classes.
      continue;
    }
    for (const rule of rules) {
      const text = rule.cssText;
      if (text.startsWith("@font-face") || text.includes("url(")) continue;
      parts.push(text);
    }
  }
  return parts.join("\n");
}

/**
 * The section as it stands on screen, minus the controls that only work inside the application.
 *
 * A button in a static page is a promise the page cannot keep, and the reader would find that out
 * by clicking it.
 */
export function staticMarkup(node: Element): string {
  const clone = node.cloneNode(true) as Element;
  for (const control of Array.from(clone.querySelectorAll(".horizon-toggle, button"))) control.remove();
  return clone.outerHTML;
}

export interface PreviewPageOptions {
  markup: string;
  css: string;
  title: string;
  fileName: string;
  theme: "light" | "dark";
  drawnAt: Date;
  /** The document the picture was drawn from, verbatim. Omitted when it could not be read. */
  source?: string;
}

export function buildPreviewPage(options: PreviewPageOptions): string {
  const { markup, css, title, fileName, theme, drawnAt, source } = options;
  const stamp = drawnAt.toISOString().replace("T", " ").slice(0, 16);
  const embedded = source
    ? `<details class="export-source"><summary>The file this was drawn from — ${escapeHtml(fileName)}</summary><pre>${escapeHtml(source)}</pre></details>`
    : `<p class="export-note">The file this was drawn from is not embedded: it could not be read a second time.</p>`;
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)}</title>
<style>${css}
/* The application's shell is a two-column grid around a sidebar that does not exist here. The
   ground is painted on the shell rather than on the body, because the dark tokens are defined on
   the shell: a body asking for --bg is above them and would answer with the light one. */
body { margin: 0; }
.app-shell { display: block; min-height: 100vh; padding: 1.5rem; background: var(--bg); color: var(--text); }
.export-head { max-width: 980px; margin: 0 auto .9rem; }
.export-head h1 { margin: 0 0 .35rem; }
.export-head p { margin: 0; font-size: .85rem; color: var(--text-soft); }
.horizon-preview { max-width: 980px; margin: 0 auto; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); }
.export-source, .export-note, .export-foot { max-width: 980px; margin: 1rem auto 0; font-size: .82rem; color: var(--text-soft); }
.export-source summary { cursor: pointer; padding: .5rem .7rem; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); }
.export-source pre { overflow-x: auto; margin: .5rem 0 0; padding: .8rem; border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); font-size: .74rem; line-height: 1.45; }
.export-foot { padding-top: .8rem; border-top: 1px solid var(--line); }
@media print { .app-shell { padding: 0; } .export-source { display: none; } }
</style></head>
<body><main class="app-shell" data-theme="${theme}">
<header class="export-head"><h1>${escapeHtml(title)}</h1>
<p>Drawn from <strong>${escapeHtml(fileName)}</strong> on ${stamp} UTC, before anything was imported. Nothing here was simulated: this is the structure the file describes, not a run of it.</p></header>
${markup}
${embedded}
<p class="export-foot">Produced by the smart-home simulator workspace. The picture and the file above are the whole of it — this page carries no script and reaches nothing outside itself.</p>
</main></body></html>`;
}

/** `giulia.json` becomes `giulia-horizon.html`, beside the dataset naming the application uses. */
export function exportFileName(fileName: string): string {
  const stem = fileName
    .replace(/\.json$/i, "")
    .replace(/[^\w.-]+/g, "_")
    .replace(/^[_.-]+|[_.-]+$/g, "");
  return stem ? `${stem}-horizon.html` : "horizon.html";
}

export async function downloadPreviewPage(
  node: Element,
  options: { title: string; fileName: string; theme: "light" | "dark"; sourceFile?: File; doc?: Document },
): Promise<void> {
  const doc = options.doc ?? node.ownerDocument;
  let source: string | undefined;
  try {
    source = await options.sourceFile?.text();
  } catch {
    source = undefined;
  }
  const page = buildPreviewPage({
    markup: staticMarkup(node),
    css: collectStyles(doc),
    title: options.title,
    fileName: options.fileName,
    theme: options.theme,
    drawnAt: new Date(),
    source,
  });
  const url = URL.createObjectURL(new Blob([page], { type: "text/html;charset=utf-8" }));
  const anchor = doc.createElement("a");
  anchor.href = url;
  anchor.download = exportFileName(options.fileName);
  doc.body.append(anchor);
  anchor.click();
  anchor.remove();
  // Released late for the same reason the dataset download releases late: revoking on the next
  // line kills a large download that has been asked for but not yet started reading.
  window.setTimeout(() => URL.revokeObjectURL(url), RELEASE_DOWNLOAD_AFTER_MS);
}
