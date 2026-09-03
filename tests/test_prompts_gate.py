"""Registration gate for the workflow prompt templates.

The 11 prompts must be absent from the registered prompt set unless
PTAB_ENABLE_PROMPTS=true (default off — mirrors the ptab_manage_users
PTAB_ENABLE_USER_MANAGEMENT registration gate).

Registration happens at import time, so each state runs in a subprocess.
"""

import os
import subprocess
import sys

_PROBE = (
    "from ptab_mcp.main import mcp\n"
    "from fastmcp.prompts.base import Prompt\n"
    "names = [c.name for c in mcp.local_provider._components.values()"
    " if isinstance(c, Prompt)]\n"
    "print('PRESENT' if 'trial_precedent_research' in names else 'ABSENT')\n"
    "print('COUNT', len(names))\n"
)


def _probe(extra_env: dict) -> tuple[str, int]:
    env = {**os.environ}
    env.pop("PTAB_ENABLE_PROMPTS", None)
    env.setdefault("USPTO_API_KEY", "x" * 30)
    env.update(extra_env)
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    lines = result.stdout.strip().splitlines()
    present = lines[-2].strip()
    count = int(lines[-1].split()[-1])
    return present, count


def test_prompts_absent_by_default():
    present, count = _probe({})
    assert present == "ABSENT"
    assert count == 0


def test_prompts_registered_when_enabled():
    present, count = _probe({"PTAB_ENABLE_PROMPTS": "true"})
    assert present == "PRESENT"
    assert count == 11
