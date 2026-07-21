# Release Notes Review

Given a GitHub draft release URL, produce a complete reno status table and write any missing release note files.

## Step 1 — Build the PR list

Fetch the draft release page with WebFetch and extract every PR entry (title, author, number).
If the user passed a URL as args, use that. Otherwise ask for it.

## Step 2 — Check existing reno files

For each PR, determine whether a release note already exists. The most reliable method is
matching git commit messages (which include the PR number) against notes added in the same commit:

```bash
# find notes added in the commit that merged a given PR
git log --oneline --diff-filter=A -- 'releasenotes/notes/*.yaml' 'releasenotes/notes/**/*.yaml' \
  | grep "(#<PR number>)"

# alternatively, match by keyword from the PR title
git log --oneline --diff-filter=A -- 'releasenotes/notes/*.yaml' 'releasenotes/notes/**/*.yaml' \
  | grep -i "<keyword from PR title>"
```

Note content does not embed PR numbers, so grep-by-number on file content will not work —
always match via commit message.

A note that lives in a versioned subfolder (e.g. `0.33.0/`) belongs to that released version and
does NOT count as a note for the new release. If a PR's note was accidentally committed into a
past versioned subfolder after that release was tagged, it must be moved to the top-level
`releasenotes/notes/` directory and counts as MISSING RENO for the new release until that move
is done.

## Step 3 — Decide reno status

Apply these rules to classify each PR as **reno OK**, **no reno needed**, or **MISSING RENO**:

**No reno needed — skip these automatically:**
- Automated dependency bumps (dependabot, renovate, any "[bot]" author) for internal or
  infrastructure packages — **but not if the bumped package is user-facing** (e.g. `qiskit*`,
  `qiskit-ibm-runtime`, any package listed in the client's `pyproject.toml` dependencies).
  A bump that changes the minimum or maximum version a user must install always needs a reno,
  regardless of who opened the PR.
- CI/CD changes (workflows, GitHub Actions, `.github/`)
- Test-only refactors (no behaviour change visible to users)
- Internal tooling: backoffice UI, admin forms, SSO/auth for internal staff
- Pure infrastructure: image base-version bumps, CVE patches with no API change
- Documentation-only changes
- Release preparation commits
- Internal data model or database schema changes with no effect on the client API
- Admin-only environment variables or settings not exposed to end users
- Internal code refactors (renaming methods, splitting classes) that don't change the public interface

**Reno needed — flag these:**
- Any change to the client API surface (new/removed/renamed symbols, changed behaviour)
- Dependency changes that affect what users install (`requirements.txt`, `pyproject.toml`, extras)
- Bug fixes visible to users (wrong output, exceptions, incorrect status)
- Deprecations of public symbols
- Changes to authentication or error messages users see
- Endpoint behaviour changes (response fields added/removed/hidden)
- Custom image / registry validation rules
- New capabilities users can call (new methods, new parameters, new return fields)
- Anything that requires users to change their code or configuration

When in doubt, err toward **reno needed**.

## Step 4 — Print the status table

Output a table in this format (mirrors what the user provided as input today):

```
<PR title> @<author>(#<number>) -> reno OK | no reno needed | MISSING RENO
```

Pause here and let the user review before proceeding to write notes.

## Step 5 — Write missing release notes

For each MISSING RENO, fetch the PR body:

```bash
gh pr view <number> --json title,body
```

Then write a file to `releasenotes/notes/<slug>-<16hexchars>.yaml`.

**Choosing the slug:** kebab-case summary of the change, e.g. `ray-optional-client`,
`fix-job-status-sub-status`. Keep it short and descriptive.

**Choosing the 16 hex chars:** run `reno new <slug>` if reno is installed (it generates the
suffix automatically). Otherwise generate a random 16-character hex string. The exact value
doesn't matter, only uniqueness across the notes directory.

**Do NOT place notes in a versioned subfolder** (e.g. `0.34.0/`). That move happens at
release time as a separate step.

### Category rules

| Category | Use when |
|---|---|
| `fixes` | Bug fix, behaviour correction, misleading error message fixed |
| `upgrade` | Breaking change, removed API, raised minimum version, dependency version change, endpoint behaviour change, image/config change users must act on |
| `features` | Genuinely new user-facing capability that didn't exist before |
| `deprecations` | Public symbols that will be removed in a future release — include migration instructions |
| `security` | Purely a vulnerability fix with no user-visible behaviour change; if admins/users see different behaviour, use `upgrade` instead |
| `other` | Infrastructure or operational changes relevant to operators but not end users (e.g. telemetry, logging format changes) |
| `prelude` | Release-level summary paragraph — only one per release, written at release time, not per-PR |

**Dependency changes are `upgrade`, not `features`** — even if they add something new to an
allowlist or enable a new library. "Can now use X" framing belongs in `upgrade`.

**Dynamic dependency allowlist additions** (new packages added to the Ray runner image) are
`upgrade`, not `features`.

### What belongs in a note vs. what to omit

Write about things the **user or operator** observes or acts on:
- New methods/parameters they can call
- Changed return values or error messages they receive
- Minimum version requirements they must satisfy
- Configuration they must update

Omit:
- Internal method/parameter renames that are not part of the public API
- Database schema or model changes not surfaced in the API
- Refactoring that preserves public behaviour
- Build-step details (image layer steps, Dockerfile changes)
- Gateway/scheduler internal implementation details

When a note contains a mix — e.g. a refactor PR that also changes a public parameter — write
only about the public-facing part.

### Writing style rules

- Write for the **user**, not the developer. Omit implementation details and build-step minutiae.
- State what changed and what the user needs to do (if anything).
- Neutral voice: don't frame an `upgrade` note as fixing a security gap — just describe the
  new behaviour.
- No vague closing sentences ("please use alternative methods", "this may affect some users").
  Either say something specific or say nothing.
- No trailing whitespace, no double spaces.
- Bare PR number references (`#NNNN`) should be removed. Public GitHub issue URLs
  (`https://github.com/.../issues/NNN`) are fine to keep.
- A note must contain enough information to be actionable. A one-liner like
  "now supports qiskit-ibm-runtime==0.45" is acceptable only if there is nothing else the
  user needs to know. If there is migration guidance, include it.
- Use RST cross-reference roles for public symbols:
  `:meth:\`~qiskit_serverless.core.job.Job.status\``
  `:class:\`~qiskit_serverless.exception.QiskitServerlessException\``

### YAML format

```yaml
---
fixes:
  - |
    <prose — wrap at ~88 chars, indent continuation lines 4 spaces>
```

Multiple bullets under the same key are fine; each `- |` is a separate rendered bullet.
A single file may contain multiple categories (e.g. both `features` and `upgrade`).

## Step 6 — Polish pass over all top-level notes

After writing missing notes, scan every file in `releasenotes/notes/*.yaml` (top-level only —
do not modify versioned subfolders) for:

- Dependency additions → confirm they use `upgrade`, not `features`
- Bare PR references (`#NNNN`) → remove (keep public issue URLs)
- Internal implementation details (internal class/method names, DB schema, build steps) → remove
- Trailing whitespace or double spaces → fix
- `security` notes that describe a user-visible behaviour change → convert to `upgrade` and
  reword neutrally
- Vague closing sentences → remove
- Notes that are empty or contain only internal details after cleanup → flag for deletion

## Step 7 — Move notes into versioned subfolder

Once the user has reviewed and confirmed all release notes look correct, ask the user for the
release version number before proceeding:

> "What version number should I use for the subfolder? (e.g. 0.34.0)"

Do not infer it from the branch name or draft release URL — always ask explicitly to avoid
moving notes into a wrongly-named directory.

Once confirmed, write a prelude note for the release before moving anything. The prelude is a
one-paragraph summary of the most important changes in this release. Write it to a new file at
the top level:

```
releasenotes/notes/prelude-<version>-<16hexchars>.yaml
```

```yaml
---
prelude: >
    ``qiskit_serverless vX.Y.Z`` <one paragraph summarising the headline changes — new
    features, removed APIs, raised minimum versions, notable bug fixes>.
```

Draw the content from the notes you wrote in Steps 5–6. Keep it to 3–5 sentences.

Then create the subfolder and move every top-level note (including the new prelude) into it:

```bash
VERSION="<confirmed by user>"
mkdir -p releasenotes/notes/${VERSION}
git mv releasenotes/notes/*.yaml releasenotes/notes/${VERSION}/
```

Do NOT move notes that are already in a versioned subfolder — only files at the top level of
`releasenotes/notes/` should be moved.

## Step 8 — Commit

Stage only the release note files and commit with a short descriptive message.
Do NOT add a co-author trailer.
