import { afterEach, describe, expect, it, vi } from "vitest";
import { buildPreviewPage, collectStyles, downloadPreviewPage, exportFileName, staticMarkup } from "../horizon/export";

function fragment(html: string): Element {
  const host = document.createElement("div");
  host.innerHTML = html;
  document.body.append(host);
  return host.firstElementChild as Element;
}

afterEach(() => {
  document.body.innerHTML = "";
  document.head.innerHTML = "";
  vi.restoreAllMocks();
});

describe("what the exported page is made of", () => {
  it("takes the section as it stands, without the controls that only work in the application", () => {
    const node = fragment(`<section class="horizon-preview"><h2>A horizon</h2><div class="horizon-toggle"><button>Hide</button><button>Import</button></div><p>Kept</p></section>`);
    const markup = staticMarkup(node);
    expect(markup).toContain("A horizon");
    expect(markup).toContain("Kept");
    expect(markup).not.toContain("horizon-toggle");
    expect(markup).not.toContain("<button");
  });

  it("leaves the live document untouched while doing it", () => {
    const node = fragment(`<section class="horizon-preview"><div class="horizon-toggle"><button>Hide</button></div></section>`);
    staticMarkup(node);
    expect(node.querySelector("button")).not.toBeNull();
  });

  it("carries the rules that drew the page and drops everything reaching off it", () => {
    const style = document.createElement("style");
    style.textContent = `
      :root { --teal: #087; }
      @font-face { font-family: "Source Sans 3 Variable"; src: url(/assets/source-sans.woff2); }
      .brand { background-image: url(/assets/logo.svg); }
      .horizon-band { border-radius: 4px; }
    `;
    document.head.append(style);
    const css = collectStyles(document);
    expect(css).toContain("--teal");
    expect(css).toContain("horizon-band");
    expect(css).not.toContain("@font-face");
    expect(css).not.toContain("url(");
  });

  it("skips a stylesheet it is not allowed to read rather than failing the export", () => {
    const unreadable = {
      get cssRules(): CSSRule[] { throw new DOMException("cross-origin", "SecurityError"); },
    } as unknown as CSSStyleSheet;
    const doc = { styleSheets: [unreadable] } as unknown as Document;
    expect(collectStyles(doc)).toBe("");
  });
});

describe("the page itself", () => {
  const base = {
    markup: `<section class="horizon-preview">the picture</section>`,
    css: ".horizon-band { color: red; }",
    title: "Giulia Ferri — orizzonte domestico 12 mesi",
    fileName: "giulia.json",
    theme: "light" as const,
    drawnAt: new Date("2026-08-26T09:30:00Z"),
  };

  it("reaches nothing outside itself and runs nothing", () => {
    const page = buildPreviewPage({ ...base, source: "{}" });
    expect(page).not.toContain("<script");
    expect(page).not.toMatch(/<link\b/);
    expect(page).not.toContain("url(");
  });

  it("says what it is, where it came from and that nothing was simulated", () => {
    const page = buildPreviewPage({ ...base, source: "{}" });
    expect(page).toContain("<title>Giulia Ferri — orizzonte domestico 12 mesi</title>");
    expect(page).toContain("giulia.json");
    expect(page).toContain("2026-08-26 09:30 UTC");
    expect(page).toContain("Nothing here was simulated");
    expect(page).toContain("the picture");
  });

  it("keeps the theme the reader was looking at", () => {
    expect(buildPreviewPage({ ...base, theme: "dark" })).toContain('data-theme="dark"');
    expect(buildPreviewPage(base)).toContain('data-theme="light"');
  });

  it("paints the ground on the element that carries the theme, not above it", () => {
    // The dark tokens are declared on the themed element. A body asking for --bg sits above them
    // and answers with the light one, which showed as dark bands on a white page.
    const page = buildPreviewPage({ ...base, theme: "dark" });
    expect(page).toMatch(/\.app-shell \{[^}]*background: var\(--bg\)/);
    expect(page).not.toMatch(/body \{[^}]*background:/);
  });

  it("puts the whole page inside one landmark, as a page read on its own must be", () => {
    const page = buildPreviewPage(base);
    expect(page).toContain('<main class="app-shell"');
    expect(page).toContain("</main>");
  });

  it("embeds the source without letting it break out of the page", () => {
    const page = buildPreviewPage({ ...base, source: `{"note": "</pre><script>alert(1)</script>"}` });
    expect(page).not.toContain("<script>alert");
    expect(page).toContain("&lt;/pre&gt;");
  });

  it("says so plainly when the source could not be embedded", () => {
    expect(buildPreviewPage(base)).toContain("could not be read a second time");
  });

  it("names the file after the one it was drawn from", () => {
    expect(exportFileName("giulia_ferri_12_mesi_fixed_v3.json")).toBe("giulia_ferri_12_mesi_fixed_v3-horizon.html");
    expect(exportFileName("outline (2).JSON")).toBe("outline_2-horizon.html");
    expect(exportFileName(".json")).toBe("horizon.html");
  });
});

describe("handing the page to the browser", () => {
  // jsdom's Blob predates `text()`, so the bytes come back the way the platform used to give them.
  function readBlob(blob: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(blob);
    });
  }

  function sourceFile(text: string): File {
    const file = new File([text], "giulia.json", { type: "application/json" });
    Object.defineProperty(file, "text", { value: () => Promise.resolve(text) });
    return file;
  }

  it("downloads it under a name derived from the chosen file", async () => {
    const node = fragment(`<section class="horizon-preview">the picture</section>`);
    const clicked: Array<{ download: string; href: string }> = [];
    const create = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const element = create(tag);
      if (tag === "a") element.addEventListener("click", () => clicked.push({ download: (element as HTMLAnchorElement).download, href: (element as HTMLAnchorElement).href }));
      return element;
    });
    await downloadPreviewPage(node, { title: "A horizon", fileName: "giulia.json", theme: "light", sourceFile: sourceFile("{}") });
    expect(clicked).toHaveLength(1);
    expect(clicked[0].download).toBe("giulia-horizon.html");
    expect(document.querySelector("a")).toBeNull();
  });

  it("still produces the page when the chosen file can no longer be read", async () => {
    // The file is chosen once and read again only here. A memory stick pulled out between the two
    // must cost the reader the embedded source, not the export.
    const node = fragment(`<section class="horizon-preview">the picture</section>`);
    const unreadable = new File(["{}"], "gone.json");
    Object.defineProperty(unreadable, "text", { value: () => Promise.reject(new Error("the file moved")) });
    let blob: Blob | undefined;
    vi.spyOn(URL, "createObjectURL").mockImplementation((value: Blob | MediaSource) => {
      blob = value as Blob;
      return "blob:test";
    });
    await downloadPreviewPage(node, { title: "A horizon", fileName: "gone.json", theme: "light", sourceFile: unreadable });
    const page = await readBlob(blob!);
    expect(page).toContain("the picture");
    expect(page).toContain("could not be read a second time");
  });
});
