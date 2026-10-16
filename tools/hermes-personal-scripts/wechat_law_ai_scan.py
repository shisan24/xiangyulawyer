# -*- coding: utf-8 -*-
# © 2026 xiangyulawyer · github.com/shisan24/xiangyulawyer · 未经许可不得转载，引用请署名
"""
公众号文章采集器（法律圈 / AI 圈 / 法律×AI / 公众号写作）
源：搜狗微信搜索 weixin.sogou.com（无需登录、无验证码，实测稳定）
流程：多关键词搜索 -> 解析 -> 跨查询去重 -> 按时间过滤 -> 排除近7天已采集 -> 抓正文 -> 落盘
输出：stdout 精简候选清单（供 agent 分析）；完整数据落 JSON

关键词表可改：见 QUERIES 与轮换池注释。实测有效词才留在表内。
"""
import re, html, json, time, random, datetime, os, glob, hashlib, sys, tempfile
from urllib.parse import urlsplit
import requests
from html.parser import HTMLParser


class _BodyParser(HTMLParser):
    """Only collect js_content; nested containers must not cut the body."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root_tag = None
        self.depth = 0
        self.closed = False
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if self.closed:
            return
        if not self.root_tag:
            if dict(attrs).get('id') != 'js_content':
                return
            self.root_tag, self.depth = tag, 1
            return
        if tag == self.root_tag:
            self.depth += 1
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag == 'br' and not self.hidden:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if not self.depth or self.closed:
            return
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1
        if tag == self.root_tag:
            self.depth -= 1
            if self.depth == 0:
                self.closed = True
        if not self.hidden and (tag in ('p', 'section', 'div') or re.fullmatch('h[1-6]', tag)):
            self.parts.append('\n')

    def handle_data(self, data):
        if self.depth and not self.hidden and not self.closed:
            self.parts.append(data)

class _PageSignals(HTMLParser):
    """Page structure, not words in an article/search summary."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.body_container = False
        self.challenge = False
        self.in_title = False
        self.title = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('div', 'section', 'article') and attrs.get('id') == 'js_content':
            self.body_container = True
        if tag == 'title': self.in_title = True
        identity = ' '.join(attrs.get(k, '') for k in ('id', 'name', 'class', 'action', 'src')).lower()
        if (tag in ('form', 'input', 'iframe') and
                re.search(r'seccode|captcha|antispider|verifycode', identity)):
            self.challenge = True
        if tag in ('div', 'section') and re.search(r'(^|\s)(?:antispider|captcha-container|verify_container)(?:\s|$)', identity):
            self.challenge = True

    def handle_endtag(self, tag):
        if tag == 'title': self.in_title = False

    def handle_data(self, value):
        if self.in_title: self.title.append(value)


def response_blocked(response):
    if response.status_code == 429:
        return True
    path = urlsplit(response.url).path.lower()
    if re.search(r'(?:^|/)(?:antispider|captcha|verifycode)(?:/|$)', path):
        return True
    signals = _PageSignals(); signals.feed(response.text)
    page_title = ''.join(signals.title).strip()
    return not signals.body_container and (signals.challenge or page_title in
        ('环境异常', '请输入验证码', '验证码', '搜狗搜索访问异常', '访问过于频繁'))


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/【IP】 Safari/537.36")

OUT_DIR = r"[本地路径]"
CACHE_DIR = os.path.join(OUT_DIR, "候选")

# (分组, 关键词) —— 实测：近3天有命中的词；无命中词留在轮换池备用
QUERIES = [
    ("法律AI", "法律 AI"),
    ("法律AI", "AI 律师"),
    ("法律AI", "人工智能 法律"),
    ("法律AI", "AI 法律 检索"),
    ("法律AI", "法律AI 应用"),
    ("法律AI", "律师 用 AI"),
    ("法律AI", "法律 AI 周报"),
    ("法律AI", "AI 律师 实务"),
    ("法律AI", "人工智能 律师 办案"),
    ("法律", "司法解释"),
    ("法律", "最高法"),
    ("法律", "典型案例"),
    ("法律", "律师 行业"),
    ("AI", "AI 智能体"),
    ("AI", "AI 大模型"),
    ("AI", "人工智能 治理"),
    ("AI", "AI 融资"),
    ("写作", "公众号 写作"),
    ("写作", "公众号 运营 选题"),
    ("写作", "公众号 标题"),
]
# 轮换池（当前召回偏旧，需要时替换上表）：法律 智能体 / 律师 AI 提效 / 法律科技 前沿 /
# AI 合规 法律 / 法律行业 AI / 写作 技巧 爆款 / AI 写作 工具 / 法律 公众号 /
# 法律 新规（弱） / 法律 热点（近14天仅1） / 法治 新闻（实测0） / 大模型 发布（实测0）
# / AI 产品（招聘招生混入多） / 人工智能 行业（产业资讯混入多）
# / AI Agent（纯拉丁词，搜狗召回不稳定：实测同词一次10条一次0条，中文同义用"AI 智能体"）

MAX_ARTICLE_FETCH = 40     # 单日最多解析链接+抓正文篇数（新增法律/AI组后由28上调）
ARTICLE_CHARS = 5000       # 每篇正文截断字数
WINDOW_DAYS = 2            # 只保留最近 N 天
DEDUP_DAYS = 7             # 与最近 N 天已采集标题去重


def session():
    s = requests.Session(); s.trust_env = False
    s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    return s


def parse(txt):
    out = []
    for b in re.split(r'<div class="txt-box">', txt)[1:]:
        b = b.split("</li>")[0]
        m = re.search(r"<h3>\s*<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", b, re.S)
        if not m:
            continue
        title = html.unescape(re.sub(r"<[^>]+>|<!--.*?-->", "", m.group(2))).strip()
        link = html.unescape(m.group(1))
        sm = re.search(r'<p class="txt-info"[^>]*>(.*?)</p>', b, re.S)
        summ = html.unescape(re.sub(r"<[^>]+>|<!--.*?-->", "", sm.group(1))).strip() if sm else ""
        acc = re.search(r'class="all-time-y2"[^>]*>([^<]*)<', b) or \
              re.search(r'class="account"[^>]*>([^<]*)<', b)
        acc = html.unescape(acc.group(1)).strip() if acc else ""
        ts = re.search(r"timeConvert\('(\d+)'\)", b)
        out.append({"title": title, "account": acc,
                    "ts": int(ts.group(1)) if ts else 0,
                    "summary": summ, "link": link})
    return out


def resolve_detail(s, link):
    """保留真实失败层级；仅有验证码/反爬页证据才标 blocked。

    HTTP 失败、临时链接失效及网络异常各自保留，不据三次普通失败推断反爬。
    不对整串 html.unescape，避免 &timestamp= 变成 ×tamp=。
    """
    if link.startswith("/link"):
        link = "https://weixin.sogou.com" + link
    detail = {'url': '', 'blocked': False, 'error_layer': 'resolve',
              'error': None, 'requested_url': link}
    try:
        r = s.get(link, timeout=25)
    except Exception as exc:
        detail['error'] = f"网络异常:{type(exc).__name__}"
        return detail
    detail.update(response_url=r.url, response_status=r.status_code,
                  response_sha256=hashlib.sha256(r.content).hexdigest(),
                  fetched_at=datetime.datetime.now().astimezone().isoformat())
    if not 200 <= r.status_code < 300:
        detail['error'] = f"HTTP {r.status_code}"
        detail['blocked'] = response_blocked(r)
        return detail
    if response_blocked(r):
        detail.update(blocked=True, error='验证码/反爬页面')
        return detail
    def valid_url(value):
        p = urlsplit(value)
        return (p.scheme in ('http', 'https') and p.hostname == 'mp.weixin.qq.com'
                and (p.path == '/s' or p.path.startswith('/s/')))
    if valid_url(r.url):
        detail.update(url=r.url, error_layer=None)
        return detail
    parts = re.findall(r"url \+= '(.*?)';", r.text)
    if parts:
        raw = "".join(parts).replace("&amp;", "&").replace("@", "").strip()
        if valid_url(raw):
            detail.update(url=raw, error_layer=None)
            return detail
    m = re.search(r"(https?://mp\.weixin\.qq\.com/s[^\"'<>\s]+)", r.text)
    if m and valid_url(m.group(1)):
        detail.update(url=m.group(1).replace('&amp;', '&'), error_layer=None)
    else:
        detail['error'] = '链接解析失败（未见可用原文链接）'
    return detail


def resolve(s, link):
    """兼容既有消费者：只返回原文链接，分层结果由 main 使用。"""
    return resolve_detail(s, link)['url']


def article_detail(s, url):
    """结构化正文获取：成功给正文与响应凭据，失败保留失败层级与真实响应证据。

    T07（2026-10-13）：正文失败原先只落一句 note，无法区分请求阶段，也没有正文
    响应自身的 URL/状态/哈希/抓取时间。这里统一由正文层返回结构化字典；普通
    HTTP 失败不判反爬，仅 429 视为限流；只有结构证据（验证码/反爬页）才标 blocked。
    """
    detail = {'url': '', 'blocked': False, 'error_layer': 'body', 'error': None,
              'requested_url': url, 'response_url': None, 'response_status': None,
              'response_sha256': None,
              'fetched_at': datetime.datetime.now().astimezone().isoformat()}
    try:
        r = s.get(url, timeout=30, headers={"Referer": "https://weixin.sogou.com/"})
    except Exception as e:
        detail['error'] = f"网络异常:{type(e).__name__}"
        return detail
    detail['response_url'] = r.url
    detail['response_status'] = r.status_code
    detail['response_sha256'] = hashlib.sha256(r.content).hexdigest()
    if not 200 <= r.status_code < 300:
        detail['error'] = f"HTTP {r.status_code}"
        detail['blocked'] = r.status_code == 429
        return detail
    t = r.text
    if response_blocked(r):
        detail['error'] = "验证码/反爬页面"
        detail['blocked'] = True
        return detail
    if "该内容已被发布者删除" in t or "此内容因违规无法查看" in t:
        detail['error'] = "文章不可访问"
        return detail
    title = re.search(r'var msg_title\s*=\s*"([^"]*)"', t) or \
            re.search(r'property="og:title" content="([^"]*)"', t)
    nick = re.search(r'var nickname\s*=\s*"([^"]*)"', t)
    parser = _BodyParser()
    parser.feed(t)
    text = re.sub(r"[ \t\u3000]+", " ", "".join(parser.parts))
    text = re.sub(r"\n{2,}", "\n", text).strip()
    detail.update(title=html.unescape(title.group(1)) if title else "",
                  nickname=html.unescape(nick.group(1)) if nick else "",
                  text=text[:ARTICLE_CHARS], extracted_body_chars=len(text),
                  body_truncated=len(text) > ARTICLE_CHARS,
                  body_container_closed=parser.closed)
    return detail


def article_text(s, url):
    """兼容既有消费者：保留旧 tuple 接口 (正文或 None, 错误或 None)。"""
    d = article_detail(s, url)
    if d.get('text') is not None:
        keys = ('title', 'nickname', 'text', 'extracted_body_chars', 'body_truncated',
                'body_container_closed', 'fetched_at', 'requested_url', 'response_url',
                'response_status', 'response_sha256')
        return {k: v for k, v in d.items() if k in keys}, None
    return None, d.get('error')
    if "该内容已被发布者删除" in t or "此内容因违规无法查看" in t:
        return None, "文章不可访问"


class day_lock:
    """同日候选文件的共享写锁（Windows 命名互斥体；无锁文件，进程退出即释放）。

    只约束遵守同一锁的写手；不含锁协议的外部进程直接改写目标仍可能被覆盖，
    这一点在交接材料里如实标注，不宣称已具备并发绝对安全。
    """

    def __init__(self, target, timeout=60.0):
        seed = hashlib.sha256(os.path.abspath(str(target)).encode('utf-8')).hexdigest()[:24]
        self.name = 'Local\\hermes_scan_day_' + seed
        self.timeout = timeout
        self.kernel32 = None
        self.handle = None

    def __enter__(self):
        import ctypes
        self.kernel32 = ctypes.windll.kernel32
        self.handle = self.kernel32.CreateMutexW(None, False, self.name)
        if not self.handle:
            raise RuntimeError('同日候选写入锁创建失败')
        WAIT_OBJECT_0, WAIT_ABANDONED = 0x0, 0x80
        result = self.kernel32.WaitForSingleObject(self.handle, int(self.timeout * 1000))
        if result not in (WAIT_OBJECT_0, WAIT_ABANDONED):
            self.kernel32.CloseHandle(self.handle)
            self.handle = None
            raise TimeoutError('同日候选写入锁等待超时（另一写手可能仍在处理）')
        return self

    def __exit__(self, *exc):
        if self.handle:
            try:
                self.kernel32.ReleaseMutex(self.handle)
            finally:
                self.kernel32.CloseHandle(self.handle)
                self.handle = None
        return False


def norm(t):
    return re.sub(r"[\s\u3000\.\,\，\。\?？\!\！\-—_:：;；\"'“”‘’\[\]【】\(\)（）\|、]+", "", t or "")[:60]


def load_recent_titles(now, days):
    seen = set()
    floor = (now - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    for p in glob.glob(os.path.join(CACHE_DIR, "*.json")):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if d.get("date", "") < floor:
            continue
        for it in d.get("items", []):
            seen.add(norm(it.get("title", "")))
    return seen


def fetch_priority(item):
    # 优先取法律相关原文；最新无关AI条目不能耗尽仅有的正文抓取机会。
    return ({'法律AI':0,'法律':1,'写作':2,'AI':3}.get(item.get('group'),4),-item.get('ts',0))


def body_metadata(item):
    body=item.get('body') or ''
    return {'source_level':'body_fragment' if body else 'title_summary',
            'body_chars':len(body),'body_reviewed':False,
            'body_sha256':hashlib.sha256(body.encode('utf-8')).hexdigest() if body else None,
            'fulltext_verified':False,
            'source_note':'脚本取回的非空文本不是全文通读或事实核验；重点内容须进一步取原文'}


def main():
    if '--preview' in sys.argv or '--explain' in sys.argv:
        print(json.dumps({'mode':'read_only_explain','queries':QUERIES,'candidate_dir':CACHE_DIR,
                          'priority':'法律AI/法律/写作/AI','source_levels':['title_summary','body_fragment'],
                          'network_called':False,'source_written':False},ensure_ascii=False));return
    now = datetime.datetime.now()
    cutoff = (now - datetime.timedelta(days=WINDOW_DAYS)).timestamp()
    history = load_recent_titles(now, DEDUP_DAYS)
    s = session()
    seen, items, stats = set(history), [], []
    blocked_hit = False

    for group, q in QUERIES:
        try:
            r = s.get("https://weixin.sogou.com/weixin",
                      params={"type": 2, "query": q, "ie": "utf8"}, timeout=25)
        except Exception as e:
            stats.append((q, 0, f"err:{type(e).__name__}")); continue
        if response_blocked(r):
            stats.append((q, 0, "blocked")); blocked_hit = True; break
        if not 200 <= r.status_code < 300:
            stats.append((q, 0, f"HTTP {r.status_code}")); continue
        got = parse(r.text)
        n = 0
        for it in got:
            if not it["ts"] or it["ts"] < cutoff or it["ts"] > now.timestamp():
                continue
            key = norm(it["title"])
            if not key or len(key) < 6 or key in seen:
                continue
            seen.add(key)
            it["group"], it["query"] = group, q
            items.append(it); n += 1
        stats.append((q, n, "ok"))
        time.sleep(random.uniform(2.0, 3.5))

    items.sort(key=lambda x: -x["ts"])

    fetched = 0
    blocked_failfast = blocked_hit
    for it in sorted(items,key=fetch_priority):
        if blocked_failfast:
            it.update(real_url="", body="", note="blocked（已见验证码/限流，后续未请求）")
            continue
        if fetched >= MAX_ARTICLE_FETCH:
            it.update(real_url="", body="", note="未抓（超上限）")
            continue
        resolved = resolve_detail(s, it["link"])
        it['resolve_provenance'] = resolved
        u = resolved['url']
        it["real_url"] = u
        if not u:
            it.update(body="", note=resolved['error'] or "链接解析失败")
            fetched += 1
            if resolved['blocked']:
                blocked_hit = blocked_failfast = True
        else:
            detail = article_detail(s, u)
            if detail.get('error'):
                it.update(body="", note=detail['error'])
                it['body_provenance'] = {k: v for k, v in detail.items()
                                         if k not in {'text', 'title', 'nickname'}}
                if detail['error'] in ('验证码/反爬页面', 'HTTP 429'):
                    blocked_hit = blocked_failfast = True
            else:
                it["body"] = detail["text"]
                it["note"] = "ok" if detail["text"] else "正文抽取为空"
                it['body_provenance'] = {k: v for k, v in detail.items()
                                         if k not in {'text', 'title', 'nickname'}}
                if detail["nickname"]:
                    it["account"] = it["account"] or detail["nickname"]
            fetched += 1
        if blocked_failfast:
            print(f"[公众号采集] 已见验证码/HTTP限流，本轮停止后续请求（已处理 {fetched} 篇）。")
            continue
        time.sleep(random.uniform(1.5, 2.8))

    os.makedirs(CACHE_DIR, exist_ok=True)
    day = now.strftime("%Y-%m-%d")
    data_path = os.path.join(CACHE_DIR, f"{day}.json")
    # T08（2026-10-13）：最后的读、合并、替换必须在同一把共享锁内完成，网络请求
    # 全部在锁外。唯一临时文件与原子 os.replace 只能避免半截文件，不能防止丢更新：
    # 两个写手各自「读旧 → 合并 → 替换」会互相覆盖。锁为进程间命名互斥体，无锁
    # 文件、进程退出即释放；不含锁协议的外部写手直接改写目标不在本锁保护范围。
    with day_lock(data_path):
        merged = items
        if os.path.exists(data_path):
            # 旧候选不可读不等于不存在：拒绝覆盖，不丢弃同日先采到的材料。
            with open(data_path, encoding="utf-8") as source:
                old = json.load(source)
            if not isinstance(old, dict) or not isinstance(old.get('items'), list):
                raise ValueError('既有候选结构无效，保留原文件，本轮未写入')
            have = {norm(i.get("title", "")) for i in old['items']}
            merged = old['items'] + [i for i in items if norm(i["title"]) not in have]
            merged.sort(key=lambda x: -x.get("ts", 0))
        for item in merged:
            item.update(body_metadata(item))
        fd, temporary = tempfile.mkstemp(dir=CACHE_DIR, prefix='.candidate-', suffix='.tmp')
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"date": day, "generated_at": now.isoformat(), "stats": stats,
                           "blocked": blocked_hit, "window_days": WINDOW_DAYS, "items": merged}, f, ensure_ascii=False, indent=1)
                f.flush(); os.fsync(f.fileno())
            os.replace(temporary, data_path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    body_ok = sum(1 for i in items if i.get("body"))
    print(f"[公众号采集] {day} 窗口{WINDOW_DAYS}天 新候选{len(items)}篇（已排除近{DEDUP_DAYS}天重复）"
          f" 抓正文{body_ok}篇; blocked={blocked_hit}; failfast={blocked_failfast}")
    print(f"数据文件: {data_path}")
    print("各词命中: " + "; ".join(f"{q}={n}{'' if st == 'ok' else '(' + st + ')'}" for q, n, st in stats))
    print("-" * 60)
    for i, it in enumerate(items, 1):
        d = datetime.datetime.fromtimestamp(it["ts"]).strftime("%m-%d %H:%M")
        print(f"{i}. [{it['group']}] {d} | {it['account']} | {it['title']}")
        print(f"   {it['summary'][:120]}")
        print(f"   链接={it['real_url'] or it['link'][:70]} | 正文{len(it.get('body') or '')}字 {it.get('note','')}")


if __name__ == "__main__":
    main()
