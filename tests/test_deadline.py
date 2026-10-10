"""Prove a slow mocked dependency failure is returned as a bounded API error."""
import json,sys,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
import app
from repository import MemoryRepository

class SlowDependency:
    def generate_presigned_post(self,**kwargs):
        time.sleep(.08)  # represents a provider that stalls; real SDK reads are capped at 3 seconds
        raise TimeoutError("simulated upstream read timeout")

class DeadlineTests(unittest.TestCase):
    def test_slow_dependency_fails_safely_well_before_45_seconds(self):
        app.configure(MemoryRepository(),SlowDependency())
        auth={"authorizer":{"jwt":{"claims":{"sub":"deadline-test"}}}}
        create={"requestContext":{"http":{"method":"POST"},**auth},"rawPath":"/v1/applications","body":"{}"}
        created=json.loads(app.handler(create,None)["body"])["applicationId"]
        event={"requestContext":{"http":{"method":"POST"},**auth},"rawPath":f"/v1/applications/{created}/documents/presign","body":json.dumps({"documentType":"government_id","contentType":"application/pdf","fileName":"sample.pdf","sizeBytes":100,"checksumSha256":"A"*43+"="})}
        with patch.dict("os.environ",{"DOCUMENT_BUCKET":"test-bucket"}):
            started=time.monotonic(); response=app.handler(event,None); elapsed=time.monotonic()-started
        self.assertLess(elapsed,45)
        self.assertEqual(response["statusCode"],500)
        self.assertEqual(json.loads(response["body"])["error"],"internal_error")

if __name__=="__main__": unittest.main()
