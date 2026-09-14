import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

from analysis import analyze, ensure_experience_solution, normalize, _review_issue, _buyer_evidence, detect_category, _category_parameter_facts, core_solution_diagnostics, repair_core_solution_with_evidence
from renderer import render
from server import TASK_JS, task_evidence_summary, task_page


class EvidenceOnlyReportTest(unittest.TestCase):
    def setUp(self):
        self.analysis = {
            'facts': {
                'product': {'title': '用户评价·51', 'itemId': '900653753390'},
                'sales': {'sold': '700+', 'currentPrice': '395.25'},
                'attributes': [
                    {'name': '1024', 'value': '"lg",'},
                    {'name': 'console.log("onload]', 'value': 'performance.now()'},
                    {'name': '面料支数', 'value': '60支'},
                    {'name': '床单面料材质', 'value': '全棉'},
                    {'name': '适用床尺寸', 'value': '1.2m床三件套'},
                ],
                'reviews': [
                    {'content': '2025年4月18日已购：【四件套】测试规格'},
                    {'content': '花色好看，摸起来很舒服', 'images': ['https://img.alicdn.com/review-rate.jpg'], 'source': 'dom_visible'},
                    {'content': '1米2床单尺寸小，床边不够'},
                ],
                'questions': [
                    {'question': '问大家·5 问 有味道吗 更多回答 问 盖上舒服吗 更多回答'},
                    {'question': '问 有味道吗 更多回答'},
                ],
                'collection': {
                    'reviewCollectionComplete': False,
                    'publicReviewCount': '51',
                    'reviewStopReason': 'no_progress_after_4_rounds',
                    'reviewPagesVisited': 35,
                },
                'images': {'main': [
                    'https://img.alicdn.com/tps-120-60.png',
                    'https://img.alicdn.com/item_pic.jpg',
                ], 'detail': [], 'sku': [], 'buyerShow': [], 'all': []},
            },
            'experienceSolution': {},
            'meta': {},
        }

    def test_empty_model_result_repairs_core_modules_before_report(self):
        result = ensure_experience_solution(self.analysis)
        self.assertFalse(result['meta']['fallbackReport'])
        self.assertTrue(result['meta']['reportReady'])
        self.assertTrue(result['meta']['reportAuditPassed'])
        self.assertEqual('passed', result['meta']['reportQuality'])
        self.assertEqual([], result['meta']['reportValidation']['missing'])
        self.assertEqual('', result['facts']['product']['title'])
        self.assertEqual(['面料支数', '床单面料材质', '适用床尺寸'], [x['name'] for x in result['facts']['attributes']])
        self.assertEqual(2, result['baseline']['reviewCount'])
        self.assertEqual(2, result['baseline']['questionCount'])
        cards = result['experienceSolution']['ownerOverview']['cards']
        self.assertTrue(cards)
        self.assertEqual('下一款明确卖点', cards[0]['label'])
        self.assertIn('ATTR_0003', cards[0]['evidenceIds'])
        self.assertGreaterEqual(len(result['experienceSolution']['productExperience']['parameterFacts']), 2)
        self.assertGreaterEqual(len(result['experienceSolution']['productExperience']['gates']), 2)
        self.assertGreaterEqual(len(result['experienceSolution']['validationLoop']['rows']), 3)
        html = render(result, 'fixture')
        self.assertNotIn('审核未通过', html)

    def test_unrepairable_core_audit_blocks_report(self):
        with patch('analysis.repair_core_solution_with_evidence', side_effect=lambda draft, raw, base=None: draft):
            result = ensure_experience_solution(self.analysis)
        self.assertFalse(result['meta']['reportReady'])
        self.assertFalse(result['meta']['reportAuditPassed'])
        self.assertEqual('blocked', result['meta']['reportQuality'])
        self.assertIn('已停止生成', result['meta']['reportBlockedReason'])
        self.assertNotIn('reportNotice', result['meta'])

    def test_analysis_runs_without_model_channel_uses_evidence_fallback(self):
        raw = dict(self.analysis['facts'])
        raw['_model_available'] = False
        result = analyze(raw)
        self.assertFalse(result['meta']['modelUsed'])
        self.assertEqual('9.3.0', result['meta']['engineVersion'])
        self.assertEqual('home_textile', result['meta']['industryTemplate'])
        self.assertFalse(result['meta']['fallbackReport'])
        self.assertTrue(result['meta']['reportReady'])
        self.assertTrue(result['experienceSolution']['reportSummary']['title'])
        self.assertEqual(7, len(result['roleOutputs']))

    def test_historical_fallback_json_is_rejected(self):
        result = ensure_experience_solution({
            'facts': self.analysis['facts'],
            'experienceSolution': {'reportSummary': {'title': '旧报告', 'verdict': '旧结论'}},
            'meta': {'fallbackReport': True},
        })
        self.assertFalse(result['meta']['reportReady'])
        self.assertIn('历史分析标记为兜底结果', result['meta']['reportBlockedReason'])

    def test_dormitory_spec_never_invents_12m_issue_and_title_is_clean(self):
        facts = {
            'product': {'title': '宿舍七件套新生床品-tmall.com天猫', 'itemId': '2'},
            'sales': {'sold': '1万+', 'currentPrice': '637.5'},
            'attributes': [
                {'name': '套件组成', 'value': '被芯、床垫、床单、被套、枕芯、枕套、床帘'},
                {'name': '适用床尺寸', 'value': '80×190cm、90×190cm、90×200cm；床垫厚4cm/6cm'},
                {'name': '面料材质', 'value': '聚酯纤维'},
                {'name': '适用人群', 'value': '学生'},
            ],
            'reviews': [
                {'content': '七件配齐，开学直接用，尺寸合适'},
                {'content': '枕套实物和页面有色差', 'sku': '90×190cm / 4cm床垫'},
            ],
            'questions': [], 'images': {},
        }
        clean = normalize(facts);issue = _review_issue(clean)
        self.assertEqual('宿舍七件套新生床品', clean['product']['title'])
        self.assertEqual('实物色差', issue['label'])
        self.assertNotIn('1.2m', str(issue))
        self.assertNotIn('1米2', str(issue))

    def test_real_12m_comment_keeps_12m_evidence(self):
        clean = normalize(self.analysis['facts']);issue = _review_issue(clean)
        self.assertIn('1米2床单尺寸小，床边不够', issue['text'])
        self.assertEqual('尺寸与床型适配', issue['label'])

    def test_apparel_uses_dynamic_category_dimensions(self):
        raw=normalize({'product':{'title':'女士宽松连衣裙'},'attributes':[{'name':'尺码','value':'S M L XL'},{'name':'面料成分','value':'棉 95% 氨纶 5%'},{'name':'版型','value':'宽松'}],'reviews':[{'content':'尺码合身，版型显瘦'}],'images':{}})
        route=detect_category(raw)
        facts=_category_parameter_facts(raw)
        self.assertEqual('apparel',route['key'])
        self.assertIn('尺码与适配',[x['label'] for x in facts])
        self.assertIn('面料与成分',[x['label'] for x in facts])
        self.assertNotIn('套件 BOM',[x['label'] for x in facts])

    def test_food_beauty_and_digital_route_to_their_own_dimensions(self):
        fixtures=[
            ('food',{'product':{'title':'坚果零食礼盒'},'attributes':[{'name':'净含量','value':'750g'},{'name':'配料表','value':'坚果'}]}),
            ('beauty',{'product':{'title':'敏感肌保湿精华'},'attributes':[{'name':'主要成分','value':'透明质酸'},{'name':'适用肤质','value':'敏感肌'}]}),
            ('digital',{'product':{'title':'无线蓝牙耳机'},'attributes':[{'name':'兼容系统','value':'iOS/Android'},{'name':'续航时间','value':'30小时'}]}),
        ]
        for expected,data in fixtures:
            data.update({'reviews':[],'images':{}})
            clean=normalize(data); route=detect_category(clean)
            self.assertEqual(expected,route['key'])
            self.assertTrue(_category_parameter_facts(clean))

    def test_complete_evidence_backed_ai_output_is_rendered_and_sanitized(self):
        facts = {
            'product': {'title': '全棉三件套-taobao.com淘宝网', 'itemId': '3'},
            'sales': {},
            'attributes': [
                {'name': '床单面料材质', 'value': '全棉'},
                {'name': '套件组成', 'value': '床单、被套、枕套'},
                {'name': '适用床尺寸', 'value': '0.9m床三件套'},
            ],
            'reviews': [{'content': '摸起来柔软舒服'}],
            'questions': [{'question': '会不会起球？'}],
            'images': {},
        }
        exp = {
            'reportSummary': {'title': '省心型大众爆款，提升转化', 'verdict': '先完成样品验证'},
            'ownerOverview': {'chapterTitle': '页面事实与评论结果已形成', 'cards': [
                {'label': '客户为什么购买', 'headline': '决定成交', 'evidenceIds': ['REV_000001']},
                {'label': '页面产品定义', 'headline': '全棉三件套', 'evidenceIds': ['ATTR_0001', 'ATTR_0002']},
                {'label': '下一款怎么开', 'headline': '先校准规格', 'evidenceIds': ['ATTR_0003']},
            ]},
            'customerExperience': {
                'chapterTitle': '1 条评论确认柔软触感', 'journeyTitle': '只显示评论已确认结果',
                'stats': [{'label': '有效评论', 'value': '1'}],
                'stages': [
                    {'stageNo': '01', 'label': '实际使用', 'positiveConfirmation': '1 条确认柔软舒服', 'evidenceIds': ['REV_000001']},
                    {'stageNo': '02', 'label': '选择规格', 'positiveConfirmation': '页面标注0.9m床三件套', 'evidenceIds': ['ATTR_0003']},
                ],
                'signals': {'positive': [], 'questions': [], 'risks': [
                    {'label': '起球产品缺陷', 'evidenceIds': ['QA_00001']},
                ]},
            },
            'productExperience': {'chapterTitle': '材质、BOM与床型必须一致', 'parameterFacts': [
                {'label': '材质 / 成分', 'value': '全棉', 'evidenceIds': ['ATTR_0001']},
                {'label': '套件 BOM', 'value': '床单、被套、枕套', 'evidenceIds': ['ATTR_0002']},
            ], 'gates': [
                {'priority': 'P0', 'label': '材质核对', 'action': '核对标签与样品', 'evidenceIds': ['ATTR_0001']},
                {'priority': 'P0', 'label': '规格实测', 'action': '按0.9m床铺装', 'evidenceIds': ['ATTR_0003']},
            ]},
            'newProductPlans': {'plans': [
                {'type': '主销款', 'name': '主销', 'positioning': '保持全棉三件套定义', 'evidenceIds': ['ATTR_0001']},
                {'name': '无证据升级', 'evidenceIds': []},
                {'type': '升级款', 'name': '第三套', 'positioning': '按BOM校准', 'evidenceIds': ['ATTR_0002']},
            ], 'chapterTitle': '只输出有证据的开品方向'},
            'validationLoop': {'chapterTitle': '三道验证门决定是否上架', 'rows': [
                {'stage': '商品定义', 'owner': '商品企划 / 商品运营', 'metrics': '核对定义', 'successMeaning': '参数一致', 'nextAction': '进入打样', 'evidenceIds': ['ATTR_0001']},
                {'stage': '规格实测', 'owner': '供应链 / 品控', 'metrics': '实床铺装', 'successMeaning': '规格适配', 'nextAction': '锁定SKU', 'evidenceIds': ['ATTR_0003']},
                {'stage': '页面验收', 'owner': '视觉与内容', 'metrics': '核对页面', 'successMeaning': '页面一致', 'nextAction': '上架', 'evidenceIds': ['ATTR_0002']},
            ]},
        }
        result = ensure_experience_solution({'facts': facts, 'experienceSolution': exp, 'meta': {}})
        output = str(result['experienceSolution'])
        labels = [x['label'] for x in result['experienceSolution']['productExperience']['parameterFacts']]
        signals = result['experienceSolution']['customerExperience']['signals']
        self.assertTrue(result['meta']['reportReady'])
        self.assertEqual('全棉三件套', result['facts']['product']['title'])
        self.assertIn('套件 BOM', labels)
        self.assertIn('材质 / 成分', labels)
        self.assertEqual([], signals['risks'])
        self.assertTrue(signals['questions'][0]['label'].startswith('购买前关注：'))
        plans = result['experienceSolution']['newProductPlans']['plans']
        self.assertEqual(3, len(plans))
        self.assertEqual(['证据驱动优化', '反馈驱动升级', '探索性方向'], [x['sourceType'] for x in plans])
        self.assertTrue(all(x['name'].endswith('款') for x in plans))
        self.assertNotIn('无证据升级', output)
        self.assertNotIn('项目负责人', output)
        self.assertNotIn('客户为什么购买', output)
        self.assertNotIn('提升转化', output)
        self.assertNotIn('决定成交', output)
        self.assertNotIn('爆款', output)
        doc = render(result, 'evidence-only')
        self.assertIn('window.REPORT_DATA=', doc)
        self.assertIn('Sansong Product Intelligence V9.3.0', doc)
        self.assertIn('<script src="/report.js?v=', doc)
        self.assertNotIn('项目负责人', doc)

    def test_incomplete_final_editor_output_is_repaired_from_real_evidence(self):
        facts = {
            'product': {'title': '学生宿舍全棉三件套', 'itemId': 'repair-1'},
            'sales': {'sold': '1000+', 'currentPrice': '129'},
            'attributes': [
                {'name': '床单面料材质', 'value': '全棉'},
                {'name': '套件组成', 'value': '床单、被套、枕套'},
                {'name': '适用床尺寸', 'value': '0.9m床三件套'},
                {'name': '产品等级', 'value': '合格品'},
            ],
            'reviews': [
                {'content': '面料柔软，尺寸合适'},
                {'content': '花色好看，宿舍床铺上正好'},
            ],
            'questions': [{'question': '洗后会不会缩水？'}],
            'images': {},
        }
        repaired = repair_core_solution_with_evidence({}, facts)
        result = ensure_experience_solution({'facts': facts, 'experienceSolution': repaired, 'meta': {}})
        self.assertTrue(result['meta']['reportReady'])
        self.assertTrue(result['meta']['reportValidation']['ok'])
        self.assertEqual([], result['meta']['reportValidation']['missing'])
        self.assertFalse(result['meta']['fallbackReport'])
        self.assertIn('evidenceIds', result['experienceSolution']['validationLoop']['rows'][0])


    def test_legacy_grouped_images_are_preserved_without_strict_provenance(self):
        raw={
            'product':{'title':'测试商品','itemId':'1'},
            'reviews':[],
            'images':{
                'main':['https://img.alicdn.com/item_pic.jpg'],
                'detail':['https://img.alicdn.com/detail_01.jpg'],
                'sku':['https://img.alicdn.com/sku_01.jpg'],
                'buyerShow':[]
            }
        }
        clean=normalize(raw)
        self.assertEqual(['https://img.alicdn.com/item_pic.jpg'], clean['images']['main'])
        self.assertEqual(['https://img.alicdn.com/detail_01.jpg'], clean['images']['detail'])
        self.assertEqual(['https://img.alicdn.com/sku_01.jpg'], clean['images']['sku'])
        self.assertEqual('legacy-review-only', clean['images']['classification']['version'])
        sources={x['group']:x['source'] for x in clean['images']['provenance'] if x['group'] in ('main','detail','sku')}
        self.assertEqual('legacy_group_main', sources['main'])
        self.assertEqual('legacy_group_detail', sources['detail'])
        self.assertEqual('legacy_group_sku', sources['sku'])

    def test_validation_reports_exact_missing_fields(self):
        validation = core_solution_diagnostics({'reportSummary': {'title': '有标题'}})
        self.assertFalse(validation['ok'])
        self.assertNotIn('reportSummary.title', validation['missing'])
        self.assertIn('reportSummary.verdict', validation['missing'])
        self.assertIn('validationLoop.rows', validation['missing'])

    def test_task_progress_exposes_real_evidence_counts(self):
        raw = self.analysis['facts']
        summary = task_evidence_summary(raw)
        self.assertEqual(3, summary['counts']['parameters'])
        self.assertEqual(2, summary['counts']['reviews'])
        self.assertEqual(1, summary['counts']['main'])
        self.assertEqual(0, summary['counts']['detail'])
        self.assertEqual(1, summary['counts']['buyerShow'])
        self.assertEqual('51', summary['publicReviewCount'])
        self.assertFalse(summary['reviewComplete'])
        page = task_page('fixture')
        self.assertIn('本次证据', page)
        self.assertIn('生成进度', page)
        self.assertIn('evidenceStats', page)
        self.assertIn("not_collected:'未采到'", TASK_JS)
        self.assertIn("visual:'商品主图核验'", TASK_JS)
        self.assertIn("detail:'商品详情图核验'", TASK_JS)
        self.assertIn("editor:'最终报告汇总与校验'", TASK_JS)
        self.assertIn("failed:'失败'", TASK_JS)
        self.assertNotIn("visual:'主图成交'", TASK_JS)

    def test_strict_image_groups_are_disjoint_and_traceable(self):
        shared = 'https://img.alicdn.com/shared-review.jpg'
        buyer_two = 'https://img.alicdn.com/second-review.jpg'
        main = 'https://img.alicdn.com/verified-main.jpg'
        structured_main = 'https://img.alicdn.com/structured-main.jpg'
        detail = 'https://img.alicdn.com/verified-detail.jpg'
        structured_detail = 'https://img.alicdn.com/structured-detail.jpg'
        facts = {
            'meta': {'imageClassificationVersion': 'strict-v1'},
            'product': {'title': '真实商品标题', 'itemId': '1'},
            'sales': {}, 'attributes': [], 'questions': [],
            'reviews': [{'content': '评论原文', 'images': [shared, buyer_two], 'source': 'dom_visible'}],
            'images': {
                'main': [shared, main, structured_main], 'detail': [shared, detail, structured_detail], 'sku': [], 'buyerShow': [shared, buyer_two],
                'provenance': [
                    {'url': shared, 'group': 'buyerShow', 'source': 'review_record'},
                    {'url': buyer_two, 'group': 'buyerShow', 'source': 'review_record'},
                    {'url': shared, 'group': 'main', 'source': 'dom_main_gallery'},
                    {'url': main, 'group': 'main', 'source': 'dom_main_gallery'},
                    {'url': structured_main, 'group': 'main', 'source': 'structured_main_gallery'},
                    {'url': detail, 'group': 'detail', 'source': 'dom_product_description'},
                    {'url': structured_detail, 'group': 'detail', 'source': 'structured_product_description'},
                ],
            },
        }
        clean = normalize(facts)
        groups = clean['images']
        self.assertEqual([shared, buyer_two], groups['buyerShow'])
        self.assertEqual([main, structured_main], groups['main'])
        self.assertEqual([detail, structured_detail], groups['detail'])
        self.assertTrue(groups['classification']['groupsAreDisjoint'])
        self.assertEqual(6, len(set(groups['buyerShow'] + groups['main'] + groups['detail'])))
        buyer_items = _buyer_evidence(clean)
        buyer = buyer_items[0]
        self.assertEqual('REV_000001', buyer['reviewEvidenceId'])
        self.assertEqual(2, len(buyer_items))


if __name__ == '__main__':
    unittest.main()
