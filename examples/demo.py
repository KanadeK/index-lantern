"""Installed-package demonstration using an isolated synthetic repository."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory(prefix='index-lantern-demo-') as tmp:
    repo = Path(tmp)
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)

    def git(*args):
        subprocess.run(['git', '-C', tmp, *args], env=env, check=True, capture_output=True)

    git('-c', 'init.templateDir=', 'init', '-q')
    git('config', 'core.autocrlf', 'false')
    path = repo / 'local-config.txt'
    path.write_bytes(b'public-default\n')
    git('add', 'local-config.txt')
    git('update-index', '--assume-unchanged', 'local-config.txt')
    before = (repo / '.git/index').read_bytes()
    path.write_bytes(b'local-change\n')
    result = subprocess.run([sys.executable, '-m', 'index_lantern', tmp, '--json'],
                            capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert result.returncode == 1, result.stdout + result.stderr
    assert report['entries'][0]['state'] == 'raw-different'
    assert (repo / '.git/index').read_bytes() == before
    print('PASS: detected the hidden raw difference; index bytes and flags preserved.')
    path.write_bytes(b'public-default\n')
    result = subprocess.run([sys.executable, '-m', 'index_lantern', tmp, '--json'],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    print('PASS: restoring the original bytes passes the divergence gate.')
