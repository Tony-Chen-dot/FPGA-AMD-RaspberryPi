import asyncio
import importlib.util
import io
import json
import os
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
try:
    from fastapi.testclient import TestClient
except (ImportError, RuntimeError):
    TestClient = None
from common.production_lines import (configured_line_id, line_data_dir, migrate_legacy_data,
                                     migrate_legacy_runtime, validate_line_id)
from dashboard.storage.database import DashboardStorage


class ProductionLineStorageTests(unittest.TestCase):
    def test_invalid_configuration_cannot_select_an_unknown_line(self):
        for value in ('0', '6', '1.5', '../line_1', True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_line_id(value)
        with patch.dict(os.environ, {'PRODUCTION_LINE_ID': '4'}):
            self.assertEqual(configured_line_id(), 4)

    def test_legacy_database_images_and_conversations_migrate_only_once(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); old = DashboardStorage(base)
            asyncio.run(old.ingest({'frame_id': 'legacy', 'result': 'NG'}, frame_bytes=None))
            from voice.dialogue.history import ConversationStore
            conversation = ConversationStore(old.db_path).create('原产线对话')
            (base / 'media/frames/legacy.jpg').write_bytes(b'original')
            migrate_legacy_data(base, 3)
            migrated = DashboardStorage(line_data_dir(base, 3))
            self.assertTrue(old.db_path.exists())
            self.assertEqual((migrated.frames_dir / 'legacy.jpg').read_bytes(), b'original')
            self.assertEqual(asyncio.run(migrated.get_snapshot())['summary']['total_count'], 1)
            self.assertIsNotNone(ConversationStore(migrated.db_path).get(conversation['id']))
            migrate_legacy_data(base, 4)
            self.assertFalse((line_data_dir(base, 4) / 'dashboard.sqlite3').exists())

    def test_camera_artifacts_do_not_follow_later_config_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); (base / 'artifacts').mkdir()
            (base / 'artifacts/sample.json').write_text('{}')
            migrate_legacy_runtime(base, 2); migrate_legacy_runtime(base, 5)
            self.assertTrue((base / 'line_2/artifacts/sample.json').exists())
            self.assertFalse((base / 'line_5/artifacts/sample.json').exists())


@unittest.skipIf(TestClient is None, "接口集成测试需要额外安装 httpx")
class ProductionLineApiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, {'PRODUCTION_LINE_ID': '3', 'DASHBOARD_DATA_DIR': temporary.name})
        environment.start(); self.addCleanup(environment.stop)
        path = Path(__file__).resolve().parents[2] / 'dashboard/api/server.py'
        spec = importlib.util.spec_from_file_location('production_line_test_api', path)
        module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module
        self.addCleanup(sys.modules.pop, spec.name, None); spec.loader.exec_module(module)
        self.api = module; self.client = TestClient(module.app); self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        encoded = io.BytesIO(); Image.new('RGB', (320, 320), (35, 45, 65)).save(encoded, format='JPEG')
        self.jpeg = encoded.getvalue()

    def send_frame(self):
        return self.client.post('/api/device/ingest',
            data={'payload': json.dumps({'line_id': 3, 'frame_id': 'sample', 'result': 'NG',
                                         'frame': {'width': 320, 'height': 320}})},
            files={'frame': ('sample.jpg', self.jpeg, 'image/jpeg')})

    def test_only_configured_line_accepts_camera_data_and_images_cannot_cross_lines(self):
        info = self.client.get('/api/lines').json()
        self.assertEqual(info['active_line_id'], 3)
        self.assertEqual([row['id'] for row in info['lines']], [1, 2, 3, 4, 5])
        self.assertEqual(self.send_frame().status_code, 200)
        active = self.client.get('/api/state?line_id=3').json()
        other = self.client.get('/api/state?line_id=2').json()
        self.assertEqual(active['summary']['total_count'], 1)
        self.assertEqual(other['summary']['total_count'], 0)
        self.assertEqual(other['device']['stream_state'], 'no_signal')
        self.assertEqual(self.client.get(active['recent_results'][0]['image_url']).status_code, 200)
        self.assertEqual(self.client.get('/api/frame/sample?line_id=2').status_code, 404)
        self.assertEqual(self.client.get('/api/stream.mjpg?line_id=2').status_code, 409)
        self.assertEqual(self.client.post('/api/device/result', json={'line_id': 2, 'result': 'OK'}).status_code, 409)

    def test_offline_line_keeps_its_own_history(self):
        asyncio.run(self.api.lines.store(2).ingest({'frame_id': 'old-line-2', 'result': 'OK'}, frame_bytes=None))
        state = self.client.get('/api/state?line_id=2').json()
        self.assertFalse(state['camera_assigned']); self.assertFalse(state['device']['online'])
        self.assertEqual(state['summary']['total_count'], 1)
        self.assertEqual(state['latest_result']['frame_id'], 'old-line-2')
        self.assertEqual(self.client.get('/api/state?line_id=3').json()['summary']['total_count'], 0)
        self.assertEqual(self.client.get('/api/history/trend?line_id=2').status_code, 200)

    @unittest.skipUnless(shutil.which('node'), '前端图片地址回归验证需要 Node.js')
    def test_recent_image_url_remains_loadable_after_frontend_cache_busting(self):
        self.assertEqual(self.send_frame().status_code, 200)
        state = self.client.get('/api/state?line_id=3').json()
        image_url = state['recent_results'][0]['image_url']
        script = Path(__file__).with_name('check_image_urls.cjs')
        rendered_url = subprocess.run(
            [shutil.which('node'), str(script), image_url],
            check=True, capture_output=True, text=True, timeout=10,
        ).stdout
        response = self.client.get(rendered_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'image/jpeg')
        self.assertEqual(Image.open(io.BytesIO(response.content)).size, (320, 320))

    def test_ai_conversations_and_database_context_are_separate(self):
        self.assertEqual(self.send_frame().status_code, 200)
        conversation = self.client.post('/api/assistant/conversations?line_id=3', json={'title': '产线3'}).json()['conversation']
        self.assertEqual(self.client.get('/api/assistant/conversations?line_id=2').json()['conversations'], [])
        self.assertEqual(self.client.get('/api/assistant/conversations/' + conversation['id'] + '?line_id=2').status_code, 404)
        selected = self.api.lines.assistant(2).prepare_context('当前检测数')
        self.assertEqual(selected.context_payload['production_line']['id'], 2)
        self.assertEqual(selected.context_payload['inspection_records'], [])

    def test_websocket_subscriptions_do_not_receive_another_lines_updates(self):
        with self.client.websocket_connect('/ws/dashboard?line_id=2') as offline:
            self.assertEqual(offline.receive_json()['payload']['line_id'], 2)
            with self.client.websocket_connect('/ws/dashboard?line_id=3') as active:
                self.assertEqual(active.receive_json()['payload']['line_id'], 3)
                self.client.post('/api/device/heartbeat', json={'line_id': 3})
                self.assertEqual(active.receive_json()['payload']['line_id'], 3)
                offline.send_text('ping'); self.assertEqual(offline.receive_json()['type'], 'pong')

    def test_invalid_line_and_conflicting_payload_are_rejected(self):
        for value in (0, 6, 'abc'):
            self.assertEqual(self.client.get(f'/api/state?line_id={value}').status_code, 422)
        self.assertEqual(self.client.post('/api/device/result?line_id=3', json={'line_id': 2, 'result': 'NG'}).status_code, 409)
        self.assertEqual(self.client.post('/api/device/ingest', data={'payload': '[]'}).status_code, 400)
