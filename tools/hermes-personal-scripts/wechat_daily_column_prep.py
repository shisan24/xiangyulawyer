# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""公众号预备材料。默认只读；选题前应再次运行此入口。"""
import argparse, datetime, hashlib, json, os, re, sys
from pathlib import Path
BRIEF_DIR = r'[本地路径]'
OPS = r'[本地路径]'

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def completion_files(day, brief_dir):
    b=Path(brief_dir)
    return {'brief':b/(day+'.md'), 'candidate':b.parent/'候选'/(day+'.json'), 'index':b.parent/'文章索引.md'}

def completion_valid(day, brief_dir):
    try:
        r=json.loads((Path(brief_dir)/(day+'.complete.json')).read_text(encoding='utf-8'))
        stamp=datetime.datetime.fromisoformat(r['completed_at'])
        return (r.get('schema_version')==1 and r.get('date')==day and r.get('status')=='completed'
                and stamp.tzinfo is not None and stamp<=datetime.datetime.now(datetime.timezone.utc)
                and all(r['hashes'][k]==sha(p) for k,p in completion_files(day,brief_dir).items()))
    except (OSError,ValueError,KeyError,TypeError):
        return False

def record_completion(day, brief_dir=BRIEF_DIR):
    files=completion_files(day,brief_dir)
    before={k:sha(p) for k,p in files.items()}
    txt=files['brief'].read_text(encoding='utf-8')
    if json.loads(files['candidate'].read_text(encoding='utf-8')).get('date')!=day:
        raise ValueError('候选日期与任务日期不同')
    for s in ['一','二','三','四','五','六']:
        if not re.search(r'^## '+s+'、',txt,re.M): raise ValueError('简报缺章节：'+s)
    count=re.search(r'收录\s*(\d+)\s*篇',txt)
    added=re.search(r'已追加索引\s*(\d+)\s*条',txt)
    rows=[]
    for line in files['index'].read_text(encoding='utf-8').splitlines():
        if day not in line or not line.startswith('|'): continue
        cells=[x.strip() for x in re.split(r'(?<!\\)\|',line)[1:-1]]
        if not cells or cells[0]!=day or len(cells)!=6: raise ValueError('当日索引表格结构错误')
        rows.append(cells)
    if not count or not added or int(count[1])!=int(added[1]) or int(count[1])!=len(rows):
        raise ValueError('简报收录/末尾追加/当日索引数量不一致')
    if len({(c[2],c[3]) for c in rows})!=len(rows): raise ValueError('当日索引重复')
    if before!={k:sha(p) for k,p in files.items()}: raise ValueError('完成证明写入前源文件漂移')
    # 内容日期与实际完成时刻分别记录，回补不能倒填历史完成时间。
    stamp=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    receipt={'schema_version':1,'date':day,'status':'completed','completed_at':stamp.isoformat(), 'hashes':before,'index_count':len(rows)}
    target=Path(brief_dir)/(day+'.complete.json')
    tmp=target.with_name(target.name+f'.{os.getpid()}.tmp')
    try:
        tmp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(tmp,target)
    finally:
        if tmp.exists(): tmp.unlink()
    return receipt

def build_materials(day, brief_dir=BRIEF_DIR, ops=OPS):
    brief_dir, ops = Path(brief_dir), Path(ops)
    bp = brief_dir/(day+'.md')
    cp = brief_dir.parent/'候选'/(day+'.json')
    out = [f'【一日一报 · 预备材料】任务日期={day}',
           '◆ 选题前重新运行本脚本并重读当天完成证明；注入时快照不代表选题时现状。']
    if bp.exists():
        txt = bp.read_text(encoding='utf-8')
        keep, section = [], None
        for line in txt.splitlines():
            if line.startswith('## '): section = line[3:4]
            if section in ('一','三','四','五'): keep.append(line)
        label='今日完成简报：' if completion_valid(day,brief_dir) else '简报文件存在，未验证完成：'
        out += [f'◆ {label}{bp}；实际源日期={day}；hash={sha(bp)}', '\n'.join(keep)]
    else:
        out.append(f'◆ 当天简报不存在：{bp}')
    out.append(f'◆ 当日候选第一兜底：{cp}（存在={cp.is_file()}）；候选不可用后再web；旧简报仅作背景，不能称当天来源。')
    led = ops/'台账'/'已发.md'
    text = led.read_text(encoding='utf-8') if led.exists() else ''
    out += ['◆ 近10条草稿入箱记录（非公开发表记录）：']+[l for l in text.splitlines() if l.startswith('- ')][-10:]
    out.append('◆ 推送须先执行daily_publish.py --check-only，附当前文章hash/标题/摘要绑定的真实人工或独立上下文复核回执；机械词表不证明法律通过。')
    return '\n'.join(out)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--date',default=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().isoformat())
    ap.add_argument('--brief-dir',default=BRIEF_DIR)
    ap.add_argument('--ops',default=OPS)
    ap.add_argument('--record-completion',action='store_true',help='核对简报六节、候选日期、索引数量后写本地完成证明；不是法律内容验收')
    a=ap.parse_args()
    try:
        datetime.date.fromisoformat(a.date)
        if a.record_completion: record_completion(a.date,a.brief_dir)
        print(build_materials(a.date,a.brief_dir,a.ops))
        return 0
    except (OSError,ValueError) as e:
        print('预备材料读取失败，未完成：'+str(e)); return 2
if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
