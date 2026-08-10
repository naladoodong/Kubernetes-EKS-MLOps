import { copyFile, cp, mkdir, rm, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const portfolioDir = fileURLToPath(new URL("..", import.meta.url));
const repositoryRoot = path.resolve(portfolioDir, "..");
const sourceDir = path.join(portfolioDir, "src");
const outputDir = path.join(portfolioDir, "dist");
const diagramOutputDir = path.join(outputDir, "assets", "diagrams");

const diagrams = [
  "diagram-01-overall-architecture.svg",
  "diagram-03-dataset-upload-processing-flow.svg",
  "diagram-04-training-model-publishing.svg",
  "diagram-05-model-deployment-inference-flow.svg",
  "diagram-06-rdb-schema.svg"
];

await rm(outputDir, { recursive: true, force: true });
await mkdir(outputDir, { recursive: true });
await cp(sourceDir, outputDir, { recursive: true });
await mkdir(diagramOutputDir, { recursive: true });

for (const diagram of diagrams) {
  await copyFile(
    path.join(repositoryRoot, "docs", "diagrams", diagram),
    path.join(diagramOutputDir, diagram)
  );
}

await copyFile(
  path.join(
    repositoryRoot,
    "docs",
    "architecture",
    "ArgMax_Mini_System_Architecture_and_Design_final.pdf"
  ),
  path.join(outputDir, "assets", "ArgMax_Mini_System_Architecture_and_Design.pdf")
);

await copyFile(
  path.join(
    repositoryRoot,
    "docs",
    "portfolio",
    "ArgMax_Mini_AWS_EKS_Architecture_Case_Study.pdf"
  ),
  path.join(outputDir, "assets", "ArgMax_Mini_AWS_EKS_Architecture_Case_Study.pdf")
);

await writeFile(path.join(outputDir, ".nojekyll"), "", "utf8");

console.log(`Built static portfolio in ${outputDir}`);
