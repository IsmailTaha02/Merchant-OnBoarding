import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from import_mcc import import_catalog


class MccImportTests(unittest.TestCase):
    def test_import_refreshes_metadata_and_preserves_curated_keywords(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); csv_path=root/"visa.csv"; catalog_path=root/"catalog.json"; metadata_path=root/"metadata.json"
            csv_path.write_text("code,description\n5411,Grocery stores\n7995,Gambling\n",encoding="utf-8")
            catalog_path.write_text(json.dumps([{"code":"5411","description":"Old title","keywords":["grocery"]}]),encoding="utf-8")
            metadata_path.write_text(json.dumps({"schemaVersion":1,"catalogVersion":"old","isComplete":True,"rowCount":99}),encoding="utf-8")
            count=import_catalog(csv_path,catalog_path,metadata_path,"April 2026","https://example.test/visa.pdf",True)
            catalog=json.loads(catalog_path.read_text(encoding="utf-8")); meta=json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(count,2)
            self.assertEqual(catalog[0]["keywords"],["grocery"])
            self.assertEqual(catalog[1]["keywords"],[])
            self.assertEqual(meta["rowCount"],2)
            self.assertTrue(meta["isComplete"])
            self.assertEqual(meta["catalogVersion"],"visa-mdsm-april-2026")

    def test_partial_csv_does_not_claim_completeness(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); source=root/"subset.csv"; catalog=root/"catalog.json"; metadata=root/"metadata.json"
            source.write_text("code,description\n5812,Restaurants\n",encoding="utf-8")
            import_catalog(source,catalog,metadata)
            self.assertFalse(json.loads(metadata.read_text(encoding="utf-8"))["isComplete"])


if __name__=="__main__": unittest.main()
