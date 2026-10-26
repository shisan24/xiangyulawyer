# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""把增量框架版公开稿落入 repo（不触碰源目录）。"""
import json
import os
import shutil
import filecmp

d = json.load(open('reports/delta-20261026.json', encoding='utf-8'))
STAGE = 'staging/staging-public-20261026/skills'
REPO = os.path.join('repo', 'skills')
copied = []
for n in d['added'] + d['changed']:
    slug = n.split('/')[-1]
    src = os.path.join(STAGE, slug, 'SKILL.md')
    dst_dir = os.path.join(REPO, slug)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, 'SKILL.md')
    shutil.copyfile(src, dst)
    copied.append((slug, os.path.getsize(dst)))

removed = []
for slug in d['orphan']:
    p = os.path.join(REPO, slug)
    if os.path.isdir(p):
        shutil.rmtree(p)
        removed.append(slug)

print('复制', len(copied), '个 SKILL.md；删除目录', removed)
for slug, sz in copied[:5]:
    print('  ', slug, sz)
