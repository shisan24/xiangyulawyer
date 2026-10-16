# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Read-only eligibility screen for approved cron improvements.

Declared reviews must be performed by the agent against original sources.
This checks scope, evidence references and byte identity; it neither proves
legal/semantic correctness nor executes, installs, writes or grants access.
"""
import argparse,hashlib,json,os,sys
from pathlib import Path
REQUIRED=('source','host','license','data_flow','counterargument','conflicts','reversible','tests')
KINDS={'skill_patch','script_fix','routing_fix','internal_template_fix'}
SENSITIVE={'.env','auth.json','config.yaml','credentials.json'}

def assess(item,home=None):
    result={'id':item.get('id') if isinstance(item,dict) else None,'action':'defer','reason':'输入或核验记录不完整','scope':'eligibility_only_not_execution_or_semantic_proof'}
    def out(action,reason):return {**result,'action':action,'reason':reason}
    if not isinstance(item,dict) or not item.get('id') or item.get('kind') not in KINDS:return result
    flags=item.get('risk_flags')
    if not isinstance(flags,list):return result
    if flags:return out('defer','存在越界或未分类风险：'+','.join(str(x) for x in flags))
    home=Path(home or os.environ['HERMES_HOME']).resolve()
    try:
        target=Path(item['target']).resolve()
        if target.name.lower() in SENSITIVE or not any(target.is_relative_to(home/x) for x in ['skills','scripts']):
            return out('defer','目标不在常规内部技能/脚本范围；不能把客户、配置或上游源码当普通补丁')
        if not target.is_file():return out('defer','目标尚不存在；新建部署另核范围')
        current=hashlib.sha256(target.read_bytes()).hexdigest()
    except (OSError,ValueError,TypeError,KeyError):return out('defer','目标不可读或路径无效')
    if item.get('deployed_sha256')==current:return out('already_applied','现盘与既有部署记录相同，核实际效果，不重复写入')
    if item.get('net_gain') is False:return out('no_change','没有净增量，不部署')
    if item.get('net_gain') is not True:return result
    checks=item.get('checks')
    if not isinstance(checks,dict):return result
    for name in REQUIRED:
        check=checks.get(name)
        if not isinstance(check,dict) or check.get('status')!='passed':return out('defer','未完成核验：'+name)
        try:
            evidence=Path(check['evidence'])
            if evidence.name.lower() in SENSITIVE or not evidence.is_file():return out('defer','核验凭据不可用：'+name)
        except (OSError,TypeError,KeyError):return out('defer','核验凭据不可用：'+name)
    if not isinstance(item.get('important_change'),bool):return result
    if item.get('important_change'):
        review=item.get('independent_review')
        if not isinstance(review,dict) or review.get('status')!='passed' or not review.get('author_session') or not review.get('reviewer_session') or review['author_session']==review['reviewer_session']:
            return out('defer','重要变动缺真实独立上下文复核，不用自审冒称独立')
        try:
            evidence=Path(review['evidence'])
            if evidence.name.lower() in SENSITIVE or not evidence.is_file():return out('defer','独立复核凭据缺失')
        except (OSError,TypeError,KeyError):return out('defer','独立复核凭据缺失')
    if item.get('baseline_sha256')!=current:return out('rebase','基线已变：先核他方是否完成，再从现版重新生成；不永久挂账、不覆盖')
    return out('eligible_for_deploy','满足已记录的范围和核验前提；仍须受保护写入、回归及读回，不等于内容正确或已经部署')

def main(argv=None):
    ap=argparse.ArgumentParser(description='只读筛选核验清单，不部署、不安装、不写状态')
    ap.add_argument('--input',type=Path,required=True)
    a=ap.parse_args(argv)
    try:
        items=json.loads(a.input.read_text(encoding='utf-8-sig'))
        if not isinstance(items,list):raise ValueError('Input must be a list')
        results=[assess(x) for x in items]
        print(json.dumps({'decisions':results,'writes_performed':False},ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,TypeError) as exc:
        print('候选核验未完成：'+str(exc),file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
