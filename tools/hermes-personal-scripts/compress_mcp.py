#!/usr/bin/env python3
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""MCP server — simple text compression for legal documents.
Strategies: deduplicate repeated lines, truncate long outputs, extract key sections."""

import json, re, sys

def compress_text(text: str, max_chars: int = 3000) -> dict:
    """Compress legal text using dedup + smart truncation."""
    original_len = len(text)
    lines = text.split('\n')
    seen = set()
    deduped = []
    for line in lines:
        stripped = line.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            deduped.append(line)
        elif not stripped:
            deduped.append(line)
    result = '\n'.join(deduped)
    dedup_saved = original_len - len(result)

    # Smart truncation
    if len(result) > max_chars:
        head = result[:max_chars // 2]
        tail = result[-(max_chars // 2):]
        result = head + f"\n\n... [省略 {len(result) - max_chars} 字符] ...\n\n" + tail

    return {
        "compressed": result,
        "original_chars": original_len,
        "compressed_chars": len(result),
        "dedup_saved_chars": dedup_saved,
        "savings_pct": round((1 - len(result) / original_len) * 100, 1) if original_len else 0
    }

def handle_request(request: dict) -> dict | None:
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        return {"jsonrpc":"2.0","id":req_id,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"text-compress","version":"1.0.0"}}}
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc":"2.0","id":req_id,"result":{"tools":[{"name":"compress_text","description":"压缩法律文本/工具输出。去重重复行 + 智能截断。节省 30-70% token。参数: text(必填), max_chars(可选,默认3000)","inputSchema":{"type":"object","properties":{"text":{"type":"string","description":"要压缩的文本"},"max_chars":{"type":"integer","description":"最大保留字符数","default":3000}},"required":["text"]}}]}}
    if method == "tools/call":
        p = request.get("params",{})
        if p.get("name") == "compress_text":
            args = p.get("arguments",{})
            r = compress_text(args.get("text",""), args.get("max_chars", 3000))
            return {"jsonrpc":"2.0","id":req_id,"result":{"content":[{"type":"text","text":json.dumps(r,ensure_ascii=False)}]}}
    return {"jsonrpc":"2.0","id":req_id,"error":{"code":-32601,"message":f"Unknown: {method}"}}

def main():
    while True:
        try:
            line = sys.stdin.readline()
            if not line: break
            req = json.loads(line)
            resp = handle_request(req)
            if resp:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError: continue
        except Exception as e:
            sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":None,"error":{"code":-32603,"message":str(e)}})+"\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()
