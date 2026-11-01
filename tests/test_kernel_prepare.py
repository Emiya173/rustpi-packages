import lzma
from pathlib import Path
import subprocess
import tempfile
import unittest

RECIPE = Path(__file__).resolve().parents[1] / 'ci/kernel.PKGBUILD.in'


class KernelPrepareTests(unittest.TestCase):
    def prepare(self, version, stable_patch=False, missing_patch=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / 'linux-7.3'
            (tree / 'scripts').mkdir(parents=True)
            (tree / 'Makefile').write_text('SUBLEVEL = 0\nkernelversion:\n\t@echo 7.3.$(SUBLEVEL)\n')
            (tree / 'scripts/config').write_text('#!/bin/sh\nexit 0\n')
            (tree / 'scripts/config').chmod(0o755)
            (root / 'config').write_text('')
            delta = lambda name: f'--- /dev/null\n+++ b/{name}\n@@ -0,0 +1 @@\n+applied\n'
            (root / '0001-alarm.patch').write_text(delta('alarm-patched'))
            (root / 'rustpi-dp.patch.xz').write_bytes(lzma.compress(delta('dp-patched').encode()))
            if stable_patch and not missing_patch:
                patch = '--- a/Makefile\n+++ b/Makefile\n@@ -1 +1 @@\n-SUBLEVEL = 0\n+SUBLEVEL = 1\n'
                (root / 'patch-7.3.1.xz').write_bytes(lzma.compress(patch.encode()))
            script = '''set -euo pipefail
source "$1"
srcdir=$2
_srcname=linux-7.3
_expected_version=$3
_stable_patch=$4
pkgrel=1
error() { echo "$*" >&2; }
cd "$srcdir"
prepare
'''
            result = subprocess.run(['bash', '-c', script, 'test', str(RECIPE), str(root), version,
                                     'patch-7.3.1.xz' if stable_patch else ''], capture_output=True, text=True)
            return result, (tree / 'dp-patched').exists()

    def test_base_release_prepares(self):
        result, patched = self.prepare('7.3.0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(patched)

    def test_stable_update_applied_before_custom_patches(self):
        result, patched = self.prepare('7.3.1', stable_patch=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(patched)

    def test_missing_update_fails_before_custom_patches(self):
        result, patched = self.prepare('7.3.1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Kernel source version 7.3.0 does not match 7.3.1', result.stderr)
        self.assertFalse(patched)

    def test_declared_patch_cannot_be_silently_skipped(self):
        result, patched = self.prepare('7.3.1', stable_patch=True, missing_patch=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Missing stable kernel patch', result.stderr)
        self.assertFalse(patched)


if __name__ == '__main__':
    unittest.main()
