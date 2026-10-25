"""Read index flags, then hash flagged paths without Git content conversion."""

import hashlib
import os
import stat
from collections import Counter
from pathlib import Path

from .git import AuditError, git


def parse_entries(data: bytes, max_entries: int) -> list[dict]:
    records = data.split(b'\0')
    if records[-1] != b'':
        raise AuditError('Git returned a truncated index listing')
    if len(records) - 1 > max_entries:
        raise AuditError('Index entry limit exceeded; raise --max-entries deliberately')
    entries = []
    for record in records[:-1]:
        try:
            header, path = record.split(b'\t', 1)
            tag, mode, oid, stage = header.split(b' ')
            if tag.lower() == tag or tag == b'S':
                flags = []
                if tag.lower() == tag:
                    flags.append('assume-unchanged')
                if tag.upper() == b'S':
                    flags.append('skip-worktree')
                entries.append({'path': os.fsdecode(path), 'flags': flags,
                                'mode': mode.decode('ascii'), 'index_oid': oid.decode('ascii'),
                                'stage': int(stage)})
        except (ValueError, UnicodeError) as exc:
            raise AuditError('Cannot parse Git index listing') from exc
    return entries


def checked_path(root: Path, relative: str) -> Path:
    parts = relative.split('/')
    if any(p in ('', '.', '..') for p in parts):
        raise AuditError('Unsafe path in index')
    if os.name == 'nt' and any('\\' in p or ':' in p for p in parts):
        raise AuditError('Unsafe Windows path in index')
    candidate = root.joinpath(*parts)
    if not candidate.is_relative_to(root):
        raise AuditError('Path leaves worktree')
    parent = root
    for part in parts[:-1]:
        parent = parent / part
        try:
            info = parent.lstat()
        except FileNotFoundError:
            return candidate
        reparse = getattr(info, 'st_file_attributes', 0) & getattr(
            stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
        if stat.S_ISLNK(info.st_mode) or reparse:
            raise AuditError('Parent is a symlink or junction; path not followed')
        if not stat.S_ISDIR(info.st_mode):
            raise AuditError('Parent is not a directory')
    return candidate


def blob_hash(data: bytes, algorithm: str) -> str:
    return hashlib.new(algorithm, b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def inspect_entry(root: Path, entry: dict, algorithm: str, max_bytes: int) -> dict:
    result = dict(entry)
    try:
        if entry['stage'] != 0 or entry['mode'] not in ('100644', '100755', '120000'):
            raise AuditError('Unmerged entries and gitlinks cannot be byte-compared')
        path = checked_path(root, entry['path'])
        try:
            before = path.lstat()
        except FileNotFoundError:
            result['state'] = ('absent-skipped' if 'skip-worktree' in entry['flags']
                               else 'missing-assumed')
            return result
        reparse = getattr(before, 'st_file_attributes', 0) & getattr(
            stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
        if reparse and not stat.S_ISLNK(before.st_mode):
            raise AuditError('Windows reparse point not followed')
        if stat.S_ISLNK(before.st_mode):
            if entry['mode'] != '120000':
                result['state'] = 'type-changed'
                return result
            target = os.fsencode(os.readlink(path))
            oid = blob_hash(target, algorithm)
            size = len(target)
        elif stat.S_ISREG(before.st_mode):
            if before.st_size > max_bytes:
                raise AuditError('File exceeds --max-bytes')
            flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0)
            flags |= getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, 'rb') as stream:
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
                        before.st_dev, before.st_ino):
                    raise AuditError('File changed while opening')
                digest = hashlib.new(algorithm, b'blob ' + str(before.st_size).encode() + b'\0')
                size = 0
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise AuditError('File grew beyond --max-bytes')
                    digest.update(chunk)
                oid = digest.hexdigest()
        else:
            result['state'] = 'type-changed'
            return result
        after = path.lstat()
        if (before.st_size, before.st_mtime_ns, before.st_ino, before.st_mode) != (
                after.st_size, after.st_mtime_ns, after.st_ino, after.st_mode):
            raise AuditError('File changed during inspection')
        result.update(state='raw-match' if oid == entry['index_oid'] else 'raw-different',
                      bytes=size)
    except (OSError, AuditError) as exc:
        result.update(state='not-inspected', reason=str(exc) if isinstance(exc, AuditError)
                      else 'Filesystem access failed')
    return result


def audit(repo: Path, max_bytes: int = 64 * 1024 * 1024,
          max_entries: int = 100_000) -> dict:
    if max_bytes < 1 or max_entries < 1:
        raise AuditError('Limits must be positive')
    raw_root = git(repo, 'rev-parse', '--show-toplevel')
    root = Path(os.fsdecode(raw_root.removesuffix(b'\n'))).resolve()
    algorithm = git(root, 'rev-parse', '--show-object-format').decode().strip()
    if algorithm not in ('sha1', 'sha256'):
        raise AuditError('Unsupported Git object format')
    listing = git(root, 'ls-files', '--stage', '-v', '-z')
    entries = [inspect_entry(root, item, algorithm, max_bytes)
               for item in parse_entries(listing, max_entries)]
    # Detect flags/stages changing while files were being read. No index writes.
    if git(root, 'ls-files', '--stage', '-v', '-z') != listing:
        raise AuditError('Index changed during inspection; retry without concurrent writers')
    counts = dict(sorted(Counter(item['state'] for item in entries).items()))
    return {'schema_version': 1, 'object_format': algorithm, 'flagged': len(entries),
            'complete': not counts.get('not-inspected', 0), 'counts': counts,
            'entries': entries, 'comparison': 'raw bytes, no EOL/encoding/filter conversion'}
