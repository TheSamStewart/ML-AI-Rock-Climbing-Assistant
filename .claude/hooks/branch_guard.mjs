#!/usr/bin/env node
// Branch guard (wired in .claude/settings.json). Two modes:
//
//   node branch_guard.mjs          PreToolUse on Edit|Write|NotebookEdit.
//     Blocks editing files inside the repo when the current branch is main/master,
//     detached, or not named <type>/<issue#>-<slug> (see docs/docs.md).
//     Files outside the repo (memory, scratchpad) are always allowed.
//     Bash edits (sed, heredocs) are NOT covered.
//
//   node branch_guard.mjs session  SessionStart.
//     Prints the active issue and where its docs are, as context for Claude.
//
// Exit 0 = allow, exit 2 = block (stderr is shown to Claude). If git can't be
// read, the guard allows rather than breaking the session. No dependencies.

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const BRANCH_RE = /^(feat|fix|refactor|docs|chore|test)\/(\d+)-([a-z0-9]+(?:-[a-z0-9]+)*)$/;
// Cloud sessions (claude.ai/code) name their own claude/* branches.
const CLOUD_RE = /^claude\//;
const PROTECTED = new Set(["main", "master"]);

const scriptRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const ROOT = process.env.CLAUDE_PROJECT_DIR || scriptRoot;

function norm(p) {
  let s = String(p).replace(/\\/g, "/");
  // Git Bash writes d:/x as /d/x; map it back so the path is seen as inside the repo.
  if (process.platform === "win32") s = s.replace(/^\/([a-zA-Z])(\/|$)/, "$1:/");
  s = path.posix.normalize(s);
  if (s.length > 1 && s.endsWith("/")) s = s.slice(0, -1);
  return s.toLowerCase(); // Windows paths are case-insensitive.
}

function insideRepo(file, cwd) {
  let s = norm(file);
  const abs = s.startsWith("/") || /^[a-z]:\//.test(s);
  if (!abs) s = norm(`${cwd}/${s}`);
  const root = norm(ROOT);
  return s === root || s.startsWith(root + "/");
}

function currentBranch() {
  try {
    return execFileSync("git", ["-C", ROOT, "branch", "--show-current"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return null; // Not a repo, or git missing.
  }
}

// docs/milestones/<version>/<n>-<slug>/ for this branch, or null.
function issueDocs(n, slug) {
  const base = path.join(ROOT, "docs", "milestones");
  let versions = [];
  try {
    versions = fs.readdirSync(base, { withFileTypes: true }).filter((d) => d.isDirectory() && !d.name.startsWith("_"));
  } catch {
    return null;
  }
  // Active issues sit in the version folder; finished ones in <version>/completed/.
  for (const v of versions) {
    for (const sub of ["", "completed/"]) {
      const rel = `docs/milestones/${v.name}/${sub}${n}-${slug}`;
      if (fs.existsSync(path.join(ROOT, rel))) return { version: v.name, rel, done: sub !== "" };
    }
  }
  return null;
}

const RENAME_HELP =
  "Branches are named <type>/<issue#>-<slug>, e.g. feat/43-hold-type " +
  "(types: feat, fix, refactor, docs, chore, test; see docs/docs.md). " +
  "Agents don't create or rename branches: ask the human to run " +
  "`git switch -c <type>/<n>-<slug>` or `git branch -m <type>/<n>-<slug>`, then retry.";

function sessionMode() {
  const branch = currentBranch();
  if (branch === null) process.exit(0);
  let msg;
  if (CLOUD_RE.test(branch)) {
    msg = `Branch guard: cloud branch ${branch}; no issue docs are tied to it.`;
  } else if (PROTECTED.has(branch) || branch === "") {
    msg = `Branch guard: on ${branch || "a detached HEAD"}. Claude can't edit repo files here. ${RENAME_HELP}`;
  } else {
    const m = BRANCH_RE.exec(branch);
    if (!m) {
      msg = `Branch guard: branch "${branch}" has no issue number, so Claude can't edit repo files. ${RENAME_HELP}`;
    } else {
      const [, , n, slug] = m;
      const docs = issueDocs(n, slug);
      msg = docs
        ? `${docs.done ? "Completed" : "Active"} issue #${n} (branch ${branch}). Docs: ${docs.rel}/spec.md and ${docs.rel}/handover.md; ` +
          `milestone status: docs/milestones/${docs.version}/milestone.md. Read handover.md's Status and newest entry first.`
        : `Active issue #${n} (branch ${branch}), but docs/milestones/*/${n}-${slug}/ doesn't exist yet: run /start-issue.`;
    }
  }
  process.stdout.write(msg + "\n");
  process.exit(0);
}

function guardMode(input) {
  const ti = input.tool_input || {};
  const file = ti.file_path || ti.notebook_path;
  if (!file) process.exit(0);
  if (!insideRepo(file, input.cwd || ROOT)) process.exit(0);

  const branch = currentBranch();
  if (branch === null) process.exit(0);
  if (CLOUD_RE.test(branch) || BRANCH_RE.test(branch)) process.exit(0);

  const where = branch === "" ? "a detached HEAD" : PROTECTED.has(branch) ? branch : `"${branch}", which has no issue number`;
  process.stderr.write(`Blocked by the branch guard: the current branch is ${where}. ${RENAME_HELP}\n`);
  process.exit(2);
}

if (process.argv[2] === "session") {
  sessionMode();
} else {
  let raw = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (c) => (raw += c));
  process.stdin.on("end", () => {
    let input;
    try {
      input = JSON.parse(raw);
    } catch {
      process.exit(0);
    }
    guardMode(input);
  });
}
