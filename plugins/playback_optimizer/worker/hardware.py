"""Probe mapped render nodes; never infer support from CPU names or file presence."""
import os
from pathlib import Path
import re
import subprocess
import time


class HardwareDetector:
    def __init__(self, render_root=Path('/dev/dri'), sys_root=Path('/sys/class/drm')):
        self.render_root, self.sys_root = render_root, sys_root
        self.checked = -float('inf')
        self.report = {'available': False, 'reason': 'No supported GPU'}
        self.env = dict(os.environ)

    def probe(self):
        if time.monotonic() - self.checked < 30:
            return self.report
        self.checked = time.monotonic()
        self.report = {'available': False, 'reason': 'No mapped Intel/AMD render node; NVIDIA backend is not implemented'}
        requested = os.environ.get('TRANSCODE_RENDER_DEVICE', '')
        nodes = sorted(self.render_root.glob('renderD*'))
        if requested:
            nodes = [node for node in nodes if str(node) == requested]
        for node in nodes:
            if not re.fullmatch(r'renderD\d+', node.name):
                continue
            try:
                vendor = (self.sys_root / node.name / 'device/vendor').read_text().strip().lower()
            except OSError:
                continue
            if vendor not in {'0x8086', '0x1002'}:
                continue
            env = dict(os.environ)
            # The modern Intel stack is isolated from stable Mesa/AMD libraries.
            if vendor == '0x8086':
                prefix = '/opt/intel-modern/usr/lib/x86_64-linux-gnu'
                env.update(LIBVA_DRIVER_NAME='iHD', LIBVA_DRIVERS_PATH=prefix + '/dri', LD_LIBRARY_PATH=prefix)
            else:
                env.update(LIBVA_DRIVER_NAME='radeonsi')
                env.pop('LIBVA_DRIVERS_PATH', None)
                env.pop('LD_LIBRARY_PATH', None)
            try:
                result = subprocess.run(['vainfo', '--display', 'drm', '--device', str(node)],
                    env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5)
                text = result.stdout.decode(errors='replace')
            except (OSError, subprocess.TimeoutExpired):
                result, text = None, ''
            encoding = bool(re.search(r'VAProfileH264High\s*:\s*VAEntrypointEncSlice(?:LP)?\b', text))
            codecs = [codec for codec, profile in [('av1', 'AV1Profile0'), ('h264', 'H264'), ('hevc', 'HEVCMain'), ('vp9', 'VP9Profile0')]
                      if re.search(r'VAProfile' + profile + r'\w*\s*:\s*VAEntrypointVLD\b', text)]
            if result is not None and result.returncode == 0 and encoding and codecs:
                self.env = env
                self.report = {'available': True, 'device': str(node), 'vendor': 'intel' if vendor == '0x8086' else 'amd',
                               'backend': 'vaapi', 'driver': env['LIBVA_DRIVER_NAME'], 'decodeCodecs': codecs,
                               'encodeCodec': 'h264', 'driverInitialized': True}
                return self.report
            self.report = {'available': False, 'vendor': 'intel' if vendor == '0x8086' else 'amd',
                           'reason': 'Driver initialization or hardware H.264 encode/decode probe failed'}
        return self.report
