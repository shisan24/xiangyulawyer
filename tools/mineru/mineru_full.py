# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名

import subprocess, os, sys

env = {**os.environ, 'HOME': '[本地路径]', 'MINERU_MODEL_SOURCE': 'modelscope'}
log = open(r"[本地路径]", 'w', encoding='utf-8')

# Step 1: Parse 案卷名称
log.write("=== 案卷名称.pdf ===\n")
r = subprocess.run([
    r"[本地路径]",
    '-p', r'[本地路径]',
    '-o', r'[本地路径]',
    '-b', 'pipeline', '-m', 'ocr', '-l', 'ch'
], capture_output=True, text=True, timeout=600, env=env)
log.write(f"exit={r.returncode}\n{r.stdout[-2000:]}\n{r.stderr[-1000:]}\n")

# Step 2: Parse 客户单位诉讼文件
log.write("\n=== 案卷名称-客户单位.pdf ===\n")
r2 = subprocess.run([
    r"[本地路径]",
    '-p', r'[本地路径]',
    '-o', r'[本地路径]',
    '-b', 'pipeline', '-m', 'ocr', '-l', 'ch'
], capture_output=True, text=True, timeout=600, env=env)
log.write(f"exit={r2.returncode}\n{r2.stdout[-2000:]}\n{r2.stderr[-1000:]}\n")

log.write("\n=== DONE ===\n")
log.close()
