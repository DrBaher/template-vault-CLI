# Post-session terminal checklist

When you get back to a terminal, these are the manual steps that the
sandboxed Claude Code session couldn't do. They close out the v0.4.x
release work and fix the historical-author-attribution issue.

Estimated total time: **~8 minutes** (3 min PyPI setup + 1 min script
+ 4 min web UI clicks).

## Pre-flight

Open these three browser tabs:

1. https://pypi.org/manage/account/publishing/ — PyPI Trusted Publishing setup
2. https://github.com/DrBaher/template-vault-CLI/releases — for release recreation
3. https://github.com/DrBaher/template-vault-CLI/actions — for watching the publish workflow

## Step 1 — PyPI Trusted Publishing setup (~3 min, browser only)

This is the one-time setup that makes the publish workflow actually fire.

1. Log into https://pypi.org/ (create the account if you don't have
   one yet).
2. Go to **"Your projects" → "Add a new pending publisher"**, or
   directly to https://pypi.org/manage/account/publishing/.
3. Fill in:
   - **PyPI project name**: `template-vault-cli`
   - **Owner**: `DrBaher`
   - **Repository name**: `template-vault-CLI`
   - **Workflow name**: `publish.yml`
   - **Environment name**: `pypi`
4. Click **Add**.

That's it. From now on every `git push origin v*` tag triggers
`.github/workflows/publish.yml`, which builds the wheel + sdist and
uploads to PyPI with no token in your secrets.

## Step 2 — Authorship rewrite + tag recreation (~1 min, paste-and-run)

The session committed 15 commits as `Claude <noreply@anthropic.com>`
before git identity was set. They need to be rewritten as you. The
rewritten history is already on `origin/main-clean`, but `main` itself
still has the wrong authorship.

There's also a new commit on `main` (PR #8, the docs/compare-cli
spec citation) that's *not* in main-clean. The script preserves it.

From a fresh terminal:

```bash
cd /tmp
git clone https://github.com/DrBaher/template-vault-CLI.git
cd template-vault-CLI

git config user.name "DrBaher"
git config user.email "drbaher@gmail.com"

# Start from main-clean (rewritten v0.3.0 / v0.4.0 history)
git checkout main-clean

# Cherry-pick the docs commit that landed on main after the rewrite (PR #8)
git cherry-pick 9bb5182a5c18ca40c6e99badc3456e77de6d675d

# Cherry-pick the v0.4.1 commits from the feature branch (the suite-refs
# + clause-detection-divergence work from this session)
git fetch origin claude/review-nda-prompt-PXyxY
# Replace <SHA> with the tip of claude/review-nda-prompt-PXyxY after the
# session pushes its v0.4.1 commit (check `git log origin/claude/review-nda-prompt-PXyxY`):
#   git cherry-pick <SHA>

# Force-push as the new main
git push origin main --force

# Delete the misplaced tags and helper branches
git push origin :refs/tags/v0.3.0 :refs/tags/v0.4.0
git push origin --delete main-clean
git push origin --delete claude/review-nda-prompt-PXyxY
git push origin --delete claude/cite-clause-detection-spec-Bv3Kn

# Re-tag at the rewritten commits
git tag -f v0.3.0 "$(git log --grep='release: 0.3.0' --format=%H | head -1)"
git tag -f v0.4.0 "$(git log --grep='v0.4.0: PyPI workflow' --format=%H | head -1)"
git tag    v0.4.1 main
git push origin v0.3.0 v0.4.0 v0.4.1

# Verify everyone's you
git log --pretty=format:'%h %an %s' | head -20
```

After this, the contributor graph will rebuild within a few minutes
and you'll be the sole author on every commit.

## Step 3 — Watch the PyPI publish (~30 seconds)

The `git push origin v0.4.1` from step 2 triggers the publish workflow.
Watch it at:

https://github.com/DrBaher/template-vault-CLI/actions/workflows/publish.yml

If the Trusted Publishing setup from step 1 is correct, the workflow
builds the wheel + sdist and uploads `template-vault-cli==0.4.1` to
PyPI within 1-2 minutes. Verify at:

https://pypi.org/project/template-vault-cli/

And:

```bash
pipx install template-vault-cli==0.4.1
template-vault --version    # → "template-vault 0.4.1"
```

## Step 4 — Recreate the GitHub releases (~4 min, 3 web UI clicks each)

The tags exist after step 2, but GitHub releases are separate records
that need to be re-published. The tags themselves got recreated, so
the release page lost its "Releases" entries for v0.3.0 and v0.4.0 (or
they now point at orphaned refs).

For each of v0.3.0, v0.4.0, v0.4.1:

1. Go to https://github.com/DrBaher/template-vault-CLI/releases/new
2. Tag: `vX.Y.Z` (pick from dropdown — the tag exists after step 2)
3. Target: `main`
4. Title and body: paste from the relevant `CHANGELOG.md` section
   (the v0.3.0, v0.4.0, and v0.4.1 sections each have ready-to-paste
   release notes).
5. Click **Publish release**.

## Step 5 — Verify everything (~30 seconds)

```bash
# Authorship: every commit should show DrBaher
git log --pretty=format:'%an' main | sort -u
# Should print only: "DrBaher"

# Tags exist at the right commits
git ls-remote --tags origin
# Should show v0.1.0, v0.3.0, v0.4.0, v0.4.1 (v0.1.0 may not exist if you never created it)

# PyPI has the latest
pip index versions template-vault-cli
# Should include 0.4.1
```

GitHub's contributor graph at
https://github.com/DrBaher/template-vault-CLI/graphs/contributors
should now show you (and only you) within ~5 minutes of the force-push.

## If anything goes wrong

- **Force-push refused**: you might have branch protection on `main`.
  Settings → Branches → temporarily disable protection, force-push,
  re-enable.
- **PyPI publish workflow fails with auth error**: the Trusted
  Publishing config probably doesn't match. Double-check **owner**,
  **repository name**, **workflow name** (`publish.yml`), and
  **environment name** (`pypi`) at
  https://pypi.org/manage/account/publishing/.
- **Cherry-pick conflicts**: the v0.4.1 commit on
  `claude/review-nda-prompt-PXyxY` should apply cleanly on top of
  main-clean + the PR #8 cherry-pick. If it doesn't, the conflict is
  in one of: README.md, ARCHITECTURE.md, FAQ.md, CHANGELOG.md,
  template_vault_cli.py, tests/test_fallback_detection.py,
  docs/clause-detection-divergence.md, docs/RECOVERY-CHECKLIST.md.
  Most likely candidates: CHANGELOG.md (manual merge), ARCHITECTURE.md
  (manual merge of the cross-repo-spec section).

## What this checklist does NOT cover

- **Re-running CI**: the matrix will fire automatically on the
  force-push to main. No manual action needed.
- **Notifying anyone**: this is a solo project so far; if you grow
  collaborators, add a "note that history was rewritten" comms step.
- **`docs/ROADMAP.md` updates**: it captures the deferred review-engine
  plan from this session. No edits needed.
