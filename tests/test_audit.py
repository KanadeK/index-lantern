import contextlib
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from index_lantern.cli import main
from index_lantern.core import audit, blob_hash, checked_path, parse_entries
from index_lantern.git import AuditError


def command(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(['git', '-C', str(repo), '-c', 'core.hooksPath=' + os.devnull,
                           *args], env=env, check=True, capture_output=True).stdout


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='index-lantern-test-')
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        command(self.repo, '-c', 'init.templateDir=', 'init', '-q')
        command(self.repo, 'config', 'user.name', 'KanadeK')
        command(self.repo, 'config', 'user.email', '121669563+KanadeK@users.noreply.github.com')
        command(self.repo, 'config', 'core.autocrlf', 'false')

    def add(self, name='config.txt', content=b'original\n', flag='--assume-unchanged'):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        command(self.repo, 'add', '--', name)
        if flag:
            command(self.repo, 'update-index', flag, '--', name)
        return path

    def entry(self):
        return audit(self.repo)['entries'][0]

    def cli(self, *args):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main([str(self.repo), '--json', *args])
        return code, json.loads(stdout.getvalue())

    def test_unflagged_edits_are_outside_scope(self):
        self.add(flag=None).write_text('changed')
        self.assertEqual(audit(self.repo)['flagged'], 0)

    def test_assumed_difference_hidden_from_status(self):
        path = self.add()
        command(self.repo, 'commit', '-qm', 'Fixture')
        path.write_bytes(b'local setting\n')
        self.assertEqual(command(self.repo, 'status', '--porcelain'), b'')
        self.assertEqual(self.entry()['state'], 'raw-different')
        self.assertEqual(self.cli()[0], 1)

    def test_matching_assumed_file(self):
        self.add()
        self.assertEqual(self.entry()['state'], 'raw-match')
        self.assertEqual(self.cli()[0], 0)
        self.assertEqual(self.cli('--fail-on', 'flags')[0], 1)

    def test_skip_present_difference(self):
        self.add(flag='--skip-worktree').write_bytes(b'changed')
        self.assertEqual(self.entry()['state'], 'raw-different')

    def test_both_flags(self):
        self.add()
        command(self.repo, 'update-index', '--skip-worktree', 'config.txt')
        self.assertEqual(self.entry()['flags'], ['assume-unchanged', 'skip-worktree'])

    def test_missing_assumed(self):
        self.add().unlink()
        self.assertEqual(self.entry()['state'], 'missing-assumed')
        self.assertEqual(self.cli()[0], 1)

    def test_sparse_absence_is_expected(self):
        self.add(flag='--skip-worktree').unlink()
        self.assertEqual(self.entry()['state'], 'absent-skipped')
        self.assertEqual(self.cli()[0], 0)

    def test_index_and_worktree_unchanged(self):
        path = self.add()
        index = self.repo / '.git/index'
        before = hashlib.sha256(index.read_bytes()).digest(), path.read_bytes()
        audit(self.repo)
        after = hashlib.sha256(index.read_bytes()).digest(), path.read_bytes()
        self.assertEqual(before, after)

    def test_odd_filenames(self):
        name = '-配置 a\tfile.txt' if os.name != 'nt' else '-配置 a file.txt'
        self.add(name).write_bytes(b'changed')
        self.assertEqual(self.entry()['path'], name)

    def test_crlf_is_explicitly_raw_difference(self):
        self.add().write_bytes(b'original\r\n')
        self.assertEqual(self.entry()['state'], 'raw-different')

    def test_limit_is_incomplete_even_with_none(self):
        self.add()
        code, report = self.cli('--max-bytes', '2', '--fail-on', 'none')
        self.assertEqual(code, 2)
        self.assertFalse(report['complete'])

    def test_invalid_limits(self):
        self.assertEqual(self.cli('--max-entries', '0')[0], 2)

    def test_entry_count_limit(self):
        self.add('a')
        self.add('b', flag=None)
        self.assertEqual(self.cli('--max-entries', '1')[0], 2)

    def test_no_content_in_report(self):
        self.add().write_bytes(b'SECRET_DO_NOT_REPORT')
        self.assertNotIn('SECRET_DO_NOT_REPORT', json.dumps(audit(self.repo)))

    def test_filters_not_executed(self):
        self.add()
        (self.repo / '.gitattributes').write_text('config.txt filter=probe\n')
        command(self.repo, 'config', 'filter.probe.clean', 'touch FILTER_RAN')
        command(self.repo, 'config', 'filter.probe.required', 'true')
        self.assertEqual(self.entry()['state'], 'raw-match')
        self.assertFalse((self.repo / 'FILTER_RAN').exists())

    def test_inherited_git_environment_ignored(self):
        self.add()
        old = os.environ.get('GIT_DIR')
        try:
            os.environ['GIT_DIR'] = str(self.repo / 'does-not-exist')
            self.assertEqual(self.entry()['state'], 'raw-match')
        finally:
            if old is None:
                os.environ.pop('GIT_DIR', None)
            else:
                os.environ['GIT_DIR'] = old

    def test_directory_replacing_file(self):
        path = self.add()
        path.unlink()
        path.mkdir()
        self.assertEqual(self.entry()['state'], 'type-changed')

    def test_bare_repository_is_error(self):
        bare = self.repo / 'bare'
        bare.mkdir()
        command(bare, 'init', '--bare', '-q')
        with self.assertRaises(AuditError):
            audit(bare)

    def test_sha256(self):
        repo = self.repo / 'sha256'
        repo.mkdir()
        command(repo, 'init', '--object-format=sha256', '-q')
        command(repo, 'config', 'core.autocrlf', 'false')
        (repo / 'f').write_bytes(b'test')
        command(repo, 'add', 'f')
        command(repo, 'update-index', '--assume-unchanged', 'f')
        report = audit(repo)
        self.assertEqual(report['object_format'], 'sha256')
        self.assertEqual(report['entries'][0]['state'], 'raw-match')

    def test_linked_worktree(self):
        self.add(flag=None)
        command(self.repo, 'commit', '-qm', 'Fixture')
        linked = self.repo / 'linked'
        command(self.repo, 'worktree', 'add', '--detach', str(linked))
        command(linked, 'update-index', '--assume-unchanged', 'config.txt')
        (linked / 'config.txt').write_bytes(b'changed')
        self.assertEqual(audit(linked)['entries'][0]['state'], 'raw-different')
        self.assertEqual(audit(self.repo)['flagged'], 0)

    @unittest.skipIf(os.name == 'nt', 'Real POSIX symlink fixture runs in Linux CI')
    def test_parent_symlink_not_followed(self):
        self.add('dir/file')
        (self.repo / 'dir/file').unlink()
        (self.repo / 'dir').rmdir()
        os.symlink(self.repo, self.repo / 'dir')
        self.assertEqual(self.entry()['state'], 'not-inspected')

    @unittest.skipIf(os.name == 'nt', 'Real POSIX symlink fixture runs in Linux CI')
    def test_symlink_target_comparison(self):
        os.symlink('absent-target', self.repo / 'link')
        command(self.repo, 'add', 'link')
        command(self.repo, 'update-index', '--assume-unchanged', 'link')
        self.assertEqual(self.entry()['state'], 'raw-match')
        (self.repo / 'link').unlink()
        os.symlink('different-target', self.repo / 'link')
        self.assertEqual(self.entry()['state'], 'raw-different')

    def test_parser_and_path_rejections(self):
        with self.assertRaises(AuditError):
            parse_entries(b'h bad', 10)
        for path in ('../a', '/a', 'a/../b', 'a//b'):
            with self.subTest(path=path), self.assertRaises(AuditError):
                checked_path(self.repo, path)
        self.assertEqual(blob_hash(b'hello', 'sha1'), 'b6fc4c620b67d95f953a5c1c1230aaab5db5a1b0')


if __name__ == '__main__':
    unittest.main()
