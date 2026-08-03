import outlinePrompt from "../../prompts/generate-horizon-outline-1.0.0.md?raw";
import advancedPrompt from "../../prompts/generate-simulation-inputs-1.3.0.md?raw";
import simplifiedPrompt from "../../prompts/generate-simulation-inputs-1.2.3-simplified.md?raw";

export const authoringPrompts = {
  simplified: {
    version: "generate-simulation-inputs-1.2.3-simplified",
    text: simplifiedPrompt,
  },
  advanced: {
    version: "generate-simulation-inputs-1.3.0",
    text: advancedPrompt,
  },
  // A different document, not a newer prompt: it returns a horizon outline that a deterministic
  // expander rolls into days. Its output is not importable as it stands, which is why the guide
  // presents it apart from the two above rather than beside them.
  outline: {
    version: "generate-horizon-outline-1.0.0",
    text: outlinePrompt,
  },
} as const;
