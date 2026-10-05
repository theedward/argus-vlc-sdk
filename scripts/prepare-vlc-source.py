#!/usr/bin/env python3
"""Prepare an immutable, Argus-owned VLC source-build candidate; never replace the SDK."""
import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import zipfile
import urllib.request
from pathlib import Path

WRAPPER = 'c942becdc4d5db8d7631a31e5f5fb2ac84e3df17'
BASE = '005e69e67a8730f128e44bde68437fbb048cf45f'
PINS = {'nightly-date-wrapper-source.zip': 'af20eeb63ea2eb81d2c7480656e319b1172ac3a871338fe3801341233d5bd5fb'}
parser = argparse.ArgumentParser()
parser.add_argument('--cache', type=Path, default=Path('/tmp/argus-ts-spike'))
parser.add_argument('--destination', type=Path, default=Path('/tmp/argus-vlc-source-build'))
args = parser.parse_args()
def git(*parts, cwd):
    env = os.environ.copy()
    # Do not inherit a temporary object-store override from app delivery commands.
    env.pop('GIT_OBJECT_DIRECTORY', None); env.pop('GIT_ALTERNATE_OBJECT_DIRECTORIES', None)
    return subprocess.check_output(['git', *parts], cwd=cwd, env=env, text=True).strip()
archive = args.cache / 'nightly-date-wrapper-source.zip'
if not archive.exists():
    args.cache.mkdir(parents=True, exist_ok=True)
    url = 'https://github.com/videolan/vlckit/archive/' + WRAPPER + '.zip'
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(8_000_001)
    if len(data) > 8_000_000: raise SystemExit('Wrapper archive exceeds size budget')
    if hashlib.sha256(data).hexdigest() != PINS[archive.name]: raise SystemExit('Downloaded wrapper checksum mismatch')
    temporary = archive.with_suffix('.partial')
    temporary.write_bytes(data)
    temporary.rename(archive)
if hashlib.sha256(archive.read_bytes()).hexdigest() != PINS[archive.name]: raise SystemExit('Wrapper archive checksum mismatch')
if args.destination.exists(): raise SystemExit('Destination exists; use a fresh destination to preserve previous work')
args.destination.mkdir(parents=True)
wrapper = args.destination / 'VLCKit'
wrapper.mkdir()
with zipfile.ZipFile(archive) as zipped:
    prefix = 'vlckit-' + WRAPPER + '/'
    for name in zipped.namelist():
        if not name.startswith(prefix): raise SystemExit('Unexpected source archive root')
        relative = Path(name[len(prefix):])
        if '..' in relative.parts or relative.is_absolute(): raise SystemExit('Unsafe source archive path')
        if name.endswith('/'): (wrapper / relative).mkdir(parents=True, exist_ok=True); continue
        mode = zipped.getinfo(name).external_attr >> 16
        if stat.S_ISLNK(mode):
            target = zipped.read(name).decode()
            resolved = (wrapper / relative).parent.joinpath(target).resolve()
            if not resolved.is_relative_to(wrapper.resolve()): raise SystemExit('Unsafe source archive symlink')
            (wrapper / relative).parent.mkdir(parents=True, exist_ok=True)
            (wrapper / relative).symlink_to(target)
            continue
        path = wrapper / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(zipped.read(name))
        path.chmod(0o755 if mode & 0o111 else 0o644)
vlc = args.destination / 'vlc'
vlc.mkdir()
git('init', '-q', cwd=vlc)
git('config', 'user.name', 'Argus Source Build', cwd=vlc)
git('config', 'user.email', 'argus-build@localhost', cwd=vlc)
git('fetch', '--depth=1', 'https://github.com/videolan/vlc.git', BASE, cwd=vlc)
git('checkout', '--detach', 'FETCH_HEAD', cwd=vlc)
if git('rev-parse', 'HEAD', cwd=vlc) != BASE: raise SystemExit('Base commit mismatch')
patches = sorted((wrapper / 'libvlc/patches').glob('*.patch'))
if len(patches) != 12: raise SystemExit('Expected exactly 12 pinned wrapper patches')
git('am', '--committer-date-is-author-date', *(str(p.resolve()) for p in patches), cwd=vlc)
if git('status', '--porcelain', cwd=vlc): raise SystemExit('Patched source is unexpectedly dirty')
if git('rev-parse', 'HEAD^{tree}', cwd=vlc) != '9cb4e084a5e41ba0f7037c209884d8816ef929ad':
    raise SystemExit('Patched source tree differs from reviewed input')
# Apply the reviewed Argus iOS privacy/component overlay after verifying the upstream tree.
root = Path(__file__).resolve().parents[1]
argus_patches = sorted((root / 'compliance/vlc/patches').glob('*.patch'))
if len(argus_patches) != 1:
    raise SystemExit('Expected the reviewed Argus iOS source overlay')
for patch in argus_patches:
    if hashlib.sha256(patch.read_bytes()).hexdigest() != '3499ac2baf9c62344004dd298f43bb79ce2259705479d333814f68b5d9017157':
        raise SystemExit('Unreviewed Argus source overlay')
    git('apply', '--check', str(patch.resolve()), cwd=vlc)
    git('apply', str(patch.resolve()), cwd=vlc)
git('add', '.', cwd=vlc)
git('commit', '-q', '-m', 'Argus iOS playback and privacy configuration', cwd=vlc)
if git('rev-parse', 'HEAD^{tree}', cwd=vlc) != '911aa4f783310e0791254b747abede299c55ad0d':
    raise SystemExit('Argus source tree differs from reviewed overlay')
# Xcode's header and static-library references remain relative to libvlc/vlc,
# even when the shell wrapper receives an external source path.
(wrapper / 'libvlc/vlc').symlink_to('../../vlc', target_is_directory=True)
# The upstream single-arch selector treats aarch64 as device-only. Keep its
# two-platform route, but omit the Intel simulator from this arm64 candidate.
build_script = wrapper / 'compileAndBuildVLCKit.sh'
original = build_script.read_bytes()
if hashlib.sha256(original).hexdigest() != '9b4fba897585e2a5a036bb7d6cf90ef47a43d2d760438d5b3b6df3d7e9b36552':
    raise SystemExit('Unexpected wrapper build script')
text = original.decode()
text = text.replace('\n', '\n# Modified by Argus, 2026-10-05: iOS 17 minimum and arm64 simulator build.\n', 1)
ios_arches = '''        if [ "$IOS" = "yes" ]; then
            if [ "$PLATFORM" = "iphonesimulator" ]; then
                architectures="x86_64 arm64"'''
intel_build = '                    buildLibVLC "x86_64" $PLATFORM\n'
if text.count(ios_arches) != 1 or text.count(intel_build) != 1:
    raise SystemExit('Unexpected iOS architecture selection')
text = text.replace('SDK_MIN=9.0', 'SDK_MIN=17.0')
text = text.replace(ios_arches, ios_arches.replace('x86_64 arm64', 'arm64')).replace(intel_build, '')
build_script.write_text(text)
report = {'wrapperArchiveSHA256': PINS[archive.name], 'wrapperCommit': WRAPPER, 'baseCommit': BASE,
    'upstreamPatchedTree': '9cb4e084a5e41ba0f7037c209884d8816ef929ad',
    'patchedCommit': git('rev-parse', 'HEAD', cwd=vlc), 'patchedTree': git('rev-parse', 'HEAD^{tree}', cwd=vlc),
    'argusPatches': [{'name': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in argus_patches],
    'patches': [{'name': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in patches],
    'wrapperBuildOverlay': {'originalSHA256': hashlib.sha256(original).hexdigest(),
        'modifiedSHA256': hashlib.sha256(build_script.read_bytes()).hexdigest(),
        'changes': ['iOS simulator arm64 only', 'omit Intel simulator compilation', 'iOS minimum 17.0 matching Argus'],
        'sourceLink': 'VLCKit/libvlc/vlc -> ../../vlc'},
    'buildCommand': './compileAndBuildVLCKit.sh -v -r -f -e ../vlc',
    'state': 'source prepared; binary not built or selected',
    'nightlyReproductionClaimed': False, 'distributionReady': False}
(args.destination / 'source-record.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
print(json.dumps(report, sort_keys=True))
