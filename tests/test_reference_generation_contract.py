import base64
import json
import sys
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import server as app
import ai_client


class ReferenceContractTest(unittest.TestCase):
    def test_original_analysis_survives_rewritten_report_roles(self):
        report = {
            'facts': {'images': {'main': ['https://example.test/1.png', 'https://example.test/2.png']}},
            'evidenceLedger': [
                {'id': f'IMG_MAIN_{i:04d}', 'type': 'image', 'value': f'https://example.test/{i}.png', 'meta': {'group': 'main'}}
                for i in (1, 2)
            ],
            'experienceSolution': {'visualCommerce': {'items': [
                {'imageEvidenceId': 'IMG_MAIN_0002', 'imageRole': '使用场景', 'visualSignals': ['四季通用']}
            ], 'evidenceDetail': []}},
            'visualDecision': {
                'imageRoles': [
                    {'imageEvidenceId': 'IMG_MAIN_0002', 'imageRole': '材质触感', 'visualSignals': ['面料细节'], 'businessMeaning': '面料特写'}
                ],
                'evidenceDetail': [
                    {'imageEvidenceId': 'IMG_MAIN_0002', 'composition': '面料特写背景，中央信息卡片', 'textInfo': '面料细节'}
                ],
            },
        }
        observation = report['visualDecision']['evidenceDetail'][0]
        observation['textInfo'] = '面料细节' + '完整参考文字' * 60
        observation['composition'] += '保持原始布局' * 100
        observation['textLayout'] = {'position': '中央', 'alignment': 'left', 'lines': 3}
        observation['displayRelations'] = {'visibleParts':[{'id':'a','description':'上层可见区域'},{'id':'b','description':'回折区域'}],
                                          'relations':[{'type':'连接','from':'a','to':'b','observation':'左侧连续回折，不是独立叠放'}]}
        role = report['visualDecision']['imageRoles'][0]
        role['visualSignals'] = ['面料细节'] + ['完整分析' * 30] * 6
        slot = app.build_generation_slots(report, {})[1]
        self.assertEqual('材质触感', slot['referenceAnalysis']['theme'])
        self.assertEqual(observation['textInfo'], slot['referenceTextInfo'])
        self.assertEqual(observation['composition'], slot['referenceAnalysis']['composition'])
        self.assertEqual(observation, slot['referenceAnalysis']['imageObservation'])
        self.assertEqual(role, slot['referenceAnalysis']['imageRoleAnalysis'])
        self.assertEqual(role['visualSignals'], slot['referenceAnalysis']['signals'])
        self.assertEqual(observation['displayRelations'],slot['referenceAnalysis']['displayRelations'])
        prompt = app.build_image_prompt(report, {}, slot=slot, variant_index=1,
                                        product_reference_mode='uploaded_identity_collected_reference', match_reference_shooting=True)
        self.assertIn('原始图片主题：材质触感', prompt)
        self.assertIn('面料特写背景，中央信息卡片', prompt)
        self.assertNotIn('唯一任务：', prompt)
        self.assertIn(observation['textInfo'], prompt)
        self.assertIn(observation['composition'], prompt)
        self.assertIn('左侧连续回折，不是独立叠放',prompt)

    def test_reference_download_uses_certificate_context_and_exact_bytes(self):
        image = b'\x89PNG\r\n\x1a\nimage-content'
        with patch.object(app, '_download_image', return_value=(image, 'image/png')):
            data_url = app._reference_data_url('https://example.test/reference.png')
        self.assertEqual(image, base64.b64decode(data_url.split(',', 1)[1]))
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = image
        response.headers.get.return_value = 'image/png'
        with patch.object(app, '_ssl_context', return_value='trusted-context'), \
             patch.object(app, 'load_config', return_value={}), \
             patch.object(app.urllib.request, 'urlopen', return_value=response) as open_url:
            self.assertEqual(image, app._download_image('https://example.test/reference.png')[0])
        self.assertEqual('trusted-context', open_url.call_args.kwargs['context'])

    def test_apiyi_request_contains_ordered_image_files_and_complete_prompt(self):
        images = [b'\x89PNG\r\n\x1a\nproduct-image', b'\x89PNG\r\n\x1a\ncollected-image']
        refs = ['data:image/png;base64,' + base64.b64encode(data).decode() for data in images]
        prompt = '图1提供产品身份；图2为展示母版。\n保持折叠状态和文字排版。'
        config = {'api_base': 'https://api.apiyi.com/v1', 'api_key': 'test-key',
                  'image_model': 'gpt-image-2', 'image_path': '/images/generations',
                  'timeout': 10, 'retries': 0}
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({'data': [{'b64_json': 'result'}]}).encode()
        with patch.object(ai_client, 'image_channel', return_value=config), \
             patch.object(ai_client, '_ssl_context', return_value='trusted-context'), \
             patch.object(ai_client.urllib.request, 'urlopen', return_value=response) as open_url:
            result = ai_client.image_generate(prompt, model='gpt-image-2', size='1024x1024', quality='high', reference_images=refs)
        self.assertEqual('result', result['data'][0]['b64_json'])
        request = open_url.call_args.args[0]
        self.assertEqual('https://api.apiyi.com/v1/images/edits', request.full_url)
        content_type = request.get_header('Content-type')
        message = BytesParser(policy=policy.default).parsebytes(
            ('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + request.data)
        fields = {}
        files = []
        for part in message.iter_parts():
            name = part.get_param('name', header='content-disposition')
            data = part.get_payload(decode=True)
            if name == 'image[]':
                files.append(data)
            else:
                fields[name] = data.decode('utf-8')
        self.assertEqual(images, files)
        self.assertEqual(prompt, fields['prompt'])
        self.assertEqual({'model': 'gpt-image-2', 'size': '1024x1024', 'quality': 'high', 'n': '1'},
                         {key: value for key, value in fields.items() if key != 'prompt'})

    def test_invalid_reference_never_sends_request(self):
        config = {'api_base': 'https://api.apiyi.com/v1', 'api_key': 'test-key',
                  'image_model': 'gpt-image-2', 'image_path': '/images/generations',
                  'timeout': 10, 'retries': 0}
        with patch.object(ai_client, 'image_channel', return_value=config), \
             patch.object(ai_client.urllib.request, 'urlopen') as open_url:
            with self.assertRaises(RuntimeError):
                ai_client.image_generate('保留展示状态', reference_images=['data:image/png;base64,aW52YWxpZA=='])
        open_url.assert_not_called()


if __name__ == '__main__':
    unittest.main()
