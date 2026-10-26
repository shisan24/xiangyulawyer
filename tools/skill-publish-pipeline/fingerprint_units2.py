# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
import json, os, time, datetime

BASE_TS = time.mktime(time.strptime('2026-10-20 17:16:11', '%Y-%m-%d %H:%M:%S'))

res = []
for namejson in ['reports/units-publishable.json', 'reports/tools-units-src.json']:
    for u in json.load(open(namejson, encoding='utf-8')):
        p = u['path']
        if not os.path.isdir(p):
            res.append({'group': namejson, 'name': u['name'], 'files': 0, 'mtime': '', 'changed': 'MISSING'})
            continue
        n = 0
        mx = 0
        big = 0
        for r, ds, fs in os.walk(p):
            ds[:] = [d for d in ds if d not in ('__pycache__', '.git')]
            for f in fs:
                if f.endswith(('.bak', '.pyc')):
                    continue
                fp_ = os.path.join(r, f)
                try:
                    st = os.stat(fp_)
                except OSError:
                    continue
                n += 1
                mx = max(mx, st.st_mtime)
                if st.st_size > 5_000_000:
                    big += 1
        res.append({'group': namejson, 'name': u['name'], 'files': n, 'big': big,
                    'mtime': datetime.datetime.fromtimestamp(mx).strftime('%m-%d %H:%M') if mx else '',
                    'changed': mx > BASE_TS})

for namejson in ['reports/units-publishable.json', 'reports/tools-units-src.json']:
    ch = [r for r in res if r['group'] == namejson and r['changed'] is True]
    print('==', namejson, 'total', len([r for r in res if r['group'] == namejson]), 'changed', len(ch))
    for r in ch:
        print('   ', r['name'], 'files', r['files'], 'big', r['big'], 'mtime', r['mtime'])
print('missing:', [r['name'] for r in res if r['changed'] == 'MISSING'])
json.dump(res, open('reports/units-fingerprint-20261026.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
