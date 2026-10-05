#!/usr/bin/env python3
"""Record a source-only candidate's inputs/configuration; no provider or signing data."""
import argparse
import hashlib
import json
import subprocess
import shutil
import os
import re
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()
def version(command):
    result = subprocess.run(command, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else 'unavailable'
source_record = args.source / 'source-record.json'
record = json.loads(source_record.read_text()) if source_record.exists() else {'state': 'source preparation incomplete'}
record['toolchain'] = {'xcode': version(['xcodebuild', '-version']), 'clang': version(['clang', '--version']),
    'sdk': version(['xcodebuild', '-showsdks']), 'git': version(['git', '--version']),
    'make': version([os.environ.get('MAKE', 'make'), '--version']),
    'brewPackages': version(['brew', 'list', '--versions'])}
vlc = args.source / 'vlc'
configurations = []
for name in ['config.mak', 'config.h', 'config.status', 'static-libs-list', 'static-module-list.c']:
    for path in sorted(vlc.rglob(name)):
        if not path.is_file() or '.git' in path.parts: continue
        relative = path.relative_to(args.source)
        dest = args.output / 'configurations' / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        configurations.append({'path': relative.as_posix(), 'sha256': digest(path)})
override = os.environ.get('XCODE_XCCONFIG_FILE')
if override and Path(override).is_file():
    shutil.copyfile(override, args.output / 'unsigned-build.xcconfig')
    configurations.append({'path': 'unsigned-build.xcconfig', 'sha256': digest(Path(override))})
record['configurations'] = configurations
record['downloadedInputs'] = []
for parent in [vlc / 'contrib/tarballs', vlc / 'extras/tools']:
    if not parent.exists(): continue
    for path in sorted(parent.iterdir()):
        if not path.is_file() or path.name.startswith('.'): continue
        # tools.mak downloads directly into extras/tools, alongside checked-in files.
        if parent.name == 'tools' and not path.name.endswith(('.tar.gz', '.tgz', '.tar.bz2', '.tar.xz', '.tar.zst', '.zip')): continue
        record['downloadedInputs'].append({'path': path.relative_to(args.source).as_posix(), 'sha256': digest(path), 'bytes': path.stat().st_size})
record['installedStaticLibraries'] = [{'path': p.relative_to(args.source).as_posix(), 'sha256': digest(p)} for p in sorted((vlc / 'contrib').rglob('*.a')) if p.is_file() and p.parent.name == 'lib' and p.parent.parent.parent == vlc / 'contrib']
# Capture archive-member owners as review leads. An imported symbol does not
# establish its purpose or the approved privacy reason by itself.
covered_api = re.compile(r'\b_(?:f?stat(?:64|fs|vfs)?|lstat(?:64)?|getattrlist(?:bulk|at)?|gettimeofday|mach_absolute_time|clock_gettime|systemUptime)\b')
api_owners = []
for entry in record['installedStaticLibraries']:
    result = subprocess.run(['xcrun', 'nm', '-u', '-A', str(args.source / entry['path'])],
                            capture_output=True, text=True)
    if result.returncode:
        raise SystemExit('Cannot inspect compiled contribution archive')
    for line in result.stdout.splitlines():
        if covered_api.search(line):
            # Replace ephemeral runner roots; no stream input is ever supplied.
            api_owners.append(line.replace(str(args.source) + '/', ''))
(args.output / 'native-api-archive-owners.txt').write_text('\n'.join(sorted(set(api_owners))) + '\n')
record['nativeAPIArchiveOwners'] = {'file': 'native-api-archive-owners.txt',
                                  'sha256': digest(args.output / 'native-api-archive-owners.txt'),
                                  'reviewLeads': len(set(api_owners))}
record['contributionStamps'] = [p.relative_to(args.source).as_posix() for p in sorted((vlc / 'contrib').rglob('.*')) if p.is_file() and p.name not in ['.gitignore', '.gitkeep'] and not p.name.startswith('.sum-')]
record['sourceNoticeCandidates'] = []
for path in sorted((vlc / 'contrib').rglob('*')):
    if not path.is_file() or path.is_symlink(): continue
    if not any(path.name.upper().startswith(prefix) for prefix in ['COPYING', 'LICENSE', 'LICENCE', 'NOTICE', 'COPYRIGHT', 'AUTHORS', 'FTL.TXT']): continue
    relative = path.relative_to(args.source)
    dest = args.output / 'source-notices' / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, dest)
    record['sourceNoticeCandidates'].append({'path': relative.as_posix(), 'sha256': digest(path)})
sdk = args.source / 'VLCKit/build/iOS/VLCKit.xcframework'
record['builtSDKFiles'] = [{'path': p.relative_to(sdk).as_posix(), 'sha256': digest(p), 'bytes': p.stat().st_size} for p in sorted(sdk.rglob('*')) if p.is_file()] if sdk.exists() else []
record['binaryBuilt'] = bool(record['builtSDKFiles'])
record['distributionReady'] = False
(args.output / 'build-record.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
print(json.dumps({'binaryBuilt': record['binaryBuilt'], 'downloadedInputs': len(record['downloadedInputs']), 'installedLibraries': len(record['installedStaticLibraries']), 'distributionReady': False}))
