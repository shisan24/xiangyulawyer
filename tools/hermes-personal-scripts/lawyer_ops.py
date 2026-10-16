# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Local lawyer operations. Read case sources; write only dedicated cron status files.

No model/network calls, no legal deadline calculation, no case or memory modification.
The caller controls when to deliver a report; --preview leaves notification state unchanged.
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from lawyer_quality_state import DATA_DIR, ITEMS_FILE, atomic_json, load_items

# 期限判定的唯一真源（与插件工作台面板共用同一份状态集合与分桶规则，避免两处漂移）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lawyer_deadline_core import (  # noqa: E402
    CONFIG_KEY_BRIEF,
    DEFAULT_BRIEF_DAYS,
    DEFAULT_SOON_DAYS as CORE_SOON_DAYS,
    MILESTONE_STATUS,
    TERMINAL_STATUS,
    needs_receipt,
    resolve_window,
)


def workbench_config():
    """工作台配置快照；读不到、或顶层不是对象，一律返回空 dict（不抛错）。"""
    try:
        home = os.environ.get('HERMES_HOME') or str(Path.home() / 'AppData' / 'Local' / 'hermes')
        cfg = json.loads((Path(home) / 'lawyer-workbench.json').read_text(encoding='utf-8'))
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}

TZ = ZoneInfo('Asia/Shanghai')
SILENT = '[SILENT]'

def hermes_home():
    return Path(os.environ.get('HERMES_HOME') or Path.home()/'.hermes').resolve()

def read(path):
    return Path(path).read_text(encoding='utf-8-sig')

def in_business_hours(now=None):
    now = (now or datetime.now(TZ)).astimezone(TZ)
    return 8 <= now.hour < 22

def parse_deadlines(text, today):
    result = {'alerts': [], 'issues': [], 'pending': [], 'completed': 0, 'rows': 0,
              'milestones': [], 'completed_unverified': []}
    header = None
    # 状态集合唯一真源：scripts/lawyer_deadline_core.py（与插件工作台面板共用，避免两处漂移）。
    # 「事件已发生」不等于办结：单列 milestones 保留在视野里 —— 改过、发生过了不等于办完了。
    terminal = TERMINAL_STATUS
    milestone = MILESTONE_STATUS
    for num, line in enumerate(text.splitlines(),1):
        if not line.strip().startswith('|'): continue
        cells = [c.strip() for c in re.split(r'(?<!\\)\|',line.strip().strip('|'))]
        if all(re.fullmatch(r':?-+:?',c.replace(' ','')) for c in cells): continue
        if any(k in cells for k in ('截止日','截止日期','期限')):
            header=cells
            continue
        if header is None: continue
        if len(cells)!=len(header):
            result['issues'].append(f'第{num}行列数不匹配，请核对原台账。')
            continue
        row=dict(zip(header,cells))
        case=row.get('案件',row.get('案件名称',''))
        task=row.get('事项','')
        deadline=row.get('截止日',row.get('截止日期',row.get('期限','')))
        status=row.get('状态','')
        result['rows']+=1
        if status in terminal:
            result['completed']+=1
            if needs_receipt(row.get('备注','')):
                # 已办结但缺登记凭据（备注为空且未注明「无须回证」）：提示补记，不否定其完成状态
                result['completed_unverified'].append({'case':case,'task':task,'status':status,'line':num})
            continue
        if status in milestone:
            # 事件已发生 ≠ 事项办结：保留在视野里，提示确认后续动作
            result['milestones'].append({'case':case,'task':task,'deadline':deadline,
                                         'status':status,'line':num})
            continue
        try:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',deadline): raise ValueError()
            days=(date.fromisoformat(deadline)-today).days
        except ValueError:
            # 约期（如「约 2027-03 上旬」）与「待核实」不是格式错误：单列登记，
            # 既不据以推算期限，也不每天把同一批未定日期当问题重复报出。
            if not deadline or re.search(r'待核|待定|未定|约|视|以.*为准',deadline):
                result['pending'].append({'case':case,'task':task,'deadline':deadline or '（空）','status':status or '未登记','line':num})
            else:
                result['issues'].append(f'第{num}行 [{case}] {task}：日期格式无法解析（{deadline}），未纳入期限判断。')
            continue
        if not case or not task:
            result['issues'].append(f'第{num}行案件或事项为空，请核对原台账。')
        # 每日提要的窗口更窄：默认 15 天（可配 `deadline_brief_days`），比工作台面板的 30 天保守。
        # 两者是**有意不同的两个用途设定**，不是漂移；窗口值都经 core.resolve_window 解析
        # （复核第 6 轮点名：CLI 此前用字面量 15，与面板无法对账）。
        if days <= resolve_window(workbench_config(), CONFIG_KEY_BRIEF, DEFAULT_BRIEF_DAYS):
            kind = '日期已过，状态待核实' if days<0 else ('今天到期' if days==0 else f'距登记日期{days}天')
            result['alerts'].append({'case':case,'task':task,'deadline':deadline,'days':days,'status':status or '未登记','kind':kind,'line':num})
    if header is None: result['issues'].append('未识别到台账表头（需含「期限」或「截止日」列），检查未完成。')
    elif result['rows']==0: result['issues'].append('台账无数据行，尚不能据此确认案件期限已登记完整。')
    result['alerts'].sort(key=lambda x:(x['days'],x['case'],x['task']))
    return result

def deadline_report(path,today=None):
    report=parse_deadlines(read(path),today or datetime.now(TZ).date())
    # 早退必须涵盖**所有**需要观察的列表：只加提示却不改这里，新提示会被空串吞掉（复核 N01）。
    if not (report['alerts'] or report['issues'] or report['pending']
            or report['milestones'] or report['completed_unverified']):
        return ''
    lines=['案件期限核对：仅检查台账已登记日期，不推算诉讼期间。']
    for x in report['alerts']:
        lines.append(f"- [{x['case']}] {x['task']}：{x['deadline']}；{x['kind']}；台账状态：{x['status']}（第{x['line']}行）。")
    if report['pending']:
        brief='、'.join(dict.fromkeys(str(p['case']) for p in report['pending']))
        lines.append(f"- 另有{len(report['pending'])}条登记为约期或待核实，不纳入期限判断，需待送达或裁判结果核定后补具体日期：{brief}（逐条见台账）。")
    if report['milestones']:
        lines.append(f"- 另有{len(report['milestones'])}项状态为「已发生事件」（已开庭/已提交/已缴费/已续冻/已解除）"
                     "——事件发生不等于事项办结，请确认是否仍需后续动作：")
        for x in report['milestones']:
            lines.append(f"  · [{x['case']}] {x['task']}：{x['deadline']}；状态：{x['status']}（第{x['line']}行）")
    lines.extend('- '+x for x in report['issues'])
    if report['completed_unverified']:
        lines.append(f"- {len(report['completed_unverified'])}项已办结但缺登记凭据（备注为空；凭据在附件或工作记录里可在备注注明「无须回证」）"
                     "（不改变其完成状态，建议补记）："
                     + '、'.join(dict.fromkeys(str(x['case']) for x in report['completed_unverified'])))
    lines.append(f'来源：{path}。已明确完成的{report["completed"]}项不提醒。')
    return '\n'.join(lines)

def parse_todo(text):
    text=re.sub(r'<!--.*?-->','',text,flags=re.S)
    tasks=[]
    for raw in text.splitlines():
        line=raw.strip()
        if not line or line.startswith(('#','>','|')): continue
        if re.match(r'^[-*+]\s+\[[xX]\]',line): continue
        pending=re.match(r'^[-*+]\s+\[ \]\s*(.+)',line)
        if pending: tasks.append(pending.group(1)); continue
        legacy=re.match(r'^(?:[-*+]\s+|\d+[.、]\s*)(.+)',line)
        if legacy:
            item=legacy.group(1)
            if not re.match(r'^(已完成|已办结|已取消)[：:\s]',item): tasks.append(item)
    return list(dict.fromkeys(tasks))

def deadline_brief(path,today=None):
    """期限摘要（并入每日待办提要）：只列 ≤ 配置窗口（`deadline_brief_days`，默认 15 天）或已逾期、且台账状态未标完成的条目。
    刻意不带剩余天数——否则每日随天数变化而重复投递；日期照台账原文。
    覆盖状态必须如实：台账缺失/不可读、列数或日期解析异常都要出声，不能返回空串冒充"没有期限"。"""
    if not path: return ''
    try:
        if not Path(path).exists():
            return '案件期限：未覆盖——配置指定的期限台账不存在，本次未作期限核对（不等于无期限或已全部登记）。'
        text = read(path)
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return f'案件期限：未覆盖——期限台账不可读（{type(e).__name__}），本次未作期限核对。'
    report=parse_deadlines(text,today or datetime.now(TZ).date())
    # 同 deadline_report：早退条件必须涵盖所有观察列表，否则新提示不可达（复核 N01）。
    if not (report['alerts'] or report['pending'] or report['issues']
            or report['milestones'] or report['completed_unverified']):
        return ''
    lines=['案件期限（来自期限台账，日期照原文，不推算诉讼期间）：']
    for x in report['alerts']:
        lines.append(f"- [{x['case']}] {x['task']}：{x['deadline']}；台账状态：{x['status']}（第{x['line']}行）。")
    if report['pending']:
        brief='、'.join(dict.fromkeys(str(p['case']) for p in report['pending']))
        lines.append(f"- 另有{len(report['pending'])}条为约期或待核实，未纳入期限判断：{brief}（逐条见台账）。")
    if report['milestones']:
        brief='、'.join(dict.fromkeys(f"[{x['case']}] {x['task']}（{x['status']}）" for x in report['milestones']))
        lines.append(f"- 另有{len(report['milestones'])}项状态为已发生事件（不等于办结，请确认后续）：{brief}")
    if report['completed_unverified']:
        lines.append(f"- {len(report['completed_unverified'])}项已办结但缺登记凭据，建议补记（未改变其完成状态；无须回证的可备注注明）。")
    lines.extend('- '+x for x in report['issues'])
    return '\n'.join(lines)

def persistent_work_brief(path=ITEMS_FILE):
    data=load_items(path)
    if not Path(path).exists():return '逐件续办状态尚未建立；不能把旧待办空白认定为当前全部办结。'
    rows=[x for x in data['items'].values() if x.get('status') not in {'completed','cancelled'}]
    if not rows:return '逐件状态库无在册未决事项；不代表未覆盖会话或案卷也无事项。'
    lines=['仍未决事项（本轮未出现不表示完成，日期冲突未解决前持续保留）：']
    for x in rows:
        lines.append(f"- [{x.get('status')}] {x.get('title')}；{x.get('next_step','按来源接续，不自动推算或结清')}（事项ID={x['id']}）")
    return '\n'.join(lines)


def todo_report(path,deadline_path=None):
    source=read(path)
    tasks=parse_todo(source)
    blocks=[persistent_work_brief(),f'业务源：{path}；文件保存时刻={datetime.fromtimestamp(Path(path).stat().st_mtime,TZ).isoformat()}。扫描新鲜不证明源事项新鲜或已办理。']
    brief=deadline_brief(deadline_path)
    if brief: blocks.append(brief)
    if tasks:
        blocks.append('台账中未标完成的待办：\n'+'\n'.join('- '+t for t in tasks)+f'\n来源：{path}\n以下日期沿用原文；「今天/明早」不代表本次运行日期，当前完成状态仍需核对。')
        return '\n\n'.join(blocks)
    unstructured=[l.strip() for l in re.sub(r'<!--.*?-->','',source,flags=re.S).splitlines() if l.strip() and not l.strip().startswith(('#','-','*','+','>'))]
    if unstructured:
        blocks.append(f'待办格式待核对：存在非列表内容，未将其自动判定为已完成。来源：{path}')
    return '\n\n'.join(blocks)

def changed_report(report,state_path,*,daily=False,today=None):
    state_path=Path(state_path)
    day=(today or datetime.now(TZ).date()).isoformat()
    digest=hashlib.sha256(report.encode('utf-8')).hexdigest()
    previous={}
    if state_path.exists(): previous=json.loads(read(state_path))
    should_send=bool(report) and (digest!=previous.get('hash') or daily and day!=previous.get('day'))
    recovered=not report and previous.get('has_report',False)
    state={'hash':digest,'day':day,'has_report':bool(report),'checked_at':datetime.now(TZ).isoformat()}
    state_path.parent.mkdir(parents=True,exist_ok=True)
    temp=state_path.with_name(state_path.name+f'.{os.getpid()}.tmp')
    temp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temp,state_path)
    return report if should_send else ('已恢复：上次提示的事项已不再触发当前检查，请以源台账为准。' if recovered else SILENT)

def memory_health(home):
    cfg=json.loads(read(home/'lawyer-workbench.json'))
    issues=[]
    for name,limit in [('MEMORY.md',cfg['memory_limits']['memory']),('USER.md',cfg['memory_limits']['user'])]:
        path=home/'memories'/name
        if not path.exists(): issues.append(f'{name}缺失，需核对实际记忆提供方。'); continue
        n=len(read(path))
        if n>int(limit*.85): issues.append(f'{name}为{n}字符，配置额度{limit}；仅报告，不删减或改写。')
    return '\n'.join(issues)

def session_health(home):
    path=home/'state.db'
    if not path.exists(): raise FileNotFoundError(path)
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=5) as conn:
        total,old=conn.execute('SELECT COUNT(*), SUM(CASE WHEN last_ts < ? THEN 1 ELSE 0 END) FROM (SELECT MAX(timestamp) AS last_ts FROM messages GROUP BY session_id)',(time.time()-90*86400,)).fetchone()
    return f'会话存储只读检查：{total}个有消息的会话，{old or 0}个超过90天未活跃。未删除会话，未执行VACUUM。文件大小{path.stat().st_size//1048576}MB。'

def _embedded_plugin_source(directory, skills_root):
    """Return traceable host/container evidence for one exact embedded root.

    Only <host>/plugins/<vendor>/skills/<resource>/SKILL.md is accepted. Each
    segment is contiguous, <host> is an existing ancestor skill, and the resource
    is a single directory. Category roots merely named plugins are not hosts.
    This establishes local containment, not plugin registration or enablement.
    A package manifest is extra provenance when present; simple bundled fixtures
    and packages without a manifest remain identifiable by their host/container.
    """
    parts = os.path.relpath(directory, skills_root).replace('\\', '/').split('/')
    if '..' in parts:
        return None
    for index, part in enumerate(parts):
        if (part != 'plugins' or index == 0 or len(parts) != index + 4
                or parts[index + 2] != 'skills'):
            continue
        host = os.path.join(skills_root, *parts[:index], 'SKILL.md')
        if not os.path.isfile(host):
            continue
        plugin = os.path.join(skills_root, *parts[:index + 2])
        manifests = [os.path.join(plugin, marker, 'plugin.json')
                     for marker in ('.claude-plugin', '.codex-plugin')]
        return {'host_skill': host, 'plugin_container': plugin,
                'resource_skill': os.path.join(directory, 'SKILL.md'),
                'manifests': [p for p in manifests if os.path.isfile(p)],
                'evidence': 'existing host ancestor + contiguous plugin resource path'}
    return None


def skills_health(home):
    import yaml
    skills=home/'skills'
    issues=[]; names={}; count=0; embedded=[]
    for p in sorted(skills.rglob('SKILL.md')):
        relative_dirs = p.relative_to(skills).parts[:-1]
        if any(s.startswith('.') for s in relative_dirs) or any(s.casefold() == 'references' for s in relative_dirs): continue
        # 宿主技能内 plugins/.../skills/<name>/SKILL.md 是随包资源，不是第二个活动根。
        # 只识别这条确切路径形态；真正独立目录下的同名技能仍报告重名。
        if _embedded_plugin_source(str(p.parent), str(skills)):
            embedded.append(str(p.relative_to(skills))); continue
        count+=1
        txt=read(p)
        try:
            if not txt.startswith('---'): raise ValueError('缺少frontmatter')
            fm=yaml.safe_load(txt.split('---',2)[1])
            if not isinstance(fm,dict) or not fm.get('name') or not fm.get('description'): raise ValueError('缺少name/description')
            name=fm['name']
            if name in names: issues.append(f'重名：{name}（{names[name]}；{p.relative_to(skills)}）')
            names[name]=str(p.relative_to(skills))
        except (ValueError,yaml.YAMLError,IndexError) as e: issues.append(f'{p.relative_to(skills)}：{type(e).__name__}')
        if len(txt)>20000: issues.append(f'长入口：{p.relative_to(skills)}（{len(txt)}字符），候选重构时保留全文到references，不自动精简。')
    if not issues and not embedded:return ''
    lines=[f'技能只读体检：{count}份活动入口，{len(issues)}条结构提示。']
    lines.extend('- '+s for s in issues)
    if embedded:
        lines.append(f'已知形态：{len(embedded)}份插件包内嵌副本（不计作独立重名，不代表已加载）：'+ '；'.join(embedded))
    return '\n'.join(lines)

def file_changes(roots,days=7,max_depth=12):
    cutoff=time.time()-days*86400
    items=[]; issues=[]; seen=set()
    for raw in roots:
        base=Path(raw)
        if not base.is_dir(): issues.append(f'目录不可用：{base}'); continue
        def onerror(e): issues.append(f'未能扫描：{e.filename}（{type(e).__name__}）')
        for directory,dirs,files in os.walk(base,onerror=onerror,followlinks=False):
            depth=len(Path(directory).relative_to(base).parts)
            readable=[]
            for d in dirs:
                if d.startswith('.'):continue
                child=Path(directory)/d
                try:
                    if not child.is_symlink():readable.append(d)
                except OSError as exc:
                    issues.append(f'未能扫描：{child}（{type(exc).__name__}）')
            dirs[:]=readable
            if depth>=max_depth:
                if dirs: issues.append(f'深度上限，未扫描更深目录：{directory}')
                dirs[:]=[]
            for name in files:
                if name.startswith(('~','.')) or Path(name).suffix.lower() not in {'.doc','.docx','.pdf','.md','.xlsx'}:continue
                p=Path(directory)/name
                try:
                    stamp=p.stat().st_mtime
                except OSError as e: issues.append(f'无法读取元数据：{p}（{type(e).__name__}）'); continue
                if stamp<cutoff or str(p) in seen: continue
                seen.add(str(p));items.append({'path':str(p),'modified_at':datetime.fromtimestamp(stamp,TZ).isoformat()})
    items.sort(key=lambda x:x['modified_at'],reverse=True)
    return {'scope':'文件修改记录，不代表已完成法律工作','days':days,'files':items,'coverage_issues':issues}

def run_legacy(home,script):
    path=(home/'scripts'/script).resolve()
    if path.parent!=(home/'scripts').resolve() or not path.is_file(): raise ValueError('无效的既有脚本路径')
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    p=subprocess.run([sys.executable,str(path)],cwd=path.parent,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120,creationflags=flags,env={**os.environ,'PYTHONIOENCODING':'utf-8'})
    if p.returncode: raise RuntimeError(f'{script}退出码{p.returncode}；需检查Hermes本地日志。')
    return p.stdout.strip()

def changes_summary(report,inventory):
    lines=[f'案件文件变动索引：过去{report["days"]}天有{len(report["files"])}份文件发生修改。修改记录不代表已完成审查或提交。']
    for item in report['files'][:15]:
        lines.append(f'- {item["modified_at"][:16]}  {item["path"]}')
    if len(report['files'])>15:lines.append(f'其余{len(report["files"])-15}份见完整索引。')
    if report['coverage_issues']:
        lines.append(f'有{len(report["coverage_issues"])}处因权限、路径或深度限制未覆盖，本次不是全目录扫描。')
        lines.extend('- '+x for x in report['coverage_issues'][:3])
    lines.append(f'完整索引：{inventory}')
    return '\n'.join(lines)

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['deadlines','todo','memory','sessions','skills','changes','weekly','gate','legacy'])
    parser.add_argument('--legacy-script')
    parser.add_argument('--preview',action='store_true')
    args=parser.parse_args(argv)
    home=hermes_home()
    if not args.preview and not in_business_hours():
        print(json.dumps({'wakeAgent':False,'reason':'Asia/Shanghai非工作时间'}) if args.mode in {'gate','weekly'} else SILENT)
        return 0
    if args.mode=='gate':
        print(json.dumps({'wakeAgent':True,'scope':'只读检查与去标识候选；常规改进须经统一采纳程序（基线核对、原子替换、写后读回）才落地；不改客户材料、不对外发送、不改模型与 provider 配置'},ensure_ascii=False))
        return 0
    cfg=json.loads(read(home/'lawyer-workbench.json'))
    actions={
        'deadlines':lambda:deadline_report(Path(cfg['deadline_file'])),
        'todo':lambda:todo_report(Path(cfg['todo_file']),Path(cfg['deadline_file'])),
        'memory':lambda:memory_health(home),
        'sessions':lambda:session_health(home),
        'skills':lambda:skills_health(home),
        'legacy':lambda:run_legacy(home,args.legacy_script),
    }
    try:
        if args.mode in {'weekly','changes'}:
            report=file_changes(cfg['case_roots'],7 if args.mode=='weekly' else 1)
            state_path=home/'cron/lawyer-status'/f'{args.mode}.json'
            payload=json.dumps(report,ensure_ascii=False,indent=2)
            if args.preview: print(payload);return 0
            if not report['files'] and not report['coverage_issues']:
                print(json.dumps({'wakeAgent':False}) if args.mode=='weekly' else SILENT);return 0
            inventory=DATA_DIR/'file-inventories'/f'{args.mode}-{datetime.now(TZ):%Y%m%d-%H%M%S}-{time.time_ns()}.json'
            atomic_json(inventory,report)
            # 留兼容最新视图，但每期概要必须指向自己的不可变完整索引。
            atomic_json(home/'cron/lawyer-status'/f'{args.mode}-inventory.json',{**report,'complete_inventory':str(inventory)})
            if args.mode=='weekly':
                bounded={**report,'files':report['files'][:80],'coverage_issues':report['coverage_issues'][:12],
                         'total_changed_files':len(report['files']),'coverage_issue_count':len(report['coverage_issues']),
                         'complete_inventory':str(inventory)}
                print(json.dumps({'wakeAgent':True,'data':bounded},ensure_ascii=False));return 0
            emitted=changed_report(changes_summary(report,inventory),state_path)
            print(emitted);return 0
        report=actions[args.mode]()
        if report==SILENT:report=''
        if args.preview:print(report or SILENT)
        else:print(changed_report(report,home/'cron/lawyer-status'/f'{args.mode}-{args.legacy_script or "check"}.json',daily=args.mode in {'deadlines','todo'}))
        return 0
    except (OSError,ValueError,RuntimeError,sqlite3.Error,subprocess.SubprocessError) as exc:
        # A failed check must never be delivered as a clean bill of health.
        print(f'检查失败：{args.mode}；{type(exc).__name__}；请核对数据源/权限/本地日志。本次未确认无待办或无临期事项。',file=sys.stderr)
        return 1

if __name__=='__main__':sys.exit(main())
