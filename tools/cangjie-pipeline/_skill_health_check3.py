# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""技能体检 v3.3（每周审计复检版）：references/scripts/templates/assets 四类引用 + frontmatter + description 长度
沿革：
- v3：四类引用 + frontmatter + desc 长度（本机每周审计脚本）
- v3.3（2026-09-28）：与 devops/skill-health-repair/scripts/skill_health_check.py 对齐——
  新增 frontmatter YAML 语法、块标量 desc（>- / |-）解析、desc 过短（≤15 字）、正文日志痕迹检测；
  误报排除扩展：website/ 源码路径、单字符占位引用（如 references/X.md 行文占位）。
输出：=== 复检（v3.3 四类引用+frontmatter+desc）: N 个问题 === + 逐条问题行。
"""
import os, re, sys
sys.stdout.reconfigure(encoding="utf-8")
try:
    import yaml
except ImportError:
    yaml = None

SKILLS_ROOT = r"[本地路径]"


def _embedded_plugin_source(directory, skills_root):
    """Return traceable host/container evidence for one exact embedded root.

    Only <host>/plugins/<vendor>/skills/<resource>/SKILL.md is accepted. Each
    segment is contiguous, <host> is an existing ancestor skill, and the resource
    is a single directory. Category roots merely named plugins are not hosts.
    This establishes local containment, not plugin registration or enablement.
    A package manifest is extra provenance when present; simple bundled fixtures
    and packages without a manifest remain identifiable by their host/container.
    """
    parts = os.path.relpath(directory, skills_root).replace('\\', '/').split('/')
    if '..' in parts:
        return None
    for index, part in enumerate(parts):
        if (part != 'plugins' or index == 0 or len(parts) != index + 4
                or parts[index + 2] != 'skills'):
            continue
        host = os.path.join(skills_root, *parts[:index], 'SKILL.md')
        if not os.path.isfile(host):
            continue
        plugin = os.path.join(skills_root, *parts[:index + 2])
        manifests = [os.path.join(plugin, marker, 'plugin.json')
                     for marker in ('.claude-plugin', '.codex-plugin')]
        return {'host_skill': host, 'plugin_container': plugin,
                'resource_skill': os.path.join(directory, 'SKILL.md'),
                'manifests': [p for p in manifests if os.path.isfile(p)],
                'evidence': 'existing host ancestor + contiguous plugin resource path'}
    return None


def _optional_mount(text, dirname, ref, occurrence):
    """Exempt only this occurrence's positive existence gate or legal fallback.

    Assertions and missing-file exceptions are requirements, not optional mounts.
    A positive if with no missing-file branch skips its body when absent. A
    ternary must test this path/variable and its fallback must not use the missing
    input. Markdown links are handled separately and never receive this waiver.
    """
    import ast
    start = text.rfind('\n', 0, occurrence.start()) + 1
    end = text.find('\n', occurrence.end())
    if end == -1:
        end = len(text)
    line = text[start:end]
    before = line[:occurrence.start() - start]
    after = line[occurrence.end() - start:]
    following = text[end + 1:].split('\n') if end < len(text) else []
    # Only the immediately following statement or the current guard's indented
    # suite/else is considered. Never let a distant guard excuse this occurrence.
    block = [line]
    if re.match(r'^\s*if\b', line):
        for next_line in following:
            if next_line.startswith((' ', '\t')) or re.match(r'^\s*else\s*:', next_line):
                block.append(next_line)
            else:
                break
    snippet = '\n'.join(block)
    if re.search(r'\b(?:assert|raise)\b|必需|必须|required', snippet, re.I):
        return False
    path = dirname + '/' + ref

    def uses(node, variable=None):
        return any((isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and n.value.removeprefix('./') == path)
                   or (variable is not None and isinstance(n, ast.Name) and n.id == variable)
                   for n in ast.walk(node))

    def exists_test(node, variable=None):
        if not isinstance(node, ast.Call):
            return False
        if isinstance(node.func, ast.Attribute) and node.func.attr == 'exists':
            return not node.args and uses(node.func.value, variable)
        return isinstance(node.func, ast.Name) and node.func.id == 'exists' and uses(node, variable)

    # Literal ternary: the exact tested path occurs in the guarded body/test;
    # the alternative must not depend on the same absent path.
    try:
        parsed = ast.parse(snippet)
    except SyntaxError:
        parsed = None
    if parsed:
        for n in ast.walk(parsed):
            if isinstance(n, ast.IfExp) and exists_test(n.test) and uses(n.body) and not uses(n.orelse):
                return True
            if isinstance(n, ast.If) and exists_test(n.test) and not n.orelse:
                return True

    # Path assigned here, immediately next statement selects this variable.
    assignment = re.search(r'\b([A-Za-z_]\w*)\s*=\s*Path\(\s*[\'\"]' + r'(?:\./)?$', before)
    if assignment and re.match(r'[\'\"]\)\s*$', after) and following:
        variable = assignment.group(1)
        try:
            next_tree = ast.parse(following[0])
        except SyntaxError:
            next_tree = None
        if next_tree and not any(isinstance(n, (ast.Assert, ast.Raise)) for n in ast.walk(next_tree)):
            for n in ast.walk(next_tree):
                if (isinstance(n, ast.IfExp) and exists_test(n.test, variable)
                        and uses(n.body, variable) and not uses(n.orelse, variable)):
                    return True

    # Legacy prose guards are explicit positive "if path exists" statements.
    # Their absent case skips usage; no bare exists(), assert, or negative guard
    # is accepted. The Path spelling with a prose action shares that semantics.
    escaped = re.escape(path)
    positive = (rf'^\s*if\s+(?:\./)?{escaped}\s+exists\s*(?::[^;]*)?\s*$',
                rf'^\s*if\s+Path\(\s*[\'\"]{escaped}[\'\"]\s*\)\.exists\(\)\s*:[^;]*$')
    # 行文里的正向前置守卫（2026-10-13 父级补）：``If `./templates/x.pptx` exists, 载入``
    # 同样是“缺失即跳过”的可选挂载：大小写不敏感，容忍反引号与 ./ 前缀。
    prose = rf'^\s*if\s+[`]?(?:\./)?{escaped}[`]?\s+exists\b[^\n]*$'
    return (any(re.fullmatch(p, line, re.I) for p in positive)
            or bool(re.fullmatch(prose, line, re.I)))


def _markdown_targets(text):
    """Yield whole inline links, not display-name path fragments.

    Parentheses within a destination are balanced; angle destinations may contain
    spaces. Optional titles are outside the destination and never asset names.
    Spans retain source offsets so masking a link cannot affect nearby bare paths.
    """
    for opening in re.finditer(r'!?\[[^\]\n]*\]\(', text):
        start = opening.end()
        pos = start
        depth = 1
        angle = False
        quote = None
        escaped = False
        while pos < len(text) and text[pos] != '\n':
            ch = text[pos]
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif quote:
                if ch == quote:
                    quote = None
            elif angle:
                if ch == '>':
                    angle = False
            elif ch == '<' and not text[start:pos].strip():
                angle = True
            elif ch in ('"', "'") and pos > start and text[pos - 1].isspace():
                quote = ch
            elif ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    raw = text[start:pos].strip()
                    if raw.startswith('<') and '>' in raw:
                        target = raw[1:raw.index('>')]
                    else:
                        target = re.split(r'\s', raw, maxsplit=1)[0]
                    target = re.sub(r'\\([()\[\]\\ ])', r'\1', target)
                    yield opening.start(), pos + 1, target
                    break
            pos += 1


def _markdown_issues(text, rel, name):
    """Check the exact destination, then mask both target and display name.

    A missing ../owner directory remains missing even if this skill contains an
    identically named asset. No owner registry or host-script fallback can replace
    an explicitly written destination. A fragment names a section, not a file;
    this asset checker validates its file component, not section existence.
    """
    from urllib.parse import unquote, urlsplit
    issues = []
    masked = list(text)
    code_spans = [(m.start(), m.end()) for m in re.finditer(r'`[^`\n]*`', text)]
    for start, end, target in _markdown_targets(text):
        for pos in range(start, end):
            if masked[pos] != '\n':
                masked[pos] = ' '
        if not target or target.startswith('#'):
            continue
        if urlsplit(target).scheme or target.startswith('//'):
            continue
        path = unquote(target.split('#', 1)[0])
        if not path or any(ch in path for ch in '<>{}'):
            continue
        # Paths explicitly belonging to a source checkout are not skill assets.
        if re.match(r'(?:\./)?(?:apps|packages|src|node_modules|examples|docs|website)/', path):
            continue
        kind = re.search(r'(?:^|/)(references|scripts|templates|assets)/', path)
        dirname = kind.group(1) if kind else 'link'
        # 只报能确认为目录限定资产路径的链接目标。裸标识符、URL 变量名或中文
        # 占位（如 (check_all_link)、(URL)、(链接)）不是技能资产，按行文示例处理；
        # 行内代码里的 markdown 语法示例同理，属于被说明的写法而非引用承诺。
        if dirname == 'link' and '/' not in path:
            continue
        if any(s <= start and end <= e for s, e in code_spans):
            continue
        if not os.path.exists(os.path.join(rel, path)):
            issues.append(f'[broken-{dirname}] {name} → {path}')
    return issues, ''.join(masked)


def _owner_skill(text, match, skill_dirs, name):
    """行文指名了哪个技能拥有这个引用：先取**最靠近**引用的前文技能名，再退到其后一小段。

    2026-10-13：旧实现按阅读顺序取第一个出现的技能名，常被更早提到的另一个技能抢先截获
    （实测「跑 de-ai-format-gate 的 scripts/x.py」被 pdf 技能名命中），真实存在的跨技能
    引用于是被误报为断链。
    """
    # 所属关系只能来自该引用的完整路径或同句明确归属，不能猜最近出现的技能名。
    # 前一句谈到别的技能、后一句碰巧有同名资产，都不证明当前必需链接有效。
    line = text[text.rfind('\n', 0, match.start()) + 1:match.start()]
    # 链接显示名中的 references 路径按该链接的真实 target 解析，而不是显示名。
    for link in re.finditer(r"\[[^\]\n]*\]\(([^)\n]+)\)", text):
        if link.start() <= match.start() < link.end():
            path_owner = re.search(r"(?:^|/)([A-Za-z][A-Za-z0-9_\-]+)/(?:references|scripts|templates|assets)/", link.group(1))
            if path_owner and path_owner.group(1) in skill_dirs:
                return skill_dirs[path_owner.group(1)]
    clean_line = line.replace('`', '')
    line_end = text.find('\n', match.end())
    after = text[match.end():line_end if line_end != -1 else len(text)]
    patterns = [r"([A-Za-z][A-Za-z0-9_\-]+)/$",
                r"(?:见|位于|in)\s+([A-Za-z][A-Za-z0-9_\-]+)\s*$",
                r"([A-Za-z][A-Za-z0-9_\-]+)\s*(?:技能)?\s*的\s*(?:\[|\[[^\]]*\]\()?$",
                r"([A-Za-z][A-Za-z0-9_\-]+)\s+技能\s*$",
                r"([A-Za-z][A-Za-z0-9_\-]+)\s*「[^」\n]*」节\s*$",
                r"([A-Za-z][A-Za-z0-9_\-]+)（其[^）。\n]{0,60}与\s*$"]
    for pattern in patterns:
        owner = re.search(pattern, clean_line)
        if owner and owner.group(1) != name:
            return skill_dirs.get(owner.group(1)) or os.path.join(os.path.dirname(skill_dirs[name]), owner.group(1))
    owner = re.match(r"[`\s]*(?:（|\()\s*(?:位于|in)\s+([A-Za-z][A-Za-z0-9_\-]+)", after)
    if owner and owner.group(1) != name:
        return skill_dirs.get(owner.group(1)) or os.path.join(os.path.dirname(skill_dirs[name]), owner.group(1))
    return None


issues = []
skill_dirs = {}
for root, dirs, files in os.walk(SKILLS_ROOT):
    # 归档副本与 references/ 下的示例文件均不作为活动技能参与体检（2026-09-28 对齐）
    dirs[:] = [d for d in dirs if d != ".archive" and d.casefold() != "references"]
    parts = os.path.relpath(root, SKILLS_ROOT).replace('\\', '/').split('/')
    if _embedded_plugin_source(root, SKILLS_ROOT):
        dirs[:] = []; continue
    if "SKILL.md" in files:
        skill_dirs[os.path.relpath(root, SKILLS_ROOT).replace("\\", "/").split("/")[-1]] = root

for rel in sorted(set(skill_dirs.values())):
    name = os.path.basename(rel)
    md = os.path.join(rel, "SKILL.md")
    try:
        with open(md, encoding="utf-8") as source:
            t = source.read()
    except Exception as e:
        issues.append(f"[读取失败] {name}: {e}")
        continue
    # frontmatter
    fm = re.match(r"^---\n(.*?)\n---", t, re.S)
    if not fm:
        issues.append(f"[无frontmatter] {name}")
        continue
    fmtext = fm.group(1)
    if yaml is not None:
        try:
            parsed_fm = yaml.safe_load(fmtext)
            if not isinstance(parsed_fm, dict):
                issues.append(f"[frontmatter-yaml] {name}: not a mapping")
        except Exception as e:
            issues.append(f"[frontmatter-yaml] {name}: {type(e).__name__}")
    if not re.search(r"^name:\s*\S+", fmtext, re.M):
        issues.append(f"[缺name] {name}")
    # 解析单行与 YAML block scalar 描述，避免 description: >- / |- 被低估
    desc = None
    fm_lines = fmtext.splitlines()
    for idx, line in enumerate(fm_lines):
        dm = re.match(r"^description:\s*(.*)$", line)
        if not dm:
            continue
        raw_desc = dm.group(1).strip()
        if raw_desc.startswith(("|", ">")):
            block = []
            for block_line in fm_lines[idx + 1:]:
                if block_line and not block_line[0].isspace():
                    break
                block.append(block_line.strip())
            desc = (" ".join(block) if raw_desc.startswith(">") else "\\n".join(block)).strip()
        else:
            desc = raw_desc.strip('"').strip("'")
        break
    if desc is None:
        issues.append(f"[缺description] {name}")
    else:
        dlen = len(desc)
        if dlen <= 15:
            issues.append(f"[desc过短] {name} ({dlen}字)")
        if dlen > 60:
            issues.append(f"[desc超60] {name} ({dlen}字)")
    # 正文日志痕迹（只认真实日志形态，避免示例串自指误报）
    log_hits = re.findall(r"本 session（\d{4}|cron 复核）|本 job：上轮 \d", t)
    if len(log_hits) >= 3:
        issues.append(f"[正文日志痕迹] {name}: {len(log_hits)} 处——正文混入运行日志，剥离到 references/ 并给写者加写盘边界")
    # 四类引用检查（跨技能感知：前 120 字找 位于X/见X；排除源码路径与占位形引用）
    link_issues, t = _markdown_issues(t, rel, name)
    issues.extend(link_issues)
    for dirname in ["references", "scripts", "templates", "assets"]:
        for m in re.finditer(rf"{dirname}/((?:[A-Za-z0-9_\-\.%\u4e00-\u9fff]+/)*[A-Za-z0-9_\-\u4e00-\u9fff\.%]+\.(?:md|py|ps1|bat|sh|cmd|json|js|yaml|yml|txt|docx|xlsx|html|css|png|jpg|svg|pptx|zip))", t):
            ref = m.group(1)
            # 排除 .template 后缀模板引用（templates/SKILL.md.template 本体是 .template）
            if t[m.end():m.end()+10].startswith(".template"):
                continue
            # 排除单字符占位引用（行文示例，如 references/X.md；2026-09-28）
            if len(os.path.splitext(ref)[0]) <= 1:
                continue
            # 排除带存在性判定的可选挂载路径（if ... exists / .exists()）：运行时开关，非缺失资产。
            # 判定细则见 _optional_mount（按引用名、只看所在行；2026-10-13 修正）。
            if _optional_mount(t, dirname, ref, m):
                continue
            # 排除写法示例，不是本技能资产（2026-10-13）：① 路径里带 <技能目录>／{name} 占位符；
            # ② 紧跟「如／例如／比如／譬如／e.g.」的路径是举例行文。
            _prefix = re.findall(r"[A-Za-z0-9_\-./\\<>{}\u4e00-\u9fff]*$", t[:m.start()])[0]
            if any(ch in _prefix for ch in "<>{}"):
                continue
            if re.search(r"(?:如|例如|比如|譬如|e\.g\.)\s*[`\[]?$", t[max(0, m.start()-8):m.start()]):
                continue
            # 排除源码/库外路径引用（apps/、packages/、src、node_modules、examples、docs、website/ 等前缀）
            if re.search(r"(?:^|/)(?:apps|packages|src|node_modules|examples|docs|website)/", _prefix):
                continue
            # 路径变量与运行根不是技能名（2026-10-13 父级实测）：SKILL_DIR/ 指本技能根，
            # [本地路径] 与 ${HERMES_HOME} 指运行根。交给 _owner_skill 会被当成“所属技能”，
            # 把真实存在的运行期脚本判成断链（mail-scan 的 HERMES_HOME/scripts/mail/*）。
            _trim = _prefix.rstrip("/")
            if _trim.endswith(("SKILL_DIR", "HERMES_SKILL_DIR", "{baseDir}", "{SKILL_DIR}")):
                if not os.path.exists(os.path.join(rel, dirname, ref)):
                    issues.append(f"[broken-{dirname}] {name} → {dirname}/{ref}")
                continue
            if ("[本地路径]" in _prefix or _prefix.startswith("~")
                    or re.search(r"(?:\$\{?HERMES_HOME\}?|\.hermes|AppData/Local/hermes|/hermes)$", _trim)):
                _home = os.environ.get("HERMES_HOME") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes")
                if not (os.path.exists(os.path.join(rel, dirname, ref))
                        or os.path.exists(os.path.join(_home, dirname, ref))):
                    issues.append(f"[broken-{dirname}] {name} → {dirname}/{ref}")
                continue
            explicit_owner = _owner_skill(t, m, skill_dirs, name)
            if explicit_owner:
                # 先解析明确所属，不能用当前技能恰好同名的文件替代对方目标。
                if not os.path.exists(os.path.join(explicit_owner, dirname, ref)):
                    issues.append(f"[broken-{dirname}] {name} → {dirname}/{ref}")
                continue
            p = os.path.join(rel, dirname, ref)
            if not os.path.exists(p):
                # 2026-10-13 修正：不再对「别的技能里恰好有同名文件」一律豁免——那会把本技能的
                # 真实断链整批藏掉（实测：裸引用 references/guide.md 本地缺失，仅因另一技能存在
                # 同名文件就不报）。改为只在行文**指名了所属技能**时按该技能目录解析；
                # 未指名的裸引用即视为本技能资产，缺失就报。仅 scripts 另保留真实挂载点
                # HERMES_HOME/scripts 的回退。
                found = False
                owner = _owner_skill(t, m, skill_dirs, name)
                if owner:
                    found = os.path.exists(os.path.join(owner, dirname, ref))
                if not found and not owner and dirname == "scripts":
                    hermes_home = os.environ.get("HERMES_HOME") or os.path.dirname(SKILLS_ROOT)
                    found = os.path.exists(os.path.join(hermes_home, dirname, ref))
                if not found:
                    issues.append(f"[broken-{dirname}] {name} → {dirname}/{ref}")

_seen = set(); _unique = []
for _i in issues:
    if _i in _seen:
        continue
    _seen.add(_i); _unique.append(_i)
issues = _unique
print(f"=== 复检（v3.3 四类引用+frontmatter+desc）: {len(issues)} 个问题 ===")
for i in issues:
    print(" ", i)
print("DONE")
