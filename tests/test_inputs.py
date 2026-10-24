import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare', ROOT / 'ci/prepare.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class InputTests(unittest.TestCase):
    def test_upstream_arrays_keep_git_tag_and_quoted_paths(self):
        text = '''source=(git+https://example.org/a.git?signed#tag=n${pkgver}
          '0001-a.patch' "config")'''
        self.assertEqual(prepare.array(text, 'source'),
                         ['git+https://example.org/a.git?signed#tag=n${pkgver}', '0001-a.patch', 'config'])

    def test_versions_are_literal_and_missing_values_fail(self):
        self.assertEqual(prepare.scalar('pkgver="7.2.12"\npkgrel=1\n', 'pkgver'), '7.2.12')
        with self.assertRaises(ValueError):
            prepare.scalar('pkgver=$(untrusted-command)', 'pkgver')

    def test_build_outputs_do_not_change_recipe_identity(self):
        old_root = prepare.ROOT
        with tempfile.TemporaryDirectory() as d:
            prepare.ROOT = Path(d)
            p = prepare.ROOT / 'packages/example'
            p.mkdir(parents=True)
            (p / 'PKGBUILD').write_text('pkgver=1\n')
            baseline = prepare.package_digest('example')
            for dirname in ('src', 'pkg', '__pycache__'):
                (p / dirname).mkdir()
                (p / dirname / 'binary').write_bytes(b'unrelated output')
            (p / 'example-1-1-any.pkg.tar.zst').write_bytes(b'archive')
            (p / '.SRCINFO').write_text('generated metadata')
            self.assertEqual(prepare.package_digest('example'), baseline)
            (p / 'PKGBUILD').write_text('pkgver=2\n')
            self.assertNotEqual(prepare.package_digest('example'), baseline)
        prepare.ROOT = old_root

    def test_kernel_triplet_is_generated_from_one_version(self):
        recipe = (ROOT / 'packages/kernel/PKGBUILD').read_text()
        self.assertIn('pkgname=("$pkgbase" "$pkgbase-headers" "$pkgbase-rknpu")', recipe)
        self.assertEqual(recipe.count('depends=("$pkgbase=$pkgver-$pkgrel"'), 2)
        self.assertIn('--fuzz=0', recipe)


if __name__ == '__main__':
    unittest.main()
