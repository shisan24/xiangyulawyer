#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
Prompt 模板加载器 — 从 [本地路径] 加载可复用 prompt 模板。
Skills 可引用模板而非内联 prompt。

用法:
    from prompt_loader import load_template
    prompt = load_template("legal-opinion-header", firm="【律所】", client="【主体】")
"""

import os, re
from pathlib import Path

TEMPLATES_DIR = Path.home() / ".hermes" / "templates"

def load_template(name: str, **variables) -> str:
    """Load a template and substitute variables.
    
    Templates use {{variable}} syntax.
    """
    path = TEMPLATES_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {name} (looked in {path})")
    
    content = path.read_text(encoding='utf-8')
    
    # Substitute {{var}} placeholders
    for key, value in variables.items():
        content = content.replace(f"{{{{{key}}}}}", str(value))
    
    # Warn about unresolved placeholders
    unresolved = re.findall(r'\{\{(\w+)\}\}', content)
    if unresolved:
        print(f"⚠️  Unresolved placeholders in '{name}': {unresolved}", file=__import__('sys').stderr)
    
    return content


def list_templates() -> list[str]:
    """List available template names."""
    return [p.stem for p in TEMPLATES_DIR.glob("*.md")]


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        name = sys.argv[1]
        kwargs = {}
        for arg in sys.argv[2:]:
            if '=' in arg:
                k, v = arg.split('=', 1)
                kwargs[k] = v
        print(load_template(name, **kwargs))
    else:
        print("Available templates:")
        for t in list_templates():
            print(f"  {t}")
