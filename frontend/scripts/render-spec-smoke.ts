import { buildClientRequestDraft, validateRenderSpec } from "../src/renderSpec";

const drafts = [
  buildClientRequestDraft("Acme Holdings LLC", "payroll files", "2026-05-06"),
  buildClientRequestDraft("Greenway Consulting LLC", "signed extension approval", "2026-05-15"),
  buildClientRequestDraft("Icom Dental", "state apportionment details", "2026-05-01")
];

for (const spec of drafts) {
  const result = validateRenderSpec(spec);
  if (!result.ok) {
    throw new Error(`${spec.title} generated invalid render spec: ${result.errors.join("; ")}`);
  }
  const hasNextStep = spec.blocks.some((block) => block.type === "choice_set" && block.choices.length > 0);
  if (!hasNextStep) {
    throw new Error(`${spec.title} did not generate a concrete next step.`);
  }
}

console.log(`render-spec smoke passed: ${drafts.length} explicit draft surfaces validated`);
