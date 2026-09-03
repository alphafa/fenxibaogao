import sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from renderer import render, image_source, img_tag
from unittest.mock import patch
import tempfile
import server as server_module
from analysis import ensure_experience_solution

class V910RegressionTest(unittest.TestCase):
    def base_result(self):
        facts={'product':{'title':'测试商品'},'sales':{},'attributes':[{'name':'材质','value':'全棉'},{'name':'规格','value':'700g'}], 'reviews':[{'content':'使用后很顺滑'}], 'questions':[], 'sku':[], 'images':{'main':['https://img.example.com/a.jpg'],'sku':['https://img.example.com/s.jpg']}}
        exp={'reportSummary':{'title':'测试报告','verdict':'先核对商品结构'},'ownerOverview':{'chapterTitle':'页面事实与评论结果已形成','cards':[{'label':'结论','headline':'先核对规格','evidenceIds':['ATTR_0001']},{'label':'产品','headline':'材质明确','evidenceIds':['ATTR_0001']},{'label':'动作','headline':'统一页面口径','evidenceIds':['ATTR_0002']}]},'customerExperience':{'stages':[{'label':'使用','positiveConfirmation':'顺滑','evidenceIds':['REV_000001']},{'label':'规格','positiveConfirmation':'700g','evidenceIds':['ATTR_0002']}], 'consumerInsights':{'coreSatisfaction':[{'driver':'顺滑体验','evidenceIds':['REV_000001']}]}},'productExperience':{'parameterFacts':[{'label':'材质','value':'全棉','evidenceIds':['ATTR_0001']},{'label':'规格','value':'700g','evidenceIds':['ATTR_0002']}], 'gates':[{'label':'材质','action':'核对','evidenceIds':['ATTR_0001']},{'label':'规格','action':'核对','evidenceIds':['ATTR_0002']}]},'newProductPlans':{'plans':[{'type':'稳健优化','name':'规格清晰化','whyThisPlan':'减少理解成本','evidenceIds':['ATTR_0002']}]},'validationLoop':{'rows':[{'stage':'定义','owner':'商品运营','metrics':'核对','successMeaning':'一致','nextAction':'进入下一步','evidenceIds':['ATTR_0001']},{'stage':'规格','owner':'供应链','metrics':'核对','successMeaning':'一致','nextAction':'锁定','evidenceIds':['ATTR_0002']},{'stage':'页面','owner':'视觉','metrics':'核对','successMeaning':'一致','nextAction':'发布','evidenceIds':['ATTR_0002']} ]}}
        r=ensure_experience_solution({'facts':facts,'experienceSolution':exp,'meta':{}})
        for e in r['evidenceLedger']:
            if e.get('id')=='IMG_MAIN_0001':
                e.setdefault('meta',{})['localUrl']='/reports/assets/test/main/IMG_MAIN_0001.jpg';e['meta']['sourceUrl']=e['value']
        return r

    def test_missing_sku_not_rendered_as_zero(self):
        doc=render(self.base_result(),'test')
        self.assertNotIn('SKU 0',doc)
        self.assertIn('结构化SKU 未完整采集',doc)
        self.assertIn('SKU图片数量不等于SKU数量',doc)

    def test_renderer_prefers_local_image_and_keeps_remote_fallback(self):
        entry={'value':'https://img.example.com/a.jpg','meta':{'localUrl':'/reports/assets/test/main/IMG_MAIN_0001.jpg','sourceUrl':'https://img.example.com/a.jpg'}}
        local,remote=image_source(entry)
        html=img_tag(local,'商品主图',remote)
        self.assertIn('/reports/assets/test/main/IMG_MAIN_0001.jpg',html)
        self.assertIn('https://img.example.com/a.jpg',html)
        self.assertIn('data-fallback',html)

    def test_renderer_never_prints_python_dict_literal(self):
        r=self.base_result()
        r['experienceSolution']['titleAnalysis']={
            'currentExpression':[{'value':'信息明确','evidenceIds':['ATTR_0001']}],
            'reinforce':[{'topic':'规格需拆清','evidenceIds':['ATTR_0002']}]
        }
        doc=render(r,'test')
        self.assertNotIn("{'point':",doc)
        self.assertIn('信息明确',doc)

    def test_cache_report_images_writes_local_url_and_preserves_source(self):
        class FakeResponse:
            headers={'Content-Type':'image/jpeg'}
            def __enter__(self):return self
            def __exit__(self,*a):return False
            def read(self,n=-1):return b'\xff\xd8\xffFAKEJPEG'
        result={'evidenceLedger':[{'id':'IMG_MAIN_0001','type':'image','value':'https://img.example.com/a.jpg','meta':{'group':'main'}}]}
        with tempfile.TemporaryDirectory() as td, patch.object(server_module,'IMAGE_ASSET_ROOT',Path(td)), patch('server.urllib.request.urlopen',return_value=FakeResponse()):
            out=server_module.cache_report_images(result,'task1')
            meta=out['evidenceLedger'][0]['meta']
            self.assertEqual('success',meta['cacheStatus'])
            self.assertEqual('https://img.example.com/a.jpg',meta['sourceUrl'])
            self.assertTrue(meta['localUrl'].startswith('/reports/assets/task1/main/'))
            self.assertTrue(list((Path(td)/'task1'/'main').glob('IMG_MAIN_0001.*')))

if __name__=='__main__':unittest.main()
