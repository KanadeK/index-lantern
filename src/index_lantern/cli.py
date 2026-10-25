import argparse
import json
from pathlib import Path

from . import __version__
from .core import audit
from .git import AuditError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Inspect files hidden by Git index flags.')
    parser.add_argument('repository', nargs='?', default='.')
    parser.add_argument('--json', action='store_true', help='One JSON report on stdout')
    parser.add_argument('--fail-on', choices=['divergent', 'flags', 'none'], default='divergent')
    parser.add_argument('--max-bytes', type=int, default=64 * 1024 * 1024)
    parser.add_argument('--max-entries', type=int, default=100_000)
    parser.add_argument('--version', action='version', version=__version__)
    args = parser.parse_args(argv)
    try:
        report = audit(Path(args.repository).resolve(), args.max_bytes, args.max_entries)
        divergent = any(report['counts'].get(s, 0) for s in (
            'raw-different', 'missing-assumed', 'type-changed'))
        code = 2 if not report['complete'] else int(
            (args.fail_on == 'divergent' and divergent) or
            (args.fail_on == 'flags' and report['flagged'] > 0))
    except (AuditError, OSError) as exc:
        report = {'schema_version': 1, 'complete': False, 'error': str(exc)}
        code = 2
    if args.json:
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    elif 'error' in report:
        print('Error: ' + report['error'])
    else:
        print(f"{report['flagged']} flagged path(s); raw comparison only")
        for entry in report['entries']:
            print(f"{entry['state']}: {json.dumps(entry['path'])} "
                  f"[{', '.join(entry['flags'])}]" +
                  (f" ({entry['reason']})" if 'reason' in entry else ''))
        print('Raw differences can be caused by Git checkout conversions. No flags were changed.')
    return code
