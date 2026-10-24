#!/usr/bin/env python3
"""Sign packages and atomically expose a complete GitHub Release snapshot.

A draft is fully populated before it becomes latest. Existing published versions
are never replaced with different bytes. Two old versions per package are kept
in the new snapshot so clients using recently cached databases can still fetch.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PINS = json.loads((ROOT / 'ci/pins.json').read_text())
REPO = PINS['repository']
NAMES = {
    'linux-aarch64-emiya-rustpi': ('kernel', 'kernel'),
    'linux-aarch64-emiya-rustpi-headers': ('kernel', 'kernel'),
    'linux-aarch64-emiya-rustpi-rknpu': ('kernel', 'kernel'),
    'ffmpeg': ('ffmpeg', 'ffmpeg'),
    'jellyfin-ffmpeg-system-rustpi': ('integration', 'jellyfin-adapter'),
    'emiya-rustpi-keyring': ('integration', 'keyring'),
}


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def download(url, destination):
    assert url.startswith('https://github.com/' + REPO + '/releases/download/')
    with urllib.request.urlopen(url, timeout=180) as source, destination.open('wb') as target:
        shutil.copyfileobj(source, target)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata(path):
    result = {}
    for line in run('bsdtar', '-xOf', str(path), '.PKGINFO').splitlines():
        if ' = ' in line:
            k, v = line.split(' = ', 1)
            result.setdefault(k, []).append(v)
    name, version, arch = (result[k][0] for k in ('pkgname', 'pkgver', 'arch'))
    assert name in NAMES and arch in ('any', 'aarch64')
    assert re.fullmatch(r'[A-Za-z0-9_.:+-]+', version)
    return name, version, arch, result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('incoming', type=Path)
    parser.add_argument('--bootstrap', action='store_true')
    parser.add_argument('--recipes', type=Path, help='Exact recipes artifact from the planning job')
    args = parser.parse_args()
    incoming = args.incoming.resolve()
    private = os.environ.pop('REPO_SIGNING_KEY', '')
    password = os.environ.pop('REPO_SIGNING_PASSPHRASE', '').strip()
    assert private and password, 'Signing secrets are not configured'
    fingerprint = (ROOT / 'keys/fingerprint').read_text().strip()
    with tempfile.TemporaryDirectory(prefix='rustpi-publish-') as temp:
        temp = Path(temp)
        home = temp / 'gnupg'
        home.mkdir(mode=0o700)
        env = os.environ | {'GNUPGHOME': str(home)}
        subprocess.run(['gpg', '--batch', '--import'], input=private, text=True, env=env, check=True)
        del private
        keys = run('gpg', '--batch', '--with-colons', '--list-secret-keys', env=env)
        assert fingerprint in keys
        stage = temp / 'repository'
        stage.mkdir()

        def sign(path):
            subprocess.run(['gpg', '--batch', '--yes', '--pinentry-mode', 'loopback', '--passphrase-fd', '0',
                            '--local-user', fingerprint, '--detach-sign', str(path)],
                           input=password + '\n', text=True, env=env, check=True)

        def verify(path):
            subprocess.run(['gpg', '--batch', '--verify', str(path) + '.sig', str(path)], env=env, check=True)

        previous = {'packages': {}, 'groups': {}, 'history': []}
        result = subprocess.run(['gh', 'api', f'repos/{REPO}/releases/latest'], capture_output=True, text=True)
        if result.returncode == 0:
            release = json.loads(result.stdout)
            assets = {a['name']: a['browser_download_url'] for a in release['assets']}
            for name in ['manifest.json', 'manifest.json.sig']:
                download(assets[name], stage / name)
            verify(stage / 'manifest.json')
            previous = json.loads((stage / 'manifest.json').read_text())
            old_records = list(previous['packages'].values()) + previous.get('history', [])
            for record in old_records:
                name = record['file']
                assert Path(name).name == name and name.endswith('.pkg.tar.zst')
                if not (stage / name).exists():
                    download(assets[name], stage / name)
                    download(assets[name + '.sig'], stage / (name + '.sig'))
                    assert digest(stage / name) == record['sha256']
                    verify(stage / name)
        else:
            assert '404' in result.stderr, result.stderr
            assert args.bootstrap, 'Initial publication must explicitly use the validated bootstrap artifacts'

        plans = list(incoming.rglob('ci-plan.json'))
        assert plans
        plan = json.loads(plans[0].read_text())
        assert all(json.loads(p.read_text()) == plan for p in plans)
        packages = dict(previous['packages'])
        history = list(previous.get('history', []))
        built = set()
        seen = set()
        for path in sorted(incoming.rglob('*.pkg.tar.zst')):
            name, version, arch, data = metadata(path)
            assert name not in seen, name
            seen.add(name)
            group, recipe = NAMES[name]
            built.add(group)
            source_hash = plan['package_recipes'][recipe]
            filename = f'{name}-{version.split(":",1)[-1]}-{arch}.pkg.tar.zst'
            old = packages.get(name)
            if old and old['version'] == version:
                assert old['recipe_sha256'] == source_hash, f'{name}: recipe changed without a version bump'
                print(f'Keeping existing immutable {name} {version}', flush=True)
                continue
            if old:
                assert int(run('vercmp', version, old['version'])) > 0, f'Refusing downgrade of {name}'
                history.append(old)
            if not args.bootstrap:
                report = json.loads((path.parent / f'validated-{group}.json').read_text())
                assert report[name]['sha256'] == digest(path)
            target = stage / filename
            assert not target.exists(), filename
            shutil.copy2(path, target)
            sign(target)
            verify(target)
            packages[name] = {'name': name, 'version': version, 'arch': arch, 'file': filename,
                              'sha256': digest(target), 'recipe_sha256': source_hash,
                              'origin': 'hardware-validated-local-build' if args.bootstrap else 'github-actions',
                              'dependencies': data.get('depend', [])}
        assert set(packages) == set(NAMES), 'Repository must contain the complete supported package set'
        kernel_version = packages['linux-aarch64-emiya-rustpi']['version']
        for name in ('linux-aarch64-emiya-rustpi-headers', 'linux-aarch64-emiya-rustpi-rknpu'):
            assert packages[name]['version'] == kernel_version
            assert f'linux-aarch64-emiya-rustpi={kernel_version}' in packages[name]['dependencies']
        # A successful matrix is published together, never as half a kernel set.
        assert built == set(plan['build'])
        groups = dict(previous['groups'])
        groups.update({g: plan['groups'][g] for g in built})
        retained = []
        for name in NAMES:
            candidates = [r for r in history if r['name'] == name and r['file'] != packages[name]['file']]
            unique = {r['file']: r for r in candidates}
            retained += list(unique.values())[-2:]
        keep = {r['file'] for r in list(packages.values()) + retained}
        for path in stage.glob('*.pkg.tar.zst'):
            if path.name not in keep:
                path.unlink()
                path.with_name(path.name + '.sig').unlink()
        dbname = PINS['repo_name']
        subprocess.run(['repo-add', str(stage / (dbname + '.db.tar.gz'))] +
                       [str(stage / packages[n]['file']) for n in sorted(packages)], env=env, check=True)
        for suffix in ('.db', '.files'):
            path = stage / (dbname + suffix)
            data = path.read_bytes()
            path.unlink()
            path.write_bytes(data)
            sign(path)
        # Release assets are regular files; only the short db/files names are needed.
        for path in stage.glob('*.tar.gz*'):
            path.unlink()
        recipes = None
        if args.recipes:
            with tarfile.open(args.recipes, 'r:gz') as archive:
                entry = archive.extractfile('./ci-plan.json')
                assert entry and json.load(entry) == plan, 'Recipe archive does not match the validated packages'
            bundle = stage / 'build-recipes.tar.gz'
            shutil.copy2(args.recipes, bundle)
            sign(bundle)
            recipes = {'file': bundle.name, 'sha256': digest(bundle)}
        else:
            assert args.bootstrap, 'CI publication requires the exact build recipes'
        manifest = {'schema': 1, 'repository': REPO, 'fingerprint': fingerprint,
                    'created': datetime.now(timezone.utc).isoformat(), 'packages': packages,
                    'groups': groups, 'history': retained, 'recipes': recipes,
                    'build_commit': os.environ.get('SOURCE_BUILD_SHA', os.environ.get('GITHUB_SHA')),
                    'build_run': os.environ.get('SOURCE_BUILD_RUN', os.environ.get('GITHUB_RUN_ID')),
                    'publication_run': os.environ.get('GITHUB_RUN_ID')}
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        sign(stage / 'manifest.json')
        shutil.copy2(ROOT / 'keys/emiya-rustpi.asc', stage / 'emiya-rustpi.asc')
        (stage / 'SHA256SUMS').write_text(''.join(f'{digest(p)}  {p.name}\n' for p in sorted(stage.iterdir()) if p.is_file()))
        sign(stage / 'SHA256SUMS')
        tag = 'repo-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        notes = temp / 'notes.txt'
        notes.write_text('Signed aarch64 packages for rustpi. Kernel, headers and RKNPU are published together.\n\n' +
                         '\n'.join(f'- {n} {r["version"]}' for n, r in sorted(packages.items())) +
                         '\n\nHardware validation applies to the initial local builds. Hosted CI checks compilation, package contents and software contracts; it cannot exercise the RK3588 board.\n')
        subprocess.run(['gh', 'release', 'create', tag, '--repo', REPO, '--draft', '--title', tag,
                        '--target', os.environ.get('GITHUB_SHA', 'main'), '--notes-file', str(notes)], check=True)
        try:
            subprocess.run(['gh', 'release', 'upload', tag, '--repo', REPO] +
                           [str(p) for p in sorted(stage.iterdir()) if p.is_file()], check=True)
            actual = json.loads(run('gh', 'release', 'view', tag, '--repo', REPO, '--json', 'assets'))
            expected = {p.name: p.stat().st_size for p in stage.iterdir() if p.is_file()}
            assert {a['name']: a['size'] for a in actual['assets']} == expected
            subprocess.run(['gh', 'release', 'edit', tag, '--repo', REPO, '--draft=false', '--latest'], check=True)
        except Exception:
            print(f'Incomplete release remains a draft: {tag}; previous latest is unchanged', flush=True)
            raise
        print(f'PUBLISHED: https://github.com/{REPO}/releases/tag/{tag}', flush=True)
        # Record successful publication in git as well as Releases. This supplies
        # durable provenance and normal repository activity for scheduled Actions.
        record = {'release': tag, 'manifest': manifest}
        record_bytes = (json.dumps(record, indent=2) + '\n').encode()
        endpoint = f'repos/{REPO}/contents/published.json'
        existing = subprocess.run(['gh', 'api', endpoint], capture_output=True, text=True)
        payload = {'message': f'Record signed repository {tag} [skip ci]', 'branch': 'main',
                   'content': base64.b64encode(record_bytes).decode()}
        if existing.returncode == 0:
            payload['sha'] = json.loads(existing.stdout)['sha']
        else:
            assert '404' in existing.stderr, existing.stderr
        subprocess.run(['gh', 'api', '--method', 'PUT', endpoint, '--input', '-'],
                       input=json.dumps(payload), text=True, check=True, stdout=subprocess.DEVNULL)
        print('Published versions recorded in published.json', flush=True)


if __name__ == '__main__':
    main()
