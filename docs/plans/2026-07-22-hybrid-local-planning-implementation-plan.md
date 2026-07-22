# Hybrid local planning implementation plan

1. Define private versioned models for the planning case, weekly brief, daily proposal,
   generation configuration and memory checkpoint.
2. Add an optional OpenAI-compatible LM Studio client that requests strict JSON and
   exposes no dependency to simulation packages.
3. Build prompts from the planning case and the public activity catalog, persist every
   exchange, and generate one weekly brief followed by sequential daily proposals.
4. Materialize rough time bands and duration classes deterministically into Scenario
   1.0.0 activities, then invoke the existing validator and compiler without executing the
   plan.
5. Measure intra-plan diversity, support at most two explicit daily revisions, and persist
   the final planning-memory checkpoint.
6. Compare the accepted generated scenario with an optional hidden baseline only after
   generation has completed.
7. Expose the vertical slice through a dedicated CLI command and add a Tommaso planning
   case that contains no baseline daily activities.
8. Test transport failures, prompt isolation, materialization, compilation, diversity,
   comparison and CLI behavior; run lint and the complete test suite.
