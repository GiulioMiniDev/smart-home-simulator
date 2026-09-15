import outlinePrompt from "../../prompts/generate-horizon-outline-2.0.0.md?raw";

// 2.0.0 makes the subject of an outline a household rather than a person (ADR-026). A
// one-person case is a roster of one, so nothing about the single-resident flow changes for the
// researcher; 1.3.0 stays in `prompts/` because bundles record it in their provenance.
// Only the outline prompt is offered. The two `generate-simulation-inputs` prompts asked one
// response for every day of the horizon, which degrades as the horizon grows: the share of distinct
// days fell from 1.00 over a week to 0.03 over eight months, where 244 days collapsed into seven
// templates. They stay in `prompts/` because the provenance of already-published exports names
// them, and a file that a record points at must remain readable.
export const authoringPrompts = {
  outline: {
    version: "generate-horizon-outline-2.0.0",
    text: outlinePrompt,
  },
} as const;
