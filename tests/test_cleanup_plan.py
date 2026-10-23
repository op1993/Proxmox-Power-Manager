import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import cleanup_plan


class CleanupPlanTests(unittest.TestCase):
    def test_requires_owned_completed_installation(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = Path(d) / 'installation.json'
            manifest.write_text(json.dumps({'schema': 1, 'web_ctid': 112,
                'web_ct_created_by_ppm': False, 'installation_complete': True}))
            with patch.object(cleanup_plan.cleanup_watch, 'MANIFEST', manifest):
                with self.assertRaises(ValueError):
                    cleanup_plan.plan()

    def test_defaults_to_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            manifest = root / 'installation.json'
            manifest.write_text(json.dumps({'schema': 1, 'web_ctid': 112,
                'web_ct_created_by_ppm': True, 'installation_complete': True}))
            with patch.object(cleanup_plan.cleanup_watch, 'MANIFEST', manifest), \
                 patch.object(cleanup_plan.cleanup_watch, 'READY', root / 'ready'), \
                 patch.object(cleanup_plan.cleanup_watch, 'RECOVERY', root / 'state'), \
                 patch.object(cleanup_plan, 'OPT_IN', root / 'policy'):
                result = cleanup_plan.plan()
            self.assertFalse(result['automatic_cleanup_enabled'])
            self.assertFalse(result['eligible_for_cleanup'])
            self.assertFalse(result['changes_applied'])
