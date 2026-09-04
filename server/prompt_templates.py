"""可复用的提示词模板注册表。

后端只负责准备 evidence/context，模板负责描述任务；接入其它项目时可直接
替换模板或覆盖变量，不需要在业务代码里拼接提示词。
"""
from dataclasses import dataclass
import json
from pathlib import Path

PRODUCT_VARIABLES = {
    "product": "商品基础信息：标题、商品ID、类目、品牌、价格、销量等页面字段",
    "attributes": "商品参数/规格：仅包含页面实际采集到的名称和值",
    "images": "图片证据：主图、详情图、SKU图、评论原图及其 evidenceId",
    "reviews": "消费者评论：原文、评分、SKU、日期和评论 evidenceId",
    "questions": "问大家/购买问答：问题、回答及 QA evidenceId",
    "programStats": "程序统计：评论数量、图片数量、参数数量等可计算指标",
    "evidence": "统一证据账本；模型只能引用其中的 evidenceId",
    "roleOutputs": "七角色中间结论：商品策略、电商转化、消费者洞察、产品/供应链、视觉设计、老板决策与总编审核；只能交叉校验和编排，不得当作无证据事实",
    "renderingPolicy": "最终可见性规则：只展示真实非空内容；证据以来源类型和内容摘要呈现，evidenceId仅用于追溯",
}

@dataclass(frozen=True)
class PromptTemplate:
    name: str
    body: str
    variables: tuple = ()

    def render(self, **values):
        missing = [v for v in self.variables if v not in values]
        if missing:
            raise ValueError(f"模板 {self.name} 缺少变量: {', '.join(missing)}")
        return self.body.format(**values)

TEMPLATES = {
    "system": PromptTemplate("system", "{system}\n\n可用商品变量说明：\n{variable_schema}", ("system", "variable_schema")),
    "task": PromptTemplate("task", "{task}\n\n输入变量：{input_variables}", ("task", "input_variables")),
}

def register_template(name, body, variables=()):
    """覆盖或新增模板，供宿主项目在启动时注入行业提示词。"""
    TEMPLATES[name] = PromptTemplate(name, body, tuple(variables))

def render_template(name, **values):
    if name not in TEMPLATES:
        raise KeyError(f"未知提示词模板: {name}")
    return TEMPLATES[name].render(**values)

def variable_schema():
    return json.dumps(PRODUCT_VARIABLES, ensure_ascii=False, indent=2)

def build_system_prompt(system_text):
    override=Path(__file__).with_name('prompts.json')
    if override.exists():
        try:
            data=json.loads(override.read_text('utf-8'))
            if isinstance(data, dict) and isinstance(data.get('system'), dict) and data['system'].get('body'):
                return data['system']['body'].format(system=system_text, variable_schema=variable_schema())
        except Exception: pass
    return TEMPLATES["system"].render(system=system_text, variable_schema=variable_schema())

def build_task_prompt(task_text, variables=("evidence",)):
    names = "、".join(f"{name}（{PRODUCT_VARIABLES.get(name, '任务上下文变量')}）" for name in variables)
    return TEMPLATES["task"].render(task=task_text, input_variables=names)
