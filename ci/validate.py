#!/usr/bin/env python3
"""Inspect actual packages and exercise their architecture/ABI/CLI contracts."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from prepare import kernel_release

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs)


def info(path):
    result = {}
    for line in run('bsdtar', '-xOf', str(path), '.PKGINFO').splitlines():
        if ' = ' in line:
            key, value = line.split(' = ', 1)
            result.setdefault(key, []).append(value)
    return result


def main():
    group, output = sys.argv[1], Path(sys.argv[2]).resolve()
    expected = {
        'kernel': {'linux-aarch64-emiya-rustpi', 'linux-aarch64-emiya-rustpi-headers', 'linux-aarch64-emiya-rustpi-rknpu'},
        'ffmpeg': {'ffmpeg'},
        'integration': {'jellyfin-ffmpeg-system-rustpi', 'emiya-rustpi-keyring'},
    }[group]
    packages = list(output.glob('*.pkg.tar.zst'))
    metadata = {info(p)['pkgname'][0]: (p, info(p)) for p in packages}
    assert set(metadata) == expected, set(metadata)
    with tempfile.TemporaryDirectory(prefix='rustpi-validate-') as directory:
        root = Path(directory)
        for name, (path, data) in metadata.items():
            assert data['arch'][0] in ('aarch64', 'any')
            entries = run('bsdtar', '-tf', str(path)).splitlines()
            assert all(not p.startswith('/') and '..' not in Path(p).parts for p in entries)
            subprocess.run(['bsdtar', '-xf', str(path), '-C', str(root)], check=True)
        if group == 'kernel':
            versions = {d['pkgver'][0] for _, d in metadata.values()}
            assert len(versions) == 1
            version = versions.pop()
            release = kernel_release(*version.rsplit('-', 1))
            tree = root / 'usr/lib/modules' / release
            assert tree.is_dir() and (tree / 'pkgbase').read_text().strip() == 'linux-aarch64-emiya-rustpi'
            for name in ('linux-aarch64-emiya-rustpi-headers', 'linux-aarch64-emiya-rustpi-rknpu'):
                assert f'linux-aarch64-emiya-rustpi={version}' in metadata[name][1]['depend']
            image = (tree / 'vmlinuz').read_bytes()
            assert image[:2] == b'MZ' and image[56:60] == b'ARMd', 'Missing ARM64 EFI stub'
            npu = tree / 'updates/rknpu.ko'
            assert run('modinfo', '-F', 'vermagic', str(npu)).split()[0] == release
            assert run('modinfo', '-F', 'name', str(npu)).strip() == 'rknpu'
            for p in (tree / 'build/scripts').rglob('*'):
                if p.is_file():
                    with p.open('rb') as f:
                        head = f.read(20)
                    if head[:4] == b'\x7fELF':
                        assert struct.unpack('<H', head[18:20])[0] == 183, p
            dtb = root / 'boot/dtbs/linux-aarch64-emiya-rustpi/rockchip/rk3588-orangepi-5-plus.dtb'
            assert run('fdtget', str(dtb), '/', 'compatible').startswith('xunlong,orangepi-5-plus')
            assert run('fdtget', str(dtb), '/dp@fde50000', 'status').strip() == 'okay'
            smoke = root / 'smoke'
            smoke.mkdir()
            (smoke / 'Makefile').write_text('obj-m += rustpi_header_test.o\n')
            (smoke / 'rustpi_header_test.c').write_text(
                '#include <linux/module.h>\nstatic int __init start(void) { return 0; }\n'
                'static void __exit stop(void) {}\nmodule_init(start); module_exit(stop); MODULE_LICENSE("GPL");\n')
            subprocess.run(['make', '-C', str(tree / 'build'), 'M=' + str(smoke), 'modules'], check=True)
            assert run('modinfo', '-F', 'vermagic', str(smoke / 'rustpi_header_test.ko')).split()[0] == release
        elif group == 'ffmpeg':
            # Use the candidate library set, not a distribution ffmpeg binary.
            import os
            env = os.environ | {'LD_LIBRARY_PATH': str(root / 'usr/lib')}
            ff = str(root / 'usr/bin/ffmpeg')
            assert 'v4l2request' in run(ff, '-hide_banner', '-hwaccels', env=env)
            config = run(ff, '-hide_banner', '-buildconf', env=env)
            assert '--enable-v4l2-request' in config and '--enable-libudev' in config
            assert any(x.startswith('ffmpeg-rustpi=') for x in metadata['ffmpeg'][1]['provides'])
            subprocess.run([ff, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=128x72:rate=5',
                            '-frames:v', '5', '-c:v', 'libx264', '-f', 'null', '-'], env=env, check=True)
            assert {'h264', 'hevc', 'av1'} <= set(run(ff, '-hide_banner', '-decoders', env=env).split())
        else:
            assert 'ffmpeg-rustpi' in metadata['jellyfin-ffmpeg-system-rustpi'][1]['depend']
            subprocess.run([sys.executable, str(ROOT / 'tests/test_adapter.py')], check=True)
    report = {name: {'file': p.name, 'version': d['pkgver'][0], 'arch': d['arch'][0],
                     'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
              for name, (p, d) in metadata.items()}
    (output / f'validated-{group}.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
