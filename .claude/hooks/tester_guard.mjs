#!/usr/bin/env node
// PreToolUse guard for the Tester subagent (wired in .claude/agents/tester.md).
// Keeps the Tester's tests independent of the implementation: it blocks Read of
// implementation files and Grep over implementation folders. Glob (file names
// only) is allowed. Bash (e.g. `cat backend/wall_analysis/scale.py`) is NOT covered.
//
// Input: the PreToolUse JSON on stdin. Exit 0 = allow, exit 2 = block (stderr
// is shown to the agent as the reason). No dependencies.

import path from "node:path";
import { fileURLToPath } from "node:url";

const APP = "mobile/ml-rock-climbing-app";
// Folders of implementation code. Read is also blocked for any backend .py
// outside backend/tests (see isImplementation), but Grep over a folder only
// checks this list, so every backend code folder must be named here.
const IMPL_DIRS = [
  "backend/api",
  "backend/coaching",
  "backend/wall_analysis",
  "backend/accuracy_checks",
  "backend/experiments",
  "backend/tests/load",
  `${APP}/app`,
  `${APP}/components`,
  `${APP}/hooks`,
  `${APP}/api`,
  `${APP}/utils`,
];
// Grep over these folders themselves (not their allowed subfolders) would
// search implementation code.
const GREP_BLOCKED_ROOTS = ["", "backend", "mobile", APP];

const MESSAGE =
  "Blocked by the tester guard: the Tester must not read implementation code, " +
  "so tests stay independent. Work from the issue's spec.md in docs/milestones/<version>/<n>-<slug>/ and " +
  "docs/architecture.md (public signatures and API contracts), plus reference data. " +
  "You may read backend/tests/** (except backend/tests/load), docs/** (except handover.md logs), assets/**, .claude/**, pyproject.toml and " +
  "the field-capture folders, and Glob for file names. For Grep, pass a path inside " +
  "one of those areas. backend/tests holds the load-test script, so grep it with " +
  'glob "test_*.py" (or "conftest.py"), or pass a single test file.';

// Lowercase, forward slashes, no trailing slash. Lowercase because the human
// runs Windows, where paths are case-insensitive.
function norm(p) {
  let s = String(p).replace(/\\/g, "/");
  // Git Bash writes d:/x as /d/x; map it back so the path is seen as inside the repo.
  if (process.platform === "win32") s = s.replace(/^\/([a-zA-Z])(\/|$)/, "$1:/");
  s = path.posix.normalize(s);
  if (s.length > 1 && s.endsWith("/")) s = s.slice(0, -1);
  return s.toLowerCase();
}

function isAbsolute(p) {
  return p.startsWith("/") || /^[a-z]:\//.test(p);
}

// Path relative to the repo root ("" for the root itself), or null when the
// path is outside the repo.
function relToRoot(p, root, cwd) {
  let s = norm(p);
  if (!isAbsolute(s)) s = norm(`${cwd}/${s}`);
  if (s === root) return "";
  if (s.startsWith(root + "/")) return s.slice(root.length + 1);
  return null;
}

function under(rel, dir) {
  return rel === dir || rel.startsWith(dir + "/");
}

// Handover logs describe the implementation (file paths, function names), so
// the Tester works from spec.md only. Matches docs/milestones/<v>/<issue>/handover.md,
// docs/milestones/<v>/completed/<issue>/handover.md, and the archived *handover*.md
// files in docs/features_deprecated/.
function isHandover(rel) {
  return (
    /^docs\/milestones\/[^/]+\/(completed\/)?[^/]+\/handover\.md$/.test(rel) ||
    /^docs\/features_deprecated\/[^/]*handover[^/]*\.md$/.test(rel)
  );
}

// Grep over a folder that holds handover logs would search them too.
function grepReachesHandover(rel) {
  if (rel === "docs" || rel === "docs/features_deprecated") return true;
  if (!under(rel, "docs/milestones")) return false;
  return !rel.endsWith(".md") || isHandover(rel);
}

function isImplementation(rel) {
  if (isHandover(rel)) return true;
  if (IMPL_DIRS.some((d) => under(rel, d))) return true;
  // Any backend Python file outside backend/tests/.
  if (rel.startsWith("backend/") && rel.endsWith(".py") && !under(rel, "backend/tests")) {
    return true;
  }
  return false;
}

function block() {
  process.stderr.write(MESSAGE + "\n");
  process.exit(2);
}

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (c) => (raw += c));
process.stdin.on("end", () => {
  let input;
  try {
    input = JSON.parse(raw);
  } catch {
    process.exit(0); // Not our input; don't break the session.
  }
  const tool = input.tool_name;
  const ti = input.tool_input || {};

  const scriptRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
  const root = norm(process.env.CLAUDE_PROJECT_DIR || scriptRoot);
  const cwd = norm(input.cwd || root);

  if (tool === "Read") {
    if (!ti.file_path) process.exit(0);
    const rel = relToRoot(ti.file_path, root, cwd);
    if (rel !== null && isImplementation(rel)) block();
    process.exit(0);
  }

  if (tool === "Grep") {
    const p = ti.path === undefined || ti.path === null || ti.path === "" ? "." : ti.path;
    const rel = relToRoot(p, root, cwd);
    if (rel === null) process.exit(0);
    if (GREP_BLOCKED_ROOTS.includes(rel) || isImplementation(rel) || grepReachesHandover(rel)) block();
    // A folder that contains an implementation folder (backend/tests holds
    // backend/tests/load) is only allowed with a glob limited to test files.
    if (IMPL_DIRS.some((d) => d !== rel && under(d, rel))) {
      const g = String(ti.glob || "");
      if (!/^(test_|conftest)[^/]*$/.test(g)) block();
    }
    process.exit(0);
  }

  process.exit(0);
});
