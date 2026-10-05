#!/usr/bin/env python3
"""Reconcile every installed iOS contrib library with pinned sources/notices.

Run again for the final SDK. Installed libraries are a conservative superset of
what the framework linker retains; header and build tools are also recorded.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--record', type=Path, required=True)
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
record = json.loads((args.record / 'build-record.json').read_text())
definitions = json.loads((root / 'compliance/vlc/components.json').read_text())
aliases = {'ass': 'libass', 'dvbpsi': 'libdvbpsi', 'freetype2': 'freetype',
           'gpg-error': 'libgpg-error', 'modplug': 'libmodplug',
           'ogg': 'libogg', 'theora': 'libtheora', 'vorbis': 'libvorbis',
           'vpx': 'libvpx', 'shout': 'libshout'}
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
libraries = [item for item in record['installedStaticLibraries']
             if re.fullmatch(r'vlc/contrib/arm64-iphone(?:os|simulator)[^/]+/lib/[^/]+', item['path'])]
unmapped = {item['path'] for item in libraries}
components = []
for definition in definitions:
    selected = [item for item in libraries if Path(item['path']).name in definition['libraries']]
    if not selected:
        continue
    unmapped.difference_update(item['path'] for item in selected)
    recipe = args.source / 'vlc/contrib/src' / definition['recipe']
    if not recipe.is_dir():
        raise SystemExit('Missing recipe: ' + definition['recipe'])
    inputs = [item for item in record['downloadedInputs']
              if Path(item['path']).name.startswith(definition['sourcePrefix'])]
    if not inputs:
        raise SystemExit('Missing exact source input: ' + definition['recipe'])
    source_name = aliases.get(definition['recipe'], definition['recipe'])
    notices = [item for item in record['sourceNoticeCandidates']
               if source_name in Path(item['path']).parts]
    # Old recorder missed Copyright, COPYRIGHT and FTL.TXT. Verified archive
    # copies fill these gaps; the revised recorder captures them on fresh builds.
    extras = list((root / 'compliance/vlc/extra-notices' / definition['recipe']).glob('*'))
    extra_notices = [{'path': str(p.relative_to(root)), 'sha256': sha(p)} for p in extras if p.is_file()]
    if not notices and not extra_notices:
        raise SystemExit('Missing notice evidence: ' + definition['recipe'])
    components.append({**definition, 'inputs': inputs, 'installedLibraries': selected,
                       'noticeEvidence': notices, 'additionalNotices': extra_notices,
                       'recipeFiles': [{'path': str(p.relative_to(args.source)), 'sha256': sha(p)}
                                       for p in sorted(recipe.rglob('*')) if p.is_file()],
                       'sourceLocation': 'Corresponding-source archive: inputs/ plus pinned VLC source and build recipes'})
if unmapped:
    raise SystemExit('Unmapped libraries: ' + ', '.join(sorted(unmapped)))
report = {'wrapperCommit': record['wrapperCommit'], 'baseCommit': record['baseCommit'],
          'patchedTree': record['patchedTree'], 'components': components,
          'installedLibraryCount': len(libraries), 'unmappedLibraries': [],
          'allDownloadedInputs': record['downloadedInputs'],
          'configurationEvidence': record['configurations'],
          'releaseBlockers': [c['recipe'] for c in components if 'REMOVE' in c['license']],
          'scope': 'Exact installed-library source/recipe/notice inventory; regenerate after SDK changes. License texts and individual source notices remain authoritative.'}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'components': len(components), 'installedLibraries': len(libraries), 'unmapped': 0, 'releaseBlockers': report['releaseBlockers']}))
