#!/usr/bin/env node
// Verifies the documentation rules from CONTRIBUTING.md:
//   1. Every relative Markdown link and image resolves to a file.
//   2. Every Mermaid block (``` or ~~~ fenced) renders with mermaid-cli.
//
// Usage: node scripts/check-docs.mjs [--no-mermaid]
// Requires Node 18+. Mermaid rendering needs `npx @mermaid-js/mermaid-cli`.

import { readdirSync, readFileSync, statSync, existsSync, mkdtempSync, writeFileSync } from "node:fs";
import { join, dirname, resolve, relative } from "node:path";
import { tmpdir } from "node:os";
import { spawnSync } from "node:child_process";

const root = resolve(dirname(new URL(import.meta.url).pathname), "..");
const skipMermaid = process.argv.includes("--no-mermaid");
const ignoreDirs = new Set([".git", "node_modules", "build", "target", "dist"]);

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    if (ignoreDirs.has(name)) continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (name.endsWith(".md")) out.push(full);
  }
  return out;
}

const files = walk(root);
let failures = 0;
const fail = (msg) => { failures++; console.error(`FAIL ${msg}`); };

// --- 1. Relative links ---------------------------------------------------
const linkRe = /!?\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g;
let linkCount = 0;
for (const file of files) {
  const text = readFileSync(file, "utf8");
  for (const m of text.matchAll(linkRe)) {
    const target = m[1];
    if (/^(https?:|mailto:|#)/.test(target)) continue;
    const path = target.split("#")[0];
    if (!path) continue;
    linkCount++;
    const resolved = resolve(dirname(file), path);
    if (!existsSync(resolved)) fail(`${relative(root, file)}: broken link -> ${target}`);
  }
}
console.log(`links: ${linkCount} relative links checked across ${files.length} files`);

// --- 2. Mermaid blocks ---------------------------------------------------
if (!skipMermaid) {
  const fenceRe = /^(`{3,}|~{3,})mermaid[^\n]*\n([\s\S]*?)\n\1[ \t]*$/gm;
  const tmp = mkdtempSync(join(tmpdir(), "talven-mermaid-"));
  let blocks = 0;
  for (const file of files) {
    const text = readFileSync(file, "utf8");
    let i = 0;
    for (const m of text.matchAll(fenceRe)) {
      i++; blocks++;
      const base = `${relative(root, file).replace(/[\/\\]/g, "__")}.${i}`;
      const input = join(tmp, `${base}.mmd`);
      writeFileSync(input, m[2]);
      const r = spawnSync("npx", ["--yes", "-p", "@mermaid-js/mermaid-cli", "mmdc", "-q", "-i", input, "-o", join(tmp, `${base}.svg`)], { encoding: "utf8" });
      if (r.status !== 0) fail(`${relative(root, file)}: mermaid block ${i} failed to render\n${(r.stderr || r.stdout).trim()}`);
    }
  }
  console.log(`mermaid: ${blocks} diagrams rendered`);
}

if (failures) { console.error(`\n${failures} problem(s) found`); process.exit(1); }
console.log("docs check passed");
