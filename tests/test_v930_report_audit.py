import json, sys, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from audit_report import audit, has_content

class V930ReportAuditTest(unittest.TestCase):
    def test_zero_and_false_are_real_content(self):
        self.assertTrue(has_content(0))
        self.assertTrue(has_content(False))
        self.assertFalse(has_content('未采集'))
        self.assertFalse(has_content({}))

    def test_current_reference_report_has_complete_roles_and_evidence(self):
        source=ROOT/'server/reports/tmall_1068693788227_20260903_181040_ac150.json'
        if not source.exists():
            self.skipTest('reference report is not distributed')
        result=audit(json.loads(source.read_text('utf-8')))
        self.assertTrue(result['ok'],result['failures'])
        self.assertEqual(7,result['roles']['present'])
        self.assertFalse(result['evidence']['unresolved'])
        self.assertGreaterEqual(result['sourceCoverage'],12)

if __name__=='__main__':unittest.main()
