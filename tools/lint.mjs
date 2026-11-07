// Uniform ESLint pass (same rules, same versions, inline disables ignored) over
// every source file of one repository.  Also extracts per-function cyclomatic
// complexity (core `complexity` rule, max 0) and cognitive complexity
// (SonarSource's `sonarjs/cognitive-complexity`, threshold 0) as metrics.
//
// usage: node /tools/lint.mjs <files.json> <out.json>     (cwd = repository root)
import { readFileSync, writeFileSync } from "node:fs";
import { ESLint } from "eslint";
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import sonarjs from "eslint-plugin-sonarjs";
import globals from "globals";

const [filesJson, outJson] = process.argv.slice(2);
const inv = JSON.parse(readFileSync(filesJson, "utf8"));
const kind = new Map([...inv.prod.map((f) => [f, "prod"]), ...inv.test.map((f) => [f, "test"])]);

const METRIC_RULES = new Set(["complexity", "sonarjs/cognitive-complexity"]);
const config = [
  js.configs.recommended,
  ...tseslint.configs.recommended,
  sonarjs.configs.recommended,
  {
    files: ["**/*.{ts,tsx,mts,cts}"],
    languageOptions: {
      parser: tseslint.parser,
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: { ...globals.browser, ...globals.node, ...globals.jest, ...globals.mocha },
    },
    linterOptions: { reportUnusedDisableDirectives: "off" },
    rules: {
      complexity: ["warn", { max: 0 }],
      "sonarjs/cognitive-complexity": ["warn", 0],
    },
  },
];

const eslint = new ESLint({
  cwd: process.cwd(),
  overrideConfigFile: true,
  overrideConfig: config,
  allowInlineConfig: false,
  errorOnUnmatchedPattern: false,
  warnIgnored: false,
});

const all = [...inv.prod, ...inv.test];
const results = [];
for (let i = 0; i < all.length; i += 200) {
  results.push(...(await eslint.lintFiles(all.slice(i, i + 200))));
}
const meta = eslint.getRulesMetaForResults(results);

const out = {
  eslint_version: ESLint.version,
  files_linted: results.length,
  fatal_parse_errors: { prod: 0, test: 0 },
  violations: { prod: {}, test: {} },          // ruleId -> count
  rule_type: {},                               // ruleId -> problem | suggestion | layout
  cyclomatic: [],                              // per prod function
  cognitive: [],                               // per prod function (>= 1)
  functions_prod: 0,
};
const rel = (p) => p.slice(process.cwd().length + 1).replaceAll("\\", "/");
for (const r of results) {
  const k = kind.get(rel(r.filePath)) ?? "prod";
  for (const m of r.messages) {
    if (m.fatal) { out.fatal_parse_errors[k]++; continue; }
    if (!m.ruleId) continue;
    if (METRIC_RULES.has(m.ruleId)) {
      if (k !== "prod") continue;
      const n = Number((m.message.match(/complexity (?:of|from) (\d+)/i) || [])[1]);
      if (!Number.isFinite(n)) continue;
      if (m.ruleId === "complexity") { out.cyclomatic.push(n); out.functions_prod++; }
      else out.cognitive.push(n);
      // the Sonar default threshold (15) is still reported as a real violation
      if (m.ruleId === "sonarjs/cognitive-complexity" && n > 15)
        out.violations[k]["sonarjs/cognitive-complexity"] = (out.violations[k]["sonarjs/cognitive-complexity"] || 0) + 1;
      continue;
    }
    out.violations[k][m.ruleId] = (out.violations[k][m.ruleId] || 0) + 1;
    out.rule_type[m.ruleId] = meta[m.ruleId]?.type ?? "unknown";
  }
}
out.rule_type["sonarjs/cognitive-complexity"] = "suggestion";
writeFileSync(outJson, JSON.stringify(out));
console.log(`linted ${results.length} files`);
