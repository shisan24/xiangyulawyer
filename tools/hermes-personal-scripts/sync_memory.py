# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
import shutil, sys, os

src = r"[本地路径]"  # 2026-08-03: 实际位置（%LOCALAPPDATA% 下不存在）
# 2026-08-03: 取消第三方同步盘同步，原 dst(承办人/本机目录) 已删，改为本机备份副本
dst = r"[本地路径]"

try:
    if not os.path.exists(src):
        print(f"ERROR: source not found: {src}")
        sys.exit(1)
    
    shutil.copy2(src, dst)
    src_size = os.path.getsize(src)
    dst_size = os.path.getsize(dst)
    
    if dst_size == src_size:
        print(f"OK: synced {dst_size} bytes")
        sys.exit(0)
    else:
        print(f"WARNING: size mismatch src={src_size} dst={dst_size}")
        sys.exit(1)
except PermissionError:
    # Nutstore cloud FS might block - try via cmd copy as fallback
    import subprocess as _sp
    r = _sp.run(['cmd', '/c', 'copy', '/Y', src, dst], capture_output=True,
                creationflags=0x08000000 if os.name == "nt" else 0)
    if r.returncode == 0:
        print(f"OK: synced via cmd copy")
    else:
        print(f"ERROR: {r.stderr.decode('gbk', errors='ignore')}")
        sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
