# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
import sys
from lawyer_ops import main
if __name__ == "__main__":
    # 只透传选项（如 --preview）；模式固定为 skills，无参调用行为不变。
    raise SystemExit(main(['skills'] + [a for a in sys.argv[1:] if a.startswith('-')]))
