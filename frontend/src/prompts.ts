import outlinePrompt from "../../prompts/generate-horizon-outline-1.3.0.md?raw";

// Only the outline prompt is offered. The two `generate-simulation-inputs` prompts asked one
// response for every day of the horizon, which degrades as the horizon grows: the share of distinct
// days fell from 1.00 over a week to 0.03 over eight months, where 244 days collapsed into seven
// templates. They stay in `prompts/` because the provenance of already-published exports names
// them, and a file that a record points at must remain readable.
export const authoringPrompts = {
  outline: {
    version: "generate-horizon-outline-1.3.0",
    text: outlinePrompt,
  },
} as const;
