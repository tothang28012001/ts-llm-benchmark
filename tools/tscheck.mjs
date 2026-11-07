// Compilation stage: runs the repository's *own* TypeScript compiler version
// (falls back to the pinned toolchain version) against its own tsconfig, and
// against every referenced sub-project when the root config is a solution file.
// Output is redirected to a throwaway directory so emit-related options never
// conflict.  Diagnostics are parsed into structured counts.
//
// usage: node /tools/tscheck.mjs <out.json>     (cwd = repository root)
import { writeFileSync, existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import path from "node:path";

const outJson = process.argv[2];
const cwd = process.cwd();
const req = createRequire(path.join(cwd, "package.json"));
let tscJs, source;
try { tscJs = req.resolve("typescript/bin/tsc"); source = "repository"; }
catch { tscJs = createRequire("/tools/package.json").resolve("typescript/bin/tsc"); source = "toolchain"; }
const tsVersion = createRequire(tscJs)("../package.json").version;
const ts = createRequire("/tools/package.json")("typescript");

function projects(cfgPath, seen = new Set()) {
  const abs = path.resolve(cfgPath);
  if (seen.has(abs)) return [];
  seen.add(abs);
  const { config } = ts.readConfigFile(abs, ts.sys.readFile);
  const refs = (config?.references || []).map((r) => {
    const p = path.resolve(path.dirname(abs), r.path);
    return existsSync(p) && !p.endsWith(".json") ? path.join(p, "tsconfig.json") : p;
  });
  const isSolution = Array.isArray(config?.files) && config.files.length === 0 && refs.length;
  return [...(isSolution ? [] : [abs]), ...refs.flatMap((r) => projects(r, seen))];
}

const re = /^(.+?)\((\d+),(\d+)\): error (TS\d+): (.*)$/;
const res = { ts_version: tsVersion, ts_source: source, projects: [], errors_total: 0,
              errors_in_project_files: 0, errors_in_dependencies: 0, global_errors: 0,
              by_code: {}, files_with_errors: 0, timed_out: false, samples: [] };
const files = new Set();
const checked = new Set();
projects("tsconfig.json").forEach((proj, i) => {
  const t0 = Date.now();
  const r = spawnSync("node", ["--max-old-space-size=6144", tscJs, "-p", proj, "--pretty", "false", "--listFiles",
                               "--outDir", `/tmp/tsc-out/${i}`],
                      { cwd, encoding: "utf8", timeout: 15 * 60 * 1000, maxBuffer: 1 << 28 });
  if (r.error?.code === "ETIMEDOUT") res.timed_out = true;
  let n = 0;
  for (const line of (r.stdout || "").split(/\r?\n/)) {
    if (line.startsWith("/") && !line.includes(": error TS")) {  // --listFiles entry
      if (!line.includes("/node_modules/")) checked.add(line.trim());
      continue;
    }
    const m = line.match(re);
    const g = !m && line.match(/^error (TS\d+): (.*)$/);
    if (!m && !g) continue;
    n++;
    const code = m ? m[4] : g[1];
    res.by_code[code] = (res.by_code[code] || 0) + 1;
    if (g) res.global_errors++;
    else if (m[1].includes("node_modules")) res.errors_in_dependencies++;
    else { res.errors_in_project_files++; files.add(m[1]); }
    if (res.samples.length < 25) res.samples.push(line.slice(0, 300));
  }
  res.errors_total += n;
  res.projects.push({ tsconfig: path.relative(cwd, proj), exit: r.status, errors: n, seconds: (Date.now() - t0) / 1000 });
});
res.files_with_errors = files.size;
res.project_files_checked = checked.size;
writeFileSync(outJson, JSON.stringify(res));
console.log(JSON.stringify({ ...res, samples: undefined }));
