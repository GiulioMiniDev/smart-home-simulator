/**
 * Why the server refused an authoring document, as a sentence and a list a researcher can act on.
 *
 * An import is refused in one of three shapes, one per gate. The outline gate returns a generic
 * sentence and, beside it, the schema errors with the path each one sits at; the expansion gate
 * returns one sentence joining every problem with ` | `; the bundle gate returns issues. Showing
 * only the sentence, which is what the page used to do, told the researcher that a file was wrong
 * and nothing about where — on a two-person month, two midnight-crossing windows buried in 1 400
 * lines.
 */

export type ImportIssue = { code?: string; path?: string; message: string; severity?: string };

/** One schema error as the outline gate reports it: pydantic's `errors()`, without the input. */
export interface OutlineErrorDetail {
  loc?: Array<string | number>;
  msg?: string;
  type?: string;
}

export interface ImportRefusal {
  valid: boolean;
  stage?: string;
  message?: string;
  details?: OutlineErrorDetail[];
  issues?: ImportIssue[];
}

export interface RefusalView {
  text: string;
  items: string[];
}

// The fields that name an entry, in the order an entry is most usefully called by. A path through
// `residents[0]` is read by nobody; `residents › giulia_ferri` is read by the person who wrote it.
const IDENTITY_FIELDS = [
  "residentId",
  "commitmentId",
  "recurringActivityId",
  "habitId",
  "phaseId",
  "eventId",
  "locationId",
  "resourceId",
  "processModelId",
  "bindingId",
  "nodeId",
  "externalPersonId",
];

function identityOf(value: unknown): string | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const record = value as Record<string, unknown>;
  for (const field of IDENTITY_FIELDS) {
    if (typeof record[field] === "string" && record[field]) return record[field] as string;
  }
  // A shared activity is named by the activity it wraps.
  return identityOf(record.activity);
}

/**
 * A schema location, walked through the document it was reported against.
 *
 * The walk is best-effort by design: pydantic may report a step the document does not contain
 * (a union branch, a model-level check), and the server may have lifted an older outline before
 * validating it. A step that cannot be followed is printed as it came, never dropped.
 */
export function readablePath(loc: Array<string | number>, document: unknown): string {
  let cursor: unknown = document;
  const steps: string[] = [];
  for (const step of loc) {
    const next = cursor !== null && typeof cursor === "object" ? (cursor as Record<string | number, unknown>)[step] : undefined;
    if (typeof step === "number") steps.push(identityOf(next) ?? `#${step + 1}`);
    else steps.push(step);
    cursor = next;
  }
  return steps.join(" › ");
}

function withoutPrefix(message: string): string {
  // Pydantic wraps every raised `ValueError` as "Value error, <the sentence we wrote>".
  return message.replace(/^Value error, /, "");
}

function unique(items: string[]): string[] {
  return [...new Set(items)];
}

function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

export function describeRefusal(result: ImportRefusal, document: unknown): RefusalView {
  if (result.details?.length) {
    const items = unique(result.details.map((detail) => {
      const where = detail.loc?.length ? readablePath(detail.loc, document) : "";
      const what = withoutPrefix(detail.msg ?? detail.type ?? "invalid value");
      return where ? `${where}: ${what}` : what;
    }));
    return { text: `${result.message ?? "The document is not valid."} ${plural(items.length, "problem")}:`, items };
  }
  if (result.stage === "expansion" && result.message) {
    const items = unique(result.message.split(" | ").map((item) => item.trim()).filter(Boolean));
    return { text: `The outline is valid, but it could not be expanded into days. ${plural(items.length, "problem")}:`, items };
  }
  if (result.issues?.length) {
    // Warnings travel beside the errors that refused the bundle; listed together, the one line
    // that matters is the hardest to find.
    const errors = result.issues.filter((issue) => issue.severity === "error");
    const shown = errors.length ? errors : result.issues;
    const items = unique(shown.map((issue) => {
      const context = [issue.code, issue.path].filter(Boolean).join(" · ");
      return context ? `${issue.message} (${context})` : issue.message;
    }));
    return { text: `The bundle was refused. ${plural(items.length, errors.length ? "error" : "issue")}:`, items };
  }
  return { text: result.message ?? "The import was refused without a reason.", items: [] };
}
