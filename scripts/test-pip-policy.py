#!/usr/bin/env python3
"""Compile the actual setter against a test controller; exercise queue/teardown.

This tests policy dispatch, not Apple automatic PiP presentation. The complete
SDK candidate is built independently on both iOS platforms.
"""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path)
args = parser.parse_args()
text = (args.source / 'vlc/modules/video_output/apple/VLCPictureInPictureController.m').read_text()
start = text.index('- (void)setAutomaticPictureInPictureEnabled:')
end = text.index('\n- (void)close {', start)
method = text[start:end]
fixture = '''
#import <Foundation/Foundation.h>
#undef TARGET_OS_IOS
#define TARGET_OS_IOS 1
@interface AVPictureInPictureController : NSObject
@property BOOL canStartPictureInPictureAutomaticallyFromInline;
@end
@implementation AVPictureInPictureController
@end
@interface PolicyController : NSObject {
@public NSObject *_avPipController;
}
- (void)setAutomaticPictureInPictureEnabled:(BOOL)enabled;
@end
@implementation PolicyController
METHOD
@end
static void drain(void) {
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:0.1];
    while ([deadline timeIntervalSinceNow] > 0)
        [[NSRunLoop mainRunLoop] runMode:NSDefaultRunLoopMode beforeDate:deadline];
}
int main(void) {
    @autoreleasepool {
        PolicyController *bridge = [PolicyController new];
        AVPictureInPictureController *window = [AVPictureInPictureController new];
        bridge->_avPipController = window;
        [bridge setAutomaticPictureInPictureEnabled:YES];
        NSCAssert(window.canStartPictureInPictureAutomaticallyFromInline, @"Immediate main-thread enable");
        [bridge setAutomaticPictureInPictureEnabled:NO];
        NSCAssert(!window.canStartPictureInPictureAutomaticallyFromInline, @"Immediate main-thread disable");
        {
            dispatch_semaphore_t done = dispatch_semaphore_create(0);
            dispatch_async(dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{
                [bridge setAutomaticPictureInPictureEnabled:YES];
                dispatch_semaphore_signal(done);
            });
            dispatch_semaphore_wait(done, DISPATCH_TIME_FOREVER);
        }
        NSCAssert(!window.canStartPictureInPictureAutomaticallyFromInline, @"Worker defers UI update");
        drain();
        NSCAssert(window.canStartPictureInPictureAutomaticallyFromInline, @"Main queue applies update");
        [bridge setAutomaticPictureInPictureEnabled:NO];
        {
            dispatch_semaphore_t done = dispatch_semaphore_create(0);
            dispatch_async(dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{
                [bridge setAutomaticPictureInPictureEnabled:YES];
                dispatch_semaphore_signal(done);
            });
            dispatch_semaphore_wait(done, DISPATCH_TIME_FOREVER);
        }
        bridge->_avPipController = nil;
        drain();
        NSCAssert(!window.canStartPictureInPictureAutomaticallyFromInline, @"Queued update cannot re-enable detached window");
        [bridge setAutomaticPictureInPictureEnabled:YES];
    }
    return 0;
}
'''.replace('METHOD', method)
with tempfile.TemporaryDirectory(prefix='argus-pip-policy-') as directory:
    root = Path(directory)
    source = root / 'policy.m'
    source.write_text(fixture)
    subprocess.run(['xcrun', 'clang', '-fobjc-arc', '-fblocks', '-framework', 'Foundation', str(source), '-o', str(root / 'policy')], check=True)
    subprocess.run([str(root / 'policy')], check=True)
    # Compile each public protocol against the real iOS SDK on both platforms.
    for header in [args.source / 'VLCKit/Headers/Public/Video/VLCDrawable.h', args.source / 'vlc/modules/video_output/apple/VLCDrawable.h']:
        source.write_text('#import "' + str(header) + '"\nvoid update(id<VLCPictureInPictureWindowControlling> controller) { [controller setAutomaticPictureInPictureEnabled:NO]; }\n')
        for sdk, target in [('iphoneos', 'arm64-apple-ios17.0'), ('iphonesimulator', 'arm64-apple-ios17.0-simulator')]:
            sdkroot = subprocess.check_output(['xcrun', '--sdk', sdk, '--show-sdk-path'], text=True).strip()
            subprocess.run(['xcrun', 'clang', '-fsyntax-only', '-Werror', '-fobjc-arc', '-fblocks', '-target', target, '-isysroot', sdkroot, str(source)], check=True)
print(json.dumps({'mainEnableDisable': True, 'workerUsesMainQueue': True, 'queuedAfterCloseIsNoOp': True,
                  'nilControllerIsSafe': True, 'publicHeadersCompileForBothPlatforms': True,
                  'scope': 'Extracted source method dispatch and public API compilation; not PiP window proof'}))
