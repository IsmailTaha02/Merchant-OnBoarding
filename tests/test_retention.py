import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import retention


class Expr:
    def __and__(self, other): return self
    def eq(self, value): return self
    def is_in(self, values): return self
    def lt(self, value): return self


class FakeTable:
    name = "apps"
    def __init__(self, events): self.events = events
    @property
    def meta(self): return types.SimpleNamespace(client=self)
    def get_item(self, **kwargs): return {}
    def scan(self, **kwargs):
        return {"Items": [{"PK": "APP#12345678-1234-1234-1234-123456789012", "SK": "META", "status": "DRAFT", "updatedAt": "2020-01-01T00:00:00+00:00"}]}
    def query(self, **kwargs):
        self.events.append("query")
        return {"Items": [{"PK": "APP#12345678-1234-1234-1234-123456789012", "SK": "META"}, {"PK": "APP#12345678-1234-1234-1234-123456789012", "SK": "PERSON"}]}
    def batch_write_item(self, **kwargs): self.events.append("batch_delete"); return {}
    def delete_item(self, **kwargs): self.events.append("meta_delete" if kwargs.get("Key", {}).get("SK") == "META" else "cursor_delete")
    def put_item(self, **kwargs): pass


class FakeS3:
    def __init__(self, events, truncated=False): self.events, self.truncated = events, truncated
    def list_object_versions(self, **kwargs):
        self.events.append("list_versions")
        return {"Versions": [{"Key": "applications/id/doc.pdf", "VersionId": "v1"}], "DeleteMarkers": [{"Key": "applications/id/doc.pdf", "VersionId": "v0"}], "IsTruncated": self.truncated}
    def delete_objects(self, **kwargs): self.events.append("delete_versions"); return {"Deleted": []}


class RetentionTests(unittest.TestCase):
    def fake_boto_conditions(self):
        boto = types.ModuleType("boto3")
        dynamodb = types.ModuleType("boto3.dynamodb")
        conditions = types.ModuleType("boto3.dynamodb.conditions")
        conditions.Attr = lambda name: Expr()
        conditions.Key = lambda name: Expr()
        return patch.dict(sys.modules, {"boto3": boto, "boto3.dynamodb": dynamodb, "boto3.dynamodb.conditions": conditions})

    def test_policy_empty_and_invalid_values(self):
        self.assertEqual(retention.parse_policy("{}"), {})
        self.assertEqual(retention.parse_policy('{"DRAFT":30}'), {"DRAFT": 30})
        for raw in ('[]', '{"OTHER":30}', '{"DRAFT":true}', '{"SUBMITTED":0}', 'not-json'):
            with self.subTest(raw=raw), self.assertRaises(ValueError): retention.parse_policy(raw)

    def test_disabled_policy_does_not_touch_storage(self):
        self.assertEqual(retention.cleanup_one(None, None, "", {}, datetime.now(timezone.utc), 1), {"status": "disabled", "deleted": 0})

    def test_document_versions_deleted_before_dynamo_meta(self):
        events = []; table = FakeTable(events); s3 = FakeS3(events)
        with self.fake_boto_conditions():
            result = retention.cleanup_one(table, s3, "bucket", {"DRAFT": 30}, datetime.now(timezone.utc), 1e20)
        self.assertEqual(result["status"], "deleted")
        self.assertEqual(events, ["list_versions", "delete_versions", "query", "batch_delete", "meta_delete", "cursor_delete"])

    def test_truncated_s3_page_defers_all_dynamo_deletion(self):
        events = []; table = FakeTable(events); s3 = FakeS3(events, truncated=True)
        with self.fake_boto_conditions():
            result = retention.cleanup_one(table, s3, "bucket", {"DRAFT": 30}, datetime.now(timezone.utc), 1e20)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(events, ["list_versions", "delete_versions"])


if __name__ == "__main__": unittest.main()
