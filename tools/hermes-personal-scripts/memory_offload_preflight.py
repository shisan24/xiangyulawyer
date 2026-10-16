# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""Read-only wake gate for the existing memory-offload workflow.

No migration, memory edits, database writes or delivery. Nonzero means the
inputs are unavailable/invalid, never a clean empty batch. Scheduler failures
must not be followed by commit/emit (enforced by the task prompt).
"""
import json
import os
from pathlib import Path
import re
import sys


def read_object(path, *, optional=False):
    try:
        data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        if optional:return {}
        raise
    if not isinstance(data,dict):raise ValueError('Expected a JSON object')
    return data


def evaluate(home, candidates_file=None, state_file=None):
    home=Path(home)
    candidates_file=Path(candidates_file or home/'skills/ops/memory-slimming/scripts/offload_candidates.json')
    state_file=Path(state_file or home/'cron/lawyer-status/memory-offload-state.json')
    cfg=read_object(candidates_file)
    candidates=cfg.get('candidates')
    if not isinstance(candidates,list) or any(not isinstance(x,str) or not x.strip() for x in candidates):
        raise ValueError('Invalid candidates list')
    state=read_object(state_file,optional=True)
    emitted=state.get('emitted',{});deleted=state.get('deleted',[])
    if not isinstance(emitted,dict) or not isinstance(deleted,list):raise ValueError('Invalid offload state')
    text=(home/'memories/MEMORY.md').read_text(encoding='utf-8-sig')
    blocks=re.split(r'\r?\n§\r?\n',text)
    labels=[next((x.strip() for x in b.splitlines() if x.strip()),'') for b in blocks]
    live=[x for x in labels if any(x.startswith(p) for p in candidates) and x not in deleted]
    pending=[x for x in labels if x in emitted and x not in deleted]
    wake=bool(live or pending)
    action='pending_verification' if pending else ('authorized_batch' if live else ('stale_allowlist' if candidates else 'empty_batch'))
    return {'wakeAgent':wake,'action':action,'authorized_live_count':len(live),
            'pending_verification_count':len(pending),'candidate_count':len(candidates),
            'reason':'仅处理现有授权名单；有待核验记录继续，不扩名单、不迁移' if wake else
                     '本批无在册待迁及待核验条目，正常等待新授权；不改记忆'}


def main():
    home=Path(os.environ.get('HERMES_HOME') or Path.home()/'AppData/Local/hermes')
    try:r=evaluate(home)
    except (OSError,ValueError,UnicodeError) as exc:
        print(json.dumps({'wakeAgent':False,'action':'input_failed','fail':True,
                          'reason':f'前置读取失败：{type(exc).__name__}；禁止commit/emit，不能判无事'},ensure_ascii=False))
        return 2
    print(json.dumps(r,ensure_ascii=False));return 0

if __name__=='__main__':sys.exit(main())
