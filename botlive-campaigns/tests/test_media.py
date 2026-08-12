import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"local-agent"))
from app.media import probe,signature
class MediaTests(unittest.TestCase):
 def test_signatures_reject_disguised_files(self):self.assertTrue(signature(".mp4",b"\x00\x00\x00\x18ftypisom0000"));self.assertFalse(signature(".mp4",b"not a video"));self.assertTrue(signature(".webm",b"\x1a\x45\xdf\xa3rest"))
 @patch("app.media.subprocess.run")
 def test_probe_extracts_real_metadata(self,run):
  run.return_value.stdout=json.dumps({"format":{"duration":"12.5","format_name":"mov,mp4","bit_rate":"1000"},"streams":[{"codec_type":"video","codec_name":"h264","width":1080,"height":1920,"avg_frame_rate":"30/1"},{"codec_type":"audio","codec_name":"aac"}]});data=probe(Path("fixture.mp4"));self.assertEqual(12.5,data["duration_seconds"]);self.assertTrue(data["has_audio"])
 @patch("app.media.subprocess.run",side_effect=subprocess.TimeoutExpired("ffprobe",20))
 def test_probe_timeout(self,_):
  with self.assertRaisesRegex(ValueError,"tempo limite"):probe(Path("fixture.mp4"))
 @patch("app.media.subprocess.run")
 def test_probe_rejects_missing_video_and_codec(self,run):
  run.return_value.stdout=json.dumps({"format":{"duration":"12"},"streams":[{"codec_type":"audio","codec_name":"aac"}]})
  with self.assertRaisesRegex(ValueError,"vídeo ausente"):probe(Path("fixture.mp4"))
if __name__=="__main__":unittest.main()
