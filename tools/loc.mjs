// Size and comment metrics computed with the TypeScript parser (JSX-aware).
// A line is a *code line* if it holds any non-whitespace character outside a
// comment, and a *comment line* if it holds any comment text (SonarQube's
// definitions).  Comment density = comment / (code + comment), as in Sonar.
//
// usage: node /tools/loc.mjs <files.json> <out.json>     (cwd = repository root)
import { readFileSync, writeFileSync } from "node:fs";
import ts from "typescript";

const [filesJson, outJson] = process.argv.slice(2);
const inv = JSON.parse(readFileSync(filesJson, "utf8"));

function measure(file) {
  const text = readFileSync(file, "utf8");
  const kind = file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
  const ranges = new Map();
  const grab = (list) => list && list.forEach((c) => ranges.set(c.pos, c));
  const visit = (node) => {
    grab(ts.getLeadingCommentRanges(text, node.pos));
    grab(ts.getTrailingCommentRanges(text, node.end));
    ts.forEachChild(node, visit);
  };
  visit(sf);
  grab(ts.getLeadingCommentRanges(text, sf.endOfFileToken.pos));

  const inComment = new Uint8Array(text.length);
  for (const c of ranges.values()) inComment.fill(1, c.pos, c.end);
  let code = 0, comment = 0, blank = 0, lines = 0;
  let start = 0;
  while (start <= text.length) {
    let end = text.indexOf("\n", start);
    if (end === -1) end = text.length;
    let hasCode = false, hasComment = false;
    for (let i = start; i < end; i++) {
      const ch = text.charCodeAt(i);
      if (ch === 32 || ch === 9 || ch === 13) continue;
      if (inComment[i]) hasComment = true; else hasCode = true;
    }
    lines++;
    if (hasCode) code++;
    if (hasComment) comment++;
    if (!hasCode && !hasComment) blank++;
    if (end === text.length) break;
    start = end + 1;
  }
  return { lines, code, comment, blank };
}

const out = { prod: { files: 0, lines: 0, code: 0, comment: 0, blank: 0 },
              test: { files: 0, lines: 0, code: 0, comment: 0, blank: 0 } };
for (const k of ["prod", "test"]) {
  for (const f of inv[k]) {
    const m = measure(f);
    out[k].files++;
    for (const key of ["lines", "code", "comment", "blank"]) out[k][key] += m[key];
  }
}
writeFileSync(outJson, JSON.stringify(out));
console.log(JSON.stringify(out));
