import { access, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const portfolioDir = fileURLToPath(new URL("..", import.meta.url));
const outputDir = path.join(portfolioDir, "dist");
const htmlPath = path.join(outputDir, "index.html");
const html = await readFile(htmlPath, "utf8");
const errors = [];

const ids = [...html.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]);
const duplicateIds = ids.filter((id, index) => ids.indexOf(id) !== index);
if (duplicateIds.length) {
  errors.push(`Duplicate IDs: ${[...new Set(duplicateIds)].join(", ")}`);
}

for (const match of html.matchAll(/href="#([^"]+)"/g)) {
  if (!ids.includes(match[1])) {
    errors.push(`Missing anchor target: #${match[1]}`);
  }
}

const localTargets = new Set();
for (const match of html.matchAll(/(?:href|src)="(\.\/[^"#?]+)(?:[?#][^"]*)?"/g)) {
  localTargets.add(decodeURIComponent(match[1].replace(/^\.\//, "")));
}

for (const target of localTargets) {
  try {
    await access(path.join(outputDir, target));
  } catch {
    errors.push(`Missing local asset: ${target}`);
  }
}

for (const match of html.matchAll(/<img\b([^>]+)>/g)) {
  const attributes = match[1];
  if (!/\salt="[^"]+"/.test(attributes)) {
    errors.push("Image missing non-empty alt text");
  }
}

for (const match of html.matchAll(/<a\b([^>]*target="_blank"[^>]*)>/g)) {
  if (!/\srel="[^"]*noreferrer[^"]*"/.test(match[1])) {
    errors.push("External target=_blank link missing rel=noreferrer");
  }
}

for (const required of [
  "<title>",
  'name="description"',
  'property="og:title"',
  'property="og:description"',
  'property="og:image"',
  'name="viewport"'
]) {
  if (!html.includes(required)) {
    errors.push(`Missing metadata marker: ${required}`);
  }
}

if (errors.length) {
  console.error(errors.join("\n"));
  process.exitCode = 1;
} else {
  console.log(`Validated ${ids.length} IDs, ${localTargets.size} local assets, anchors, image alternatives, external-link safety, and sharing metadata.`);
}
