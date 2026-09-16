import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import server as app


class ImageUserIntentTest(unittest.TestCase):
    def setUp(self):
        app.IMAGE_INTENT_CACHE.clear()
        self.report={'facts':{'product':{'title':'被子','category':'床品'},'attributes':{'尺寸':'200x230'}}}
        self.plan={'name':'方案内部名称','productAction':'舒适睡眠','pageAction':'保持信息层级'}
        self.slots=[{'assetType':'main','index':i,'task':['默认槽位任务'],
                     'referenceTextInfo':'被子尺寸200x230',
                     'referenceAnalysis':{'theme':'舒适支撑','composition':'上方文字、下方商品','imageObservation':{'textLayout':'左对齐'}}}
                    for i in (1,2)]
        self.response={'productUpdates':[{'field':'category','value':'枕头','sourceText':'品类换成枕头'}],
                       'globalInstructions':['整套产品换成枕头，保留舒适睡眠方案方向'],
                       'perSlot':{f'main:{i}':{'instructions':['文案随枕头调整'], 'theme':'枕头舒适支撑',
                                              'display':'保持参考构图，枕头不执行被子折叠动作',
                                              'copy':'生成枕头支撑文案，保持参考文字位置大小，不沿用被子尺寸'} for i in (1,2)}}

    def resolve(self,text='品类换成枕头，文案跟随改变',edits=None):
        return app._resolve_image_user_intent(self.report,self.plan,self.slots,app._image_user_direction(text),edits or {},[],True)

    def test_empty_input_uses_plan_without_analysis(self):
        direction=app._image_user_direction('')
        with patch.object(app,'chat_json') as model:
            self.assertIs(direction,app._resolve_image_user_intent(self.report,self.plan,self.slots,direction,{},[],True))
        model.assert_not_called()
        prompt=app.build_image_prompt(self.report,self.plan,slot=self.slots[0],user_direction=direction)
        self.assertIn('舒适睡眠',prompt)
        self.assertNotIn('统一产品—方案—参考关系',prompt)

    def test_category_copy_and_reference_are_resolved_for_every_image(self):
        original=copy.deepcopy(self.report)
        with patch.object(app,'chat_json',return_value=self.response) as model:
            direction=self.resolve()
        request=json.loads(model.call_args.args[1])
        self.assertEqual(self.plan,request['plan'])
        self.assertEqual(self.slots[0]['referenceAnalysis'],request['images'][0]['referenceAnalysis'])
        lock=app.build_identity_lock(self.report,self.plan,direction,True)
        self.assertEqual('枕头',lock['productName'])
        for slot in self.slots:
            per_slot=app._user_direction_for_slot(direction,slot)
            prompt=app.build_image_prompt(self.report,self.plan,slot=slot,user_direction=per_slot,
                                          identity_lock=lock,product_reference_mode='uploaded_identity_collected_reference',match_reference_shooting=True)
            self.assertIn('当前品类以用户要求为准：枕头',prompt)
            self.assertIn('舒适睡眠',prompt)
            self.assertIn('生成枕头支撑文案',prompt)
            self.assertIn('不沿用被子尺寸',prompt)
            self.assertNotIn('商品外观完全由第1张上传产品图决定',prompt)
            self.assertNotIn('商品品类完全一致',prompt)
        self.assertEqual(original,self.report)

    def test_preview_generation_share_result_but_changed_input_is_reinterpreted(self):
        with patch.object(app,'chat_json',return_value=self.response) as model:
            preview=self.resolve()
            execution=self.resolve()
            self.assertEqual(preview,execution)
            model.assert_called_once()
            self.resolve('品类换成枕头，标题改为舒适支撑')
            self.assertEqual(2,model.call_count)

    def test_long_global_and_per_image_input_arrives_complete(self):
        text='品类换成枕头；'+('要求保持每张参考图的文字位置并调整文案；'*100)
        edit='标题写成舒适支撑；'+('保留文字层级和完整商品展示；'*600)
        with patch.object(app,'chat_json',return_value=self.response) as model:
            self.resolve(text,{'main:1':edit})
        request=json.loads(model.call_args.args[1])
        self.assertEqual(text,request['userInput'])
        self.assertEqual(edit,request['perImageInput']['main:1'])
        self.assertEqual(text,app._image_user_direction(text)['raw'])

    def test_per_image_visual_edit_is_not_promoted_to_other_images(self):
        response=copy.deepcopy(self.response)
        response['productUpdates']=[]
        response['globalInstructions']=[]
        response['perSlot']['main:1']['instructions']=['标题写成舒适支撑']
        response['perSlot']['main:2']['instructions']=[]
        with patch.object(app,'chat_json',return_value=response):
            direction=self.resolve('',{'main:1':'标题写成舒适支撑'})
        self.assertEqual(['标题写成舒适支撑'],app._user_direction_for_slot(direction,self.slots[0])['accepted'])
        self.assertEqual([],app._user_direction_for_slot(direction,self.slots[1])['accepted'])
        base='已经完成统一判断的提示词'
        result,_=app.merge_image_prompt_with_user_edit(base,'标题写成舒适支撑',self.slots[0],direction)
        self.assertEqual(base,result)

    def test_product_change_in_single_image_input_is_shared(self):
        with patch.object(app,'chat_json',return_value=self.response):
            direction=self.resolve('',{'main:1':'品类换成枕头'})
        for slot in self.slots:
            self.assertEqual('枕头',app._user_direction_for_slot(direction,slot)['productUpdates'][0]['value'])

    def test_missing_image_or_invented_update_preserves_input_without_adopting_invention(self):
        for invalid in ('missing_slot','invented_update'):
            response=copy.deepcopy(self.response)
            if invalid=='missing_slot':del response['perSlot']['main:2']
            else:response['productUpdates'][0]['sourceText']='用户没有要求的新品'
            with self.subTest(invalid=invalid),patch.object(app,'chat_json',return_value=response):
                result=self.resolve()
                self.assertEqual('品类换成枕头，文案跟随改变',result['raw'])
                self.assertIn('main:2',result['resolvedBySlot'])
                if invalid=='invented_update':self.assertEqual([],result['productUpdates'])
            app.IMAGE_INTENT_CACHE.clear()

    def test_expression_request_and_analysis_failure_never_block_generation_prompt(self):
        for response in ({'productUpdates':[{'field':'text','value':'无字','sourceText':'图片上不要有文字'}]},None):
            app.IMAGE_INTENT_CACHE.clear()
            with patch.object(app,'chat_json',return_value=response):
                direction=self.resolve('图片上不要有文字')
            slot=self.slots[0]
            per_slot=app._user_direction_for_slot(direction,slot)
            prompt=app.build_image_prompt(self.report,self.plan,slot=slot,user_direction=per_slot)
            self.assertIn('图片上不要有文字',prompt)
            self.assertNotIn('生成并真实绘制当前产品中文文案',prompt)
            self.assertNotIn('Render Chinese copy',prompt)
            self.assertLess(prompt.index('本图用户完整输入'),prompt.index('对应参考图职责'))
        app.IMAGE_INTENT_CACHE.clear()
        with patch.object(app,'chat_json',side_effect=RuntimeError('分析接口不可用')):
            direction=self.resolve('背景换成室内，主体不变')
        self.assertEqual('背景换成室内，主体不变',direction['raw'])
        self.assertEqual('分析接口不可用',direction['analysisRecord']['error'])

    def test_rejected_identity_inference_cannot_leak_into_reference_display(self):
        response=copy.deepcopy(self.response)
        response['productUpdates']=[{'field':'category','value':'四件套','sourceText':'图片是床品套装'}]
        response['perSlot']['main:1']['display']='被套和枕套铺展在床上'
        response['globalInstructions']=['保留床铺场景']
        self.slots[0]['referenceAnalysis']['composition']='折叠商品居中，背景纯色'
        with patch.object(app,'chat_json',return_value=response):
            direction=self.resolve('图片上不要有文字')
        per_slot=app._user_direction_for_slot(direction,self.slots[0])
        prompt=app.build_image_prompt(self.report,self.plan,slot=self.slots[0],user_direction=per_slot,match_reference_shooting=True)
        self.assertIn('折叠商品居中，背景纯色',prompt)
        self.assertIn('图片上不要有文字',prompt)
        self.assertNotIn('被套和枕套铺展在床上',prompt)
        self.assertNotIn('保留床铺场景',prompt)
        self.assertEqual(response,direction['analysisRecord']['response'])
        self.assertLess(prompt.index('对应图展示状态执行依据'),prompt.index('辅助解析资料'))

    def test_spatial_relationships_are_shared_by_default_and_user_paths(self):
        self.slots[0]['referenceAnalysis']['displayRelations']={
            'visibleParts':[{'id':'a','description':'悬挂主体'},{'id':'b','description':'支撑位置'}],
            'relations':[{'type':'接触','from':'a','to':'b','observation':'顶部接触支撑，右侧遮挡'}],
            'uncertainAreas':['背面连接不可见']}
        with patch.object(app,'chat_json',return_value={}):
            direction=self.resolve('保持产品，调整文字')
        for d in (app._image_user_direction(''),app._user_direction_for_slot(direction,self.slots[0])):
            prompt=app.build_image_prompt(self.report,self.plan,slot=self.slots[0],user_direction=d,match_reference_shooting=True)
            self.assertIn('顶部接触支撑，右侧遮挡',prompt)
            self.assertIn('背面连接不可见',prompt)
            self.assertIn('可见层数不等于商品件数',prompt)
        disabled=app.build_image_prompt(self.report,self.plan,slot=self.slots[0],match_reference_shooting=False)
        self.assertNotIn('可见展示空间关系｜对应原图约束',disabled)


if __name__=='__main__':unittest.main()
