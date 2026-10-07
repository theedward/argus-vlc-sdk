# Argus VLC SDK

Pinned VLC/VLCKit source builds for the Argus iOS player, targeting arm64 iPhone
and simulator on iOS 17 or later. Argus uses AVPlayer for native formats and
VLCKit as a fallback for confirmed MPEG-TS streams.

This repository contains the dependency build scripts, Argus library patches,
privacy manifest and component notices. It does not contain the Argus app.
Versioned releases will pair each verified SDK with its exact corresponding
source package, build records and checksums. A successful build alone is not a
claim of App Store approval.

## Build

The source-only workflow pins the wrapper and VLC revisions, verifies patches,
builds both platforms, checks component configurations and packages notices.
It does not publish an app. Use the recorded Xcode and GNU Make toolchain.

```sh
python3 scripts/prepare-vlc-source.py --cache .cache --destination build/source
```

The workflow in `.github/workflows/vlc-source-build.yml` contains the complete
compile, inventory and packaging sequence. Each source release includes
`REBUILD.md` and the original dependency archives to reproduce that version.

## Licenses

VLCKit/libVLC are used under LGPL 2.1-or-later; bundled components retain their
individual licenses. The selected build disables GPL/nonfree FFmpeg options and
unused GPL teletext code. Original license and copyright texts are authoritative.
Argus changes to upstream files retain those files' license terms; the build and
packaging scripts provided here are LGPL 2.1-or-later. See `COPYING.LIB`, component
notices and the corresponding source package. No warranty is provided.

VLC and VideoLAN are trademarks of VideoLAN. This is an Argus-maintained build,
not an official VideoLAN release.

## Automatic picture in picture policy

The Argus source overlay adds the optional public method
`setAutomaticPictureInPictureEnabled:` to the PiP window controller protocol.
On iOS it updates Apple's automatic inline-entry property on the main thread,
without restarting playback or presenting a window. Main-thread callers receive
an immediate update; off-main callers are queued. Closing a controller disables
automatic entry, and a queued update after teardown is harmless. Clients still
own preference handling and stopping an existing PiP window.

The wrapper header and VLC implementation are separately checksum-pinned.
`python3 scripts/test-pip-policy.py PATH_TO_PREPARED_SOURCE` checks policy dispatch,
teardown and public-header compilation for both iOS platforms. This does not
prove automatic PiP on a phone; the built SDK and app must be tested separately.
