#!/usr/bin/env python3
"""Preserve complete corresponding library sources alongside the built SDK.

The prepared VLC repo has only public upstream sources and Argus library patches.
No app checkout, provider data, signing assets or runner credentials are exported.
"""
import argparse
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--record', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
record = json.loads((args.record / 'build-record.json').read_text())
args.output.parent.mkdir(parents=True, exist_ok=True)

def digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def add_bytes(tar, name, value):
    info = tarfile.TarInfo(name)
    info.size = len(value)
    info.mode = 0o644
    tar.addfile(info, io.BytesIO(value))

with tarfile.open(args.output, 'w:xz', preset=3) as tar:
    vlc = args.source / 'vlc'
    # Export tracked source, not generated objects/build products. Preserve the
    # shallow Git object store/boundary so offline version generation still works.
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=vlc).decode().split('\0')
    for name in names:
        if name:
            tar.add(vlc / name, arcname='vlc/' + name, recursive=False)
    for name in ('HEAD', 'index', 'shallow', 'objects', 'refs', 'packed-refs'):
        path = vlc / '.git' / name
        if path.exists():
            tar.add(path, arcname='vlc/.git/' + name)
    add_bytes(tar, 'vlc/.git/config', b'[core]\nrepositoryformatversion = 0\nfilemode = true\nbare = false\n')
    wrapper = args.source / 'VLCKit'
    for path in sorted(wrapper.rglob('*')):
        relative = path.relative_to(wrapper)
        if 'build' in relative.parts or '.git' in relative.parts:
            continue
        if path.is_file() or path.is_symlink():
            tar.add(path, arcname='VLCKit/' + relative.as_posix(), recursive=False)
    for entry in record['downloadedInputs']:
        path = args.source / entry['path']
        digest = digest_file(path)
        if digest != entry['sha256']:
            raise SystemExit('Source input changed after build')
        # Restore exact archives to the locations the offline recipes expect.
        tar.add(path, arcname=entry['path'], recursive=False)
    tar.add(args.record, arcname='build-evidence')
    tar.add(root / 'compliance/vlc', arcname='compliance/vlc')
    tar.add(args.source / 'source-record.json', arcname='source-record.json', recursive=False)
    for name in ('prepare-vlc-source.py', 'verify-vlc-candidate.py',
                 'record-vlc-build.py', 'inventory-vlc.py',
                 'package-vlc-sdk.py', 'package-vlc-source.py'):
        tar.add(root / 'scripts' / name, arcname='scripts/' + name, recursive=False)
    tar.add(root / '.github/workflows/vlc-source-build.yml',
            arcname='.github/workflows/vlc-source-build.yml', recursive=False)
    add_bytes(tar, 'REBUILD.md', b'''# Argus VLC corresponding source

This package contains the exact patched VLC tree, wrapper, contribution/build-tool
source archives, recipes, configuration records, notices and Argus library changes.
The shallow Git boundary is preserved; no network Git checkout is required.

Use a Mac with the Xcode version recorded in build-evidence/build-record.json and
at least 12 GiB free. Install the recorded build prerequisites (GNU Make, autoconf,
automake, libtool, pkg-config, gettext, cmake, ninja). Set PATH to Homebrew GNU Make
and gettext, MAKE to gmake, MAKEFLAGS to -j3, and select the recorded Xcode using
DEVELOPER_DIR. The wrapper already links libvlc/vlc to ../../vlc.

From VLCKit run:
./compileAndBuildVLCKit.sh -v -r -f -e ../vlc

Original dependency archives are restored in vlc/contrib/tarballs and
vlc/extras/tools; rebuilding uses those exact inputs rather than current releases.
The wrapper emits build/iOS/VLCKit.xcframework with arm64 iPhone/simulator slices.
Argus's exact build/packaging scripts and source-only workflow are included.
For those scripts, pass the unpacked source root via --source. The workflow
records the packaging sequence; build-evidence holds the original configurations.
The source tree is already patched: do not reapply the preparation overlay. Source changes retain the upstream LGPL/permissive
terms; individual source and license files are authoritative. No warranty.
''')
digest = digest_file(args.output)
receipt = {'file': args.output.name, 'bytes': args.output.stat().st_size,
           'sha256': digest, 'patchedTree': record['patchedTree'],
           'inputArchives': len(record['downloadedInputs'])}
(args.output.parent / 'corresponding-source-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))
