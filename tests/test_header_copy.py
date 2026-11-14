import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest

RECIPE = Path(__file__).resolve().parents[1] / 'ci/kernel.PKGBUILD.in'


@unittest.skipUnless(shutil.which('fakeroot'), 'fakeroot is required; the native kernel job runs these checks')
class HeaderCopyTests(unittest.TestCase):
    def test_copy_under_fakeroot_retains_headers_tools_and_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'headers'
            source.mkdir()
            (source / 'include').mkdir()
            header = source / 'include/example.h'
            header.write_text('#define RUSTPI 1\n')
            header.chmod(0o644)
            os.utime(header, ns=(1600000000000000000, 1600000000000000000))
            tool = source / 'tool'
            tool.write_text('#!/bin/sh\necho header-tool\n')
            tool.chmod(0o755)
            (source / 'tool-link').symlink_to('tool')
            os.link(tool, source / 'tool-hardlink')
            destination = root / 'package'
            destination.mkdir()
            script = '''set -euo pipefail
source "$1"
_copy_header_tree "$2" "$3/"
python3 -c 'import json,os,sys; print(json.dumps({"uid":os.stat(sys.argv[1]).st_uid}))' "$3/headers/tool"
'''
            result = subprocess.run(['fakeroot', '--', 'bash', '-c', script, 'test',
                                     str(RECIPE), str(source), str(destination)],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)['uid'], 0)
            copied = destination / 'headers'
            self.assertEqual((copied / 'include/example.h').read_bytes(), header.read_bytes())
            self.assertEqual(stat.S_IMODE((copied / 'include/example.h').stat().st_mode), 0o644)
            self.assertEqual((copied / 'include/example.h').stat().st_mtime_ns, header.stat().st_mtime_ns)
            self.assertEqual(stat.S_IMODE((copied / 'tool').stat().st_mode), 0o755)
            self.assertEqual(os.readlink(copied / 'tool-link'), 'tool')
            self.assertEqual((copied / 'tool').stat().st_ino, (copied / 'tool-hardlink').stat().st_ino)
            self.assertEqual(subprocess.check_output([str(copied / 'tool')], text=True).strip(), 'header-tool')

    def test_missing_source_is_a_real_copy_error(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(['fakeroot', '--', 'bash', '-c',
                                     'source "$1"; _copy_header_tree "$2/missing" "$2/package"',
                                     'test', str(RECIPE), directory], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
