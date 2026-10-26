# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
import json, os, hashlib, time, datetime

BASE_TS = time.mktime(time.strptime('2026-10-20 17:16:11', '%Y-%m-%d %H:%M:%S'))
SEP = chr(92)  # backslash


def unit_files(p):
    out = []
    for r, ds, fs in os.walk(p):
        ds[:] = [d for d in ds if d not in ('__pycache__', '.git')]
        for f in fs:
            if f.endswith(('.bak', '.pyc')):
                continue
            fp_ = os.path.join(r, f)
            if os.path.getsize(fp_) == 0:
                continue
            out.append(fp_)
    return out


def fp(p):
    h = hashlib.sha256()
    n = 0
    mx = 0
    for fp_ in sorted(unit_files(p)):
        rel = os.path.relpath(fp_, p).replace(SEP, '/')
        b = open(fp_, 'rb').read()
        h.update(rel.encode())
        h.update(str(len(b)).encode())
        h.update(hashlib.sha256(b).digest())
        n += 1
        mx = max(mx, os.path.getmtime(fp_))
    return h.hexdigest()[:16], n, mx


res = []
for namejson in ['reports/units-publishable.json', 'reports/tools-units-src.json']:
    for u in json.load(open(namejson, encoding='utf-8')):
        p = u['path']
        if not os.path.isdir(p):
            res.append({'group': namejson, 'name': u['name'], 'fp': None, 'files': 0, 'mtime': '', 'changed': 'MISSING'})
            continue
        f, n, mx = fp(p)
        res.append({'group': namejson, 'name': u['name'], 'fp': f, 'files': n,
                    'mtime': datetime.datetime.fromtimestamp(mx).strftime('%m-%d %H:%M') if mx else '',
                    'changed': mx > BASE_TS})

for namejson in ['reports/units-publishable.json', 'reports/tools-units-src.json']:
    ch = [r for r in res if r['group'] == namejson and r['changed'] is True]
    print('==', namejson, 'total', len([r for r in res if r['group'] == namejson]), 'changed', len(ch))
    for r in ch:
        print('   ', r['name'], 'files', r['files'], 'mtime', r['mtime'], 'fp', r['fp'])
print('missing:', [r['name'] for r in res if r['changed'] == 'MISSING'])
json.dump(res, open('reports/units-fingerprint-20261026.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
