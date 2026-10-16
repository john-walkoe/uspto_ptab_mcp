"""CR-20 (review 2026-09-28): vendored-module drift guard.

Each module below is hand-copied (not a package dependency) into every USPTO
MCP repo that needs it — no shared import path exists because there is no
shared package on PyPI, and the two-way `git subtree`/symlink alternatives
were rejected earlier for the same reason a straight file copy was chosen in
the first place (repo-specific constants stay OUT of the vendored file,
everything else is byte-identical). That means nothing enforces the copies
staying in sync except a human remembering to re-vendor, so this test pins
the md5 of this repo's copy of each module: if it drifts (an edit landed
here directly instead of at the canonical copy, or a re-vendor was missed)
CI goes red instead of the repos silently diverging.

Canonical copies (edit here, then copy byte-for-byte to every sharer):
  - shared/response_bounds.py: **uspto_ptab_mcp is canonical.** Re-vendor
    into uspto_pfw_mcp and uspto_fpd_mcp FROM this file.
  - shared/uspto_shared_rate_limiter.py: **uspto_ptab_mcp is canonical**
    (2026-10-13, ODP rate-limit wave: FIFO queue, slot-then-token with a
    capacity-1 bucket, 45 s ceiling, shared 429 cooldown). Copy into
    uspto_pfw_mcp, uspto_fpd_mcp and uspto_enriched_citation_mcp FROM this
    file (Citations' copy had already diverged before the wave; re-vendor,
    never merge).
  - shared/citations.py, shared/dpapi_crypto.py, shared/uspto_hosts.py:
    the copy uspto_pfw_mcp / uspto_ptab_mcp / uspto_fpd_mcp already share
    byte-identical.

Re-vendoring rule: `cp` the file across verbatim, then re-run this test (and
the sibling repo's own copy of it) to confirm the md5 landed.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

_SHARED_DIR = Path(__file__).resolve().parents[1] / "src" / "ptab_mcp" / "shared"

# filename -> expected md5 hex digest of this repo's vendored copy.
_EXPECTED_MD5 = {
    "response_bounds.py": "ef54141d6eedba49ee801a15a5452679",
    "uspto_shared_rate_limiter.py": "a381d6cd21d2a6b4590fe2a54daf432b",  # 2026-10-13 ODP rate-limit wave
    "citations.py": "d89111f88fa1a8f5b608beaad8b52c5b",
    "dpapi_crypto.py": "8464b50be7be2a52337b0cebbb6e22f3",
    "uspto_hosts.py": "fd2e4902fdc1e9972b26e078dd9cf5bc",
}


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("filename, expected", sorted(_EXPECTED_MD5.items()))
def test_vendored_module_matches_recorded_md5(filename: str, expected: str) -> None:
    path = _SHARED_DIR / filename
    assert path.is_file(), f"vendored module missing: {path}"
    actual = _md5(path)
    assert actual == expected, (
        f"{filename} has drifted from its recorded md5 ({expected} -> "
        f"{actual}). If this edit was intentional, re-vendor it to every "
        "sharer named in this file's module docstring and update the "
        "constant here AND in each sibling repo's copy of this test."
    )
