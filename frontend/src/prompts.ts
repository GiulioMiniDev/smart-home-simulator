import advancedPrompt from "../../prompts/generate-simulation-inputs-1.2.0.md?raw";
import simplifiedPrompt from "../../prompts/generate-simulation-inputs-1.2.2-simplified.md?raw";

export const authoringPrompts = {
  simplified: {
    version: "generate-simulation-inputs-1.2.2-simplified",
    text: simplifiedPrompt,
  },
  advanced: {
    version: "generate-simulation-inputs-1.2.0",
    text: advancedPrompt,
  },
} as const;
