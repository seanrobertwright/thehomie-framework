"""Sanitizer tests for PRP-7e Phase 5 (and forward).

R3 NM1 fix: tests use the sanitizer's ``is_denied()`` API directly instead
of the ``--dry-run | grep`` pattern. The dry-run print is
``sorted(allowed)[:50]`` (truncated) so a stdout grep can pass falsely.
Direct API calls test the rule, not the run.

This is the FIRST test file in this suite. PRP-7f (Phase 6) extends with
the broader ``test_prp7_paths_classify_correctly`` covering all PRP-7
paths.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Allow ``import sanitize`` from the scripts/ directory regardless of where
# pytest is invoked from. ``Path(__file__).parent`` is ``scripts/``.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sanitize  # noqa: E402  (import after sys.path manipulation)


REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_REL = ".claude/templates/profile-isolation-smoke.yaml"


def test_phase5_archon_template_included() -> None:
    """The PRP-7e smoke workflow template must NOT be denied by the
    sanitizer - it has to ship in the public export so consumers of
    ``thehomie-framework`` can run profile-isolation-smoke against their
    own Archon installs.

    Direct ``is_denied()`` call (R3 NM1 fix):
      - ``.claude/templates/`` is NOT in DENY_DIRS
      - ``.yaml`` is NOT in DENY_EXTENSIONS
      - the path is NOT in DENY_FILES
    Therefore ``is_denied()`` MUST return False.
    """
    assert sanitize.is_denied(TEMPLATE_REL) is False, (
        f"sanitizer denied {TEMPLATE_REL!r} - public export will be missing "
        f"the smoke workflow asset. Check DENY_DIRS / DENY_FILES / "
        f"DENY_EXTENSIONS in scripts/sanitize.py."
    )


def test_phase5_archon_template_present_on_disk() -> None:
    """The asset file must exist on disk (WS2a Task 5). Without this file,
    ``personas.archon._seed_smoke_workflow`` silently no-ops and the
    profile gets no smoke workflow. This test is the canary that the asset
    actually shipped to the repo.
    """
    asset = REPO_ROOT / TEMPLATE_REL
    assert asset.is_file(), (
        f"Smoke workflow asset missing at {asset}. WS2a Task 5 must "
        f"create this file."
    )


def test_phase5_archon_template_tracked_by_git() -> None:
    """The asset must be ``git add``'d. An untracked file would not ship in
    the public export even if the sanitizer allows it (the sanitizer
    operates on ``git ls-files`` output - that's the source of truth).
    """
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", TEMPLATE_REL],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    tracked = result.returncode == 0
    assert tracked, (
        f"Smoke workflow asset {TEMPLATE_REL!r} is not tracked by git. "
        f"WS2a Task 5 must `git add` the file before commit. "
        f"git stderr: {result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# PRP-7f Phase 6 — paperclip seam doc + runtime-state defense
# ---------------------------------------------------------------------------

PAPERCLIP_SEAM_REL = "docs/paperclip-seam.md"


def test_prp7_paperclip_seam_doc_included() -> None:
    """The paperclip seam doc must NOT be denied by the sanitizer. It lives
    under ``docs/`` (which is in DENY_DIRS) but is surgically lifted via
    ``INCLUDE_FILES`` because it is the public Paperclip integration
    contract.

    Direct ``is_denied()`` call — proves the layered precedence in
    ``is_denied()`` (Section: Layer 4 INCLUDE_FILES override of Layer 5
    DENY_DIRS) is wired correctly.
    """
    assert sanitize.is_denied(PAPERCLIP_SEAM_REL) is False, (
        f"sanitizer denied {PAPERCLIP_SEAM_REL!r} — public mirror will "
        f"be missing the Paperclip integration seam contract. Check that "
        f"INCLUDE_FILES in scripts/sanitize.py contains this path AND "
        f"that DENY_FILES / DENY_EXTENSIONS / DENY_PATTERNS do not match it."
    )


def test_prp7_paperclip_seam_doc_present_on_disk() -> None:
    """The doc file must exist on disk. Without this file, the
    INCLUDE_FILES allowlist points at vapor and the sanitizer silently
    ships nothing (the export step only includes paths that exist).
    """
    asset = REPO_ROOT / PAPERCLIP_SEAM_REL
    assert asset.is_file(), (
        f"Paperclip seam doc missing at {asset}. PRP-7f truncated Phase "
        f"6 must create this file."
    )


def test_prp7_paperclip_seam_doc_tracked_by_git() -> None:
    """The doc must be ``git add``'d. The sanitizer reads ``git ls-files``
    as the source of truth; an untracked file is invisible to the export
    pipeline regardless of INCLUDE_FILES.
    """
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", PAPERCLIP_SEAM_REL],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    tracked = result.returncode == 0
    assert tracked, (
        f"Paperclip seam doc {PAPERCLIP_SEAM_REL!r} is not tracked by "
        f"git. PRP-7f Phase 6 must `git add` the file before commit. "
        f"git stderr: {result.stderr!r}"
    )


def test_prp7_runtime_state_denied() -> None:
    """Runtime state files must be denied — these contain live PIDs,
    session UUIDs, lock metadata, or feature-flag state that should
    never ship in the public mirror.

    Each path is named explicitly so a regression report points at the
    exact rule that should have caught the leak.
    """
    cases = [
        # path, rule the test expects to match
        (".claude/chat/bot.pid", "DENY_FILES + DENY_EXTENSIONS .pid"),
        (".claude/chat/bot.lock", "DENY_FILES + DENY_EXTENSIONS .lock"),
        (".claude/data/state/bot.pid", "DENY_FILES + DENY_DIRS .claude/data/ + .pid"),
        (".claude/scheduled_tasks.lock", "DENY_FILES + DENY_EXTENSIONS .lock"),
        (".claude/banner-exemption.flag", "DENY_FILES + DENY_PATTERNS \\.flag$"),
    ]
    for path, rule in cases:
        assert sanitize.is_denied(path) is True, (
            f"sanitizer FAILED to deny runtime state file {path!r}. "
            f"Expected catch by: {rule}. This is a near-miss leak — "
            f"runtime state must never ship publicly."
        )


def test_prp7_homie_profiles_pattern_denied() -> None:
    """Any file under ``.homie/profiles/`` (top-level OR nested) must be
    denied — these are external operator profile-state directories that
    can show up if accidentally tracked by an operator who initialized
    a profile inside the repo by mistake.

    Tested via DENY_PATTERNS regex — handles both top-level
    ``.homie/profiles/...`` and nested ``foo/.homie/profiles/...``.
    """
    nested_cases = [
        ".homie/profiles/sales/agent.yaml",
        "home/.homie/profiles/sales/CLAUDE.md",
    ]
    for path in nested_cases:
        assert sanitize.is_denied(path) is True, (
            f"sanitizer FAILED to deny {path!r} — operator profile state "
            f"would leak. Check DENY_PATTERNS regex in scripts/sanitize.py."
        )


def test_prp7_include_files_does_not_override_deny_files() -> None:
    """Class-of-bug test for PRP-7f R1 B3.

    INCLUDE_FILES must NEVER bypass DENY_FILES. If a future operator
    accidentally puts ``.claude/chat/bot.pid`` in INCLUDE_FILES (e.g.
    cargo-cult copy of the paperclip-seam allowlist entry), the file
    must STILL be denied because DENY_FILES is layer 1 (absolute).

    Try/finally save+restore (no monkeypatch fixture) to match the
    existing test style in this file.
    """
    target = ".claude/chat/bot.pid"
    saved = sanitize.INCLUDE_FILES[:]
    try:
        sanitize.INCLUDE_FILES = saved + [target]
        assert sanitize.is_denied(target) is True, (
            f"layered precedence broken: INCLUDE_FILES override leaked "
            f"past DENY_FILES for {target!r}. DENY_FILES (layer 1) MUST "
            f"win over INCLUDE_FILES (layer 4)."
        )
    finally:
        sanitize.INCLUDE_FILES = saved


def test_prp7_include_files_does_not_override_deny_extensions() -> None:
    """Class-of-bug test for PRP-7f R1 B3 — extension layer.

    INCLUDE_FILES must NEVER bypass DENY_EXTENSIONS. Same shape as
    the DENY_FILES test, but exercises layer 2 (.lock extension).
    """
    target = "docs/example.lock"  # would otherwise pass DENY_DIRS via INCLUDE_FILES
    saved = sanitize.INCLUDE_FILES[:]
    try:
        sanitize.INCLUDE_FILES = saved + [target]
        assert sanitize.is_denied(target) is True, (
            f"layered precedence broken: INCLUDE_FILES override leaked "
            f"past DENY_EXTENSIONS for {target!r}. DENY_EXTENSIONS "
            f"(layer 2) MUST win over INCLUDE_FILES (layer 4)."
        )
    finally:
        sanitize.INCLUDE_FILES = saved


def test_prp7_include_files_does_not_override_deny_patterns() -> None:
    """Class-of-bug test for PRP-7f R1 B3 — pattern layer.

    INCLUDE_FILES must NEVER bypass DENY_PATTERNS. Exercises layer 3
    via the ``\\.flag$`` regex.
    """
    target = "docs/example.flag"
    saved = sanitize.INCLUDE_FILES[:]
    try:
        sanitize.INCLUDE_FILES = saved + [target]
        assert sanitize.is_denied(target) is True, (
            f"layered precedence broken: INCLUDE_FILES override leaked "
            f"past DENY_PATTERNS for {target!r}. DENY_PATTERNS (layer 3) "
            f"MUST win over INCLUDE_FILES (layer 4)."
        )
    finally:
        sanitize.INCLUDE_FILES = saved


def test_prd8_claude_agents_dir_denied() -> None:
    """Domain-owner charters at .claude/agents/ must be denied from public
    export. Charters reference shipped class-of-bug history (PRs #16, #19,
    R1 B2 wrong-gate, NB1 R3 data-loss class) and competitive intel about
    framework architecture. This is not PII per se but is competitive
    leakage owner doesn't want public until CLUTCH ships intentionally.

    Existing piv-* agents at .claude/agents/piv-*.md were already private;
    the new domain-owner charters (memory-cognition-owner, runtime-chat-owner,
    personas-owner, orchestration-owner, public-export-owner) + CODEOWNERS.toml
    + _drafts/ all live under the same dir and inherit the deny rule.

    Flip to ALLOW only with explicit user approval when CLUTCH adoption goes
    public.
    """
    cases = [
        ".claude/agents/memory-cognition-owner.md",
        ".claude/agents/runtime-chat-owner.md",
        ".claude/agents/personas-owner.md",
        ".claude/agents/orchestration-owner.md",
        ".claude/agents/public-export-owner.md",
        ".claude/agents/CODEOWNERS.toml",
        ".claude/agents/_drafts/memory-cognition-analysis.md",
        ".claude/agents/piv-validator.md",  # pre-existing — still denied
    ]
    for path in cases:
        assert sanitize.is_denied(path) is True, (
            f"sanitizer FAILED to deny .claude/agents/ file {path!r}. "
            f"Expected catch by: DENY_DIRS '.claude/agents/'. Domain owner "
            f"charters and CODEOWNERS.toml must stay private."
        )


def test_prp7_dynamic_lock_pid_scan() -> None:
    """Dynamic regression: every currently-tracked .lock or .pid file
    must be denied. Catches future operator mistakes where a new
    runtime-state file is accidentally ``git add``'d.

    This test reads ``git ls-files`` at runtime — the test set is NOT
    hardcoded. If a new ``foo.lock`` shows up tracked, the test fails
    immediately and points at the file, the rule that should catch it,
    and what the sanitizer actually returned.
    """
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().endswith((".lock", ".pid"))
    ]
    failures: list[str] = []
    for path in tracked:
        if sanitize.is_denied(path) is not True:
            failures.append(path)
    assert not failures, (
        f"sanitizer FAILED to deny tracked runtime-state files: "
        f"{failures!r}. Each one is a public-mirror leak risk. Add to "
        f"DENY_FILES (layer 1) or fix DENY_EXTENSIONS / DENY_PATTERNS."
    )
