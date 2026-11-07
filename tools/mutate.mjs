// Mutation-testing stage (StrykerJS).  Runs inside the container, after the
// project's own test suite passed.
//
// * Mutates a seeded random sample of production files (fixed line budget) so
//   that every repository gets a comparable, bounded amount of work.
// * Uses the native runner when the project's framework version is supported
//   (vitest >= 2, jest, mocha 7.2-12), otherwise / on failure falls back to the
//   framework-agnostic command runner (`<pm> test` per mutant).
//
// usage: node /tools/mutate.mjs <files.json> <pm> <out.json>   (cwd = repository root)
import { readFileSync, writeFileSync, existsSync, statSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";

const LINE_BUDGET = Number(process.env.MUTATE_LINE_BUDGET || 400);
const MAX_FILES = 10;
const TIME_LIMIT_MIN = Number(process.env.MUTATE_TIME_LIMIT_MIN || 20);
const [filesJson, pm, outJson] = process.argv.slice(2);
const cwd = process.cwd();
const inv = JSON.parse(readFileSync(filesJson, "utf8"));
const req = createRequire(path.join(cwd, "package.json"));
const pkgVersion = (name) => { try { return req(`${name}/package.json`).version; } catch { return null; } };
const major = (v) => (v ? Number(v.split(".")[0]) : 0);
const minor = (v) => (v ? Number(v.split(".")[1]) : 0);

// ---- deterministic sample of production files -----------------------------
function mulberry32(a) { return () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
const rand = mulberry32(479);
const candidates = inv.prod.filter((f) => !f.endsWith(".d.ts") && !/(^|\/)index\.tsx?$/.test(f))
  .map((f) => ({ f, lines: readFileSync(f, "utf8").split("\n").length }))
  .filter((x) => x.lines >= 10)
  .sort((a, b) => a.f.localeCompare(b.f));
for (let i = candidates.length - 1; i > 0; i--) { const j = Math.floor(rand() * (i + 1)); [candidates[i], candidates[j]] = [candidates[j], candidates[i]]; }
const sample = []; let budget = 0;
for (const c of candidates) {
  if (sample.length >= MAX_FILES || budget >= LINE_BUDGET) break;
  sample.push(c.f); budget += c.lines;
}

// ---- choose runner ---------------------------------------------------------
const vitest = pkgVersion("vitest"), jest = pkgVersion("jest"), mocha = pkgVersion("mocha");
const runners = [];
if (vitest && major(vitest) >= 2) runners.push("vitest");
else if (jest && major(jest) >= 27) runners.push("jest");
else if (mocha && (major(mocha) > 7 || (major(mocha) === 7 && minor(mocha) >= 2)) && major(mocha) < 13) runners.push("mocha");
runners.push("command");

// The command runner re-runs a command per mutant. When jest is installed, run jest itself: `test`
// scripts that chain type-checking or linting (e.g. `run-s test:*`) fail on Stryker's instrumented code.
const testCmd = jest ? "npx jest --ci"
  : ({ npm: "npm test", pnpm: "corepack pnpm test", yarn: "corepack yarn test" }[pm] || "npm test");

const result = { sample_files: sample, sample_lines: budget, framework_versions: { vitest, jest, mocha },
                 attempts: [], runner: null, status: "not-run" };
if (!sample.length) { result.status = "no-mutable-files"; writeFileSync(outJson, JSON.stringify(result)); process.exit(0); }

// Stryker's jest runner does not follow a root config that only lists `projects`; point it at the
// unit-test project config instead (first project named *unit*, else the first project).
let jestConfigFile = null;
for (const f of ["jest.config.js", "jest.config.mjs", "jest.config.cjs", "jest.config.ts"]) {
  if (!existsSync(f)) continue;
  const txt = readFileSync(f, "utf8");
  if (!/projects\s*:/.test(txt)) break;
  const refs = [...txt.matchAll(/['"](?:<rootDir>\/)?([\w./-]*jest[\w.-]*\.(?:c|m)?(?:js|ts))['"]/g)].map((m) => m[1]).filter(existsSync);
  jestConfigFile = refs.find((r) => /unit/i.test(r)) || refs[0] || null;
  break;
}

// StrykerJS is pre-installed in the image under /stryker with a *nested* layout, so copying the
// @stryker-mutator folder into the project brings all of Stryker's own dependencies with it and
// never re-resolves (or upgrades) the project's dependency tree.
const inst = spawnSync("bash", ["-c", "mkdir -p node_modules/@stryker-mutator && cp -a /stryker/node_modules/@stryker-mutator/. node_modules/@stryker-mutator/"],
                       { cwd, encoding: "utf8" });
if (inst.status !== 0) { result.status = "stryker-install-failed"; result.log = (inst.stderr || "").slice(-2000); writeFileSync(outJson, JSON.stringify(result)); process.exit(0); }

// Each runner is tried with Stryker's default `disableTypeChecks` (prepends `// @ts-nocheck` to all
// source files) and, if the initial test run then fails, again with the directive limited to the
// mutated files (some suites read their own sources as fixtures).
// A native runner whose project uses a custom test environment cannot collect per-test coverage;
// it is retried once with coverage analysis off before falling back to the command runner.
const plan = runners.flatMap((runner) => runner === "command"
  ? [{ runner, dtc: "default", cov: "off" }, { runner, dtc: "sample", cov: "off" }]
  : [{ runner, dtc: "default", cov: "perTest" }, { runner, dtc: "sample", cov: "perTest" }, { runner, dtc: "default", cov: "off" }]);
let lastCoverageFailure = false;
let lastInitialFailure = false;
for (const { runner, dtc, cov } of plan) {
  if (dtc === "sample" && !lastInitialFailure) continue;
  if (cov === "off" && runner !== "command" && !lastCoverageFailure) continue;
  const report = `/out/mutation-${runner}-${dtc}-${cov}.json`;
  const conf = {
    testRunner: runner, mutate: sample, reporters: ["json"], jsonReporter: { fileName: report },
    coverageAnalysis: cov, concurrency: Number(process.env.MUTATE_CONCURRENCY || 3),
    // the command runner re-runs the whole suite per mutant, so concurrent runs are much slower than the
    // dry run; a generous timeout keeps "Timeout" (counted as killed) for genuinely hanging mutants
    timeoutMS: runner === "command" ? 60000 : 10000, timeoutFactor: runner === "command" ? 3 : 1.5,
    tempDirName: ".stryker-tmp", cleanTempDir: true,
    // the container is disposable, so mutate in place: no sandbox copy, real node_modules (jest haste maps
    // ignore the symlinked node_modules of a sandbox)
    inPlace: true,
    ...(dtc === "sample" ? { disableTypeChecks: sample.length === 1 ? sample[0] : `{${sample.join(",")}}` } : {}),
    ...(cov === "perTest" ? { ignoreStatic: true } : {}),  // ignoreStatic requires perTest coverage
    ...(runner === "jest" && jestConfigFile ? { jest: { configFile: jestConfigFile } } : {}),
    plugins: ["@stryker-mutator/*"], ...(runner === "command" ? { commandRunner: { command: testCmd } } : {}),
  };
  writeFileSync("stryker.bench.json", JSON.stringify(conf, null, 2));
  const t0 = Date.now();
  const r = spawnSync("node", ["node_modules/@stryker-mutator/core/bin/stryker.js", "run", "stryker.bench.json", "--logLevel", "warn"],
    { cwd, encoding: "utf8", timeout: TIME_LIMIT_MIN * 60 * 1000, maxBuffer: 1 << 27, env: { ...process.env, CI: "true" } });
  const attempt = { runner, dtc, cov, exit: r.status, seconds: (Date.now() - t0) / 1000, timed_out: r.error?.code === "ETIMEDOUT",
                    log_tail: ((r.stdout || "") + (r.stderr || "")).replace(/^\s+at .*$/gm, "").slice(-2500) };
  result.attempts.push(attempt);
  lastInitialFailure = /failed tests in the initial test run/.test(attempt.log_tail);
  if (cov === "perTest") lastCoverageFailure = /coverage-analysis|Something went wrong in the initial test run/.test(attempt.log_tail);
  if (existsSync(report) && statSync(report).size > 0) {
    const rep = JSON.parse(readFileSync(report, "utf8"));
    const counts = {};
    for (const file of Object.values(rep.files || {}))
      for (const m of file.mutants || []) counts[m.status] = (counts[m.status] || 0) + 1;
    const killed = (counts.Killed || 0) + (counts.Timeout || 0);
    const valid = killed + (counts.Survived || 0) + (counts.NoCoverage || 0);
    const covered = killed + (counts.Survived || 0);
    Object.assign(result, { runner, disable_type_checks: dtc, coverage_analysis: cov, status: "ok", counts, mutants_valid: valid,
      mutation_score: valid ? killed / valid : null, mutation_score_covered: covered ? killed / covered : null });
    break;
  }
  result.status = attempt.timed_out ? "timeout" : "failed";
}
writeFileSync(outJson, JSON.stringify(result));
console.log(JSON.stringify({ ...result, attempts: result.attempts.map((a) => ({ ...a, log_tail: undefined })) }));
