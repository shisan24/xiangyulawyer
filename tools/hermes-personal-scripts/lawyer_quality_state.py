# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Evidence-bound shared cron work state. Runtime data is on D, not in memory.

This module verifies provenance and version identity, not legal merits. An
omitted item stays unresolved. A local receipt is not customer acceptance or
external delivery. All read/parse errors remain errors.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid

TZ=timezone(timedelta(hours=8))
DATA_DIR=Path(os.environ.get('LAWYER_QUALITY_DIR','[本地路径]'))
ITEMS_FILE=DATA_DIR/'work-items.json'
STATUSES={'pending','in_progress','waiting','conflict','completed','cancelled'}
CLOSING_EVIDENCE={'delivery_message','user_confirmation','receipt'}


def stamp():return datetime.now(TZ).isoformat(timespec='seconds')

def read_object(path, *, missing=None):
    try:data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        if missing is not None:return missing
        raise
    if not isinstance(data,dict):raise ValueError(f'JSON object required: {path}')
    return data


@contextmanager
def file_lock(path, timeout=15):
    """OS-owned lock; a process exit releases it. No stale-file deletion."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    f=open(path,'a+b')
    if f.seek(0,2)==0:f.write(b'0');f.flush()
    deadline=time.monotonic()+timeout
    try:
        while True:
            f.seek(0)
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except (OSError,BlockingIOError):
                if time.monotonic()>=deadline:raise TimeoutError(f'State writer busy: {path}')
                time.sleep(0.05)
        try:yield
        finally:
            f.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(f.fileno(),fcntl.LOCK_UN)
    finally:f.close()


def atomic_json(path, data, retries=4):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(f'{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp')
    try:
        with tmp.open('x',encoding='utf-8',newline='\n') as f:
            json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        for n in range(retries+1):
            try:os.replace(tmp,path);break
            except PermissionError:
                if n==retries:raise
                time.sleep(0.05*(n+1))
    finally:
        if tmp.exists():tmp.unlink()


def verify_evidence(evidence, home=None):
    if not isinstance(evidence,dict) or not evidence.get('quote'):raise ValueError('Evidence quote required')
    if evidence.get('path'):
        p=Path(evidence['path'])
        if p.name.lower() in {'.env','auth.json','config.yaml'}:raise ValueError('Credential/config file is not work evidence')
        content=p.read_text(encoding='utf-8-sig')
    elif evidence.get('session_id') and evidence.get('message_id'):
        home=Path(home or os.environ['HERMES_HOME'])
        with sqlite3.connect((home/'state.db').resolve().as_uri()+'?mode=ro',uri=True,timeout=5) as db:
            row=db.execute('SELECT content FROM messages WHERE id=? AND session_id=?',(evidence['message_id'],evidence['session_id'])).fetchone()
        if row is None:raise ValueError('Evidence message not found in exact session')
        content=str(row[0] or '')
    else:raise ValueError('Evidence needs exact path or session/message IDs')
    if str(evidence['quote']) not in content:raise ValueError('Evidence quote not found in source')
    return {**evidence,'checked_at':stamp(),'source_sha256':hashlib.sha256(content.encode('utf-8')).hexdigest()}


def load_items(path=ITEMS_FILE):
    data=read_object(path,missing={'schema':'cron-work-items/v1','revision':0,'items':{}})
    if data.get('schema')!='cron-work-items/v1' or not isinstance(data.get('items'),dict):raise ValueError('Invalid work state schema')
    return data


def merge_items(path, updates):
    if not isinstance(updates,list):raise ValueError('Updates must be a list; omitted items are retained')
    verified=[]
    for item in updates:
        if not isinstance(item,dict) or not item.get('id') or not item.get('title') or item.get('status') not in STATUSES:raise ValueError('Invalid work item')
        evidence=item.get('evidence')
        if not isinstance(evidence,list) or not evidence:raise ValueError('Every work item needs source evidence')
        evidence=[verify_evidence(e) for e in evidence]
        if item['status'] in {'completed','cancelled'} and not any(e.get('type') in CLOSING_EVIDENCE for e in evidence):
            raise ValueError('Completion/cancellation needs delivery, user confirmation or receipt evidence')
        verified.append({**item,'evidence':evidence})
    path=Path(path)
    with file_lock(path.with_suffix('.lock')):
        data=load_items(path)
        for item in verified:
            previous=data['items'].get(item['id'],{})
            history=list(previous.get('history',[]))
            if previous:history.append({k:v for k,v in previous.items() if k!='history'})
            data['items'][item['id']]={**previous,**item,'history':history,'updated_at':stamp()}
        data['revision']=int(data.get('revision',0))+1;data['updated_at']=stamp()
        atomic_json(path,data)
    return data


def validate_gate(gate_path, folder, register=False):
    """Bind the recorded engineering check to the current artifact bytes.

    三件套（主稿/净版/台账）都要与门禁记录的摘要逐一比对；只在主稿上比、
    净版与台账重算后直接绑定，会让旧门禁给新产物背书（2026-10-24 复核 C04）。

    register=True 用于「新增完成登记」：要求 release_ready is True、三件套摘要齐全、
    逐项匹配；缺任一摘要即拒绝——不能靠登记时重算补成证明（复核 2 的 Q2）。
    register=False 用于「历史读取」：旧门禁缺 release_ready 字段时不拒绝，
    但返回 full_binding_verified=False，调用方不得据此升级为当前完成。
    """
    folder=Path(folder).resolve();gate_path=Path(gate_path).resolve()
    if not gate_path.is_relative_to(folder):raise ValueError('Gate outside attachment folder')
    raw=gate_path.read_bytes()
    try:
        gate=json.loads(raw.decode("utf-8"))
    except Exception:
        raise ValueError("Gate unreadable")
    if gate.get('ok') is not True or not gate.get('sha256') or not gate.get('path'):raise ValueError('Gate not passed or not bound to an artifact')
    release=gate.get('release_ready')
    role_of={'path':'document','expected':'clean','ledger':'ledger'}
    recorded=gate.get('artifact_hashes') or {}
    if not isinstance(recorded,dict):raise ValueError('artifact_hashes 必须是对象')
    if register:
        if release is not True:
            raise ValueError('正式登记要求 release_ready is True（实得 %r）' % (release,))
        if gate.get('profile') != 'contract':
            raise ValueError('正式合同登记要求 profile=contract（实得 %r）' % (gate.get('profile'),))
        required=gate.get('required_checks') or []
        if not required:
            raise ValueError('门禁未声明 required_checks，不能作为正式放行证据')
        states={c.get('id'):c.get('status') for c in gate.get('checks',[]) if isinstance(c,dict)}
        not_passed=[r for r in required if states.get(r)!='pass']
        if not_passed:
            raise ValueError('必需检查未通过或缺失：%s' % ','.join(map(str,not_passed)))
        missing=[r for r in ('document','clean','ledger') if not recorded.get(r)]
        if missing:
            raise ValueError('正式登记要求三件套摘要齐全，缺：%s' % ','.join(missing))
    elif release is False:
        raise ValueError('Gate 未达正式放行条件（release_ready=false）：存在未认证检查或缺必需项')
    if gate.get('specialist_missing'):
        raise ValueError('专项门禁缺必需检查：%s' % ','.join(map(str, gate['specialist_missing'])))
    if any(c.get('status')=='fail' for c in gate.get('checks',[]) if isinstance(c,dict)):raise ValueError('Gate contains failed checks')
    artifacts=[]
    for key in ('path','expected','ledger'):
        if not gate.get(key):
            if register and key!='path':raise ValueError('正式登记要求门禁绑定 %s' % key)
            continue
        p=Path(gate[key]).resolve()
        if not p.is_relative_to(folder) or not p.is_file():raise ValueError('Artifact missing or outside attachment folder')
        digest=hashlib.sha256(p.read_bytes()).hexdigest()
        if key=='path' and digest!=gate['sha256']:raise ValueError('Artifact changed since gate; preserve user version')
        want=recorded.get(role_of[key])
        if want and digest!=want:
            raise ValueError('%s 在门禁之后被改动，须重新跑门禁（不沿用旧通过记录）' % key)
        if register and not want:
            raise ValueError('%s 无门禁摘要，不能作为正式放行证据' % key)
        artifacts.append({'role':key,'path':str(p),'sha256':digest,'hash_matches_gate':bool(want) and digest==want})
    full=release is True and all(recorded.get(r) for r in ('document','clean','ledger')) \
         and all(a['hash_matches_gate'] for a in artifacts)
    return {'gate_path':str(gate_path),'gate_sha256':hashlib.sha256(raw).hexdigest(),
            'artifacts':artifacts,'release_ready':release,
            'gate_has_release_field':'release_ready' in gate,
            'full_binding_verified':bool(full)}


def inspect_receipt(folder):
    """读回执，区分「当前完成」「历史记录」「明确不办理」。

    current_version_matched 只发给带 `full_gate_binding is True` 的新回执：
    旧回执即使三件套摘要都对得上，也只是 historical_unbound_gate——文件相同
    不等于曾经通过完整门禁（2026-10-24 复核 2 的 Q2）。
    declined 单独核验对象与决定依据，不要求修订三件套（复核 2 的 #14 误挡）。
    """
    folder=Path(folder)
    p=folder/'_处理回执.json'
    if not p.is_file():return {'folder':str(folder),'status':'not_completed','version_state':'no_receipt'}
    rec=read_object(p)
    result={'folder':str(folder),'receipt_path':str(p),'status':rec.get('status'),
            'handled_at':rec.get('handled_at'),'note':rec.get('note',''),
            'resume':rec.get('resume',''),'stage':rec.get('stage'),
            'version_state':'historical_unbound','external_delivery_verified':False}
    if rec.get('status')=='declined':
        basis=rec.get('decision_basis')
        if isinstance(basis,dict) and str(basis.get('object') or '').strip() and str(basis.get('reason') or '').strip():
            result['version_state']='declined_verified';result['decision_basis']=basis
        else:
            result['version_state']='declined_unverified'
        return result
    bound=rec.get('version_evidence')
    if bound:
        if not isinstance(bound,dict) or not isinstance(bound.get('artifacts'),list) or not bound['artifacts']:
            raise ValueError('Invalid version evidence')
        for item in bound['artifacts']:
            artifact=Path(item['path']).resolve()
            if not artifact.is_relative_to(folder.resolve()):
                raise ValueError('Receipt artifact outside attachment folder')
            if not artifact.is_file() or hashlib.sha256(artifact.read_bytes()).hexdigest()!=item.get('sha256'):
                result['version_state']='changed_after_receipt';return result
        result['version_evidence']=bound
        if rec.get('full_gate_binding') is True and bound.get('full_binding_verified') is True:
            # 标记只作历史信息：当前状态由回读门禁重新计算（2026-10-25 复核 3 的 Q2）。
            gp=bound.get('gate_path'); gs=bound.get('gate_sha256')
            roles={a.get('role') for a in (bound.get('artifacts') or [])}
            if not gp or not gs or roles!={'path','expected','ledger'}:
                result['version_state']='binding_incomplete'
            elif not Path(gp).is_file():
                result['version_state']='gate_missing'
            else:
                try:
                    v=validate_gate(Path(gp),folder,register=True)
                except Exception:
                    result['version_state']='gate_invalid'
                else:
                    if v.get('gate_sha256')!=gs:
                        result['version_state']='gate_replaced'
                    elif {a['role']:a['sha256'] for a in v['artifacts']}!={a['role']:a['sha256'] for a in bound['artifacts']}:
                        result['version_state']='artifact_mismatch'
                    else:
                        result['version_state']='current_version_matched'
        else:
            result['version_state']='historical_unbound_gate'
    return result


def main(argv=None):
    ap=argparse.ArgumentParser(description='逐件状态：不从遗漏推定完成，不改案件台账')
    ap.add_argument('action',choices=['show','merge'])
    ap.add_argument('--input',type=Path)
    ap.add_argument('--state',type=Path,default=ITEMS_FILE)
    args=ap.parse_args(argv)
    try:
        data=load_items(args.state) if args.action=='show' else merge_items(args.state,json.loads(args.input.read_text(encoding='utf-8-sig')))
        print(json.dumps(data,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,TypeError,sqlite3.Error) as exc:
        print(f'逐件状态未完成：{type(exc).__name__}: {exc}；没有据此清空或结清事项',file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
