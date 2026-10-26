# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""产物冻结与指纹复核（同一脚本写、同一脚本验，指纹可被任何人独立复现）。

用法:
  python freeze.py write  <tree_label>=<dir> [...]   # 写 reports/frozen-manifest.json
  python freeze.py verify                            # 按清单重算并逐树比对

哈希算法（写进清单，供独立复核）：
  对树内每个文件（跳过 __pycache__/.git），按「相对路径(POSIX 分隔) + '|' + 字节长度 + '|'」
  与「文件内容 sha256 的原始 32 字节」依次喂入一个累计 sha256；文件按相对路径排序。
  即：H = sha256( for f in sorted(files): f"{rel}|{len(bytes)}|".encode() + sha256(bytes).digest() )
"""
import hashlib
import json
import os
import sys

W = r"[本地路径]"
MANIFEST = os.path.join(W, "reports", "frozen-manifest.json")
SKIP = {"__pycache__", ".git"}


def fp(root):
    h = hashlib.sha256()
    n = 0
    rels = []
    for r, dirs, fs in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for f in fs:
            p = os.path.join(r, f)
            rels.append((os.path.relpath(p, root).replace("\\", "/"), p))
    for rel, p in sorted(rels):
        b = open(p, "rb").read()
        h.update(f"{rel}|{len(b)}|".encode())
        h.update(hashlib.sha256(b).digest())
        n += 1
    return {"files": n, "sha256": h.hexdigest()}


def parse_trees(args):
    out = {}
    for a in args:
        label, _, d = a.partition("=")
        out[label] = d
    return out


def main():
    mode = sys.argv[1]
    if mode == "write":
        trees = parse_trees(sys.argv[2:])
        man = {"frozen_at": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
               "algorithm": "sha256 over sorted rel|len| + sha256(content) per file (see docstring)",
               "trees": {k: dict(v, path=v) for k, v in ((k, fp(p)) for k, p in trees.items())}}
        for k, p in trees.items():
            man["trees"][k]["path"] = p
        json.dump(man, open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(json.dumps(man, ensure_ascii=False, indent=1))
    elif mode == "verify":
        man = json.load(open(MANIFEST, encoding="utf-8"))
        ok = True
        for label, rec in man["trees"].items():
            cur = fp(rec["path"])
            same = (cur["files"] == rec["files"] and cur["sha256"] == rec["sha256"])
            ok = ok and same
            print(f"{label}: {'一致' if same else '不一致'}  清单={rec['files']}/{rec['sha256'][:16]}"
                  f"  实算={cur['files']}/{cur['sha256'][:16]}")
        print("冻结态核验:", "通过" if ok else "不通过")
        sys.exit(0 if ok else 1)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
