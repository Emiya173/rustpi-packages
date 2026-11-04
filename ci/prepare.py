#!/usr/bin/env python3
"""Pin ALARM sources, generate recipes, and select changed build groups.

Upstream PKGBUILDs are parsed as text, never executed in the planning/signing job.
Updates are compiled in disposable ARM64 ALARM roots without signing credentials.
"""
import argparse
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PINS = json.loads((ROOT / 'ci/pins.json').read_text())
GROUPS = {'kernel': ['kernel'], 'ffmpeg': ['ffmpeg'], 'integration': ['jellyfin-adapter', 'keyring']}


def get(url):
    headers = {'User-Agent': 'emiya-rustpi-ci'}
    if url.startswith('https://api.github.com/') and os.environ.get('GH_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as response:
        return response.read()


def scalar(text, name):
    m = re.search(r'^' + re.escape(name) + r'=[\'\"]?([A-Za-z0-9_.+-]+)', text, re.M)
    if not m:
        raise ValueError(f'Missing literal {name} in upstream recipe')
    return m[1]


def array(text, name):
    m = re.search(r'^' + re.escape(name) + r'=\((.*?)\)', text, re.M | re.S)
    if not m:
        raise ValueError(f'Missing {name} array')
    return shlex.split(re.sub(r'^\s*#.*$', '', m[1], flags=re.M))


def source_commit(path):
    url = f'https://api.github.com/repos/archlinuxarm/PKGBUILDs/commits?path={path}/PKGBUILD&per_page=1'
    return json.loads(get(url))[0]['sha']


def snapshot(path, name):
    commit = source_commit(path)
    base = f'https://raw.githubusercontent.com/archlinuxarm/PKGBUILDs/{commit}/{path}/'
    recipe = get(base + 'PKGBUILD').decode()
    target = ROOT / 'upstream' / name
    target.mkdir(exist_ok=True)
    (target / 'PKGBUILD').write_text(recipe)
    (target / 'commit').write_text(commit + '\n')
    return recipe, base, target, commit


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check_kernel_series(version, supported):
    if not re.fullmatch(re.escape(supported) + r'(?:\.\d+)*', version):
        raise ValueError(f'DP patch supports Linux {supported}.x; upstream {version} needs a reviewed rebase')


def kernel_release(version, pkgrel):
    # The initial release is packaged as e.g. 7.3, but Kbuild includes SUBLEVEL=0.
    if len(version.split('.')) == 2:
        version += '.0'
    return f'{version}-{pkgrel}-aarch64-emiya-rustpi'


def kernel_source_plan(version, source_name, urls):
    base = source_name.removeprefix('linux-')
    series = '.'.join(version.split('.')[:2])
    if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', base) or '.'.join(base.split('.')[:2]) != series:
        raise ValueError(f'Unexpected kernel source {source_name} for {version}')
    directory = f'https://www.kernel.org/pub/linux/kernel/v{version.split(".")[0]}.x/'
    archive = directory + source_name + '.tar.xz'
    if not urls or urls[0] != archive:
        raise ValueError(f'Unexpected kernel source URLs: {urls}')
    if kernel_release(base, '1') == kernel_release(version, '1'):
        if urls != [archive]:
            raise ValueError('Unexpected stable patch for a full-version kernel source')
        return source_name, urls, '', False
    patch = f'patch-{version}.xz'
    if urls == [archive, directory + patch]:
        return source_name, urls, patch, False
    if urls != [archive]:
        raise ValueError(f'Unexpected stable patch URLs: {urls}')
    # ALARM 7.3.1 bumped pkgver but left the stable patch URL commented out.
    # Obtain the exact version from kernel.org, with a developer signature.
    return f'linux-{version}', [directory + f'linux-{version}.tar.xz'], '', True


def verify_kernel_archive(data, signature):
    allowed = {'647F28654894E3BD457199BE38DBBDC86092693E',
               'E27E5D8A3403A2EF66873BBCDEA66FF797772CDC'}
    with tempfile.TemporaryDirectory(prefix='rustpi-kernel-signature-') as directory:
        home = Path(directory)
        command = ['gpg', '--batch', '--homedir', str(home)]
        subprocess.run(command + ['--import', str(ROOT / 'keys/kernel-stable.asc')],
                       capture_output=True, check=True)
        signed = home / 'linux.tar.sign'
        signed.write_bytes(signature)
        with subprocess.Popen(command + ['--status-fd=1', '--verify', str(signed), '-'],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            with lzma.LZMAFile(io.BytesIO(data)) as archive:
                shutil.copyfileobj(archive, process.stdin, length=1024 * 1024)
            process.stdin.close()
            process.stdin = None
            status, errors = process.communicate()
            if process.returncode:
                raise ValueError('Kernel developer signature failed: ' + errors.decode())
        for line in status.decode().splitlines():
            fields = line.split()
            if fields[:2] == ['[GNUPG:]', 'VALIDSIG'] and fields[-1] in allowed:
                return fields[-1]
        raise ValueError('Kernel archive was not signed by a pinned stable release developer')


def kernel():
    recipe, base, upstream, commit = snapshot('core/linux-aarch64', 'kernel')
    version, release, source_name = (scalar(recipe, n) for n in ('pkgver', 'pkgrel', '_srcname'))
    template = (ROOT / 'ci/kernel.PKGBUILD.in').read_text()
    check_kernel_series(version, scalar(template, '_dp_kernel_series'))
    source_names = array(recipe, 'source')
    checksums = array(recipe, 'md5sums')
    assert len(source_names) == len(checksums)
    package = ROOT / 'packages/kernel'
    # Only explicitly supported input kinds are accepted. A changed upstream
    # recipe structure fails rather than silently omitting a new kernel patch.
    patches = [x for x in source_names if re.fullmatch(r'\d{4}-[A-Za-z0-9_.+-]+\.patch', x)]
    unknown = [x for x in source_names if x.endswith('.patch') and x not in patches]
    assert not unknown, unknown
    for old in package.glob('000*.patch'):
        old.unlink()
    hashes = {}
    for name in patches + ['config']:
        data = get(base + name)
        assert hashlib.md5(data).hexdigest() == checksums[source_names.index(name)], name
        (upstream / name).write_bytes(data)
        (package / name).write_bytes(data)
        hashes[name] = sha(data)
    downloads = {}
    for text, expected in zip(source_names, checksums):
        if text.startswith('https://www.kernel.org/'):
            url = text.replace('${_srcname}', source_name).replace('${pkgver}', version)
            downloads[url] = expected
    source_name, selected, stable_patch, fallback = kernel_source_plan(version, source_name, list(downloads))
    urls = []
    verification = None
    for url in selected:
        data = get(url)
        if fallback:
            signature_url = url.removesuffix('.xz') + '.sign'
            signature = get(signature_url)
            signer = verify_kernel_archive(data, signature)
            (upstream / 'kernel-source.tar.sign').write_bytes(signature)
            verification = {'reason': 'ALARM version differs from its source and omits the stable patch',
                            'url': url, 'signature_url': signature_url,
                            'signature_sha256': sha(signature), 'signer': signer}
        else:
            assert hashlib.md5(data).hexdigest() == downloads[url], url
        urls.append((url, sha(data)))
    if not fallback:
        (upstream / 'kernel-source.tar.sign').unlink(missing_ok=True)
    revision = PINS['kernel_revision']
    pkgrel = release + (f'.{revision}' if revision else '')
    src = [x[0] for x in urls] + patches + ['rustpi-dp.patch.xz', 'config', 'dp-commits.txt']
    sums = [x[1] for x in urls] + [hashes[x] for x in patches]
    sums += [sha((package / x).read_bytes()) for x in ['rustpi-dp.patch.xz', 'config', 'dp-commits.txt']]
    npu_commit = PINS['rknpu_commit']
    src += [f'rknpu-{npu_commit}.tar.gz::https://codeload.github.com/lurenJBD/rk3588-rknn-core/tar.gz/{npu_commit}',
            '60-rustpi-rknpu.conf', '60-rustpi-rknpu-load.conf']
    sums += [PINS['rknpu_sha256']] + [sha((package / x).read_bytes()) for x in src[-2:]]
    for key, value in {'VERSION': version, 'RELEASE': pkgrel, 'SOURCE_NAME': source_name,
                       'KERNEL_VERSION': kernel_release(version, pkgrel).split('-')[0],
                       'KERNEL_RELEASE': kernel_release(version, pkgrel),
                       'STABLE_PATCH': stable_patch,
                       'NOEXTRACT': ' '.join(repr(x) for x in ['rustpi-dp.patch.xz', stable_patch] if x),
                       'ALARM_COMMIT': commit, 'RKNPU_COMMIT': npu_commit,
                       'SOURCES': '\n  '.join(repr(x) for x in src),
                       'SUMS': '\n  '.join(repr(x) for x in sums)}.items():
        template = template.replace('@' + key + '@', value)
    assert not re.search(r'@[A-Z_]+@', template)
    (package / 'PKGBUILD').write_text(template)
    kver = kernel_release(version, pkgrel)
    (package / 'rknpu.install').write_text(
        f'post_install() {{ depmod {kver}; }}\n'
        'post_upgrade() { post_install; }\n'
        f'post_remove() {{ if [[ -f /usr/lib/modules/{kver}/modules.order ]]; then post_install; fi; }}\n')
    result = {'alarm_commit': commit, 'version': f'{version}-{pkgrel}', 'rknpu_commit': npu_commit,
              'source_name': source_name, 'sources': dict(zip(src, sums))}
    if verification:
        result['kernel_org_verification'] = verification
    return result


def ffmpeg_package_version(recipe, epoch, version, release, previous):
    """Keep published pkgrel stable; advance it when same-version inputs change."""
    prefix = f'{epoch}:{version}-{release}.'
    old = re.fullmatch(re.escape(prefix) + r'(\d+)', previous.get('version', ''))
    revision = max(PINS['ffmpeg_revision'], int(old[1]) if old else 0)

    def render(number):
        assert recipe.count('@RUSTPI_RELEASE@') == 1
        return recipe.replace('@RUSTPI_RELEASE@', f'{release}.{number}')

    candidate = render(revision)
    if old and revision == int(old[1]):
        if package_digest('ffmpeg', recipe_override=candidate) != previous['recipe_sha256']:
            revision += 1
            candidate = render(revision)
    return candidate, prefix + str(revision)


def ffmpeg(previous=None):
    recipe, base, upstream, commit = snapshot('extra/ffmpeg', 'ffmpeg')
    version, release = scalar(recipe, 'pkgver'), scalar(recipe, 'pkgrel')
    package = ROOT / 'packages/ffmpeg'
    chromium = '0001-Add-av_stream_get_first_dts-for-Chromium.patch'
    patch = get(base + chromium)
    sources, sums = array(recipe, 'source'), array(recipe, 'b2sums')
    assert hashlib.blake2b(patch).hexdigest() == sums[sources.index(chromium)]
    (package / chromium).write_bytes(patch)
    (upstream / chromium).write_bytes(patch)
    assert re.search(r'^arch=\(.*?\)$', recipe, re.M), 'Missing ALARM architecture array'
    recipe = re.sub(r'^arch=\(.*?\)$', 'arch=(aarch64)', recipe, count=1, flags=re.M)
    edits = [
        (f'pkgrel={release}', 'pkgrel=@RUSTPI_RELEASE@'),
        ('  libudev.so\n', '  libudev.so\n'),
        ('  libavcodec.so\n', '  "ffmpeg-rustpi=${pkgver}"\n  libavcodec.so\n'),
        ('  systemd-libs\n', '  systemd-libs\n'),
        (f'  {chromium}\n', f'  {chromium}\n  0002-v4l2-request-rustpi.patch\n'),
        (f'  git apply -3 ../{chromium}\n',
         f'  git apply -3 ../{chromium}\n  git apply --check ../0002-v4l2-request-rustpi.patch\n  git apply ../0002-v4l2-request-rustpi.patch\n'),
        ('    --enable-libdrm \\\n', '    --enable-libdrm \\\n    --enable-libudev \\\n    --enable-v4l2-request \\\n    --extra-version=emiya-rustpi \\\n'),
    ]
    # Avoid relying on the installed device's userspace snapshot in CI.
    if '  systemd-libs\n' not in recipe:
        recipe = recipe.replace('  srt\n', '  srt\n  systemd-libs\n')
    if '  libudev.so\n' not in recipe:
        recipe = recipe.replace('    libzmq.so\n', '    libzmq.so\n    libudev.so\n')
    for old, new in edits:
        if old == new:
            continue
        assert recipe.count(old) == 1, f'FFmpeg recipe changed around {old!r}; review required'
        recipe = recipe.replace(old, new, 1)
    # Native configure needs glslang to preserve Vulkan encoders.
    if '  glslang\n' not in recipe:
        assert '  git\n' in recipe
        recipe = recipe.replace('  git\n', '  git\n  glslang\n', 1)
    custom_sum = hashlib.blake2b((package / '0002-v4l2-request-rustpi.patch').read_bytes()).hexdigest()
    match = re.search(r'^b2sums=\((.*?)\)', recipe, re.M | re.S)
    assert match
    recipe = recipe[:match.end()-1] + f"\n        '{custom_sum}'" + recipe[match.end()-1:]
    recipe, package_version = ffmpeg_package_version(recipe, scalar(recipe, 'epoch'), version, release, previous or {})
    (package / 'PKGBUILD').write_text(recipe)
    return {'alarm_commit': commit, 'version': package_version}


def recipe_files(name):
    base = ROOT / 'packages' / name
    return [p for p in base.rglob('*') if p.is_file()
            and not set(p.relative_to(base).parts) & {'src', 'pkg', '__pycache__', '.git'}
            and '.pkg.tar.' not in p.name and not p.name.endswith('.log') and p.name != '.SRCINFO']


def digest(group):
    h = hashlib.sha256()
    paths = [ROOT / 'ci/pins.json', ROOT / 'ci/build-alarm.sh', ROOT / 'ci/validate.py']
    for name in GROUPS[group]:
        paths += recipe_files(name)
    for p in sorted(paths):
        h.update(str(p.relative_to(ROOT)).encode() + b'\0' + p.read_bytes())
    return h.hexdigest()


def package_digest(name, recipe_override=None):
    h = hashlib.sha256()
    for path in sorted(recipe_files(name)):
        data = (recipe_override.encode() if recipe_override is not None
                and path == ROOT / 'packages' / name / 'PKGBUILD' else path.read_bytes())
        h.update(str(path.relative_to(ROOT)).encode() + b'\0' + data)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    manifest = {}
    try:
        release = json.loads(get(f'https://api.github.com/repos/{PINS["repository"]}/releases/latest'))
        url = next(a['browser_download_url'] for a in release['assets'] if a['name'] == 'manifest.json')
        manifest = json.loads(get(url))
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    if args.refresh:
        lock = {'kernel': kernel(), 'ffmpeg': ffmpeg(manifest.get('packages', {}).get('ffmpeg'))}
        (ROOT / 'sources.lock.json').write_text(json.dumps(lock, indent=2) + '\n')
    lock = json.loads((ROOT / 'sources.lock.json').read_text())
    previous = manifest.get('groups', {})
    hashes = {g: digest(g) for g in GROUPS}
    selected = [g for g in GROUPS if args.force or previous.get(g, {}).get('recipe_sha256') != hashes[g]]
    plan = {'groups': {g: {'recipe_sha256': hashes[g], 'source': lock.get(g, {})} for g in GROUPS},
            'build': selected,
            'package_recipes': {name: package_digest(name) for names in GROUPS.values() for name in names}}
    (ROOT / 'ci-plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write('matrix=' + json.dumps({'group': selected}) + '\n')
            f.write('changed=' + str(bool(selected)).lower() + '\n')
    print(json.dumps(plan, indent=2))


if __name__ == '__main__':
    main()
