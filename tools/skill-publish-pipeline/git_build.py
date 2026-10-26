# -*- coding: utf-8 -*-
"""建库并逐个单元提交，分批推送。
用法: python git_build.py <repo_dir> <repo_name> <visibility> <units.json> <batch_size> <desc>
"""
import json
import os
import subprocess
import sys

NAME = "xiangyulawyer"
EMAIL = "邮箱"


def run(cmd, cwd, check=True):
    # shell=True 仅用于本机固定的 git/gh 命令串；变量全部来自本脚本枚举的技能目录名
    # （本地文件系统、无外部输入），不构成注入面。
    r = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        print("FAIL:", cmd, "\n", (r.stderr or "")[:400])
        sys.exit(1)
    return r


def main():
    repo_dir, repo_name, vis, units_file = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    batch = int(sys.argv[5])
    desc = sys.argv[6]
    units = json.load(open(units_file, encoding="utf-8"))
    run("git init -b main", repo_dir)
    run(f'git config user.name "{NAME}"', repo_dir)
    run(f'git config user.email "{EMAIL}"', repo_dir)
    run(f'git config core.quotepath false', repo_dir)
    run(f'git config core.autocrlf false', repo_dir)

    # 建远端
    r = run(f'gh repo view shisan24/{repo_name} --json name', repo_dir, check=False)
    if r.returncode != 0:
        run(f'gh repo create shisan24/{repo_name} --{vis} --description "{desc}"', repo_dir)
        print("已创建远端仓库:", repo_name)
    else:
        print("远端已存在:", repo_name)
    run(f"git remote remove origin", repo_dir, check=False)
    run(f"git remote add origin https://github.com/shisan24/{repo_name}.git", repo_dir)

    run("git add README.md 技能总览.md .gitignore", repo_dir)
    run('git commit -m "init: 库说明与技能总览"', repo_dir)

    done = 0
    for u in units:
        name = u["name"].split("/")[-1]
        rel = os.path.join("skills", name)
        if not os.path.isdir(os.path.join(repo_dir, rel)):
            continue
        run(f'git add "{rel}"', repo_dir)
        st = run('git diff --cached --name-only', repo_dir)
        if not st.stdout.strip():
            continue
        run(f'git commit -m "skill: {name}"', repo_dir)
        done += 1
        if done % batch == 0:
            run("git push -u origin main", repo_dir)
            print(f"  已推送 {done} 个技能")
    # 收尾：全量补提交并推送
    run("git add -A", repo_dir)
    st = run("git diff --cached --name-only", repo_dir)
    if st.stdout.strip():
        run('git commit -m "chore: 补齐剩余文件"', repo_dir)
    run("git push -u origin main", repo_dir)
    r = run("git log --oneline | wc -l", repo_dir)
    print(f"提交 {done} 个技能，批次 {batch}，git log 行数 {r.stdout.strip()}")


if __name__ == "__main__":
    main()
