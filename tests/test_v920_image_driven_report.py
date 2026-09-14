import sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from analysis import ensure_experience_solution, _evidence_backed_launch_fallback, evidence_ledger, normalize
from renderer import render, img_tag, image_source

class V920ImageDrivenReportTest(unittest.TestCase):
    def fixture(self):
        facts={
          'meta':{'imageClassificationVersion':'strict-v1'},
          'product':{'title':'学生宿舍七件套纯棉床笠床单四季子母被'},
          'sales':{'currentPrice':'637.5','sold':'1万+'},
          'attributes':[{'name':'面料支数','value':'40支'},{'name':'床单面料材质','value':'全棉'},{'name':'适用床尺寸','value':'90×190cm'},{'name':'套件组成','value':'七件套'}],
          'sku':[],
          'reviews':[{'content':'面料柔软透气，宿舍用很方便'},{'content':'枕头有点偏软'}],
          'questions':[],
          'images':{'main':['https://img.example.com/m1.jpg','https://img.example.com/m2.jpg'],'detail':['https://img.example.com/d1.jpg','https://img.example.com/d2.jpg'],'sku':['https://img.example.com/s1.jpg'],'buyerShow':['https://img.example.com/b1.jpg'],'provenance':[{'url':'https://img.example.com/m1.jpg','group':'main','source':'dom_main_gallery'},{'url':'https://img.example.com/m2.jpg','group':'main','source':'dom_main_gallery'},{'url':'https://img.example.com/d1.jpg','group':'detail','source':'dom_product_description'},{'url':'https://img.example.com/d2.jpg','group':'detail','source':'dom_product_description'},{'url':'https://img.example.com/s1.jpg','group':'sku','source':'dom_sku'},{'url':'https://img.example.com/b1.jpg','group':'buyerShow','source':'review_record'}]}
        }
        led=evidence_ledger(normalize(facts)); ids={x['id'] for x in led}
        exp={
          'reportSummary':{'title':'宿舍七件套商品分析报告','verdict':'当前围绕宿舍一站式买齐形成商品逻辑，下一款优先把规格与睡感选择说清。','coverImageId':'IMG_MAIN_0001'},
          'ownerOverview':{'cards':[{'label':'商品定位','headline':'宿舍一站式七件套','evidenceIds':['P_TITLE']},{'label':'主要产品资产','headline':'40支全棉 + 七件套','evidenceIds':['ATTR_0001','ATTR_0002']},{'label':'下一款优先方向','headline':'规格与睡感更易选','evidenceIds':['ATTR_0003','REV_000002']}]},
          'titleAnalysis':{'professionalOpinion':'场景与套件范围清楚，建议进一步强化40支品质参数。','currentExpression':[{'label':'场景','value':'学生宿舍','evidenceIds':['P_TITLE']}],'reinforce':[{'topic':'40支全棉','reason':'品质参数可前置','evidenceIds':['ATTR_0001','ATTR_0002']}],'recommendedActions':[{'action':'统一标题与SKU口径','evidenceIds':['P_TITLE']}]},
          'visualCommerce':{'professionalOpinion':'主图先建立套装认知，再解释具体产品。','sequence':['一站式','套件清单'], 'items':[{'imageEvidenceId':'IMG_MAIN_0001','role':'一站式套装','message':'建立宿舍整套购买认知','professionalAdvice':'场景更贴近真实宿舍','evidenceIds':['IMG_MAIN_0001']},{'imageEvidenceId':'IMG_MAIN_0002','role':'套件清单','message':'解释具体包含内容','professionalAdvice':'补尺寸差异','evidenceIds':['IMG_MAIN_0002']}]},
          'detailCommerce':{'professionalOpinion':'详情负责承接材质和规格证明。','contentGroups':[{'type':'材质品质','representativeImageId':'IMG_DETAIL_0001','message':'解释40支全棉','professionalAdvice':'前置品质证明','evidenceIds':['IMG_DETAIL_0001','ATTR_0001']}]},
          'customerExperience':{'professionalOpinion':'评论验证了柔软透气，同时出现睡感差异。','consumerInsights':{'experienceSignals':[{'type':'稳定体验','insight':'柔软透气','implication':'继续保留全棉','evidenceIds':['REV_000001']},{'type':'体验差异','insight':'枕头偏软','implication':'增加睡感说明','evidenceIds':['REV_000002']}]},'stages':[{'label':'使用','positiveConfirmation':'柔软透气','evidenceIds':['REV_000001']},{'label':'睡感','positiveConfirmation':'软硬有差异','evidenceIds':['REV_000002']}]},
          'productExperience':{'parameterFacts':[{'label':'支数','value':'40支','evidenceIds':['ATTR_0001']},{'label':'材质','value':'全棉','evidenceIds':['ATTR_0002']}], 'gates':[{'label':'规格','action':'核对','evidenceIds':['ATTR_0003']},{'label':'套件','action':'核对','evidenceIds':['ATTR_0004']}]},
          'newProductPlans':{'professionalOpinion':'下一款围绕规格更清楚与睡感区分优化。','plans':[{'type':'现有基础优化','name':'宿舍七件套2.0','whyThisPlan':'保留全棉与七件套逻辑，强化规格选择。','visualReferenceImageIds':['IMG_MAIN_0001'],'productChanges':[{'action':'明确床型尺寸','evidenceIds':['ATTR_0003']}],'skuStrategy':'款式→尺寸→花色','mainImagePlan':['首图保留一站式'],'detailPagePlan':['紧接材质证明'],'evidenceIds':['P_TITLE','ATTR_0001','ATTR_0003','IMG_MAIN_0001']}]},
          'validationLoop':{'rows':[{'stage':'定义','owner':'商品运营','metrics':'核对','successMeaning':'一致','nextAction':'打样','evidenceIds':['P_TITLE']},{'stage':'规格','owner':'供应链','metrics':'实测','successMeaning':'一致','nextAction':'锁定','evidenceIds':['ATTR_0003']},{'stage':'页面','owner':'视觉','metrics':'核对','successMeaning':'一致','nextAction':'发布','evidenceIds':['IMG_MAIN_0001']}]}
        }
        return ensure_experience_solution({'facts':facts,'experienceSolution':exp,'meta':{}})

    def test_renderer_is_image_driven_and_professional(self):
        doc=render(self.fixture(),'v920')
        self.assertIn('window.REPORT_DATA=',doc)
        self.assertIn('<script src="/report.js?v=',doc)
        self.assertIn('IMG_MAIN_0001',doc)
        self.assertIn('IMG_DETAIL_0001',doc)
        self.assertNotIn('v92-main-grid',doc)
        self.assertNotIn('v925-detail-list',doc)
        self.assertNotIn('[数据事实]',doc)
        self.assertNotIn('[分析判断]',doc)
        self.assertNotIn('[设计建议]',doc)
        self.assertNotIn('整体有效点',doc)
        self.assertNotIn('主要问题',doc)

    def test_cover_has_no_card_border_wrapper(self):
        doc=render(self.fixture(),'v920')
        self.assertIn('"coverImageId":"IMG_MAIN_0001"',doc)
        self.assertNotIn('class="v92-cover"',doc)
        self.assertNotIn('cover-ratio',doc)
        self.assertNotIn('hero-shot',doc)

    def test_launch_fallback_never_empty_with_real_evidence(self):
        facts=normalize(self.fixture()['facts'])
        ids={x['id'] for x in evidence_ledger(facts)}
        plans=_evidence_backed_launch_fallback(facts,ids)
        self.assertGreaterEqual(len(plans.get('plans') or []),1)
        self.assertTrue(plans['plans'][0]['evidenceIds'])

if __name__=='__main__':unittest.main()


def test_img_tag_remote_fallback_does_not_force_no_referrer():
    html = img_tag('https://img.example.com/a.jpg', '图', 'https://img.example.com/b.jpg')
    assert 'referrerpolicy="no-referrer"' not in html
    assert 'data-fallback="https://img.example.com/b.jpg"' in html


def test_image_source_keeps_remote_when_cache_failed():
    e={'type':'image','value':'https://img.example.com/a.jpg','meta':{'sourceUrl':'https://img.example.com/a.jpg','cacheStatus':'failed'}}
    src,fb=image_source(e)
    assert src=='https://img.example.com/a.jpg'
    assert fb=='https://img.example.com/a.jpg'
