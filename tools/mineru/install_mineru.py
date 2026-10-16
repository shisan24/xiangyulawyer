# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
import subprocess, os, sys, time

mineru_py = r"[本地路径]"
log_file = r"[本地路径]"
os.makedirs(os.path.dirname(log_file), exist_ok=True)

with open(log_file, 'w', encoding='utf-8') as log:
    log.write(f"=== MinerU Install Started {time.ctime()} ===\n")
    log.write(f"Python: {mineru_py}\n")
    
    # Set ASCII home
    env = {**os.environ, 'HOME': '[本地路径]', 'PIP_CACHE_DIR': '[本地路径]'}
    
    # Upgrade pip first
    log.write("Upgrading pip...\n")
    r = subprocess.run([mineru_py, '-m', 'pip', 'install', '--upgrade', 'pip', '-q'],
                       capture_output=True, text=True, timeout=120, env=env)
    log.write(f"pip upgrade: exit={r.returncode}\n")
    
    # Install mineru
    log.write("Installing mineru[core]...\n")
    r = subprocess.run([mineru_py, '-m', 'pip', 'install', '-U', 'mineru[core]'],
                       capture_output=True, text=True, timeout=600, env=env)
    log.write(f"mineru install: exit={r.returncode}\n")
    if r.stdout:
        log.write("STDOUT:\n" + r.stdout[-2000:] + "\n")
    if r.stderr:
        log.write("STDERR:\n" + r.stderr[-2000:] + "\n")
    
    if r.returncode == 0:
        # Verify
        r2 = subprocess.run([mineru_py, '-c', 'import magic_pdf; print("OK")'],
                           capture_output=True, text=True, timeout=30, env=env)
        log.write(f"import test: {r2.stdout.strip()}\n")
    
    log.write(f"=== Done {time.ctime()} ===\n")

print(f"Installer script: {install_script}")
print(f"Log: {log_file}")
