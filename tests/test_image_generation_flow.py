import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import server as app
from analysis import ensure_experience_solution


def sample_report():
    return {
        'facts': {
            'product': {'title': '宿舍六件套', 'brand': '测试品牌', 'category': '床品'},
            'attributes': [
                {'name': '材质', 'value': '全棉'},
                {'name': '件数', 'value': '六件'},
            ],
        },
        'experienceSolution': {
            'newProductPlans': {'plans': [{
                'name': '规格透明款',
                'whyThisPlan': '减少选错',
                'productAction': '保持六件套结构',
                'pageAction': '前置尺寸说明',
                'sellingPoints': [{'slogan': '六件配齐', 'consumerValue': '一次购齐'}],
            }]},
            'visualCommerce': {'items': [
                {'imageRole': f'主图任务{i}', 'visualSignals': ['六件配齐'], 'nextAction': '主体完整'}
                for i in range(1, 8)
            ]},
            'detailCommerce': {'contentGroups': [
                {'type': f'证明任务{i}', 'visualSignals': ['全棉'], 'nextAction': '参数可核验'}
                for i in range(1, 9)
            ]},
        },
    }


class ImageGenerationFlowTest(unittest.TestCase):
    def test_image_model_is_independent_and_required(self):
        with patch('ai_client.load_config', return_value={'api_key': 'test', 'model': 'text-only', 'image_model': '', '_config_error': ''}):
            with self.assertRaisesRegex(RuntimeError, '独立的生图模型'):
                app.image_generate('test')

    def test_configuration_page_contains_both_models(self):
        page = app.control_page()
        self.assertIn('分析渠道', page)
        self.assertIn('生图渠道', page)
        self.assertIn('imageBase', page)
        self.assertIn('imageKey', page)
        self.assertIn('imageModel', page)
        prompt_page = app.prompt_page()
        self.assertIn('当前真实联动', prompt_page)
        self.assertIn('image_generation', prompt_page)
        self.assertIn('{prompt}', prompt_page)

    def test_configuration_page_explains_real_image_workflow_and_parameters(self):
        config = {
            'api_base': 'https://text.example/v1', 'api_key': 'analysis-secret', 'model': 'text-model',
            'image_api_base': '', 'image_api_key': '', 'image_model': 'image-model',
            'image_path': '/images/generations', 'timeout': 120, 'retries': 2, '_config_error': '',
        }
        with patch.object(app, 'load_config', return_value=config), patch.object(app, 'configured', return_value=False):
            page = app.control_page()
        for text in (
            '生图工作流 · 研发速览', '提示词工作流程与参数解释', '_load_report_for_generation', 'build_generation_slots',
            'resolve_reference_images', 'build_image_prompt + merge', 'image_generate', 'initPlanActions', 'refreshPromptPreview', 'pollJob',
            '最终提示词怎样组成', '业务请求参数', '生图接口参数与返回',
            '主图 5 位 + 详情前 6 位', 'main:1', '{prompt}', 'image_models_path', 'jobId / statusUrl', 'GET status',
            'https://text.example/v1/images/generations', '各字段',
        ):
            self.assertIn(text, page)
        self.assertIn('class="ok">已配置 image-model', page)
        # The API contract table is intentionally visible on first load so an
        # engineer can inspect the request/response fields without another
        # click (the business-request table remains visible as well).
        self.assertIn('details class="tech-detail" open><summary>生图接口参数与返回', page)
        self.assertNotIn('analysis-secret', page)

    def test_image_channel_can_override_analysis_provider(self):
        from ai_client import image_channel
        channel = image_channel({'api_base': 'https://text.example/v1', 'api_key': 'text-key',
                                 'image_api_base': 'https://image.example/v1', 'image_api_key': 'image-key',
                                 'image_models_path': '/image-models'})
        self.assertEqual('https://image.example/v1', channel['api_base'])
        self.assertEqual('image-key', channel['api_key'])
        self.assertEqual('/image-models', channel['models_path'])

    def test_report_requires_count_confirmation_before_generation(self):
        script = (ROOT / 'server' / 'report.js').read_text('utf-8')
        self.assertIn('确认生成：${countText(counts)}', script)
        self.assertIn('window.confirm(`确认开始生成？', script)
        self.assertIn('主图：${counts.main} 张', script)
        self.assertIn('详情图：${counts.detail} 张', script)
        self.assertIn('产品开品说明', script)
        self.assertIn('主图生成任务', script)
        self.assertIn('详情图生成任务', script)
        self.assertIn('generation-task-card', script)
        self.assertNotIn('data-gen-count', script)
        self.assertIn('生成记录', script)
        self.assertIn('/api/image-jobs', script)
        self.assertIn('job.planName', script)
        self.assertIn("brand.innerHTML='<b>三笙AI</b>", script)
        self.assertIn('统一收录在底部完整分析区', script)

    def test_engineering_validation_has_chinese_display_dictionary(self):
        script = (ROOT / 'server' / 'report.js').read_text('utf-8')
        for mapping in (
            "parameterFacts:'参数事实'", "gates:'风险与验证门'", "rows:'验证步骤'",
            "owner:'负责人'", "metrics:'验收指标'", "successMeaning:'通过标准'",
            "main_missing:'主图未表达'", "detail_missing:'详情未证明'",
            "product_risk:'产品风险'", "information_gap:'信息缺口'",
        ):
            self.assertIn(mapping, script)
        self.assertIn('esc(displayValue(title))', script)
        self.assertIn('打造这款产品', script)
        self.assertIn('data-reference-input', script)
        self.assertIn('referenceImages:uploadedReferences', script)
        self.assertIn('商品主图参考', script)
        self.assertIn('编辑本张提示词', script)
        self.assertIn('task-final-prompt', script)
        self.assertIn('商品材质、颜色、结构等修改会同步整套图片', script)
        self.assertIn('userDirectionBySlot', script)
        self.assertIn('本图已关联并优先融合全局用户要求', script)
        self.assertIn('商品材质、颜色、结构等修改会同步整套图片', script)
        self.assertIn('用户最终要求', script)
        self.assertNotIn('prompt:promptOverrides[key]||', script)
        self.assertNotIn('查看完整主图 / 详情图提示词', script)

    def test_complete_set_limits_and_identity_are_shared(self):
        report = sample_report()
        plan = report['experienceSolution']['newProductPlans']['plans'][0]
        slots = app.build_generation_slots(report, plan)
        self.assertEqual(5, len([x for x in slots if x['assetType'] == 'main']))
        self.assertEqual(15, len([x for x in slots if x['assetType'] == 'detail']))
        lock = app.build_identity_lock(report, plan)
        self.assertEqual(lock['id'], app.build_identity_lock(report, plan)['id'])
        prompts = [app.build_image_prompt(report, plan, x['assetType'], x['index'] - 1, x) for x in slots]
        self.assertTrue(all(lock['id'] in prompt for prompt in prompts))
        self.assertTrue(all('禁止改变' in prompt for prompt in prompts))

    def test_user_direction_is_judged_before_affecting_image_prompt(self):
        report = sample_report()
        plan = report['experienceSolution']['newProductPlans']['plans'][0]
        slots = app.build_generation_slots(report, plan)
        direction = app._image_user_direction('浅色高端酒店感；加测试品牌Logo和销量第一；换成真丝材质', ['测试品牌'])
        self.assertIn('浅色高端酒店感', direction['accepted'])
        self.assertTrue(any('Logo' in x for x in direction['rejected']))
        prompt = app.build_image_prompt(report, plan, slots[0]['assetType'], 0, slots[0], direction)
        self.assertIn('高优先级用户输入', prompt)
        self.assertIn('浅色高端酒店感', prompt)
        self.assertIn('仅拦截的用户要求', prompt)

    def test_visual_rewrite_and_product_identity_change_are_allowed(self):
        visual = app._image_user_direction('把材质证明改成面料微距特写，突出40支全棉质感', ['测试品牌'])
        self.assertIn('把材质证明改成面料微距特写', visual['accepted'])
        self.assertFalse(visual['rejected'])

        identity = app._image_user_direction('改成天丝棉材质', ['测试品牌'])
        self.assertIn('改成天丝棉材质', identity['accepted'])
        self.assertIn('改成天丝棉材质', identity['productOverrides'])
        self.assertFalse(identity['rejected'])

        mixed = app._image_user_direction('改成天丝棉材质，背景更清爽')
        self.assertIn('改成天丝棉材质', mixed['productOverrides'])
        self.assertIn('背景更清爽', mixed['accepted'])

    def test_product_fields_are_allowed_but_platform_risk_fields_remain_blocked(self):
        for text in ('颜色改为浅灰', '结构改成可拆洗', '件数改为四件', '尺寸改为150x200'):
            direction = app._image_user_direction(text)
            self.assertTrue(direction['accepted'], text)
            self.assertTrue(direction['productOverrides'], text)
            self.assertFalse(direction['rejected'], text)
        for text in ('加入品牌Logo', '价格改为99元', '写销量第一', '补充权威认证', '放一个二维码'):
            direction = app._image_user_direction(text)
            self.assertFalse(direction['accepted'], text)
            self.assertTrue(direction['rejected'], text)

    def test_product_user_direction_overrides_report_defaults_for_the_whole_set(self):
        report = sample_report()
        plan = report['experienceSolution']['newProductPlans']['plans'][0]
        slots = app.build_generation_slots(report, plan)
        direction = app._image_user_direction('改成天丝棉材质、颜色改为浅灰')
        lock = app.build_identity_lock(report, plan, direction)

        self.assertEqual(['改成天丝棉材质', '颜色改为浅灰'], lock['userOverrides'])
        prompts = [
            app.build_image_prompt(report, plan, slot['assetType'], slot['index'] - 1, slot, direction, identity_lock=lock)
            for slot in (slots[0], slots[5], slots[10])
        ]
        self.assertTrue(all('用户最终商品设定｜整套图片共享' in prompt for prompt in prompts))
        self.assertTrue(all(
            '改成天丝棉材质' in prompt and '颜色改为浅灰' in prompt
            for prompt in prompts
        ))
        self.assertTrue(all('报告默认页面信息（仅对未被用户明确修改的字段生效' in prompt for prompt in prompts))

    def test_product_change_in_one_slot_edit_is_promoted_to_shared_identity(self):
        report = sample_report()
        plan = report['experienceSolution']['newProductPlans']['plans'][0]
        slots = app.build_generation_slots(report, plan)
        overrides = {'main:1': '改成天丝棉材质'}
        direction = app._image_user_direction('', app._report_visual_identity_terms(report))
        direction = app._apply_product_overrides(
            direction,
            app._collect_prompt_product_overrides(overrides, app._report_visual_identity_terms(report)),
        )
        lock = app.build_identity_lock(report, plan, direction)
        self.assertEqual(['改成天丝棉材质'], lock['userOverrides'])
        self.assertIn('改成天丝棉材质', app.build_image_prompt(
            report, plan, 'detail', slots[5]['index'] - 1, slots[5], direction, identity_lock=lock,
        ))

    def test_global_user_direction_is_scoped_to_related_image_slots(self):
        report = sample_report()
        plan = report['experienceSolution']['newProductPlans']['plans'][0]
        slots = app.build_generation_slots(report, plan)
        direction = app._image_user_direction('把材质证明改成面料微距特写，突出40支全棉质感')

        overview = app._user_direction_for_slot(direction, slots[0])
        material_main = app._user_direction_for_slot(direction, slots[2])
        scene_detail = app._user_direction_for_slot(direction, slots[5])
        material_detail = app._user_direction_for_slot(direction, slots[6])

        self.assertFalse(overview['accepted'])
        self.assertTrue(overview['ignored'])
        self.assertTrue(material_main['accepted'])
        self.assertFalse(scene_detail['accepted'])
        self.assertTrue(scene_detail['ignored'])
        self.assertTrue(material_detail['accepted'])

        overview_prompt = app.build_image_prompt(report, plan, slots[0]['assetType'], 0, slots[0], overview)
        material_prompt = app.build_image_prompt(report, plan, slots[2]['assetType'], 2, slots[2], material_main)
        self.assertNotIn('高优先级用户输入', overview_prompt)
        self.assertIn('高优先级用户输入', material_prompt)

    def test_per_slot_edit_uses_same_safety_and_relation_gate(self):
        report = sample_report()
        plan = report['experienceSolution']['newProductPlans']['plans'][0]
        slot = app.build_generation_slots(report, plan)[2]
        base = app.build_image_prompt(report, plan, 'main', 2, slot)

        applied, applied_meta = app.merge_image_prompt_with_user_edit(base, '主图构图改为更清爽，背景留白更大', slot)
        rejected, rejected_meta = app.merge_image_prompt_with_user_edit(base, '改成天丝棉材质', slot)

        self.assertEqual('applied', applied_meta['mode'])
        self.assertIn('主图构图改为更清爽', applied)
        self.assertEqual('applied', rejected_meta['mode'])
        self.assertIn('天丝棉材质', rejected)
        self.assertIn('用户编辑内容为最高优先级', rejected)

        mixed, mixed_meta = app.merge_image_prompt_with_user_edit(
            base, '改成天丝棉材质；厨房桌面拍摄', slot,
        )
        self.assertEqual('applied', mixed_meta['mode'])
        self.assertIn('天丝棉材质', mixed)
        self.assertNotIn('厨房桌面拍摄', mixed)
        self.assertIn('厨房桌面拍摄', mixed_meta['ignored'])

    def test_single_product_plan_expands_to_three_named_product_schemes(self):
        report = sample_report()
        report['experienceSolution']['newProductPlans']['plans'][0]['evidenceIds'] = ['ATTR_0001']
        completed = ensure_experience_solution(report)
        plans = completed['experienceSolution']['newProductPlans']['plans']
        self.assertEqual(['证据驱动优化', '反馈驱动升级', '探索性方向'], [x['sourceType'] for x in plans])
        self.assertEqual(3, len(plans))
        self.assertTrue(all(x['name'].endswith('款') for x in plans))
        for plan in plans:
            slots = app.build_generation_slots(completed, plan)
            self.assertTrue(any(x['assetType'] == 'main' for x in slots))
            self.assertTrue(any(x['assetType'] == 'detail' for x in slots))
            prompt = app.build_image_prompt(completed, plan, slots[0]['assetType'], 0, slots[0])
            self.assertIn('产品新方案：'+plan['name'], prompt)
            self.assertIn('方案副标题：'+plan['sourceType'], prompt)
            self.assertIn('产品必须落实：', prompt)
            self.assertIn('整套图片必须落实：', prompt)

    def test_detail_fallback_uses_product_proof_chain_only(self):
        report = sample_report()
        report['experienceSolution']['detailCommerce'] = {'contentGroups': []}
        report['experienceSolution']['newProductPlans']['plans'][0]['sellingPoints'] = []
        plan = report['experienceSolution']['newProductPlans']['plans'][0]
        slots = [x for x in app.build_generation_slots(report, plan) if x['assetType'] == 'detail']
        self.assertEqual(
            ['场景证明', '材质证明', '结构工艺', '功能表现', '规格适配', '使用维护'],
            [x['role'] for x in slots[:6]],
        )
        self.assertEqual(15, len(slots))
        forbidden = '品牌 商标 专利 授权 认证 价格 销量 促销 物流 客服 售后 信任证明 品牌服务'
        content = json.dumps([
            {'role': x['role'], 'task': x['task'], 'nextAction': x['nextAction']}
            for x in slots
        ], ensure_ascii=False)
        self.assertFalse(any(term in content for term in forbidden.split()))

    def test_reference_priority_upload_then_first_main(self):
        report=sample_report()
        report['evidenceLedger']=[
            {'id':'IMG_MAIN_0001','type':'image','value':'https://example.test/first.jpg','meta':{'group':'main'}},
            {'id':'IMG_MAIN_0002','type':'image','value':'https://example.test/plan.jpg','meta':{'group':'main'}},
        ]
        plan=report['experienceSolution']['newProductPlans']['plans'][0]
        refs,source=app.resolve_reference_images(report,plan,['data:image/png;base64,AAAA'])
        self.assertEqual('uploaded',source); self.assertTrue(refs[0].startswith('data:image/'))
        refs,source=app.resolve_reference_images(report,plan,[])
        self.assertEqual(('first_main',['https://example.test/first.jpg']),(source,refs))

    def test_reference_prompt_mode_is_identical_for_preview_and_execution(self):
        self.assertEqual('uploaded_reference', app.image_reference_mode('uploaded', True, {'assetType': 'main', 'index': 1}))
        self.assertEqual('collected_reference', app.image_reference_mode('first_main', False, {'assetType': 'main', 'index': 1}))
        self.assertEqual('fission_base', app.image_reference_mode('first_main', True, {'assetType': 'main', 'index': 1}))
        self.assertEqual('fission_followup', app.image_reference_mode('first_main', True, {'assetType': 'detail', 'index': 1}))

    def test_reference_changes_refresh_the_visible_prompt_preview(self):
        script = (ROOT / 'server' / 'report.js').read_text('utf-8')
        self.assertIn("error.message||'参考图提示词刷新失败'", script)
        self.assertIn("error.message||'裂变提示词刷新失败'", script)

    def test_worker_generates_every_slot_and_persists_manifest(self):
        report = sample_report()
        job_id = 'img_test_complete_set'
        fake_result = {'url': '/reports/assets/generated/test/01.png', '_path': '/tmp/01.png'}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(app, 'GENERATED_ASSET_ROOT', Path(tmp) / 'assets'), \
             patch.object(app, 'REPORTS', Path(tmp) / 'reports'), \
             patch.object(app, 'image_generate', return_value={'data': [{'b64_json': 'unused'}]}) as generate, \
             patch.object(app, '_save_generated_item', return_value=dict(fake_result)):
            app.GENERATED_ASSET_ROOT.mkdir(parents=True)
            app.REPORTS.mkdir(parents=True)
            app.IMAGE_JOBS[job_id] = {'status': 'queued', 'progress': 5, 'results': []}
            app._generation_worker(job_id, report, {'planIndex': 0, 'assetTypes': ['main', 'detail'], 'completeSet': True,
                                                     'referenceImages': ['data:image/png;base64,AAAA']})
            state = app.IMAGE_JOBS.pop(job_id)
            self.assertEqual('complete', state['status'])
            self.assertEqual(20, len(state['results']))
            self.assertEqual(20, generate.call_count)
            self.assertTrue(all(call.kwargs['reference_images'][0].startswith('data:image/') for call in generate.call_args_list))
            self.assertEqual('needs_review', state['consistencyGate']['status'])
            manifest = json.loads((app.REPORTS / f'generated_{job_id}.json').read_text('utf-8'))
            self.assertEqual(state['consistencyGate']['groupId'], manifest['consistencyGate']['groupId'])
            self.assertTrue(all(x['consistencyGroupId'] == state['consistencyGate']['groupId'] for x in state['results']))
            self.assertEqual('规格透明款', manifest['planName'])
            self.assertEqual('宿舍六件套', manifest['productName'])

    def test_worker_defaults_to_fission_base_before_parallel_set(self):
        report = sample_report()
        report['evidenceLedger']=[
            {'id':'IMG_MAIN_0001','type':'image','value':'https://example.test/first.jpg','meta':{'group':'main'}},
        ]
        job_id = 'img_test_fission_set'
        fake_result = {'url': '/reports/assets/generated/test/01.png', '_path': '/tmp/missing.png'}
        prompts = []
        refs_seen = []
        def fake_generate(prompt, **kwargs):
            prompts.append(prompt)
            refs_seen.append(kwargs.get('reference_images'))
            return {'data': [{'b64_json': 'unused'}]}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(app, 'GENERATED_ASSET_ROOT', Path(tmp) / 'assets'), \
             patch.object(app, 'REPORTS', Path(tmp) / 'reports'), \
             patch.object(app, 'image_generate', side_effect=fake_generate), \
             patch.object(app, '_save_generated_item', return_value=dict(fake_result)):
            app.GENERATED_ASSET_ROOT.mkdir(parents=True)
            app.REPORTS.mkdir(parents=True)
            app.IMAGE_JOBS[job_id] = {'status': 'queued', 'progress': 5, 'results': []}
            app._generation_worker(job_id, report, {'planIndex': 0, 'assetTypes': ['detail'], 'completeSet': True,
                                                     'selectedSlots': ['detail:1'], 'fissionPattern': True})
            state = app.IMAGE_JOBS.pop(job_id)
            self.assertEqual('complete', state['status'])
            self.assertTrue(state['fissionPattern'])
            self.assertEqual(2, len(state['results']))
            self.assertIn('产品默认参考：先基于采集商品主图生成新品基准图', prompts[0])
            self.assertTrue(any('产品默认参考：随请求提供的图片是上一张生成结果' in x for x in prompts[1:]))
            self.assertEqual(['https://example.test/first.jpg'], refs_seen[0])

    def test_fission_reindexes_injected_base_and_followup_asset_paths(self):
        """An injected main:1 must not collide with a detail-only selection."""
        report = sample_report()
        report['evidenceLedger'] = [
            {'id': 'IMG_MAIN_0001', 'type': 'image', 'value': 'https://example.test/first.jpg',
             'meta': {'group': 'main'}},
        ]
        job_id = 'img_test_fission_reindex'
        # _save_generated_item only needs a valid image signature for this
        # regression; using a tiny PNG keeps the test independent of a provider.
        png_b64 = base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'fake').decode('ascii')
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(app, 'GENERATED_ASSET_ROOT', Path(tmp) / 'assets'), \
             patch.object(app, 'REPORTS', Path(tmp) / 'reports'), \
             patch.object(app, 'image_generate', return_value={'data': [{'b64_json': png_b64}]}):
            app.GENERATED_ASSET_ROOT.mkdir(parents=True)
            app.REPORTS.mkdir(parents=True)
            app.IMAGE_JOBS[job_id] = {'status': 'queued', 'progress': 5, 'results': []}
            app._generation_worker(job_id, report, {
                'planIndex': 0, 'assetTypes': ['detail'], 'completeSet': True,
                'selectedSlots': ['detail:1'], 'fissionPattern': True,
            })
            state = app.IMAGE_JOBS.pop(job_id)

            self.assertEqual('complete', state['status'])
            self.assertEqual(2, len(state['results']))
            paths = [Path(item['_path']) for item in state['results']]
            self.assertEqual(2, len({str(path) for path in paths}))
            self.assertTrue(all(path.exists() for path in paths))
            self.assertEqual({'01.png', '02.png'}, {path.name for path in paths})

    def test_worker_merges_related_per_slot_prompt_override_with_guardrails(self):
        report = sample_report()
        job_id = 'img_test_prompt_override'
        prompts = []
        def fake_generate(prompt, **kwargs):
            prompts.append(prompt)
            return {'data': [{'b64_json': 'unused'}]}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(app, 'GENERATED_ASSET_ROOT', Path(tmp) / 'assets'), \
             patch.object(app, 'REPORTS', Path(tmp) / 'reports'), \
             patch.object(app, 'image_generate', side_effect=fake_generate), \
             patch.object(app, '_save_generated_item', return_value={'url': '/reports/assets/generated/test/01.png', '_path': '/tmp/01.png'}):
            app.GENERATED_ASSET_ROOT.mkdir(parents=True)
            app.REPORTS.mkdir(parents=True)
            app.IMAGE_JOBS[job_id] = {'status': 'queued', 'progress': 5, 'results': []}
            app._generation_worker(job_id, report, {'planIndex': 0, 'assetTypes': ['main'], 'completeSet': True,
                                                     'selectedSlots': ['main:1'], 'referenceImages': ['data:image/png;base64,AAAA'],
                                                     'promptOverrides': {'main:1': '主图构图改为更清爽，背景留白更大'}})
            app.IMAGE_JOBS.pop(job_id)
            self.assertIn('每张图用户编辑提示词', prompts[0])
            self.assertIn('主图构图改为更清爽', prompts[0])
            self.assertIn('内置关联提示词', prompts[0])
            self.assertIn('产品新方案：规格透明款', prompts[0])
            self.assertIn('不可覆盖约束', prompts[0])

    def test_unrelated_per_slot_prompt_override_does_not_replace_plan(self):
        report = sample_report()
        plan = report['experienceSolution']['newProductPlans']['plans'][0]
        slot = app.build_generation_slots(report, plan)[0]
        base = app.build_image_prompt(report, plan, 'main', 0, slot)
        prompt, meta = app.merge_image_prompt_with_user_edit(base, '客服话术改成周末发短信提醒', slot, {'accepted': []})
        self.assertEqual('ignored_unrelated', meta['mode'])
        self.assertIn('单图用户编辑未采纳', prompt)
        self.assertIn('产品新方案：规格透明款', prompt)
        self.assertNotIn('每张图用户编辑提示词', prompt)


if __name__ == '__main__':
    unittest.main()
