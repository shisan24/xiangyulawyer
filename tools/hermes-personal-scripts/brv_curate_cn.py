#!/usr/bin/env python
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""jieba-enhanced ByteRover curate — 中文分词后 curate，提升 BM25 检索精度"""
import subprocess, sys, json, re, os
import jieba

# 法律术语词典
LEGAL_TERMS = []  # 名单类数据（主体/当事人/律所/本机标识/地域）在本机维护，不入公开版
for t in LEGAL_TERMS:
    jieba.add_word(t)

def tokenize(text: str) -> str:
    """中文 jieba 分词，英文/数字原样保留"""
    # 分离中英文块
    parts = re.split(r'([\u4e00-\u9fff]+)', text)
    result = []
    for p in parts:
        if re.match(r'[\u4e00-\u9fff]+', p):
            result.append(" ".join(jieba.cut(p)))
        else:
            result.append(p)
    return " ".join(result).strip()


def curate(text: str, timeout: int = 60) -> dict:
    """curate with jieba-tokenized text alongside original"""
    tokenized = tokenize(text)
    # 组合：原文字段 + 分词字段，BM25 双路命中
    combined = f"[zh] {text}\n[tokens] {tokenized}"
    brv_path = os.path.expandvars(r"%APPDATA%\npm\brv.cmd")
    if not os.path.exists(brv_path):
        brv_path = "brv"  # fallback to PATH
    cmd = [brv_path, "curate", combined, "--timeout", str(timeout)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
    return {"ok": r.returncode == 0, "stdout": r.stdout, "stderr": r.stderr}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # demo mode
        test = "承办人是该律所的律师，负责建设工程合同纠纷案件"
        print("原文:", test)
        print("分词:", tokenize(test))
        print("\n--- 测试 curate ---")
        r = curate(test)
        print("OK" if r["ok"] else "FAILED")
        if r["stdout"]:
            print(r["stdout"][:500])
    else:
        text = " ".join(sys.argv[1:])
        r = curate(text)
        print(r["stdout"])
        sys.exit(0 if r["ok"] else 1)
