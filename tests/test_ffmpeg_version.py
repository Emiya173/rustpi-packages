import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare', ROOT / 'ci/prepare.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class FFmpegVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_root, self.old_pins = prepare.ROOT, prepare.PINS
        prepare.ROOT = Path(self.temp.name)
        prepare.PINS = prepare.PINS | {'ffmpeg_revision': 2}
        self.package = prepare.ROOT / 'packages/ffmpeg'
        self.package.mkdir(parents=True)
        self.template = 'pkgver=9.0.2\npkgrel=@RUSTPI_RELEASE@\nfeature=old\n'
        (self.package / 'PKGBUILD').write_text(self.template)
        (self.package / 'request.patch').write_text('hardware decoding\n')

    def tearDown(self):
        prepare.ROOT, prepare.PINS = self.old_root, self.old_pins
        self.temp.cleanup()

    def published(self, revision):
        text = self.template.replace('@RUSTPI_RELEASE@', f'2.{revision}')
        return {'version': f'2:9.0.2-2.{revision}',
                'recipe_sha256': prepare.package_digest('ffmpeg', recipe_override=text)}

    def generate(self, previous, text=None, version='9.0.2', release='2'):
        return prepare.ffmpeg_package_version(text or self.template, '2', version, release, previous)

    def test_initial_and_unchanged_inputs_keep_revision(self):
        self.assertEqual(self.generate({})[1], '2:9.0.2-2.2')
        self.assertEqual(self.generate(self.published(2))[1], '2:9.0.2-2.2')

    def test_upstream_recipe_changes_advance_revision_once(self):
        previous = self.published(2)
        changed = self.template.replace('feature=old', 'feature=new')
        first = self.generate(previous, changed)
        self.assertEqual(first[1], '2:9.0.2-2.3')
        # Retrying an unpublished build must choose the same version and bytes.
        self.assertEqual(self.generate(previous, changed), first)
        published = {'version': first[1],
                     'recipe_sha256': prepare.package_digest('ffmpeg', recipe_override=first[0])}
        self.assertEqual(self.generate(published, changed), first)

    def test_changed_patch_is_part_of_version_identity(self):
        previous = self.published(2)
        (self.package / 'request.patch').write_text('updated hardware decoding\n')
        self.assertEqual(self.generate(previous)[1], '2:9.0.2-2.3')

    def test_unchanged_revision_does_not_reset_to_configured_minimum(self):
        self.assertEqual(self.generate(self.published(8))[1], '2:9.0.2-2.8')

    def test_new_upstream_version_or_release_resets_local_revision(self):
        previous = self.published(8)
        self.assertEqual(self.generate(previous, version='9.0.3')[1], '2:9.0.3-2.2')
        self.assertEqual(self.generate(previous, release='3')[1], '2:9.0.2-3.2')

    def test_explicit_revision_bump_is_respected(self):
        previous = self.published(2)
        prepare.PINS['ffmpeg_revision'] = 4
        self.assertEqual(self.generate(previous)[1], '2:9.0.2-2.4')


if __name__ == '__main__':
    unittest.main()
