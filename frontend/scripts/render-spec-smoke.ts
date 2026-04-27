import { buildFallbackRenderSpec, validateRenderSpec } from "../src/renderSpec";

const randomDemands = [
  "Show me which clients are blocked by missing payroll files",
  "帮我看看 Acme 上次为什么没交文件",
  "I need a quick note for Greenway before lunch",
  "这三个客户里面谁最危险",
  "Prepare a polite but firm follow-up for Icom Dental",
  "What changed after the California extension notice"
];

for (const demand of randomDemands) {
  const spec = buildFallbackRenderSpec(demand);
  const result = validateRenderSpec(spec);
  if (!result.ok) {
    throw new Error(`${demand} generated invalid render spec: ${result.errors.join("; ")}`);
  }
  const hasNextStep = spec.blocks.some((block) => block.type === "choice_set" && block.choices.length > 0);
  if (!hasNextStep) {
    throw new Error(`${demand} did not generate a concrete next step.`);
  }
}

console.log(`render-spec smoke passed: ${randomDemands.length} random demands generated useful constrained surfaces`);
