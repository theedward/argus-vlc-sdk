#!/usr/bin/env python3
"""Seal a freshly built Argus SDK with reviewed privacy metadata and notices.

Never run this on the downloaded immutable baseline. Run in the source builder,
before recording final output hashes and publishing any dependency artifact.
"""
import argparse
import hashlib
import json
import plistlib
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--record', type=Path, required=True)
parser.add_argument('--inventory', type=Path, required=True)
args = parser.parse_args()
source = json.loads((args.source / 'source-record.json').read_text())
if source['patchedTree'] != '911aa4f783310e0791254b747abede299c55ad0d':
    raise SystemExit('Only the reviewed Argus iOS source tree can be packaged')
inventory = json.loads(args.inventory.read_text())
if inventory['unmappedLibraries'] or inventory['releaseBlockers']:
    raise SystemExit('Unreviewed/mixed-license component in final SDK')
removed = {'zvbi', 'protobuf', 'opencv4', 'libarchive', 'librist'}
if any(c['recipe'] in removed for c in inventory['components']):
    raise SystemExit('An excluded component remains installed')
# Reject incompatible configurations instead of inferring licensing/privacy
# from the wrapper's requested configure flags.
build = json.loads((args.record / 'build-record.json').read_text())
for component, required in {
    'ffmpeg': ('#define CONFIG_GPL 0', '#define CONFIG_VERSION3 0',
               '#define CONFIG_NONFREE 0', '#define HAVE_ARC4RANDOM_BUF 1'),
    'gcrypt': ('#define USE_RNDGETENTROPY 1',),
}.items():
    headers = [args.record / 'configurations' / entry['path']
               for entry in build['configurations']
               if '/' + component + '/vlc_build/config.h' in entry['path']]
    if len(headers) != 2:
        raise SystemExit('Missing both platform contribution configurations')
    for header in headers:
        text = header.read_text()
        if not all(line in text.splitlines() for line in required):
            raise SystemExit('Unreviewed contribution build configuration')
        if component == 'gcrypt' and '#define USE_RNDOLDLINUX 1' in text.splitlines():
            raise SystemExit('Legacy entropy-device backend remains enabled')
for entry in build['installedStaticLibraries']:
    if entry['path'].endswith('/libfreetype.a') or Path(entry['path']).name.startswith('libharfbuzz'):
        imports = subprocess.check_output(['xcrun', 'nm', '-u', str(args.source / entry['path'])], text=True)
        if any(line.split()[-1] in {'_fstat', '_fstat64'}
               for line in imports.splitlines() if line.split()):
            raise SystemExit('System-font metadata reader remains in text libraries')
catalog = []
for component in inventory['components']:
    texts = []
    seen = set()
    for entry in component['noticeEvidence'] + component['additionalNotices']:
        if entry['sha256'] in seen:
            continue
        seen.add(entry['sha256'])
        if entry['path'].startswith('compliance/'):
            path = root / entry['path']
        else:
            path = args.record / 'source-notices' / entry['path']
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise SystemExit('Notice checksum mismatch')
        texts.append({'name': path.name, 'text': data.decode(errors='replace')})
    if not texts:
        raise SystemExit('Component has no packaged notice')
    credits = {
        'freetype2': 'This software is based in part on the work of the FreeType Team (https://freetype.org).',
        'jpeg': 'This software is based in part on the work of the Independent JPEG Group.',
    }
    if component['recipe'] in credits:
        texts.insert(0, {'name': 'Acknowledgement', 'text': credits[component['recipe']]})
    catalog.append({'name': component['recipe'], 'license': component['license'],
                    'sources': [Path(x['path']).name for x in component['inputs']],
                    'notices': texts})
for name, directory in [('VLCKit', args.source / 'VLCKit'), ('VLC', args.source / 'vlc')]:
    texts = [{'name': p.name, 'text': p.read_text(errors='replace')}
             for p in sorted(directory.iterdir()) if p.is_file()
             and p.name.upper() in {'COPYING', 'COPYING.LIB', 'AUTHORS', 'LICENSE'}]
    if not texts:
        raise SystemExit('Missing core/wrapper notices')
    catalog.insert(0, {'name': name, 'license': 'LGPL-2.1-or-later',
                       'sources': [source['wrapperCommit'] if name == 'VLCKit' else source['patchedTree']],
                       'notices': texts})
sdk = args.source / 'VLCKit/build/iOS/VLCKit.xcframework'
info = plistlib.loads((sdk / 'Info.plist').read_bytes())
report = []
for platform in info['AvailableLibraries']:
    framework = sdk / platform['LibraryIdentifier'] / platform['LibraryPath']
    imports = subprocess.check_output(['nm', '-u', str(framework / 'VLCKit')], text=True)
    forbidden = {'_fstatfs', '_statfs', '_fstatvfs', '_statvfs'}
    if any(line.split()[-1] in forbidden for line in imports.splitlines() if line.split()):
        raise SystemExit('Unexplained disk API remains in final framework')
    if 'protobuf' in subprocess.check_output(['nm', '-g', str(framework / 'VLCKit')], text=True).lower():
        raise SystemExit('Excluded Protobuf code remains linked')
    # The contrib GPL switch does not govern VLC's own plugins. Inspect
    # local symbols too: plugin entry points are not exported by VLCKit.
    symbols = subprocess.check_output(['nm', str(framework / 'VLCKit')], text=True)
    excluded_modules = {
        '_vlc_entry__control_dummy', '_vlc_entry__logger_file',
        '_vlc_entry__logger_syslog', '_vlc_entry__services_discovery_libsap',
        '_vlc_entry__stream_out_libstream_out_rtp',
        '_vlc_entry__video_filter_rotate',
        '_vlc_entry__video_filter_deinterlace_libdeinterlace',
    }
    entries = {line.split()[-1] for line in symbols.splitlines() if line.split()}
    if '_vlc_entry__access_output_livehttp' not in entries:
        raise SystemExit('Required HLS output writer is missing from the candidate')
    if entries & excluded_modules:
        raise SystemExit('GPL-only VLC plugin remains in the LGPL SDK')
    if any('rist' in name for name in entries if name.startswith('_vlc_entry__')):
        raise SystemExit('Excluded RIST transport remains linked')
    shutil.copyfile(root / 'compliance/vlc/PrivacyInfo.xcprivacy', framework / 'PrivacyInfo.xcprivacy')
    bundle = framework / 'ArgusVLCNotices.bundle'
    bundle.mkdir(exist_ok=True)
    (bundle / 'Info.plist').write_bytes(plistlib.dumps({
        'CFBundleIdentifier': 'com.theedward.argus.vlc.notices',
        'CFBundleName': 'ArgusVLCNotices', 'CFBundlePackageType': 'BNDL',
        'CFBundleVersion': '1', 'CFBundleShortVersionString': '1'}))
    (bundle / 'Acknowledgements.json').write_text(json.dumps(catalog, indent=2) + '\n')
    (bundle / 'BuildProvenance.json').write_text(json.dumps(source, indent=2) + '\n')
    report.append({'slice': platform['LibraryIdentifier'], 'notices': len(catalog),
                   'privacyManifestSHA256': hashlib.sha256((framework / 'PrivacyInfo.xcprivacy').read_bytes()).hexdigest(),
                   'diskAPIImports': [], 'excludedGPLModuleSymbols': sorted(excluded_modules),
                   'activeModuleSymbols': sorted(name for name in entries if name.startswith('_vlc_entry__'))})
args.record.mkdir(parents=True, exist_ok=True)
(args.record / 'sdk-compliance-packaging.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
