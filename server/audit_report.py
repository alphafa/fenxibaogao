#!/usr/bin/env python3
"""Audit a generated report JSON before delivery."""
import json
import sys
from pathlib import Path

EXPECTED_ROLES = (
    'productStrategy', 'conversion', 'consumerInsight', 'productSupply',
    'visualDesign', 'executiveDecision', 'editorReview',
)
VISIBLE_SOURCES = {
    'experienceSolution.reportSummary': ('reportSummary',),
    'experienceSolution.ownerOverview': ('ownerOverview',),
    'experienceSolution.newProductPlans': ('newProductPlans',),
    'experienceSolution.titleAnalysis': ('titleAnalysis',),
    'experienceSolution.visualCommerce': ('visualCommerce',),
    'experienceSolution.detailCommerce': ('detailCommerce',),
    'experienceSolution.skuAnalysis': ('skuAnalysis',),
    'experienceSolution.customerExperience': ('customerExperience',),
    'reportPlan': ('supportAnalysis',),
    'reviewBatchAnalysis': ('supportAnalysis',),
    'experienceSolution.productExperience': ('supportAnalysis',),
    'experienceSolution.validationLoop': ('supportAnalysis',),
    'experienceSolution.expressionContinuity': ('supportAnalysis',),
    'dataQuality': ('supportAnalysis',),
    'consumerResearch': ('reviews', 'supportAnalysis'),
    'questionResearch': ('supportAnalysis',),
    'commercialDecision': ('supportAnalysis',),
    'competitionDecision': ('supportAnalysis',),
    'merchandisingDecision': ('supportAnalysis',),
    'productDecision': ('supportAnalysis',),
    'visualDecision': ('supportAnalysis',),
    'roleOutputs': ('roleOutputs',),
}

PLACEHOLDERS = {'暂无', '无', '未采集', '未评级', '待补充', '尚未结构化'}

def has_content(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip()) and value.strip() not in PLACEHOLDERS
    if isinstance(value, (int, float, bool)):
        return True
    if isinstance(value, list):
        return any(has_content(item) for item in value)
    if isinstance(value, dict):
        return any(has_content(item) for item in value.values())
    return False

def get_path(data, path):
    value = data
    for part in path.split('.'):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value

def evidence_refs(value):
    refs=[]
    if isinstance(value, dict):
        ids=value.get('evidenceIds')
        if isinstance(ids, list):
            refs.extend(str(item) for item in ids if item)
        for child in value.values():
            refs.extend(evidence_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.extend(evidence_refs(child))
    return refs

def audit(data):
    ledger=data.get('evidenceLedger') or []
    known={str(item.get('id')) for item in ledger if isinstance(item,dict) and item.get('id')}
    refs=evidence_refs(data.get('experienceSolution') or {})+evidence_refs(data.get('roleOutputs') or {})
    unresolved=sorted(set(refs)-known)
    roles=data.get('roleOutputs') or {}
    missing_roles=[role for role in EXPECTED_ROLES if not has_content(roles.get(role))]
    present_sources=[]
    mapped_sources=[]
    for path,targets in VISIBLE_SOURCES.items():
        if has_content(get_path(data,path)):
            present_sources.append(path)
            mapped_sources.append({'source':path,'renderers':list(targets)})
    images=[item for item in ledger if isinstance(item,dict) and item.get('type')=='image']
    invalid_images=[item.get('id') for item in images if not has_content((item.get('meta') or {}).get('localUrl') or item.get('value'))]
    exp=data.get('experienceSolution') or {}
    required={
        'reportSummary':has_content(exp.get('reportSummary')),
        'ownerOverview':has_content(exp.get('ownerOverview')),
        'newProductPlans':has_content(exp.get('newProductPlans')),
    }
    failures=[]
    failures += [f'缺少核心报告模块：{key}' for key,ok in required.items() if not ok]
    failures += [f'缺少角色输出：{role}' for role in missing_roles]
    failures += [f'证据引用无法解析：{eid}' for eid in unresolved]
    failures += [f'图片证据无可用地址：{eid}' for eid in invalid_images]
    return {
        'ok':not failures,
        'engineVersion':(data.get('meta') or {}).get('engineVersion'),
        'presentMappedSources':mapped_sources,
        'sourceCoverage':len(mapped_sources),
        'roles':{'present':len(EXPECTED_ROLES)-len(missing_roles),'expected':len(EXPECTED_ROLES),'missing':missing_roles},
        'evidence':{'ledger':len(ledger),'references':len(refs),'unresolved':unresolved},
        'images':{'total':len(images),'invalid':invalid_images},
        'failures':failures,
    }

def main():
    if len(sys.argv)!=2:
        raise SystemExit('用法：python3 audit_report.py <report.json>')
    source=Path(sys.argv[1])
    result=audit(json.loads(source.read_text('utf-8')))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['ok'] else 1)

if __name__=='__main__':
    main()
