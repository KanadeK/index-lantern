"""Small read-only Git boundary. Never invokes a shell or repository filters."""

import os
import subprocess
from pathlib import Path


class AuditError(Exception):
    pass


def git(repo: Path, *args: str, allow_failure: bool = False) -> bytes:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0',
               GIT_NO_LAZY_FETCH='1', GIT_NO_REPLACE_OBJECTS='1', GIT_ALLOW_PROTOCOL='')
    command = ['git', '-C', str(repo), '-c', 'core.fsmonitor=false',
               '-c', 'gc.auto=0', '-c', 'maintenance.auto=false', *args]
    try:
        result = subprocess.run(command, capture_output=True, env=env, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuditError('Git could not run or exceeded the 60-second command limit') from exc
    if result.returncode and not allow_failure:
        raise AuditError(f'Git {args[0]} failed; verify repository access and Git version')
    return result.stdout if result.returncode == 0 else b''
