import base64
import json
import ssl
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from io import BytesIO
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

    def test_image_quality_is_sent_per_request(self):
        import ai_client
        config = {
            'api_base': 'https://image.example/v1', 'api_key': 'image-key',
            'image_model': 'gpt-image-2.5-flare', 'image_path': '/images/generations',
            'image_quality': 'low', 'timeout': 120, 'retries': 0, '_config_error': '',
        }
        response = {'data': [{'b64_json': 'unused'}]}
        with patch.object(ai_client, 'image_channel', return_value=config), \
             patch.object(ai_client, '_do_post_path', return_value=response) as post:
            actual = ai_client.image_generate('test', quality='high')
        self.assertEqual(response, actual)
        self.assertEqual('high', post.call_args.args[2]['quality'])

    def test_comparison_models_keep_independent_quality(self):
        report = sample_report()
        job_id = 'img_test_model_quality_comparison'
        calls = []

        def fake_generate(prompt, **kwargs):
            calls.append(kwargs)
            return {'data': [{'b64_json': 'unused'}]}

        config = {
            'api_key': 'image-key', 'model': 'text-model', 'image_model': 'flare',
            'image_models': [
                {'id': 'flare', 'label': 'Flare'},
                {'id': 'sunburst', 'label': 'Sunburst'},
            ],
            '_config_error': '',
        }
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(app, 'load_config', return_value=config), \
             patch.object(app, 'GENERATED_ASSET_ROOT', Path(tmp) / 'assets'), \
             patch.object(app, 'REPORTS', Path(tmp) / 'reports'), \
             patch.object(app, 'image_generate', side_effect=fake_generate), \
             patch.object(app, '_save_generated_item', side_effect=lambda *args, **kwargs: {
                 'url': '/reports/assets/generated/test/01.png', '_path': '/tmp/01.png',
             }):
            app.GENERATED_ASSET_ROOT.mkdir(parents=True)
            app.REPORTS.mkdir(parents=True)
            app.IMAGE_JOBS[job_id] = {'status': 'queued', 'progress': 5, 'results': []}
            app._generation_worker(job_id, report, {
                'planIndex': 0, 'assetTypes': ['main'], 'completeSet': True,
                'selectedSlots': ['main:1'], 'fissionPattern': False,
                'referenceImages': ['data:image/png;base64,AAAA'],
                'imageModels': [
                    {'id': 'flare', 'quality': 'medium'},
                    {'id': 'sunburst', 'quality': 'high'},
                ],
            })
            state = app.IMAGE_JOBS.pop(job_id)

        self.assertEqual('complete', state['status'])
        self.assertEqual(['high', 'medium'], sorted(item.get('quality') for item in calls))
        self.assertEqual({'flare': 'medium', 'sunburst': 'high'}, {
            item['model']: item['quality'] for item in state['results']
        })
        self.assertEqual(['medium', 'high'], [item['quality'] for item in state['comparisonModels']])

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
        self.assertIn('本次生成参数', script)
        self.assertIn('请求质量', script)
        self.assertIn('generation-task-result-meta', script)
        self.assertIn('质量：${modelQuality(item)}', script)

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
        self.assertIn('按此方向开品', script)
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
            self.assertNotIn(plan['name'], prompt)
            self.assertNotIn(plan['sourceType'], prompt)
            self.assertIn('产品与页面执行约束：', prompt)
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
        self.assertEqual('uploaded_identity_collected_reference', app.image_reference_mode(
            'uploaded', False, {'assetType': 'main', 'index': 1}, True,
        ))
        self.assertEqual('collected_reference', app.image_reference_mode('first_main', False, {'assetType': 'main', 'index': 1}))
        self.assertEqual('fission_base', app.image_reference_mode('first_main', True, {'assetType': 'main', 'index': 1}))
        self.assertEqual('fission_followup', app.image_reference_mode('first_main', True, {'assetType': 'detail', 'index': 1}))

    def test_reference_shooting_toggle_has_strict_boolean_defaults_and_aliases(self):
        self.assertFalse(app._match_reference_shooting({}, False))
        self.assertTrue(app._match_reference_shooting({'matchReferenceShooting': True}, False))
        self.assertFalse(app._match_reference_shooting({'matchReferenceShooting': 'false'}, True))
        self.assertTrue(app._match_reference_shooting({'referenceShootingMatch': 'on'}, False))
        self.assertFalse(app._match_reference_shooting({'reference_shooting_match': 'off'}, True))
        # Unknown values must fall back to the explicit default rather than
        # treating every non-empty form string as true.
        self.assertFalse(app._match_reference_shooting({'matchReferenceShooting': 'off-ish'}, False))

    def test_reference_shooting_toggle_changes_prompt_without_changing_product_goal(self):
        report = sample_report()
        plan = report['experienceSolution']['newProductPlans']['plans'][0]
        slot = app.build_generation_slots(report, plan)[0]
        disabled = app.build_image_prompt(
            report, plan, 'main', 0, slot,
            product_reference_mode='uploaded_reference',
            match_reference_shooting=False,
        )
        enabled = app.build_image_prompt(
            report, plan, 'main', 0, slot,
            product_reference_mode='uploaded_reference',
            match_reference_shooting=True,
        )
        self.assertIn('matchReferenceShooting=false', disabled)
        self.assertIn('不继承参考图的拍摄语言或产品展示状态', disabled)
        self.assertIn('不要复制其机位、景别', disabled)
        self.assertIn('matchReferenceShooting=true', enabled)
        self.assertIn('拍摄语言必须尽量一致：机位与视角', enabled)
        self.assertIn('产品展示状态必须具体复现', enabled)
        self.assertIn('动作状态必须具体复现', enabled)
        self.assertIn('支撑点、遮挡关系、部件相对位置', enabled)
        self.assertIn('action direction and action phase', enabled)
        self.assertIn('业务目标（不可丢失）', enabled)
        self.assertIn('产品目标（不可丢失）', enabled)
        self.assertNotIn('规格透明款', enabled)
        self.assertIn('保持用户最终确认的商品品类', enabled)
        enabled_benchmark = enabled[enabled.index('爆款商品特征借鉴') : enabled.index('本套图中的第')]
        self.assertIn('只借鉴高转化的信息层级、证明顺序、文字层次和转化逻辑', enabled_benchmark)
        self.assertNotIn('借鉴爆款主图/详情图的高转化结构、主体占比、场景钩子', enabled_benchmark)
        self.assertIn('以参考图拍摄语言为主', enabled)
        self.assertIn('最小适配', enabled)
        # With the switch off, the normal ecommerce composition remains the
        # source of truth instead of inheriting the reference shoot.
        self.assertIn('商品主体占画面60-80%', disabled)
        self.assertNotEqual(disabled, enabled)

    def test_reference_shooting_prompt_freezes_first_main_product_and_is_bilingual(self):
        report = sample_report()
        plan = report['experienceSolution']['newProductPlans']['plans'][0]
        slots = [item for item in app.build_generation_slots(report, plan) if item['assetType'] == 'main']
        first = app.build_image_prompt(
            report, plan, 'main', 0, slots[0],
            product_reference_mode='uploaded_reference',
            match_reference_shooting=True,
        )
        second = app.build_image_prompt(
            report, plan, 'main', 1, slots[1],
            product_reference_mode='uploaded_reference',
            match_reference_shooting=True,
        )
        # main:1 is the product master; later slots inherit the same identity
        # but must not be labelled as the first-image master.
        self.assertIn('首张主图（main:1）', first)
        self.assertIn('第一张参考图作为商品外观母版', first)
        self.assertIn('只有“产品目标”或用户最终设定明确列出的字段可以改变', first)
        self.assertIn('当前槽位继续继承同一产品身份', second)
        self.assertNotIn('首张主图（main:1）', second)
        self.assertIn('【English constraints】Match both the reference shooting grammar', first)
        self.assertIn('Preserve the current product silhouette', first)
        # Business/product goals must be stated before the lower-priority
        # shooting language so a provider cannot trade conversion intent for
        # visual imitation.
        self.assertLess(first.index('产品目标（不可丢失）'), first.index('拍摄语言必须尽量一致：机位与视角'))

    def test_reference_shooting_toggle_is_persisted_on_worker_and_each_result(self):
        report = sample_report()
        job_id = 'img_test_reference_shooting_toggle'
        prompts = []

        def fake_generate(prompt, **kwargs):
            prompts.append(prompt)
            return {'data': [{'b64_json': 'unused'}]}

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(app, 'GENERATED_ASSET_ROOT', Path(tmp) / 'assets'), \
             patch.object(app, 'REPORTS', Path(tmp) / 'reports'), \
             patch.object(app, 'image_generate', side_effect=fake_generate), \
             patch.object(app, '_save_generated_item', side_effect=lambda *args, **kwargs: {
                 'url': '/reports/assets/generated/test/01.png', '_path': '/tmp/01.png',
             }):
            app.GENERATED_ASSET_ROOT.mkdir(parents=True)
            app.REPORTS.mkdir(parents=True)
            app.IMAGE_JOBS[job_id] = {'status': 'queued', 'progress': 5, 'results': []}
            app._generation_worker(job_id, report, {
                'planIndex': 0, 'assetTypes': ['main'], 'completeSet': True,
                'selectedSlots': ['main:1'], 'fissionPattern': False,
                'referenceImages': ['data:image/png;base64,AAAA'],
                'matchReferenceShooting': True,
            })
            state = app.IMAGE_JOBS.pop(job_id)
            self.assertEqual('complete', state['status'])
            self.assertTrue(state['matchReferenceShooting'])
            self.assertEqual('match_reference', state['referenceShootingPolicy'])
            self.assertTrue(state['results'][0]['matchReferenceShooting'])
            self.assertIn('matchReferenceShooting=true', prompts[0])
            manifest = json.loads((app.REPORTS / f'generated_{job_id}.json').read_text('utf-8'))
            self.assertTrue(manifest['matchReferenceShooting'])
            self.assertEqual('match_reference', manifest['referenceShootingPolicy'])

    def test_match_reference_shooting_binds_collected_image_to_each_slot(self):
        """Matching mode must use the corresponding source image, not one shared first image."""
        report = sample_report()
        report['facts']['images'] = {'main': [
            'https://example.test/main-1.jpg',
            'https://example.test/main-2.jpg',
        ]}
        report['evidenceLedger'] = [
            {'id': 'IMG_MAIN_0001', 'type': 'image', 'value': 'https://example.test/main-1.jpg',
             'meta': {'group': 'main'}},
            {'id': 'IMG_MAIN_0002', 'type': 'image', 'value': 'https://example.test/main-2.jpg',
             'meta': {'group': 'main'}},
        ]
        job_id = 'img_test_slot_reference_binding'
        calls = []

        def fake_generate(prompt, **kwargs):
            calls.append((prompt, list(kwargs.get('reference_images') or [])))
            return {'data': [{'b64_json': 'unused'}]}

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(app, 'GENERATED_ASSET_ROOT', Path(tmp) / 'assets'), \
             patch.object(app, 'REPORTS', Path(tmp) / 'reports'), \
             patch.object(app, 'image_generate', side_effect=fake_generate), \
             patch.object(app, '_save_generated_item', side_effect=lambda *args, **kwargs: {
                 'url': '/reports/assets/generated/test/01.png', '_path': '/tmp/01.png',
             }):
            app.GENERATED_ASSET_ROOT.mkdir(parents=True)
            app.REPORTS.mkdir(parents=True)
            app.IMAGE_JOBS[job_id] = {'status': 'queued', 'progress': 5, 'results': []}
            app._generation_worker(job_id, report, {
                'planIndex': 0, 'assetTypes': ['main'], 'completeSet': True,
                'selectedSlots': ['main:1', 'main:2'], 'fissionPattern': True,
                'matchReferenceShooting': True,
            })
            state = app.IMAGE_JOBS.pop(job_id)

        self.assertEqual('complete', state['status'])
        self.assertFalse(state['fissionPattern'])
        first = next(item for item in calls if '第1版main' in item[0])
        second = next(item for item in calls if '第2版main' in item[0])
        self.assertEqual(['https://example.test/main-1.jpg'], first[1])
        self.assertEqual(['https://example.test/main-2.jpg'], second[1])
        self.assertIn('当前槽位参考图绑定', first[0])
        self.assertIn('IMG_MAIN_0001', first[0])
        self.assertIn('IMG_MAIN_0002', second[0])
        main2 = next(item for item in state['results'] if item['slotIndex'] == 2)
        self.assertEqual('slot_evidence_reference', main2['referenceBinding'])
        self.assertEqual('IMG_MAIN_0002', main2['referenceEvidenceId'])

    def test_uploaded_identity_does_not_override_collected_slot_display_state(self):
        """Uploaded product identity and collected slot presentation must be separate inputs."""
        report = sample_report()
        report['facts']['images'] = {
            'main': ['https://example.test/collected-main-1.jpg', 'https://example.test/collected-main-2.jpg'],
            'detail': ['https://example.test/collected-detail-1.jpg'],
        }
        report['evidenceLedger'] = [
            {'id': 'IMG_MAIN_0001', 'type': 'image', 'value': 'https://example.test/collected-main-1.jpg',
             'meta': {'group': 'main'}},
            {'id': 'IMG_MAIN_0002', 'type': 'image', 'value': 'https://example.test/collected-main-2.jpg',
             'meta': {'group': 'main'}},
            {'id': 'IMG_DETAIL_0001', 'type': 'image', 'value': 'https://example.test/collected-detail-1.jpg',
             'meta': {'group': 'detail'}},
        ]
        job_id = 'img_test_hybrid_reference_roles'
        calls = []

        def fake_generate(prompt, **kwargs):
            calls.append((prompt, list(kwargs.get('reference_images') or [])))
            return {'data': [{'b64_json': 'unused'}]}

        uploaded = 'data:image/png;base64,UPLOADED_PRODUCT'
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(app, 'GENERATED_ASSET_ROOT', Path(tmp) / 'assets'), \
             patch.object(app, 'REPORTS', Path(tmp) / 'reports'), \
             patch.object(app, 'image_generate', side_effect=fake_generate), \
             patch.object(app, '_save_generated_item', side_effect=lambda *args, **kwargs: {
                 'url': '/reports/assets/generated/test/01.png', '_path': '/tmp/01.png',
             }):
            app.GENERATED_ASSET_ROOT.mkdir(parents=True)
            app.REPORTS.mkdir(parents=True)
            app.IMAGE_JOBS[job_id] = {'status': 'queued', 'progress': 5, 'results': []}
            app._generation_worker(job_id, report, {
                'planIndex': 0, 'assetTypes': ['main', 'detail'], 'completeSet': True,
                'selectedSlots': ['main:1', 'main:2', 'detail:1'], 'fissionPattern': True,
                'referenceImages': [uploaded], 'matchReferenceShooting': True,
            })
            state = app.IMAGE_JOBS.pop(job_id)

        self.assertEqual('complete', state['status'])
        self.assertFalse(state['fissionPattern'])
        main1 = next(item for item in calls if '第1版main' in item[0])
        main2 = next(item for item in calls if '第2版main' in item[0])
        detail1 = next(item for item in calls if '第1版detail' in item[0])
        # Every slot receives the uploaded identity master first and its own
        # collected display-state master second.
        self.assertEqual([uploaded, 'https://example.test/collected-main-1.jpg'], main1[1])
        self.assertEqual([uploaded, 'https://example.test/collected-main-2.jpg'], main2[1])
        self.assertEqual([uploaded, 'https://example.test/collected-detail-1.jpg'], detail1[1])
        for prompt, _ in (main1, main2, detail1):
            self.assertIn('双参考输入顺序', prompt)
            self.assertIn('第1张输入图是用户上传产品图', prompt)
            self.assertIn('第2张输入图是采集商品当前槽位图', prompt)
            self.assertIn('第2张图中的商品外观、颜色、花型、材质和结构不得覆盖第1张产品图', prompt)
            self.assertIn('严禁让产品图决定本图视角', prompt)
        main2_result = next(item for item in state['results'] if item['assetType'] == 'main' and item['slotIndex'] == 2)
        self.assertEqual('uploaded_identity_collected_slot', main2_result['referenceBinding'])
        self.assertEqual('uploaded_identity_collected_display', main2_result['referenceRole'])
        self.assertEqual('IMG_MAIN_0002', main2_result['referenceEvidenceId'])
        self.assertEqual(1, main2_result['identityReferenceImageIndex'])
        self.assertEqual(2, main2_result['displayReferenceImageIndex'])
        self.assertEqual(1, main2_result['referenceImageIndex'])
        self.assertEqual(2, main2_result['referenceCountUsed'])

    def test_first_main_uses_only_primary_reference_while_followup_can_use_supporting_refs(self):
        """Do not let the provider average several products into main:1."""
        report = sample_report()
        job_id = 'img_test_primary_reference_routing'
        calls = []

        def fake_generate(prompt, **kwargs):
            calls.append((prompt, list(kwargs.get('reference_images') or [])))
            return {'data': [{'b64_json': 'unused'}]}

        references = [
            'data:image/png;base64,PRIMARY',
            'data:image/png;base64,SUPPORTING',
        ]
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(app, 'GENERATED_ASSET_ROOT', Path(tmp) / 'assets'), \
             patch.object(app, 'REPORTS', Path(tmp) / 'reports'), \
             patch.object(app, 'image_generate', side_effect=fake_generate), \
             patch.object(app, '_save_generated_item', side_effect=lambda *args, **kwargs: {
                 'url': '/reports/assets/generated/test/01.png', '_path': '/tmp/01.png',
             }):
            app.GENERATED_ASSET_ROOT.mkdir(parents=True)
            app.REPORTS.mkdir(parents=True)
            app.IMAGE_JOBS[job_id] = {'status': 'queued', 'progress': 5, 'results': []}
            app._generation_worker(job_id, report, {
                'planIndex': 0, 'assetTypes': ['main', 'detail'], 'completeSet': True,
                'selectedSlots': ['main:1', 'detail:1'], 'fissionPattern': False,
                'referenceImages': references,
            })
            state = app.IMAGE_JOBS.pop(job_id)

        self.assertEqual('complete', state['status'])
        main_call = next(item for item in calls if '第1版main' in item[0])
        detail_call = next(item for item in calls if '第1版detail' in item[0])
        self.assertEqual([references[0]], main_call[1])
        self.assertEqual(references, detail_call[1])
        main_result = next(item for item in state['results'] if item['assetType'] == 'main')
        self.assertEqual('primary_product_master', main_result['referenceRole'])
        self.assertEqual(1, main_result['referenceCount'])
        self.assertEqual(1, main_result['referenceCountUsed'])

    def test_image_transport_error_retries_same_payload_before_alias_fallback(self):
        import ai_client
        config = {
            'api_base': 'https://image.example/v1', 'api_key': 'image-key',
            'image_model': 'image-model', 'image_path': '/images/generations',
            'timeout': 120, 'retries': 2, '_config_error': '',
        }
        response = {'data': [{'b64_json': 'unused'}]}
        with patch.object(ai_client, 'image_channel', return_value=config), \
             patch.object(ai_client, '_do_post_path', side_effect=[ssl.SSLEOFError(8, 'EOF'), response]) as post, \
             patch.object(ai_client.time, 'sleep') as sleep:
            actual = ai_client.image_generate(
                'test', reference_images=['data:image/png;base64,AAAA'],
            )
        self.assertEqual(response, actual)
        self.assertEqual(2, post.call_count)
        self.assertEqual(post.call_args_list[0].args[2], post.call_args_list[1].args[2])
        sleep.assert_called_once_with(2)

    def test_persistent_transport_error_does_not_cycle_payload_aliases(self):
        import ai_client
        config = {
            'api_base': 'https://image.example/v1', 'api_key': 'image-key',
            'image_model': 'image-model', 'image_path': '/images/generations',
            'timeout': 120, 'retries': 2, '_config_error': '',
        }
        with patch.object(ai_client, 'image_channel', return_value=config), \
             patch.object(ai_client, '_do_post_path', side_effect=ssl.SSLEOFError(8, 'EOF')) as post, \
             patch.object(ai_client.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, '图片接口调用失败'):
                ai_client.image_generate(
                    'test', reference_images=['data:image/png;base64,AAAA'],
                )
        self.assertEqual(3, post.call_count)
        self.assertEqual([2, 4], [call.args[0] for call in sleep.call_args_list])

    def test_gateway_html_error_is_sanitized_for_users(self):
        import ai_client
        config = {
            'api_base': 'https://image.example/v1', 'api_key': 'image-key',
            'image_model': 'image-model', 'image_path': '/images/generations',
            'timeout': 120, 'retries': 0, '_config_error': '',
        }
        error = urllib.error.HTTPError(
            'https://image.example/v1/images/generations', 502, 'Bad Gateway', {},
            BytesIO(b'<html><body><h1>502 Bad Gateway</h1></body></html>'),
        )
        with patch.object(ai_client, 'image_channel', return_value=config), \
             patch.object(ai_client, '_do_post_path', side_effect=error):
            with self.assertRaisesRegex(RuntimeError, '生图网关暂时不可用') as caught:
                ai_client.image_generate('test')
        self.assertNotIn('<html>', str(caught.exception))

    def test_worker_keeps_successful_images_when_one_independent_slot_fails(self):
        report = sample_report()
        job_id = 'img_test_partial_failure'

        def fake_generate(prompt, **kwargs):
            if '第1版main' in prompt:
                raise RuntimeError('temporary TLS EOF')
            return {'data': [{'b64_json': 'unused'}]}

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(app, 'GENERATED_ASSET_ROOT', Path(tmp) / 'assets'), \
             patch.object(app, 'REPORTS', Path(tmp) / 'reports'), \
             patch.object(app, 'image_generate', side_effect=fake_generate), \
             patch.object(app, '_save_generated_item', return_value={
                 'url': '/reports/assets/generated/test/02.png', '_path': '/tmp/02.png',
             }):
            app.GENERATED_ASSET_ROOT.mkdir(parents=True)
            app.REPORTS.mkdir(parents=True)
            app.IMAGE_JOBS[job_id] = {'status': 'queued', 'progress': 5, 'results': []}
            app._generation_worker(job_id, report, {
                'planIndex': 0, 'assetTypes': ['main'], 'completeSet': True,
                'selectedSlots': ['main:1', 'main:2'], 'fissionPattern': False,
                'referenceImages': ['data:image/png;base64,AAAA'],
            })
            state = app.IMAGE_JOBS.pop(job_id)

        self.assertEqual('complete', state['status'])
        self.assertTrue(state['partialFailure'])
        self.assertEqual(1, len(state['results']))
        self.assertEqual(1, len(state['failedSlots']))
        self.assertEqual(('main', 1), (
            state['failedSlots'][0]['assetType'], state['failedSlots'][0]['slotIndex'],
        ))
        self.assertIn('temporary TLS EOF', state['failedSlots'][0]['error'])

    def test_reference_changes_refresh_the_visible_prompt_preview(self):
        script = (ROOT / 'server' / 'report.js').read_text('utf-8')
        self.assertIn("error.message||'参考图提示词刷新失败'", script)
        self.assertIn("error.message||'裂变提示词刷新失败'", script)

    def test_report_explains_html_returned_by_json_api(self):
        script = (ROOT / 'server' / 'report.js').read_text('utf-8')
        self.assertIn('async function readJsonResponse', script)
        self.assertIn("returnedHtml?'返回了网页内容':'返回内容不是有效 JSON'", script)
        self.assertIn("readJsonResponse(response,'/api/image-prompt-preview')", script)
        self.assertIn("readJsonResponse(response,'/api/generate-images')", script)

    def test_reference_shooting_match_toggle_reaches_preview_and_generation(self):
        script = (ROOT / 'server' / 'report.js').read_text('utf-8')
        # The checkbox is deliberately opt-in: product identity remains locked
        # by default, while camera treatment follows each image task unless the
        # user asks to match the reference shoot.
        self.assertIn('data-match-reference-shooting', script)
        self.assertIn('data-match-reference-wrap', script)
        self.assertIn('产品展示与参考图拍摄一致', script)
        self.assertIn("matchReferenceLabel.textContent='产品展示状态跟随采集商品对应图片'", script)
        self.assertIn('matchReferenceShooting=()=>!!matchReferenceInput?.checked', script)
        self.assertIn('!matchReferenceShooting()', script)
        self.assertIn('matchReferenceShooting:matchReferenceShooting()', script)
        self.assertIn('视角、动作、朝向、展开/折叠、摆放、支撑和部件关系跟随采集商品对应图片', script)
        self.assertGreaterEqual(script.count('matchReferenceShooting:matchReferenceShooting()'), 4)
        self.assertIn("state.matchReferenceShooting?'已按参考图拍摄与产品展示状态生成。'", script)
        self.assertIn("job.matchReferenceShooting?'已按参考图拍摄与展示状态一致'", script)

    def test_partial_failure_ui_retries_only_failed_slots_and_keeps_successes(self):
        script = (ROOT / 'server' / 'report.js').read_text('utf-8')
        self.assertIn('retainedResults=[], generatedTaskSlots=[]', script)
        self.assertIn('const displayResults=mergeResults(retainedResults,state.results)', script)
        self.assertIn('orderedResults(job.results)', script)
        self.assertIn('selectedSlotKeys=new Set(failedSlots.map', script)
        self.assertIn('仅重试失败：${countText(counts)}', script)
        self.assertIn('点击按钮仅重试失败槽位', script)
        self.assertIn('部分完成 · 失败 ${failedCount} 张', script)

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
            self.assertNotIn('规格透明款', prompts[0])
            self.assertIn('不可覆盖约束', prompts[0])

    def test_unrelated_per_slot_prompt_override_does_not_replace_plan(self):
        report = sample_report()
        plan = report['experienceSolution']['newProductPlans']['plans'][0]
        slot = app.build_generation_slots(report, plan)[0]
        base = app.build_image_prompt(report, plan, 'main', 0, slot)
        prompt, meta = app.merge_image_prompt_with_user_edit(base, '客服话术改成周末发短信提醒', slot, {'accepted': []})
        self.assertEqual('ignored_unrelated', meta['mode'])
        self.assertIn('单图用户编辑未采纳', prompt)
        self.assertNotIn('规格透明款', prompt)
        self.assertNotIn('每张图用户编辑提示词', prompt)

    def test_plan_label_never_enters_image_prompt_even_when_repeated_in_actions(self):
        report = sample_report()
        plan = report['experienceSolution']['newProductPlans']['plans'][0]
        plan.update({
            'name': '规格校准款',
            'sourceType': '反馈驱动升级',
            'whyThisPlan': '规格校准款先解决选错问题',
            'productAction': '规格校准款统一材质和件数',
            'pageAction': '规格校准款主图讲清规格，详情逐项证明',
        })
        slot = app.build_generation_slots(report, plan)[0]
        prompt = app.build_image_prompt(report, plan, slot['assetType'], 0, slot)
        self.assertNotIn('规格校准款', prompt)
        self.assertNotIn('反馈驱动升级', prompt)
        self.assertIn('统一材质和件数', prompt)
        self.assertIn('主图讲清规格', prompt)
        self.assertIn('详情逐项证明', prompt)

    def test_image_job_archive_contains_images_and_portable_manifest(self):
        job_id = 'img_test_download'
        with tempfile.TemporaryDirectory() as tmp:
            generated_root = Path(tmp) / 'assets'
            reports_root = Path(tmp) / 'reports'
            job_root = generated_root / job_id
            job_root.mkdir(parents=True)
            reports_root.mkdir(parents=True)
            image_path = job_root / '01.png'
            image_path.write_bytes(b'\x89PNG\r\n\x1a\nfake')
            state = {
                'jobId': job_id,
                'status': 'complete',
                'results': [{
                    'url': f'/reports/assets/generated/{job_id}/01.png',
                    '_path': str(image_path),
                    'assetType': 'main',
                    'slotIndex': 1,
                }],
            }
            with patch.object(app, 'GENERATED_ASSET_ROOT', generated_root), \
                 patch.object(app, 'REPORTS', reports_root), \
                 patch.object(app, 'IMAGE_JOBS', {job_id: state}):
                archive = app._image_job_archive(job_id)
            with zipfile.ZipFile(BytesIO(archive)) as bundle:
                self.assertEqual({'images/main-01.png', 'manifest.json'}, set(bundle.namelist()))
                manifest = json.loads(bundle.read('manifest.json').decode('utf-8'))
                self.assertEqual('images/main-01.png', manifest['results'][0]['downloadFile'])
                self.assertNotIn('_path', manifest['results'][0])
                self.assertEqual(b'\x89PNG\r\n\x1a\nfake', bundle.read('images/main-01.png'))

    def test_report_exposes_floating_history_and_task_download(self):
        script = (ROOT / 'server' / 'report.js').read_text('utf-8')
        css = (ROOT / 'server' / 'report.css').read_text('utf-8')
        self.assertIn('data-generation-history-open', script)
        self.assertIn('data-generation-history-dialog', script)
        self.assertIn('/api/image-job/${encodeURIComponent(job.jobId)}/download', script)
        self.assertIn('generation-history-fab', css)
        self.assertIn('#quick-plan-dialog,\n.generation-history-dialog,\n.image-preview-dialog', css)
        self.assertIn('border-radius:24px!important', css)
        self.assertIn('#quick-plan-dialog .dialog-close,\n.generation-history-dialog .dialog-close', css)
        self.assertIn('border-radius:12px!important', css)


if __name__ == '__main__':
    unittest.main()
