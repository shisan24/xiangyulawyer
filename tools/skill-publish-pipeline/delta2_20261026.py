# -*- coding: utf-8 -*-
"""比对框架版公开稿与 repo 现有件，输出真实增量（忽略水印行与 CRLF）。"""
import json
import os

STAGE = 'staging/staging-public-20261026/skills'
REPO = os.path.join('repo', 'skills')
units = json.load(open('reports/units-publishable-20261026.json', encoding='utf-8'))


def norm(t):
    out = []
    for ln in t.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        if '© 2026 xiangyulawyer' in ln or 'github.com/shisan24/xiangyulawyer' in ln:
            continue
        out.append(ln.rstrip())
    return '\n'.join(out).strip()


added, changed, same, nostage = [], [], [], []
for u in units:
    name = u['name']
    slug = name.split('/')[-1]
    sp = os.path.join(STAGE, slug, 'SKILL.md')
    rp = os.path.join(REPO, slug, 'SKILL.md')
    if not os.path.isfile(sp):
        nostage.append(name)
        continue
    s = norm(open(sp, encoding='utf-8-sig').read())
    if not os.path.isfile(rp):
        added.append(name)
        continue
    r = norm(open(rp, encoding='utf-8-sig').read())
    if s == r:
        same.append(name)
    else:
        changed.append(name)

repo_skills = sorted(d for d in os.listdir(REPO) if os.path.isdir(os.path.join(REPO, d)))
names = {u['name'].split('/')[-1] for u in units}
orphan = [d for d in repo_skills if d not in names]

print('可发布单元:', len(units), 'repo 技能目录:', len(repo_skills))
print('新增:', added)
print('变化:', len(changed))
for x in changed:
    print('  ~', x)
print('无变化:', len(same))
print('无框架稿:', nostage)
print('repo 内多余:', orphan)
json.dump({'added': added, 'changed': changed, 'same': same, 'nostage': nostage, 'orphan': orphan},
          open('reports/delta-20261026.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
