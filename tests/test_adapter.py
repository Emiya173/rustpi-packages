import importlib.machinery
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

adapter = importlib.machinery.SourceFileLoader('adapter', str(Path(__file__).resolve().parents[1] / 'packages/jellyfin-adapter/ffmpeg')).load_module()
class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'movie with spaces.mkv')
        Path(self.path).touch()
        self.stream = {'index': 0, 'codec_type': 'video', 'codec_name': 'hevc', 'pix_fmt': 'yuv420p10le'}
    def tearDown(self):
        self.tmp.cleanup()
    def adapt(self, args, streams=None):
        data = json.dumps({'streams': streams or [self.stream]})
        with patch.object(adapter.subprocess, 'run') as run:
            run.return_value.stdout = data
            return adapter.adapt(args)
    def test_seek_filters_and_paths(self):
        args = ['-ss','3.5','-c:v','hevc','-i','file:'+self.path,'-map','0:0','-vf','scale=1280:-2,subtitles=some.ass','-c:v:0','libx264','-threads','4','out.m3u8']
        out, msg = self.adapt(args)
        self.assertIn('v4l2request', out)
        self.assertEqual(out[out.index('-i'):],args[args.index('-i'):])
        self.assertEqual(out[out.index('-ss')+1],'3.5')
        self.assertEqual(out.count('-c:v'),0)
        self.assertIn('hevc yuv420p10le',msg)
    def test_passthrough_commands(self):
        for args in [['-version'],['-i',self.path,'-c:v','copy','out.ts'],['-hwaccel','vaapi','-i',self.path,'-c:v','libx264','out.ts'],['-i','https://example.invalid/a.mkv','-c:v','libx264','out.ts']]:
            with self.subTest(args=args): self.assertEqual(self.adapt(args),(args,None))
    def test_unsupported_formats(self):
        args=['-i',self.path,'-c:v','libx264','out.ts']
        for codec,pixel in [('vp9','yuv420p'),('h264','yuv420p10le'),('hevc','yuv444p10le'),('av1','yuv420p12le')]:
            self.stream.update(codec_name=codec,pix_fmt=pixel)
            self.assertEqual(self.adapt(args),(args,None))
    def test_multiple_video(self):
        args=['-i',self.path,'-c:v','libx264','out.ts']
        out,msg=self.adapt(args,[self.stream,{**self.stream,'index':1}])
        self.assertEqual(out,args)
    def test_nonselected_stream(self):
        args=['-i',self.path,'-map','0:1','-c:v','libx264','out.ts']
        self.assertEqual(self.adapt(args),(args,None))
if __name__=='__main__':unittest.main()
