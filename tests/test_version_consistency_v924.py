import json, re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXPECTED='9.3.0'

def test_version_consistency():
    assert (ROOT/'VERSION.txt').read_text().strip()==EXPECTED
    for rel in ['extension/manifest.json','collector-extension-standalone/manifest.json','codex-plugin-toolkit/sansong-tmall-product-report/assets/capture-extension/manifest.json']:
        data=json.loads((ROOT/rel).read_text(encoding='utf-8'))
        assert data['version']==EXPECTED, rel
    popup=(ROOT/'extension/popup.js').read_text(encoding='utf-8')
    assert f"EXPECTED_SERVER_VERSION='{EXPECTED}'" in popup
    server=(ROOT/'server/server.py').read_text(encoding='utf-8')
    assert f"SERVER_VERSION='{EXPECTED}'" in server or f'SERVER_VERSION = \'{EXPECTED}\'' in server
    analysis=(ROOT/'server/analysis.py').read_text(encoding='utf-8')
    assert f"ENGINE_VERSION='{EXPECTED}'" in analysis
    ai=(ROOT/'server/ai_client.py').read_text(encoding='utf-8')
    assert f"SERVER_VERSION = '{EXPECTED}'" in ai
    start=(ROOT/'start-tmall-ai.command').read_text(encoding='utf-8')
    assert f'VERSION="{EXPECTED}"' in start
