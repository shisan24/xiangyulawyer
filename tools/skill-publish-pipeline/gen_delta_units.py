# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""生成增量单元清单（仅 added+changed），指向框架版公开稿目录，供 scan/entity/质检使用。"""
import json
import os

d = json.load(open('reports/delta-20261026.json', encoding='utf-8'))
STAGE = 'staging/staging-public-20261026/skills'
sel = d['added'] + d['changed']
units = []
for n in sel:
    slug = n.split('/')[-1]
    p = os.path.join(STAGE, slug)
    if os.path.isdir(p):
        units.append({'name': n, 'path': p.replace('/', os.sep)})
json.dump(units, open('reports/units-delta-20261026.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('增量单元', len(units))
