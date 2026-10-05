#!/usr/bin/env python3
"""Require real arm64 iPhone and simulator frameworks before accepting a build."""
import json
import plistlib
import subprocess
import sys
from pathlib import Path

sdk = Path(sys.argv[1])
info = plistlib.loads((sdk / 'Info.plist').read_bytes())
slices = info['AvailableLibraries']
if len(slices) != 2:
    raise SystemExit('Candidate must contain exactly two iOS slices')
platforms = set()
for item in slices:
    if item['SupportedPlatform'] != 'ios' or item['SupportedArchitectures'] != ['arm64']:
        raise SystemExit('Unexpected candidate platform/architecture')
    variant = item.get('SupportedPlatformVariant', 'device')
    platforms.add(variant)
    framework = sdk / item['LibraryIdentifier'] / item['LibraryPath']
    binary = framework / 'VLCKit'
    arch = subprocess.check_output(['lipo', '-archs', str(binary)], text=True).strip()
    if arch != 'arm64': raise SystemExit('Binary architecture does not match metadata')
    build = subprocess.check_output(['xcrun', 'vtool', '-show-build', str(binary)], text=True)
    expected = 'IOSSIMULATOR' if variant == 'simulator' else 'IOS'
    actual = [line.split()[-1] for line in build.splitlines() if line.strip().startswith('platform ')]
    legacy_device = variant == 'device' and not actual and 'cmd LC_VERSION_MIN_IPHONEOS' in build
    if actual != [expected] and not legacy_device:
        raise SystemExit('Binary platform does not match metadata')
    if not (framework / 'Headers/VLCMediaPlayer.h').is_file():
        raise SystemExit('Missing public playback header')
if platforms != {'device', 'simulator'}:
    raise SystemExit('Both iPhone and simulator are required')
print(json.dumps({'candidateBuilt': True, 'platforms': sorted(platforms), 'architecture': 'arm64', 'distributionReady': False}))
