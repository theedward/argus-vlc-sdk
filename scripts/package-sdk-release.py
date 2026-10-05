#!/usr/bin/env python3
"""Create dependency-only release assets from a successfully audited build.

Provided under LGPL-2.1-or-later; see COPYING.LIB. This does not publish an app
or select the SDK in Argus. Application compatibility must be checked separately.
"""
import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--artifact', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--version', required=True)
parser.add_argument('--commit', required=True)
args = parser.parse_args()

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

artifact = args.artifact
build = json.loads((artifact / 'vlc-record/build-record.json').read_text())
inventory = json.loads((artifact / 'vlc-record/component-inventory.json').read_text())
packaging = json.loads((artifact / 'vlc-record/sdk-compliance-packaging.json').read_text())
receipt = json.loads((artifact / 'corresponding-source-receipt.json').read_text())
if not build['binaryBuilt'] or inventory['releaseBlockers'] or inventory['unmappedLibraries']:
    raise SystemExit('Build/component review did not pass')
if build['patchedTree'] != inventory['patchedTree'] or build['patchedTree'] != receipt['patchedTree']:
    raise SystemExit('Source identity mismatch')
if len(packaging) != 2 or any(p['diskAPIImports'] for p in packaging):
    raise SystemExit('Both reviewed platform packages are required')
for p in packaging:
    if not p.get('excludedGPLModuleSymbols') or set(p['excludedGPLModuleSymbols']) & set(p['activeModuleSymbols']):
        raise SystemExit('Missing/failed GPL module review')
sdk = artifact / 'vlc-source/VLCKit/build/iOS/VLCKit.xcframework'
files = build['builtSDKFiles']
if {str(p.relative_to(sdk)) for p in sdk.rglob('*') if p.is_file()} != {p['path'] for p in files}:
    raise SystemExit('Unrecorded/missing SDK files')
for item in files:
    p = sdk / item['path']
    if p.is_symlink() or p.stat().st_size != item['bytes'] or digest(p) != item['sha256']:
        raise SystemExit('SDK file checksum/size mismatch')
source = artifact / receipt['file']
if source.stat().st_size != receipt['bytes'] or digest(source) != receipt['sha256']:
    raise SystemExit('Corresponding-source checksum/size mismatch')
uuids = []
notice_hashes = set()
manifest_hashes = set()
for p in packaging:
    framework = sdk / p['slice'] / 'VLCKit.framework'
    output = subprocess.check_output(['xcrun', 'dwarfdump', '--uuid', str(framework / 'VLCKit')], text=True)
    uuids += [line.split()[1].lower() for line in output.splitlines() if line.startswith('UUID: ')]
    notice_hashes.add(digest(framework / 'ArgusVLCNotices.bundle/Acknowledgements.json'))
    manifest_hashes.add(digest(framework / 'PrivacyInfo.xcprivacy'))
if len(uuids) != 2 or len(set(uuids)) != 2 or len(notice_hashes) != 1 or len(manifest_hashes) != 1:
    raise SystemExit('Invalid binary identity or unequal platform notices/manifests')
args.output.mkdir(parents=True, exist_ok=True)
archive = args.output / ('ArgusVLCKit-' + args.version + '.zip')
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
    for item in files:
        zipped.write(sdk / item['path'], 'VLCKit.xcframework/' + item['path'])
base = 'https://github.com/theedward/argus-vlc-sdk/releases/download/' + args.version + '/'
release = {'state': 'candidate', 'version': args.version, 'sourceRepositoryCommit': args.commit,
    'patchedTree': build['patchedTree'], 'wrapperCommit': build['wrapperCommit'],
    'privacyManifestSHA256': next(iter(manifest_hashes)), 'noticesSHA256': next(iter(notice_hashes)),
    'binaryUUIDs': uuids, 'sdkFiles': files,
    'sdkArchive': {'url': base + archive.name, 'bytes': archive.stat().st_size, 'sha256': digest(archive)},
    'correspondingSource': dict(receipt, url=base + source.name),
    'componentCount': len(inventory['components']), 'installedLibraryCount': inventory['installedLibraryCount'],
    'scope': 'Dependency source/build checks passed; Argus compatibility/adoption still required'}
(args.output / 'vlc-sdk-release.json').write_text(json.dumps(release, indent=2) + '\n')
print(json.dumps({k:v for k,v in release.items() if k != 'sdkFiles'}, indent=2))
