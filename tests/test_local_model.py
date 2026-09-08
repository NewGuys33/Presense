import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest
from presense.local_model import LocalModel, LocalModelError
from bootstrap import patch_main, OLD, TRANSLATOR_OLD, TRANSLATOR_NEW


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.calls.append((self.path, data))
        code = 200
        if data['model'] == 'missing':
            code, result = 404, {'error': 'model missing'}
        elif self.path == '/api/show':
            result = {'remote_host': 'https://example.org'} if data['model'] == 'remote-alias' else {}
        elif data.get('format') == 'json':
            result = {'done': True, 'message': {'content': json.dumps({
                'prediction': 'voltage may decrease', 'prediction_translation': '电压可能降低',
                'live_translation': '当触发角增大', 'key_concepts': ['触发角']})}}
        else:
            result = {'done': True, 'message': {'content': '增大触发角会延迟导通。'}}
        raw = json.dumps(result).encode()
        self.send_response(code)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class LocalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.calls = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.model = LocalModel(base_url=self.url)

    async def asyncTearDown(self):
        await self.model.close()
        await asyncio.to_thread(self.server.shutdown)
        self.server.server_close()
        self.thread.join()

    async def test_translation_uses_local_native_endpoint_without_key(self):
        await self.model.check()
        self.assertEqual(await self.model.translate('Increasing alpha delays conduction.'), '增大触发角会延迟导通。')
        path, body = self.server.calls[-1]
        self.assertEqual(path, '/api/chat')
        self.assertFalse(body['stream'])
        self.assertNotIn('api_key', body)

    async def test_prediction_and_cold_start(self):
        req = {'history': ['Rectifier lecture'], 'live': 'When the firing angle increases', 'allow_prediction': True}
        self.assertEqual((await self.model(req))['prediction'], 'voltage may decrease')
        req['allow_prediction'] = False
        result = await self.model(req)
        self.assertEqual(result['prediction'], '')
        self.assertEqual(result['live_translation'], '当触发角增大')

    async def test_missing_model_has_actionable_error(self):
        model = LocalModel(model='missing', base_url=self.url)
        with self.assertRaisesRegex(LocalModelError, 'ollama pull missing'):
            await model.check()

    async def test_cloud_alias_is_rejected(self):
        model = LocalModel(model='remote-alias', base_url=self.url)
        with self.assertRaises(LocalModelError): await model.check()

    async def test_closed_provider_cannot_send(self):
        await self.model.close()
        with self.assertRaises(LocalModelError): await self.model.translate('test')
        self.assertEqual(self.server.calls, [])

    async def test_inference_is_serialized(self):
        active = peak = 0
        def fake(method, path, body=None):
            nonlocal active, peak
            import time
            active += 1
            peak = max(peak, active)
            time.sleep(0.03)
            active -= 1
            return {'done': True, 'message': {'content': '译文'}}
        self.model._request = fake
        await asyncio.gather(self.model.translate('one'), self.model.translate('two'))
        self.assertEqual(peak, 1)


class LocalConfigTests(unittest.TestCase):
    def test_remote_endpoints_and_cloud_tags_rejected(self):
        for url in ('https://api.openai.com', 'http://example.com', 'http://user@localhost:11434', 'http://localhost:11434/redirect'):
            with self.assertRaises(ValueError): LocalModel(base_url=url)
        with self.assertRaises(ValueError): LocalModel(model='model:cloud')

    def test_local_upstream_patch_does_not_construct_cloud_client(self):
        from types import SimpleNamespace
        def forbidden(config): raise AssertionError('Cloud client constructed')
        scope = {'self': SimpleNamespace(), 'trans_model': 'ollama', 'config': {}, 'TranslationService': forbidden}
        exec(TRANSLATOR_NEW.strip(), scope)
        self.assertIsNone(scope['self']._translator)
        patch = patch_main(OLD + '\n' + TRANSLATOR_OLD)
        self.assertIn(TRANSLATOR_NEW, patch)
        scope.update(trans_model='openai', TranslationService=lambda cfg: 'cloud')
        exec(TRANSLATOR_NEW.strip(), scope)
        self.assertEqual(scope['self']._translator, 'cloud')


if __name__ == '__main__': unittest.main()
