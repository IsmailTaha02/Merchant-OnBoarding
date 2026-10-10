import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from domain import ValidationError
from statement import parse_statement

class StatementParserTests(unittest.TestCase):
    def test_fixture_totals_are_normalized_without_raw_text(self):
        source=(ROOT/"tests/fixtures/sample_statement.txt").read_text(encoding="utf-8")
        result=parse_statement(source)
        normalized=result["normalized"]
        self.assertEqual(normalized["currentMonthlyVolume"],10000.0)
        self.assertEqual(normalized["currentFees"],190.0)
        self.assertEqual(normalized["effectiveRatePercent"],1.9)
        self.assertFalse(normalized["verified"])
        self.assertFalse(result["rawTextStored"])
        self.assertNotIn(source,str(normalized))

    def test_rejects_unbounded_or_unusable_text(self):
        for text in ("", "no supported lines", "x"*20001):
            with self.subTest(text_length=len(text)), self.assertRaises(ValidationError):
                parse_statement(text)

if __name__=="__main__": unittest.main()
