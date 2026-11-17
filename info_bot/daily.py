#!/usr/bin/env python3
"""정보쇼츠 매일 자동 제작 (GitHub Actions 에서 매일 17:07 KST 실행)
  1) queue/ 폴더에 대본(.json)이 있으면 그걸 먼저 만듭니다 (정치 브리핑처럼 채팅에서 만든 대본)
  2) 없으면 순서대로 돌아가며: 오늘의 시황 → 종목 분석 → 생활 꿀팁 (장이 열리지 않은 날은 시황을 건너뜀)
  3) 영상·썸네일을 GitHub Releases 에 올리고, videos.json · index.html(아이폰용 보관함)을 갱신
시황·종목 대본은 네이버 증권·업비트에서 받은 '숫자'로만 씁니다. 원인 해석·전망·매수 권유는 넣지 않습니다.
환경변수: GH_TOKEN, GITHUB_REPOSITORY, CATEGORY(auto|market|stock|life|queue), DRY(1이면 업로드 안 함)
"""
import datetime as dt, html, json, os, random, re, subprocess, sys, time, urllib.request
from pathlib import Path

BOT = Path(__file__).resolve().parent; ROOT = BOT.parent; sys.path.insert(0, str(BOT))
import shorts as SH  # noqa: E402

REPO = os.environ.get('GITHUB_REPOSITORY', 'yunsub2002/yscominformation')
KST = dt.timezone(dt.timedelta(hours=9)); NOW = dt.datetime.now(KST); TODAY = NOW.date()
ROTATION = ['market', 'stock', 'life']
TAB = {'life': ('생활꿀팁', '생활 꿀팁', '#2ee6a6'), 'market': ('오늘의시황', '오늘의 시황', '#ffcf4a'), 'stock': ('종목분석', '종목 분석', '#4ab0ff'), 'politics': ('정치브리핑', '정치 브리핑', '#b49cff')}
UA = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)'}
# 종목 분석에서 돌아가며 다룰 종목 (시가총액 상위 위주). 바꾸고 싶으면 이 목록만 고치면 됩니다.
STOCKS = [('005930', '삼성전자'), ('000660', 'SK하이닉스'), ('373220', 'LG에너지솔루션'), ('207940', '삼성바이오로직스'), ('005380', '현대차'), ('012450', '한화에어로스페이스'),
          ('000270', '기아'), ('068270', '셀트리온'), ('105560', 'KB금융'), ('035420', 'NAVER'), ('055550', '신한지주'), ('005490', 'POSCO홀딩스'), ('028260', '삼성물산'),
          ('012330', '현대모비스'), ('329180', 'HD현대중공업'), ('035720', '카카오'), ('034020', '두산에너빌리티'), ('006400', '삼성SDI'), ('051910', 'LG화학'), ('015760', '한국전력'),
          ('032830', '삼성생명'), ('086790', '하나금융지주'), ('066570', 'LG전자'), ('003550', 'LG'), ('017670', 'SK텔레콤'), ('096770', 'SK이노베이션'), ('010130', '고려아연')]
BIGCAPS = STOCKS[:14]
DISC_MKT = '정보 제공용 영상이며 투자 권유가 아닙니다. 투자 판단과 책임은 본인에게 있습니다.'
DISC_STK = '특정 종목의 매수·매도를 권하는 영상이 아닙니다. 투자 판단과 책임은 본인에게 있습니다.'


def sh(*cmd, check=True):
    print('  >', ' '.join(str(c) for c in cmd), flush=True); return subprocess.run([str(c) for c in cmd], cwd=ROOT, check=check)


# ───────────────────────────── 데이터 받기
def get(url, enc='utf-8', tries=4):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r: return r.read().decode(enc, 'replace')
        except Exception as e:
            if k == tries - 1: raise
            print(f'  다시 시도 ({type(e).__name__}) {url[:60]}', flush=True); time.sleep(3 * (k + 1))


def jget(url): return json.loads(get(url))
def num(s): return float(str(s).replace(',', '').replace('+', '').replace('%', '').replace('배', '').replace('원', '').strip() or 0)


def index_today(code):
    """KOSPI/KOSDAQ: 오늘 종가가 확정됐으면 dict, 장이 안 열린 날이면 None"""
    rows = jget(f'https://m.stock.naver.com/api/index/{code}/price?pageSize=2&page=1'); r = rows[0]
    if r['localTradedAt'] != TODAY.isoformat(): return None
    b = jget(f'https://m.stock.naver.com/api/index/{code}/basic')
    if b.get('marketStatus') not in ('CLOSE', 'CLOSED') and NOW.hour < 16: return None
    return dict(close=num(r['closePrice']), diff=num(r['compareToPreviousClosePrice']), ratio=num(r['fluctuationsRatio']))


def flows(code):
    try:
        t = jget(f'https://m.stock.naver.com/api/index/{code}/trend')
        if t.get('bizdate') != TODAY.strftime('%Y%m%d'): return None
        return dict(personal=num(t['personalValue']), foreign=num(t['foreignValue']), inst=num(t['institutionalValue']))
    except Exception as e: print('  수급 정보 없음:', e); return None


def fx():
    try:
        r = jget('https://m.stock.naver.com/front-api/marketIndex/productDetail?category=exchange&reutersCode=FX_USDKRW')['result']
        sign = -1 if r['fluctuationsType']['name'] == 'FALLING' else 1
        return dict(close=num(r['closePrice']), diff=sign * abs(num(r['fluctuations'])))
    except Exception as e: print('  환율 정보 없음:', e); return None


def coins():
    try:
        rows = jget('https://api.upbit.com/v1/ticker?markets=KRW-BTC,KRW-ETH')
        return {r['market']: dict(price=r['trade_price'], ratio=r['signed_change_rate'] * 100) for r in rows}
    except Exception as e: print('  코인 정보 없음:', e); return None


def stock_basic(code):
    b = jget(f'https://m.stock.naver.com/api/stock/{code}/basic')
    return dict(name=b['stockName'], close=num(b['closePrice']), diff=num(b['compareToPreviousClosePrice']), ratio=num(b['fluctuationsRatio']), date=b.get('localTradedAt', '')[:10])


def stock_info(code):
    d = jget(f'https://m.stock.naver.com/api/stock/{code}/integration'); return {x['code']: x['value'] for x in d.get('totalInfos', [])}


def history(code, n=260):
    xml = get(f'https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={n}&requestType=0', 'euc-kr')
    rows = re.findall(r'data="(\d{8})\|([\d.]+)\|([\d.]+)\|([\d.]+)\|([\d.]+)\|(\d+)"', xml)
    return [(r[0], float(r[4]), int(r[5])) for r in rows]


# ───────────────────────────── 말하기용 숫자
def eok(v):
    """억 원 → 화면용 '+1조 1,929억' / 말하기용 '1조 1929억'"""
    a = abs(int(round(v))); jo, rest = divmod(a, 10000); sgn = '+' if v > 0 else '−' if v < 0 else ''
    disp = (f'{jo}조 {rest:,}억' if jo and rest else f'{jo}조' if jo else f'{rest:,}억')
    say = (f'{jo}조 {rest}억' if jo and rest else f'{jo}조' if jo else f'{rest}억')
    return sgn + disp, say + ' 원'


def won_say(v):
    v = int(round(v)); man, rest = divmod(v, 10000)
    if v >= 100000000: eokv, man = divmod(man, 10000); return f'{eokv}억 {man}만 원' if man else f'{eokv}억 원'
    if man and rest: return f'{man}만 {rest}원'
    return f'{man}만 원' if man else f'{rest}원'


def josa(w, a, b):
    """받침에 맞는 조사: josa('삼성전자', '은', '는') → '삼성전자는'"""
    ch = w.strip()[-1] if w.strip() else ''
    if '가' <= ch <= '힣': fin = (ord(ch) - 0xAC00) % 28 != 0
    else: fin = ch.upper() in 'LMN0136789'
    return w + (a if fin else b)


def pct(r, d=2): return f"{'+' if r > 0 else ''}{r:.{d}f}%"
def pct_say(r, d=2): return re.sub(r'\.0+퍼센트$', '퍼센트', f'{abs(r):.{d}f}퍼센트')
def updown(r, big=2.5): return ('급등' if r >= big else '상승' if r > .2 else '보합' if r >= -.2 else '하락' if r > -big else '급락')
def updown_say(r): return '올랐' if r > 0 else '내렸' if r < 0 else '변동이 없었'


# ───────────────────────────── 대본 만들기
def write_market(R):
    k = index_today('KOSPI')
    if not k: return None
    q = index_today('KOSDAQ'); fl = flows('KOSPI'); f = fx(); c = coins(); md = f'{TODAY.month}월 {TODAY.day}일'
    caps = []
    for code, nm in BIGCAPS:
        try: b = stock_basic(code); caps.append((nm, b['ratio']))
        except Exception as e: print('  종목 건너뜀', nm, e)
    sc = []; word = updown(k['ratio'])
    hook_sub = None
    if fl:
        fd, fs = eok(fl['foreign']); hook_sub = f"외국인 {'순매수' if fl['foreign'] > 0 else '순매도'} {fd.lstrip('+−')}"
    sc.append(dict(type='hook', kicker=f'{md} 마감', title=f"코스피\n{pct(k['ratio'])} {word}", sub=hook_sub or '오늘 장 1분 정리',
                   say=R.choice([f'{md} 코스피는 {pct_say(k["ratio"])} {updown_say(k["ratio"])}습니다. 오늘 장을 숫자로 정리합니다.',
                                 f'오늘 코스피, {pct_say(k["ratio"])} {"올랐" if k["ratio"] > 0 else "떨어졌"}습니다. 1분 시황 시작합니다.'])))
    items = [dict(label='코스피', value=f"{k['close']:,.2f}", change=pct(k['ratio']))]; say = f'코스피는 {int(k["close"])}포인트'
    if q: items.append(dict(label='코스닥', value=f"{q['close']:,.2f}", change=pct(q['ratio']))); say += f', 코스닥은 {int(q["close"])}포인트로 각각 {pct_say(k["ratio"])}, {pct_say(q["ratio"])} {updown_say(q["ratio"]) if (k["ratio"] > 0) == (q["ratio"] > 0) else "움직였"}습니다.'
    else: say += f'로 마감했습니다.'
    sc.append(dict(type='stats', title='지수 마감', items=items, say=say))
    if fl:
        parts = [('개인', fl['personal']), ('외국인', fl['foreign']), ('기관', fl['inst'])]
        its = [dict(label=n, value=v, text=eok(v)[0], color=SH.UP if v > 0 else SH.DOWN) for n, v in parts]
        buy = [f'{n}이 {eok(v)[1]}' if n != '개인' else f'개인이 {eok(v)[1]}' for n, v in parts if v > 0]; sell = [f'{n}이 {eok(v)[1]}' for n, v in parts if v < 0]
        say = ''
        if sell: say += ', '.join(sell) + '어치를 팔았고, '
        if buy: say += ', '.join(buy) + '어치를 샀습니다.'
        sc.append(dict(type='bars', title='코스피 누가 사고 팔았나', unit='단위: 억 원 (순매수 +, 순매도 −)', items=its, say=say.rstrip(', ') or '수급은 엇갈렸습니다.'))
    if len(caps) >= 4:
        caps.sort(key=lambda x: -x[1]); pick = caps[:2] + caps[-2:]
        its = [dict(label=n, value=r, text=pct(r), color=SH.UP if r > 0 else SH.DOWN) for n, r in pick]
        say = f'대형주 중에서는 {josa(pick[0][0], "이", "가")} {pct_say(pick[0][1])} {updown_say(pick[0][1])}고, {josa(pick[-1][0], "은", "는")} {pct_say(pick[-1][1])} {updown_say(pick[-1][1])}습니다.'
        sc.append(dict(type='bars', title='대형주 등락 상위·하위', unit='전일 대비 등락률', items=its, say=say))
    its = []; say = []
    if f: its.append(dict(label='원·달러 환율', value=f"{f['close']:,.1f}원", change=f"{'+' if f['diff'] > 0 else ''}{f['diff']:.1f}원")); say.append(f'원 달러 환율은 {f["close"]:.0f}원')
    if c:
        b, e = c.get('KRW-BTC'), c.get('KRW-ETH')
        if b: its.append(dict(label='비트코인', value=f"{b['price'] / 10000:,.0f}만원", change=pct(b['ratio']))); say.append(f'비트코인은 {won_say(b["price"] // 10000 * 10000)}')
        if e: its.append(dict(label='이더리움', value=f"{e['price'] / 10000:,.0f}만원", change=pct(e['ratio'])))
    if its: sc.append(dict(type='stats', title='환율 · 코인', items=its, say=', '.join(say) + '입니다.'))
    sc.append(dict(type='end', title='투자 판단은 신중하게', sub='내일도 장 마감 후 1분 시황', disclaimer=DISC_MKT, say='정보 제공용 영상입니다. 내일도 장 마감 후 정리해 드릴게요.'))
    tags = ['코스피', '코스닥', '주식 시황', '오늘의 증시', '증시 마감', '환율', '비트코인', '코인 시세', '주식', '쇼츠']
    return dict(category='market', date=TODAY.strftime('%Y.%m.%d'), name=f'market_{TODAY:%Y%m%d}', rate='+12%', disclaimer=DISC_MKT,
                source_line=f'데이터: 네이버 증권 · 업비트 ({TODAY:%m.%d} 마감 기준)', scenes=sc,
                sources=['네이버 증권 (지수·투자자별 매매·환율·종목 시세) https://m.stock.naver.com', '업비트 (코인 시세, 전일 대비) https://upbit.com'],
                yt=dict(title=f"코스피 {pct(k['ratio'])} {word} | {md} 1분 시황", desc=f'{md} 국내 증시 마감 숫자를 1분으로 정리했습니다. (지수·수급·대형주·환율·코인)', tags=tags))


def write_stock(R, idx):
    for j in range(len(STOCKS)):
        code, nm = STOCKS[(idx + j) % len(STOCKS)]
        try:
            b = stock_basic(code); info = stock_info(code); h = history(code, 260)
            if len(h) >= 130: break
        except Exception as e: print('  종목 데이터 실패', nm, e)
    else: return None
    closes = [x[1] for x in h]; last = closes[-1]; d0 = h[-1][0]; date = f'{int(d0[4:6])}월 {int(d0[6:])}일'
    ret = lambda k: (last / closes[-1 - k] - 1) * 100 if len(closes) > k else None
    r1, r3, r6, r12 = ret(21), ret(63), ret(126), ret(len(closes) - 1)
    hi52 = num(info.get('highPriceOf52Weeks', max(closes))); lo52 = num(info.get('lowPriceOf52Weeks', min(closes)))
    from_hi = (last / hi52 - 1) * 100 if hi52 else None
    ser = closes[-126:]; ma_all = [None if i < 19 else sum(closes[i - 19:i + 1]) / 20 for i in range(len(closes))]; ma = ma_all[-126:]
    vol20 = sum(x[2] for x in h[-21:-1]) / 20; vol_x = h[-1][2] / vol20 if vol20 else None
    sc = [dict(type='hook', kicker=f'종목 분석 · {date} 종가 기준', title=f'{nm}\n지금 어디쯤?', sub='숫자로만 보는 1분 점검',
               say=R.choice([f'{nm}, 지금 주가는 어디쯤일까요? 숫자로만 1분 점검합니다.', f'오늘은 {nm}입니다. 감정 빼고 숫자로만 보겠습니다.'])),
          dict(type='stat', label=f'{date} 종가', value=f'{last:,.0f}원', change=pct(b['ratio']) if b['date'] == f'{d0[:4]}-{d0[4:6]}-{d0[6:]}' else None,
               sub=f"52주 최고 {hi52:,.0f}원 · 최저 {lo52:,.0f}원",
               say=f'{date} 종가는 {won_say(last)}' + (f', 하루 동안 {pct_say(b["ratio"])} {updown_say(b["ratio"])}습니다.' if b['date'] == f'{d0[:4]}-{d0[4:6]}-{d0[6:]}' else '입니다.')),
          dict(type='chart', title='최근 6개월 주가', unit='흰 선: 20일 평균', values=[round(x) for x in ser], ma=[None if m is None else round(m) for m in ma],
               start=f'{int(h[-126][0][4:6])}월 {int(h[-126][0][6:])}일', end_label=date, note=f'6개월 {pct(r6, 1)}' if r6 is not None else '',
               say=f'최근 6개월 동안 {pct_say(r6, 1)} {updown_say(r6)}습니다.' + (' 지금은 20일 평균선 ' + ('위' if last > ma[-1] else '아래') + '에 있습니다.' if ma[-1] else ''))]
    per = [(l, v) for l, v in (('1개월', r1), ('3개월', r3), ('1년', r12)) if v is not None]
    ud = lambda r: '상승' if r > 0 else '하락' if r < 0 else '보합'
    sc.append(dict(type='stats', title='기간별 수익률', items=[dict(label='기간', value=l, change=pct(v, 1)) for l, v in per],
                   say=', '.join(f'{l} {pct_say(v, 1)} {ud(v)}' for l, v in per) + '입니다.'))
    val = [(k, l) for k, l in (('marketValue', '시가총액'), ('per', 'PER (주가수익비율)'), ('pbr', 'PBR (주가순자산비율)'), ('dividendYieldRatio', '배당수익률')) if info.get(k)]
    if len(val) >= 2:
        sc.append(dict(type='stats', title='가치 지표 (네이버 증권)', items=[dict(label=l, value=info[k]) for k, l in val[:4]],
                       say=' '.join([f'시가총액은 {info["marketValue"].replace(",", "")}' + ('원,' if info.get('per') else '원입니다.') if info.get('marketValue') else '',
                                     f'PER은 {info["per"].replace("배", "")}배' + (',' if info.get('pbr') else '입니다.') if info.get('per') else '',
                                     f'PBR은 {info["pbr"].replace("배", "")}배입니다.' if info.get('pbr') else '']).strip()))
    pos = f'52주 최고가보다 {pct_say(abs(from_hi), 1)} 낮은 수준' if from_hi is not None and from_hi < -.5 else '52주 최고가 근처'
    sc.append(dict(type='bullets', title='오늘의 숫자 정리', items=[f'52주 위치|{pos}', f'거래량|20일 평균의 {vol_x:.1f}배' if vol_x else '거래량|데이터 없음', f'20일 평균선|' + ('위' if ma[-1] and last > ma[-1] else '아래') + '에 있음'],
                   say=f'지금 주가는 {pos}이고, 오늘 거래량은 20일 평균의 {vol_x:.1f}배였습니다.' if vol_x else f'지금 주가는 {pos}입니다.'))
    sc.append(dict(type='end', title='숫자는 참고만', sub='내일은 다른 종목을 살펴볼게요', disclaimer=DISC_STK, say='특정 종목을 권하는 영상이 아닙니다. 판단은 직접 하세요.'))
    return dict(category='stock', date=TODAY.strftime('%Y.%m.%d'), name=f'stock_{code}_{TODAY:%Y%m%d}', rate='+12%', disclaimer=DISC_STK, stock=code,
                source_line=f'데이터: 네이버 증권 ({date} 종가 기준)', scenes=sc, sources=[f'네이버 증권 {nm} https://m.stock.naver.com/domestic/stock/{code}/total'],
                yt=dict(title=f'{nm} 주가, 지금 어디쯤? 6개월 {pct(r6, 1)} | 종목 분석', desc=f'{nm}의 최근 주가 흐름과 기간별 수익률, 가치 지표를 숫자로만 정리했습니다. ({date} 종가 기준)',
                        tags=[nm, f'{nm} 주가', f'{nm} 주식', '종목 분석', '주식', '주가', '코스피', '주식 공부', '재테크', '쇼츠']))


def write_life(idx):
    tips = json.loads((BOT / 'tips.json').read_text(encoding='utf-8'))
    S = dict(tips[idx % len(tips)]); S['name'] = f"life_{S.pop('id')}_{TODAY:%Y%m%d}"; return S


# ───────────────────────────── 보관함 페이지 (아이폰용)
PAGE = r'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><meta name="theme-color" content="#0d0f18"><meta name="format-detection" content="telephone=no">
<title>정보쇼츠 보관함</title><style>
:root{--bg:#0d0f18;--card:#161a28;--ln:#272c40;--tx:#eceef6;--mut:#9aa0b8}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--tx);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",sans-serif}
main{max-width:720px;margin:0 auto;padding:calc(14px + env(safe-area-inset-top)) max(16px,env(safe-area-inset-right)) calc(40px + env(safe-area-inset-bottom)) max(16px,env(safe-area-inset-left))}
h1{font-size:21px;margin:6px 0 2px}p.s{color:var(--mut);margin:0 0 10px;font-size:13px}
.tabs{display:flex;gap:8px;overflow-x:auto;padding:10px 0;margin:0 -16px 10px;padding-left:16px;padding-right:16px;position:sticky;top:0;z-index:5;background:linear-gradient(var(--bg) 80%,transparent);scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tabs button{flex:0 0 auto;font:inherit;font-size:15px;font-weight:700;border:1px solid var(--ln);background:var(--card);color:var(--tx);border-radius:999px;padding:9px 15px;min-height:42px}
.tabs button.on{background:var(--c);color:#0d0f18;border-color:transparent}.tabs .n{opacity:.6;margin-left:5px;font-weight:600}
.v{background:var(--card);border:1px solid var(--ln);border-radius:18px;padding:12px;margin-bottom:14px}
.top{display:flex;gap:12px}.th{flex:0 0 96px;aspect-ratio:9/16;border-radius:12px;overflow:hidden;background:#000}.th img{width:100%;height:100%;object-fit:cover;display:block}
.info{min-width:0;display:flex;flex-direction:column;gap:6px}.tag{align-self:flex-start;font-size:12px;font-weight:800;border-radius:6px;padding:2px 8px;color:#0d0f18}
.t{font-weight:700;font-size:16px;line-height:1.35;word-break:keep-all}.m{color:var(--mut);font-size:13px}
.r{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px}.r3{grid-template-columns:1fr 1fr 1fr;margin-top:8px}
.r a,.r button{display:flex;align-items:center;justify-content:center;min-height:46px;font:inherit;font-size:15px;font-weight:700;color:#fff;background:#4a5bd6;border:0;border-radius:12px;text-decoration:none}
.r a.t2,.r button{background:#262b40}details{margin-top:10px;font-size:13px;color:var(--mut)}summary{min-height:36px;display:flex;align-items:center}
details pre{white-space:pre-wrap;font:inherit;background:#0a0d18;padding:10px;border-radius:10px;margin:6px 0 0}
.empty{color:var(--mut);padding:40px 0;text-align:center}.toast{position:fixed;left:50%;bottom:calc(24px + env(safe-area-inset-bottom));transform:translateX(-50%);background:#fff;color:#000;font-weight:700;padding:10px 18px;border-radius:999px;opacity:0;transition:.2s;pointer-events:none}
.toast.on{opacity:1}
</style></head><body><main><h1>📺 정보쇼츠 보관함</h1>
<p class="s">매일 오후 5시쯤 새 쇼츠가 자동으로 올라옵니다. ⬇ 영상 받기 → 파일에 저장 → 사진에 저장 → YouTube 앱에서 업로드 → 📋 제목·설명·태그 붙여 넣기</p>
<div class="tabs" id="tabs"></div><div id="list"></div><div class="toast" id="toast">복사됨 ✓</div></main>
<script>
const DATA=__DATA__,TABS=__TABS__;let cur='all';try{cur=localStorage.getItem('tab')||'all'}catch(e){}
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function toast(){const t=document.getElementById('toast');t.classList.add('on');setTimeout(()=>t.classList.remove('on'),1200)}
function copy(t){if(navigator.clipboard){navigator.clipboard.writeText(t).then(toast,fb)}else fb();function fb(){const a=document.createElement('textarea');a.value=t;a.style.position='fixed';a.style.opacity=0;document.body.appendChild(a);a.select();try{document.execCommand('copy');toast()}catch(e){}a.remove()}}
function render(){const tb=document.getElementById('tabs');tb.innerHTML='';
 [['all','전체','#ffffff'],...TABS].forEach(([k,ko,c])=>{const n=k==='all'?DATA.length:DATA.filter(d=>d.cat===k).length;const b=document.createElement('button');b.innerHTML=esc(ko)+'<span class="n">'+n+'</span>';
  b.style.setProperty('--c',c);if(k===cur)b.className='on';b.onclick=()=>{cur=k;try{localStorage.setItem('tab',k)}catch(e){};render();window.scrollTo({top:0})};tb.appendChild(b)});
 const L=document.getElementById('list');L.innerHTML='';const list=DATA.filter(d=>cur==='all'||d.cat===cur);
 if(!list.length){L.innerHTML='<div class="empty">아직 이 탭에 영상이 없습니다.</div>';return}
 list.forEach((d,i)=>{const t=TABS.find(x=>x[0]===d.cat)||['', d.cat,'#fff'];const el=document.createElement('div');el.className='v';
  el.innerHTML=`<div class="top"><div class="th">${d.thumb?`<img loading="lazy" src="${esc(d.thumb)}" alt="">`:''}</div><div class="info"><span class="tag" style="background:${t[2]}">${esc(t[1])}</span><div class="t">${esc(d.title)}</div><div class="m">${esc(d.date)} · ${Math.round(d.sec)}초 · ${d.mb}MB</div></div></div>
  <div class="r"><a href="${esc(d.url)}">⬇ 영상 받기</a><a class="t2" href="${esc(d.thumb_url||d.thumb)}">⬇ 썸네일</a></div>
  <div class="r r3"><button data-k="title">📋 제목</button><button data-k="desc">📋 설명</button><button data-k="tags">📋 태그</button></div>
  <details><summary>설명 미리 보기</summary><pre>${esc(d.desc)}</pre></details>`;
  el.querySelectorAll('button[data-k]').forEach(b=>b.onclick=()=>copy(d[b.dataset.k]));L.appendChild(el)})}
render();
</script></body></html>'''


def render_page(db):
    tabs = [[k, TAB[k][1], TAB[k][2]] for k in ('market', 'stock', 'life', 'politics')]
    page = PAGE.replace('__DATA__', json.dumps(db, ensure_ascii=False).replace('</', '<\\/')).replace('__TABS__', json.dumps(tabs, ensure_ascii=False))
    (ROOT / 'index.html').write_text(page, encoding='utf-8')


# ───────────────────────────── 실행
def main():
    dbp = ROOT / 'videos.json'; db = json.loads(dbp.read_text(encoding='utf-8')) if dbp.exists() else []
    want = (os.environ.get('CATEGORY') or 'auto').strip(); R = random.Random(int(NOW.strftime('%Y%m%d')))
    S = None; qfile = None
    queue = sorted((ROOT / 'queue').glob('*.json'))
    if queue and want in ('auto', 'queue'):
        qfile = queue[0]; S = json.loads(qfile.read_text(encoding='utf-8')); S.setdefault('name', qfile.stem); print(f'대기열 대본: {qfile.name}')
    if S is None:
        order = [want] if want in ROTATION else ROTATION[(ROTATION.index(next((v['cat'] for v in db if v['cat'] in ROTATION), 'life')) + 1) % 3:] + ROTATION
        for cat in order:
            n_cat = sum(1 for v in db if v['cat'] == cat)
            S = write_market(R) if cat == 'market' else write_stock(R, n_cat) if cat == 'stock' else write_life(n_cat)
            if S: break
            print(f'  {cat}: 오늘은 만들 수 없음 (장 휴장 등) → 다음 주제')
    if not S: print('만들 대본이 없습니다'); return
    print(f"===== {S['category']} · {S['name']} =====", flush=True)
    (ROOT / '_out').mkdir(exist_ok=True); (ROOT / '_out' / f"{S['name']}.json").write_text(json.dumps(S, ensure_ascii=False, indent=1), encoding='utf-8')
    res = SH.make(S, ROOT / '_out', name=S['name'])
    if os.environ.get('DRY') == '1': print('DRY: 업로드 생략'); return res
    tag = f"info-{NOW:%Y%m%d-%H%M}"
    sh('gh', 'release', 'create', tag, res['mp4'], res['thumb'], '--repo', REPO, '--title', f"정보쇼츠 {NOW:%Y-%m-%d} {TAB[S['category']][1]}", '--notes', res['title'])
    base = f'https://github.com/{REPO}/releases/download/{tag}/'
    (ROOT / 'thumbs').mkdir(exist_ok=True); tj = ROOT / 'thumbs' / res['thumb'].name
    sh('ffmpeg', '-y', '-loglevel', 'error', '-i', res['thumb'], '-vf', 'scale=360:-1', '-q:v', '4', tj)
    title, _, rest = res['body'].partition('\n\n')
    db.insert(0, dict(cat=S['category'], name=S['name'], title=res['title'] or title, desc=rest.strip(), tags=', '.join(res['tags']), date=f'{NOW:%Y-%m-%d}', sec=res['sec'],
                      mb=round(res['mp4'].stat().st_size / 1e6, 1), url=base + res['mp4'].name, thumb=f'thumbs/{tj.name}', thumb_url=base + res['thumb'].name, stock=S.get('stock')))
    dbp.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding='utf-8'); render_page(db)
    add = ['videos.json', 'index.html', 'thumbs']
    if qfile: sh('git', 'rm', '-q', str(qfile.relative_to(ROOT)))
    sh('git', 'add', *add); sh('git', 'commit', '-m', f"정보쇼츠 추가: {res['title'][:60]}")
    br = os.environ.get('GITHUB_REF_NAME') or 'main'
    for k in range(5):
        if subprocess.run(['git', 'push', 'origin', f'HEAD:{br}'], cwd=ROOT).returncode == 0: break
        sh('git', 'pull', '--rebase', '-X', 'theirs', 'origin', br, check=False)
    else: raise RuntimeError('git push 실패')
    user, rn = REPO.split('/'); print(f'\n완료 → https://{user}.github.io/{rn}/')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'page':
        render_page(json.loads((ROOT / 'videos.json').read_text(encoding='utf-8'))); print('index.html 갱신')
    else: main()
