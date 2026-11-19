#!/usr/bin/env python3
"""정보 채널 쇼츠 제작기 — 대본(JSON) 한 개 → 세로 60초 쇼츠(1080x1920) + 업로드용 제목·설명·태그
  · 카테고리(탭) 4개: life 생활 꿀팁 · market 오늘의 시황 · stock 종목 분석 · politics 정치 브리핑
  · 음성: Microsoft Edge 신경망 한국어 음성(선희·인준 등), 단어마다 시간 정보를 받아 말하는 단어에 맞춰 자막 강조
  · 화면: 장면 종류 hook · bullets · stat · stats · bars · versus · timeline · end (모두 프로그램이 직접 그림, 외부 이미지 없음)
  · 배경음악: 카테고리 분위기에 맞춰 직접 합성한 아주 작은 음악 (말할 때는 더 작아짐)
사용: python 도구/shorts.py 도구/scripts/market_20261117.json  →  카테고리(탭) 폴더에 mp4 · 썸네일 · 업로드 문구, 보관함.html 자동 갱신
한국 주식 관례대로 상승은 빨강, 하락은 파랑. 정치 카테고리는 특정 정당을 떠올리게 하는 색을 쓰지 않습니다.
"""
import asyncio, json, math, os, re, subprocess, sys, wave
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1080, 1920, 30
ROOT = Path(__file__).resolve().parent
FONT_DIRS = ['/usr/share/fonts/opentype/noto', 'C:/Windows/Fonts']


def _font(weight, size):
    files = {'black': ['NotoSansCJK-Black.ttc', 'malgunbd.ttf'], 'bold': ['NotoSansCJK-Bold.ttc', 'malgunbd.ttf'], 'medium': ['NotoSansCJK-Medium.ttc', 'malgun.ttf'],
             'regular': ['NotoSansCJK-Regular.ttc', 'malgun.ttf']}[weight]
    files = files + ['NotoSansCJK-Bold.ttc', 'NotoSansCJK-Regular.ttc', 'malgunbd.ttf', 'malgun.ttf']                  # 굵기 글꼴이 없으면 가까운 굵기로
    for f in files:
        for d in FONT_DIRS:
            p = os.path.join(d, f)
            if os.path.exists(p): return ImageFont.truetype(p, size, index=1 if p.endswith('.ttc') else 0)   # .ttc 의 1번 = 한국어(KR)
    raise FileNotFoundError('한글 글꼴(Noto Sans CJK 또는 맑은 고딕)을 찾을 수 없습니다')


_FC = {}
def F(weight, size):
    k = (weight, size)
    if k not in _FC: _FC[k] = _font(weight, size)
    return _FC[k]


def hexc(h, a=255): h = h.lstrip('#'); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (a,)


# ───────────────────────────── 카테고리(탭)별 디자인
CATS = {
    'life':     dict(folder='생활꿀팁', ko='생활 꿀팁', acc='#2ee6a6', acc2='#b8ffe6', bg=('#06201c', '#0b3a32', '#041512'), voice='ko-KR-SunHiNeural', rate='+8%', bgm='bright'),
    'market':   dict(folder='오늘의시황', ko='오늘의 시황', acc='#ffcf4a', acc2='#fff0c0', bg=('#070b1e', '#121a3e', '#05070f'), voice='ko-KR-InJoonNeural', rate='+10%', bgm='pulse'),
    'stock':    dict(folder='종목분석', ko='종목 분석', acc='#4ab0ff', acc2='#cfe8ff', bg=('#04101e', '#0a2440', '#030912'), voice='ko-KR-InJoonNeural', rate='+8%', bgm='pulse'),
    'politics': dict(folder='정치브리핑', ko='정치 브리핑', acc='#b49cff', acc2='#e6dcff', bg=('#0d0b18', '#1d1a30', '#08070f'), voice='ko-KR-SunHiNeural', rate='+6%', bgm='calm'),
}
UP, DOWN, FLAT = '#ff4d5a', '#3d8bff', '#c8ccd8'                  # 한국식: 상승 빨강 · 하락 파랑
SIDE_A, SIDE_B = '#9aa6c8', '#c8b88a'                            # 정치 양쪽 비교: 정당 색과 무관한 중립색


# ───────────────────────────── 음성
def _ssl_fix():
    """회사·클라우드 프록시 환경에서 인증서 오류가 날 때만 사용 (일반 PC에서는 아무 영향 없음)"""
    ca = os.environ.get('SHORTS_CA') or ('/root/.ccr/ca-bundle.crt' if os.path.exists('/root/.ccr/ca-bundle.crt') else None)
    if not ca: return
    import ssl, edge_tts.communicate as C
    C._SSL_CTX = ssl.create_default_context(cafile=ca)


async def _tts(text, voice, rate, mp3):
    import edge_tts
    words = []
    c = edge_tts.Communicate(text, voice, rate=rate, boundary='WordBoundary')
    with open(mp3, 'wb') as f:
        async for ch in c.stream():
            if ch['type'] == 'audio': f.write(ch['data'])
            elif ch['type'] == 'WordBoundary': words.append((ch['offset'] / 1e7, (ch['offset'] + ch['duration']) / 1e7, ch['text']))
    return words


def tts(text, voice, rate, mp3, tries=5):
    """음성 서버가 잠깐 바쁠 때(503 등)는 조금 기다렸다가 다시 시도"""
    import time
    _ssl_fix()
    for k in range(tries):
        try:
            words = asyncio.run(_tts(text, voice, rate, mp3))
            if words and os.path.getsize(mp3) > 1000: return words
            raise RuntimeError('빈 음성')
        except Exception as e:
            if k == tries - 1: raise
            print(f'  음성 다시 시도 {k + 1}/{tries - 1} ({type(e).__name__})', flush=True); time.sleep(3 * (k + 1))


def read_audio(path, sr=44100):
    raw = subprocess.run(['ffmpeg', '-loglevel', 'error', '-i', str(path), '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-'], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


# ───────────────────────────── 배경음악 (직접 합성, 아주 작게)
def bgm(kind, secs, sr=44100, seed=1):
    R = np.random.default_rng(seed); n = int(secs * sr); t = np.arange(n) / sr; out = np.zeros(n, np.float32)
    root = 57 + int(R.choice([0, 2, 5, 7])); bpm = {'bright': 96, 'pulse': 88, 'calm': 72}[kind]; beat = 60 / bpm
    prog = [[0, 4, 7], [9, 12, 16], [5, 9, 12], [7, 11, 14]] if kind != 'calm' else [[0, 4, 7, 11], [5, 9, 12, 16], [9, 12, 16, 19], [7, 11, 14, 17]]
    hz = lambda m: 440 * 2 ** ((m - 69) / 12)
    bar = 4 * beat
    for b in range(int(secs / bar) + 1):
        ch = prog[b % 4]; t0 = b * bar; i0 = int(t0 * sr); L = int(bar * 1.1 * sr)
        if i0 >= n: break
        tt = np.arange(min(L, n - i0)) / sr; env = np.clip(tt / .4, 0, 1) * np.clip((bar * 1.1 - tt) / .5, 0, 1)
        for m in ch: out[i0:i0 + len(tt)] += (np.sin(2 * np.pi * hz(root + m - 12) * tt) * .045 * env).astype(np.float32)          # 패드
        out[i0:i0 + len(tt)] += (np.sin(2 * np.pi * hz(root + ch[0] - 24) * tt) * .06 * env).astype(np.float32)                      # 베이스
        if kind in ('bright', 'pulse'):
            for k in range(8):                                                                                                        # 뜯는 아르페지오
                m = root + ch[k % len(ch)] + (12 if k % 4 >= 2 else 0); j0 = i0 + int(k * beat / 2 * sr); jl = int(.6 * sr)
                if j0 >= n: break
                tk = np.arange(min(jl, n - j0)) / sr; f = hz(m)
                tone = (np.sin(2 * np.pi * f * tk) + .3 * np.sin(4 * np.pi * f * tk)) * np.exp(-tk / (.18 if kind == 'pulse' else .25))
                out[j0:j0 + len(tk)] += (tone * (.05 if k % 2 == 0 else .035)).astype(np.float32)
        if kind == 'pulse':                                                                                                           # 아주 작은 킥
            for k in range(4):
                j0 = i0 + int(k * beat * sr); tk = np.arange(min(int(.15 * sr), max(0, n - j0))) / sr
                if len(tk): out[j0:j0 + len(tk)] += (np.sin(2 * np.pi * (55 + 60 * np.exp(-tk / .02)) * tk) * np.exp(-tk / .05) * .08).astype(np.float32)
    from scipy import signal
    out = signal.sosfilt(signal.butter(2, 4500, 'low', fs=sr, output='sos'), out).astype(np.float32)
    return out / (np.abs(out).max() + 1e-9) * .5


# ───────────────────────────── 그리기 도구
def ease(x): x = min(1.0, max(0.0, x)); return 1 - (1 - x) ** 3


def wrap(text, font, maxw):
    """한국어 줄바꿈: 띄어쓰기 단위로 maxw 픽셀 안에 맞춤 (\n 은 강제 줄바꿈)"""
    lines = []
    for para in str(text).split('\n'):
        cur = ''
        for w in para.split(' '):
            cand = (cur + ' ' + w).strip()
            if font.getlength(cand) <= maxw or not cur: cur = cand
            else: lines.append(cur); cur = w
            while font.getlength(cur) > maxw and len(cur) > 1:                  # 한 단어가 줄보다 길면 글자 단위로 자름
                k = len(cur)
                while k > 1 and font.getlength(cur[:k]) > maxw: k -= 1
                lines.append(cur[:k]); cur = cur[k:]
        lines.append(cur)
    return lines


def text_block(d, xy, text, font, fill, maxw, spacing=1.18, align='left', shadow=True):
    x, y = xy; lh = int(font.size * spacing)
    for ln in wrap(text, font, maxw):
        w = font.getlength(ln); xx = x + (maxw - w) / 2 if align == 'center' else x
        if shadow: d.text((xx + 3, y + 4), ln, font=font, fill=(0, 0, 0, 120))
        d.text((xx, y), ln, font=font, fill=fill); y += lh
    return y


def rich_line(d, xy, parts, font, maxw=None, align='left'):
    """[(글자, 색)] 을 한 줄에 이어 그림"""
    total = sum(font.getlength(p) for p, _ in parts); x, y = xy
    if align == 'center' and maxw: x = x + (maxw - total) / 2
    for p, c in parts:
        d.text((x + 3, y + 4), p, font=font, fill=(0, 0, 0, 120)); d.text((x, y), p, font=font, fill=c); x += font.getlength(p)


def chg_color(v):
    try: f = float(str(v).replace('%', '').replace('+', '').replace(',', ''))
    except ValueError: return FLAT
    return UP if f > 0 else DOWN if f < 0 else FLAT


def arrow(v):
    c = chg_color(v); return '▲' if c == UP else '▼' if c == DOWN else '–'


class Background:
    def __init__(s, cat, seed=3):
        a, b, c = CATS[cat]['bg']; R = np.random.default_rng(seed)
        y = np.linspace(0, 1, H)[:, None]; col = lambda h: np.array(hexc(h)[:3], np.float32)
        g = np.where(y < .5, col(a) * (1 - y * 2) + col(b) * (y * 2), col(b) * (2 - y * 2) + col(c) * (y * 2 - 1))
        s.base = np.repeat(g[:, None, :].reshape(H, 1, 3), W, axis=1)
        s.blobs = [(R.uniform(0, W), R.uniform(0, H), R.uniform(250, 520), R.uniform(0, 6.3), R.uniform(.05, .12)) for _ in range(5)]
        s.acc = np.array(hexc(CATS[cat]['acc'])[:3], np.float32); s.grid = s._grid()
        s.small = (W // 6, H // 6)
    def _grid(s):
        im = Image.new('L', (W, H), 0); d = ImageDraw.Draw(im)
        for x in range(0, W, 90): d.line([(x, 0), (x, H)], fill=10)
        for y in range(0, H, 90): d.line([(0, y), (W, y)], fill=10)
        return np.asarray(im, np.float32)[..., None] / 255
    def frame(s, t):
        sw, sh = s.small; yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32); glow = np.zeros((sh, sw), np.float32)
        for x0, y0, r, p, w in s.blobs:
            cx = (x0 + 120 * math.sin(t * w * 6.28 + p)) / 6; cy = (y0 + 160 * math.cos(t * w * 5 + p)) / 6
            glow += np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (r / 6) ** 2) * .16
        big = np.asarray(Image.fromarray((np.clip(glow, 0, 1) * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR), np.float32)[..., None] / 255
        img = s.base + big * s.acc * .55 + s.grid * 255 * .5
        return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).convert('RGBA')


def badge(d, cat, date, t):
    C = CATS[cat]; f = F('bold', 40); txt = C['ko']; w = f.getlength(txt) + 60; a = int(255 * ease(t / .5))
    d.rounded_rectangle([60, 120, 60 + w, 196], 38, fill=hexc(C['acc'], a)); d.text((90, 128), txt, font=f, fill=(10, 12, 20, a))
    if date: d.text((60 + w + 26, 132), date, font=F('medium', 36), fill=(255, 255, 255, int(a * .75)))


# ───────────────────────────── 아이콘 (직접 그리는 벡터 그림, 외부 이미지 없음)
def icon(d, kind, cx, cy, s, col, a=255):
    """kind 아이콘을 (cx, cy) 중심, 크기 s 로 그림"""
    c = col[:3] + (a,); c2 = col[:3] + (int(a * .28),); w = max(4, int(s * .07)); wh = (255, 255, 255, a); h = s / 2
    if kind in ('chart_up', 'chart_down', 'chart'):
        up = kind != 'chart_down'; d.rounded_rectangle([cx - h, cy - h, cx + h, cy + h], int(s * .16), fill=c2, outline=c, width=w)
        hs = [.35, .55, .75] if up else [.75, .55, .35]
        for i, f in enumerate(hs):
            x = cx - h * .62 + i * h * .5; d.rounded_rectangle([x, cy + h * .62 - s * f * .62, x + h * .32, cy + h * .62], 6, fill=c)
        pts = [(cx - h * .7, cy + (h * .1 if up else -h * .55)), (cx - h * .1, cy + (-h * .2 if up else -h * .15)), (cx + h * .15, cy + (-h * .05 if up else -h * .3)), (cx + h * .72, cy + (-h * .62 if up else h * .15))]
        d.line(pts, fill=wh, width=w, joint='curve'); ex, ey = pts[-1]
        d.polygon([(ex, ey), (ex - h * .3, ey + (h * .05 if up else -h * .22)), (ex - h * .08, ey + (h * .26 if up else -h * .02))] if up else [(ex, ey), (ex - h * .3, ey - h * .05), (ex - h * .1, ey - h * .26)], fill=wh)
    elif kind == 'coin':
        d.ellipse([cx - h, cy - h, cx + h, cy + h], fill=c, outline=wh, width=w); d.ellipse([cx - h * .72, cy - h * .72, cx + h * .72, cy + h * .72], outline=(255, 255, 255, int(a * .6)), width=max(3, w // 2))
        d.text((cx, cy + s * .02), '₩', font=F('black', int(s * .62)), fill=(20, 16, 6, a), anchor='mm')
    elif kind == 'won':
        for k in range(3): d.rounded_rectangle([cx - h + k * 10, cy - h * .55 + k * 16, cx + h * .8 + k * 10, cy + h * .35 + k * 16], 10, fill=c if k == 2 else c2, outline=c, width=max(3, w // 2))
        d.text((cx + 20, cy + 10), '₩', font=F('black', int(s * .4)), fill=(20, 16, 6, a), anchor='mm')
    elif kind == 'phone':
        d.rounded_rectangle([cx - h * .55, cy - h, cx + h * .55, cy + h], int(s * .12), fill=c2, outline=c, width=w)
        d.rounded_rectangle([cx - h * .4, cy - h * .78, cx + h * .4, cy + h * .66], 8, fill=(0, 0, 0, int(a * .4)))
        d.text((cx, cy - h * .06), '!', font=F('black', int(s * .58)), fill=c, anchor='mm'); d.ellipse([cx - 7, cy + h * .78, cx + 7, cy + h * .78 + 14], fill=c)
    elif kind == 'shield':
        d.polygon([(cx, cy - h), (cx + h * .85, cy - h * .6), (cx + h * .7, cy + h * .35), (cx, cy + h), (cx - h * .7, cy + h * .35), (cx - h * .85, cy - h * .6)], fill=c2, outline=c, width=w)
        d.line([(cx - h * .38, cy), (cx - h * .08, cy + h * .3), (cx + h * .42, cy - h * .3)], fill=c, width=int(w * 1.4), joint='curve')
    elif kind == 'snow':
        for k in range(6):
            ang = k * math.pi / 3; ex, ey = cx + h * math.cos(ang), cy + h * math.sin(ang); d.line([(cx, cy), (ex, ey)], fill=c, width=w)
            for sgn in (-1, 1):
                mx, my = cx + h * .6 * math.cos(ang), cy + h * .6 * math.sin(ang); d.line([(mx, my), (mx + h * .25 * math.cos(ang + sgn * .9), my + h * .25 * math.sin(ang + sgn * .9))], fill=c, width=max(3, w - 2))
    elif kind == 'plug':
        d.rounded_rectangle([cx - h * .45, cy - h * .35, cx + h * .45, cy + h * .45], 14, fill=c2, outline=c, width=w)
        for dx in (-.2, .2): d.rounded_rectangle([cx + h * dx - 6, cy - h * .85, cx + h * dx + 6, cy - h * .35], 5, fill=c)
        d.line([(cx, cy + h * .45), (cx, cy + h * .7), (cx + h * .5, cy + h * .95)], fill=c, width=w, joint='curve')
        d.polygon([(cx + 4, cy - h * .2), (cx - h * .14, cy + h * .08), (cx, cy + h * .08), (cx - 6, cy + h * .32), (cx + h * .16, cy - h * .02), (cx + 2, cy - h * .02)], fill=wh)
    elif kind == 'house':
        d.polygon([(cx, cy - h), (cx + h, cy - h * .05), (cx - h, cy - h * .05)], fill=c); d.rectangle([cx - h * .72, cy - h * .05, cx + h * .72, cy + h * .9], fill=c2, outline=c, width=w)
        d.rounded_rectangle([cx - h * .2, cy + h * .3, cx + h * .2, cy + h * .9], 6, fill=c)
    elif kind == 'fire':
        for sc_, col_, yo in ((1.0, c, 0), (.58, (255, 236, 170, a), h * .3)):
            r = h * sc_; pts = []
            for k in range(41):                                                          # 아래는 둥글고 위는 살짝 휘며 뾰족한 불꽃
                th = 2 * math.pi * k / 40; rr = r * (.62 + .38 * math.cos(th / 2) ** 0) * (1 - .55 * max(0, -math.sin(th)) ** .5)
                px_ = cx + r * .72 * math.cos(th) * (1 - .8 * max(0, -math.sin(th)) ** 1.6) + r * .18 * max(0, -math.sin(th)) ** 2
                py_ = cy + yo + r * .45 + r * .55 * math.sin(th) * (1 if math.sin(th) > 0 else 2.6)
                pts.append((px_, py_))
            d.polygon(pts, fill=col_)
    elif kind == 'drop':
        d.ellipse([cx - h * .7, cy - h * .1, cx + h * .7, cy + h * .95], fill=c); d.polygon([(cx, cy - h), (cx + h * .66, cy + h * .25), (cx - h * .66, cy + h * .25)], fill=c)
        d.ellipse([cx - h * .38, cy + h * .25, cx - h * .12, cy + h * .55], fill=(255, 255, 255, int(a * .7)))
    elif kind == 'calendar':
        d.rounded_rectangle([cx - h, cy - h * .8, cx + h, cy + h], 16, fill=c2, outline=c, width=w); d.rectangle([cx - h, cy - h * .8, cx + h, cy - h * .35], fill=c)
        for i in range(3):
            for j in range(3): d.rounded_rectangle([cx - h * .7 + i * h * .5, cy - h * .15 + j * h * .38, cx - h * .4 + i * h * .5, cy + h * .08 + j * h * .38], 4, fill=c if (i, j) == (1, 1) else (255, 255, 255, int(a * .5)))
    elif kind == 'building':
        d.pieslice([cx - h * .55, cy - h * 1.0, cx + h * .55, cy - h * .05], 180, 360, fill=c); d.rectangle([cx - h, cy - h * .45, cx + h, cy - h * .3], fill=c)
        for i in range(5): x = cx - h * .8 + i * h * .4; d.rectangle([x - 7, cy - h * .3, x + 7, cy + h * .7], fill=c)
        d.rectangle([cx - h * 1.05, cy + h * .7, cx + h * 1.05, cy + h * .9], fill=c)
    elif kind == 'bulb':
        d.ellipse([cx - h * .7, cy - h, cx + h * .7, cy + h * .4], fill=c2, outline=c, width=w); d.rounded_rectangle([cx - h * .32, cy + h * .4, cx + h * .32, cy + h * .9], 8, fill=c)
        for k in range(5): ang = math.pi * (1.1 + k * .2); d.line([(cx + h * .95 * math.cos(ang), cy - h * .3 + h * .95 * math.sin(ang)), (cx + h * 1.2 * math.cos(ang), cy - h * .3 + h * 1.2 * math.sin(ang))], fill=c, width=w)
    elif kind == 'search':
        d.ellipse([cx - h * .8, cy - h * .8, cx + h * .3, cy + h * .3], fill=c2, outline=c, width=int(w * 1.3)); d.line([(cx + h * .15, cy + h * .15), (cx + h * .8, cy + h * .8)], fill=c, width=int(w * 2))
    elif kind == 'bell':
        d.pieslice([cx - h * .7, cy - h * .9, cx + h * .7, cy + h * .5], 180, 360, fill=c); d.rectangle([cx - h * .7, cy - h * .2, cx + h * .7, cy + h * .45], fill=c)
        d.rounded_rectangle([cx - h * .9, cy + h * .4, cx + h * .9, cy + h * .58], 8, fill=c); d.ellipse([cx - h * .18, cy + h * .58, cx + h * .18, cy + h * .9], fill=c)
    else:                                                                                  # question
        d.ellipse([cx - h, cy - h, cx + h, cy + h], fill=c2, outline=c, width=w); d.text((cx, cy + s * .02), '?', font=F('black', int(s * .7)), fill=c, anchor='mm')


CAT_ICON = {'life': 'bulb', 'market': 'chart', 'stock': 'search', 'politics': 'building'}


# ───────────────────────────── 효과음 (직접 합성, 아주 작게)
def sfx(kind, sr=44100):
    R = np.random.default_rng(len(kind))
    if kind == 'whoosh':                                                                   # 장면 넘어갈 때 '휙'
        n = int(.42 * sr); t = np.arange(n) / sr; x = R.standard_normal(n).astype(np.float32)
        from scipy import signal
        out = np.zeros(n, np.float32); seg = n // 12
        for k in range(12):
            fc = 400 + 3800 * (k / 11) ** 1.4; sos = signal.butter(2, [fc * .7, min(fc * 1.4, 20000)], 'band', fs=sr, output='sos')
            out[k * seg:(k + 1) * seg] = signal.sosfilt(sos, x[k * seg:(k + 1) * seg])
        env = np.sin(np.pi * np.clip(t / .42, 0, 1)) ** 1.5; return (out * env * .5).astype(np.float32)
    if kind == 'pop':                                                                      # 항목 등장 '톡'
        n = int(.09 * sr); t = np.arange(n) / sr; f = 900 - 350 * t / .09
        return (np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t / .025) * .5).astype(np.float32)
    if kind == 'ding':                                                                     # 정답·큰 숫자 공개 '띵'
        n = int(1.3 * sr); t = np.arange(n) / sr
        return ((np.sin(2 * np.pi * 1318.5 * t) + .5 * np.sin(2 * np.pi * 2637 * t) + .3 * np.sin(2 * np.pi * 1975.5 * t)) * np.exp(-t / .35) * .28).astype(np.float32)
    if kind == 'tick':
        n = int(.04 * sr); t = np.arange(n) / sr; return (np.sin(2 * np.pi * 2000 * t) * np.exp(-t / .006) * .35).astype(np.float32)
    if kind == 'riser':                                                                    # 첫 화면 '슈욱'
        n = int(.8 * sr); t = np.arange(n) / sr; f = 200 + 900 * (t / .8) ** 2
        tone = np.sin(2 * np.pi * np.cumsum(f) / sr) * .25 + R.standard_normal(n) * .08
        return (tone * (t / .8) ** 2 * np.exp(-np.clip(t - .7, 0, 1) / .03)).astype(np.float32)
    return np.zeros(1, np.float32)


def reveal_times(sc, dur):
    """장면 안에서 항목이 나타나는 시각(초) — 효과음 위치"""
    k = sc['type']; p2t = lambda p: p * dur
    if k == 'bullets': n = len(sc['items']); return [0.05] + [p2t(i * .85 / n) for i in range(1, n)]
    if k == 'stats': n = len(sc['items']); return [0.05] + [p2t(i * .9 / (n * 1.3)) for i in range(1, n)]
    if k == 'bars': return [.05 + .25 * i for i in range(len(sc['items']))]
    if k == 'timeline': n = len(sc['items']); return [0.05] + [p2t(i * .9 / (n * 1.2)) for i in range(1, n)]
    return []


class Particles:
    """배경에 천천히 떠오르는 작은 빛 입자"""
    def __init__(s, cat, seed=1):
        R = np.random.default_rng(seed); s.col = hexc(CATS[cat]['acc'])[:3]
        s.p = [(R.uniform(0, W), R.uniform(0, H), R.uniform(2, 6), R.uniform(15, 45), R.uniform(0, 6.3), R.uniform(.25, .7)) for _ in range(34)]
    def draw(s, d, t):
        for x0, y0, r, v, ph, a in s.p:
            y = (y0 - v * t) % (H + 40) - 20; x = x0 + 18 * math.sin(t * .4 + ph); al = int(255 * a * (.5 + .5 * math.sin(t * 1.3 + ph)) * .5)
            d.ellipse([x - r, y - r, x + r, y + r], fill=s.col + (al,))


def ticker(d, items, t, cat, y=1712):
    """하단 시세 전광판 (오른쪽→왼쪽으로 흐름). items: ['코스피 5,002.87 ▼1.91%', ...]"""
    if not items: return
    f = F('bold', 38); gap = 70; widths = [f.getlength(x) for x in items]; total = sum(widths) + gap * len(items)
    d.rectangle([0, y, W, y + 66], fill=(0, 0, 0, 120)); d.rectangle([0, y, W, y + 3], fill=hexc(CATS[cat]['acc'], 140))
    x = -((t * 140) % total)
    while x < W:
        for txt, w in zip(items, widths):
            if x + w > 0 and x < W:
                col = hexc(UP) if '▲' in txt else hexc(DOWN) if '▼' in txt else (230, 232, 240, 255); d.text((x, y + 12), txt, font=f, fill=col)
            x += w + gap


def progress(d, segs, t, total, cat):
    """화면 맨 위, 장면 수만큼 나뉜 진행 막대 (스토리 형식)"""
    n = len(segs); gw = 8; seg_w = (W - 80 - gw * (n - 1)) / n; acc = hexc(CATS[cat]['acc'])
    for i, g in enumerate(segs):
        x = 40 + i * (seg_w + gw); f = min(1, max(0, (t - g['t0']) / g['dur']))
        d.rounded_rectangle([x, 44, x + seg_w, 52], 4, fill=(255, 255, 255, 60))
        if f > 0: d.rounded_rectangle([x, 44, x + max(8, seg_w * f), 52], 4, fill=acc)


def fade_layer(im, a):
    """RGBA 레이어 전체 투명도 조절"""
    if a >= .999: return im
    r, g, b, al = im.split(); al = al.point(lambda v: int(v * max(0, a))); return Image.merge('RGBA', (r, g, b, al))


def countup(v, t, dur=.8):
    """'5,002.87' · '8,813만원' 같은 숫자 문자열을 0부터 올라가게"""
    m = re.match(r'^([-+−]?)([\d,]*\.?\d+)(.*)$', str(v))
    if not m or t >= dur: return v
    num = float(m.group(2).replace(',', '')); dec = len(m.group(2).split('.')[1]) if '.' in m.group(2) else 0; cur = num * ease(t / dur)
    s_ = f'{cur:,.{dec}f}' if ',' in m.group(2) or num >= 1000 else f'{cur:.{dec}f}'; return m.group(1) + s_ + m.group(3)


# ───────────────────────────── 장면 그리기
def draw_scene(d, sc, cat, t, dur, words):
    C = CATS[cat]; acc = hexc(C['acc']); acc2 = hexc(C['acc2']); kind = sc['type']; p = t / max(dur, .1)
    top = 300; X0, MW = 70, W - 140
    if kind == 'hook':
        a = int(255 * ease(t / .4)); y = top
        ic = sc.get('icon', CAT_ICON.get(cat)); ia = ease((t - .05) / .5); bob = 10 * math.sin(t * 2.2)
        if ic and ia > 0:
            sz = 230 * (.6 + .4 * ease((t - .05) / .5)) + 18 * (1 - ease((t - .3) / .4)) * (ease(t / .3))
            d.ellipse([X0 + 115 - 150, y + 120 - 150 + bob, X0 + 115 + 150, y + 120 + 150 + bob], fill=hexc(C['acc'], int(40 * ia)))
            icon(d, ic, X0 + 115, y + 120 + bob, sz, hexc(C['acc']), int(255 * ia))
        y += 290
        if sc.get('kicker'): y = text_block(d, (X0, y), sc['kicker'], F('bold', 60), hexc(C['acc'], a), MW) + 24
        fT = F('black', 128); lines = wrap(sc['title'], fT, MW); lh = int(128 * 1.12); wi = 0
        for ln in lines:                                                                 # 제목 단어가 0.12초 간격으로 튀어나옴
            x = X0
            for wd in ln.split(' '):
                ap = ease((t - .15 - wi * .12) / .3); wi += 1
                if ap > 0:
                    dy = 40 * (1 - ap) - 14 * math.sin(math.pi * min(1, (t - .15 - (wi - 1) * .12) / .3)) * (ap < 1)
                    d.text((x + 4, y + dy + 6), wd, font=fT, fill=(0, 0, 0, int(120 * ap))); d.text((x, y + dy), wd, font=fT, fill=(255, 255, 255, int(255 * ap)))
                x += fT.getlength(wd + ' ')
            y += lh
        d.rounded_rectangle([X0, y + 40, X0 + 220 * ease((t - .5) / .6), y + 54], 7, fill=hexc(C['acc'], a))
        if sc.get('sub'): text_block(d, (X0, y + 76), sc['sub'], F('bold', 60), hexc('#d8dcef', int(255 * ease((t - .6) / .4))), MW)
    if sc.get('icon') and kind not in ('hook', 'end', 'quiz'):
        ia = ease(t / .4); icon(d, sc['icon'], X0 + MW - 46, top + 20 + 6 * math.sin(t * 2), 92, hexc(C['acc']), int(255 * ia))
    if kind == 'hook': pass
    elif kind == 'bullets':
        y = top + 40
        if sc.get('title'): y = text_block(d, (X0, y), sc['title'], F('black', 76), (255, 255, 255, 255), MW) + 40
        items = sc['items']; n = len(items)
        for i, it in enumerate(items):
            ap = ease((p * n - i * .85) / .35) if i else ease(t / .4)
            if ap <= 0: continue
            a = int(255 * ap); x = X0 + 40 * (1 - ap); head, _, rest = it.partition('|')
            fh, fr = F('bold', 64), F('medium', 46)
            hgt = len(wrap(head, fh, MW - 150)) * int(fh.size * 1.18) + (len(wrap(rest, fr, MW - 150)) * int(fr.size * 1.18) + 8 if rest else 0) + 56
            d.rounded_rectangle([x - 14, y, X0 + MW + 14, y + hgt], 32, fill=(255, 255, 255, int(16 * ap)), outline=hexc(C['acc'], int(70 * ap)), width=2)
            d.ellipse([x + 16, y + 28, x + 96, y + 108], fill=hexc(C['acc'], a)); d.text((x + 56, y + 68), str(i + 1), font=F('black', 50), fill=(10, 12, 20, a), anchor='mm')
            yy = text_block(d, (x + 124, y + 26), head, fh, (255, 255, 255, a), MW - 150)
            if rest: yy = text_block(d, (x + 124, yy + 8), rest, fr, hexc('#c8cde0', a), MW - 150, shadow=False)
            y += max(hgt, 136) + 30
    elif kind == 'stat':
        a = int(255 * ease(t / .4)); y = top + 120
        y = text_block(d, (X0, y), sc['label'], F('bold', 62), hexc('#d8dcef', a), MW, align='center') + 30
        v = sc['value']; fv = F('black', 170 if len(v) <= 7 else 130)
        m = re.match(r'^([-+]?[\d,]*\.?\d+)(.*)$', v)                                     # 숫자는 0부터 올라가는 카운트업
        if m and sc.get('count', v.endswith('%')):
            num = float(m.group(1).replace(',', '')); dec = len(m.group(1).split('.')[1]) if '.' in m.group(1) else 0
            cur = num * ease(t / 1.0); s = f'{cur:,.{dec}f}' if ',' in m.group(1) else f'{cur:.{dec}f}'; v = s + m.group(2)
        w = fv.getlength(v); d.text(((W - w) / 2 + 4, y + 6), v, font=fv, fill=(0, 0, 0, 120)); d.text(((W - w) / 2, y), v, font=fv, fill=(255, 255, 255, a))
        y += fv.size + 40
        if sc.get('change'):
            c = hexc(chg_color(sc['change']), a); txt = f"{arrow(sc['change'])} {sc['change']}"; f = F('black', 92); w = f.getlength(txt)
            d.rounded_rectangle([(W - w) / 2 - 40, y - 10, (W + w) / 2 + 40, y + 120], 30, fill=c[:3] + (int(a * .18),))
            d.text(((W - w) / 2, y), txt, font=f, fill=c); y += 160
        if sc.get('sub'): text_block(d, (X0, y + 10), sc['sub'], F('medium', 46), hexc('#c8cde0', a), MW, align='center')
    elif kind == 'stats':
        y = top + 30
        if sc.get('title'): y = text_block(d, (X0, y), sc['title'], F('black', 72), (255, 255, 255, 255), MW) + 30
        items = sc['items']; n = len(items)
        for i, it in enumerate(items):
            ap = ease((p * n * 1.3 - i * .9) / .3) if i else ease(t / .4); a = int(255 * ap)
            if ap <= 0: y += 250; continue
            xo = 90 * (1 - ap); lt_ = t - (i * .9 * dur / (n * 1.3) if i else 0)
            d.rounded_rectangle([X0 + xo, y, X0 + MW + xo, y + 220], 34, fill=(255, 255, 255, int(20 * ap)), outline=hexc(C['acc'], int(90 * ap)), width=3)
            d.rounded_rectangle([X0 + xo, y + 30, X0 + xo + 10, y + 190], 5, fill=hexc(chg_color(it['change']) if it.get('change') else C['acc'], a))
            d.text((X0 + 44 + xo, y + 34), it['label'], font=F('bold', 48), fill=hexc('#d8dcef', a))
            d.text((X0 + 44 + xo, y + 100), countup(it['value'], lt_), font=F('black', 86), fill=(255, 255, 255, a))
            if it.get('change'):
                c = hexc(chg_color(it['change']), a); txt = f"{arrow(it['change'])} {it['change']}"; f = F('black', 64)
                d.text((X0 + MW - 44 - f.getlength(txt) + xo, y + 112), txt, font=f, fill=c)
            y += 250
    elif kind == 'bars':
        y = top + 30
        if sc.get('title'): y = text_block(d, (X0, y), sc['title'], F('black', 70), (255, 255, 255, 255), MW) + 20
        if sc.get('unit'): d.text((X0, y), sc['unit'], font=F('medium', 38), fill=hexc('#aab0c8')); y += 70
        items = sc['items']; mx = max(abs(float(it['value'])) for it in items) or 1
        for i, it in enumerate(items):
            ap = ease((t - .25 * i) / 1.0); val = float(it['value']); col = hexc(it.get('color') or C['acc'])
            d.text((X0, y), it['label'], font=F('bold', 50), fill=(255, 255, 255, 255))
            bw = (MW - 10) * abs(val) / mx * ap; d.rounded_rectangle([X0, y + 72, X0 + max(bw, 14), y + 142], 20, fill=col)
            txt = it.get('text') or f"{val:g}"; f = F('black', 54)
            tx = X0 + bw + 20 if bw + 20 + f.getlength(txt) < MW else X0 + bw - f.getlength(txt) - 20
            d.text((tx, y + 76), txt, font=f, fill=(255, 255, 255, int(255 * ap)) if tx > X0 + bw else (10, 12, 20, int(255 * ap)))
            y += 200
        if sc.get('note'): text_block(d, (X0, y + 10), sc['note'], F('medium', 42), hexc('#c8cde0'), MW)
    elif kind == 'versus':
        y = top + 30
        if sc.get('title'): y = text_block(d, (X0, y), sc['title'], F('black', 70), (255, 255, 255, 255), MW, align='center') + 40
        colw = (MW - 30) / 2; fb = F('bold', 44)
        ch = max(140 + sum(len(wrap('·\u00a0' + ln, fb, colw - 68)) * int(fb.size * 1.22) + 30 for ln in side['points']) for side in sc['sides']) + 30
        for k, side in enumerate(sc['sides']):
            ap = ease((t - .3 - k * .6 * dur / 4) / .5) if k else ease((t - .2) / .5); a = int(255 * ap); x = X0 + k * (colw + 30); col = hexc(SIDE_A if k == 0 else SIDE_B)
            d.rounded_rectangle([x, y, x + colw, y + ch], 34, fill=col[:3] + (int(26 * ap),), outline=col[:3] + (int(160 * ap),), width=3)
            d.text((x + colw / 2, y + 70), side['name'], font=F('black', 56), fill=col[:3] + (a,), anchor='mm')
            yy = y + 140
            for ln in side['points']: yy = text_block(d, (x + 34, yy), '·\u00a0' + ln, fb, (255, 255, 255, a), colw - 68, 1.22) + 30
        if sc.get('note'): text_block(d, (X0, y + ch + 34), sc['note'], F('medium', 38), hexc('#aab0c8'), MW, align='center', shadow=False)
    elif kind == 'timeline':
        y = top + 30
        if sc.get('title'): y = text_block(d, (X0, y), sc['title'], F('black', 72), (255, 255, 255, 255), MW) + 40
        items = sc['items']; n = len(items); x = X0 + 40
        d.line([(x, y + 30), (x, y + 30 + (n - 1) * 190 * ease(t / 1.2))], fill=hexc(C['acc'], 160), width=6)
        for i, it in enumerate(items):
            ap = ease((p * n * 1.2 - i * .9) / .35) if i else ease(t / .4); a = int(255 * ap); yy = y + i * 190; now = it.get('now')
            r = 26 if now else 18; d.ellipse([x - r, yy + 30 - r, x + r, yy + 30 + r], fill=hexc(C['acc'] if now else '#ffffff', a))
            d.text((x + 60, yy), it['date'], font=F('black', 54), fill=hexc(C['acc'] if now else '#ffffff', a))
            text_block(d, (x + 60, yy + 70), it['text'], F('medium', 44), hexc('#d8dcef', a), MW - 120, shadow=False)
    elif kind == 'chart':                                                           # 주가 선 그래프: 왼쪽에서 오른쪽으로 그려짐
        y = top + 30
        if sc.get('title'): y = text_block(d, (X0, y), sc['title'], F('black', 70), (255, 255, 255, 255), MW) + 16
        if sc.get('unit'): d.text((X0, y), sc['unit'], font=F('medium', 38), fill=hexc('#aab0c8')); y += 66
        v = [float(x) for x in sc['values']]; n = len(v); lo, hi = min(v), max(v); rng = (hi - lo) or 1; gh = 640
        col = hexc(chg_color(v[-1] - v[0])); px = lambda i: X0 + 10 + (MW - 20) * i / (n - 1); py = lambda x: y + 100 + (gh - 160) * (1 - (x - lo) / rng)
        for k in range(5): yy = y + 100 + (gh - 160) * k / 4; d.line([(X0, yy), (X0 + MW, yy)], fill=(255, 255, 255, 22), width=2)
        m = max(2, int(n * ease(t / 1.6)))
        pts = [(px(i), py(v[i])) for i in range(m)]
        poly = pts + [(pts[-1][0], y + gh), (pts[0][0], y + gh)]; d.polygon(poly, fill=col[:3] + (34,))
        d.line(pts, fill=col, width=7, joint='curve')
        if sc.get('ma'):
            ma = [float(x) if x is not None else None for x in sc['ma']]; mp = [(px(i), py(ma[i])) for i in range(m) if ma[i] is not None]
            if len(mp) > 1: d.line(mp, fill=(255, 255, 255, 120), width=3)
        ex, ey = pts[-1]; d.ellipse([ex - 13, ey - 13, ex + 13, ey + 13], fill=col)
        ih, il = v.index(hi), v.index(lo)
        if m > ih: d.text((px(ih), py(hi) - 52), f"최고 {sc.get('fmt', '{:,.0f}').format(hi)}", font=F('bold', 36), fill=(255, 255, 255, 220), anchor='ms' if 0.15 < ih / n < .85 else ('ls' if ih / n <= .15 else 'rs'))
        if m > il: d.text((px(il), py(lo) + 56), f"최저 {sc.get('fmt', '{:,.0f}').format(lo)}", font=F('bold', 36), fill=(255, 255, 255, 220), anchor='ms' if 0.15 < il / n < .85 else ('ls' if il / n <= .15 else 'rs'))
        d.text((X0, y + gh + 14), sc.get('start', ''), font=F('medium', 34), fill=hexc('#aab0c8')); f = F('medium', 34); e = sc.get('end_label', '')
        d.text((X0 + MW - f.getlength(e), y + gh + 14), e, font=f, fill=hexc('#aab0c8'))
        if sc.get('note'): text_block(d, (X0, y + gh + 80), sc['note'], F('bold', 46), (255, 255, 255, int(255 * ease((t - 1.4) / .5))), MW)
    elif kind == 'quiz':                                                             # 퀴즈: 보기 → 남은 시간 원 → 정답 공개
        y = top + 20; a = int(255 * ease(t / .4)); rv = sc.get('reveal', dur * .62)
        d.rounded_rectangle([X0, y, X0 + 200, y + 70], 35, fill=hexc(C['acc'], a)); d.text((X0 + 100, y + 35), 'QUIZ', font=F('black', 44), fill=(10, 12, 20, a), anchor='mm')
        if t < rv:                                                                       # 남은 시간 원
            f_ = max(0, 1 - t / rv); cx, cy, r = X0 + MW - 60, y + 35, 50
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 60), width=10); d.arc([cx - r, cy - r, cx + r, cy + r], -90, -90 + 360 * f_, fill=hexc(C['acc']), width=10)
            d.text((cx, cy), str(max(1, math.ceil(rv - t))) if rv - t < 3.5 else '?', font=F('black', 46), fill=(255, 255, 255, 230), anchor='mm')
        y = text_block(d, (X0, y + 110), sc['question'], F('black', 78), (255, 255, 255, a), MW, 1.16) + 40
        for i, op in enumerate(sc['options']):
            ap = ease((t - .3 - .25 * i) / .35); right = i == sc['answer']; shown = t >= rv
            if ap <= 0: y += 160; continue
            col = hexc(C['acc']) if shown and right else (255, 255, 255)
            fa = int(255 * ap * (.35 if shown and not right else 1)); xo = 60 * (1 - ap)
            d.rounded_rectangle([X0 + xo, y, X0 + MW + xo, y + 130], 30, fill=col[:3] + (int((70 if shown and right else 18) * ap),), outline=col[:3] + (int(150 * ap),), width=4 if shown and right else 2)
            d.text((X0 + 50 + xo, y + 65), 'ABCD'[i], font=F('black', 56), fill=col[:3] + (fa,), anchor='mm')
            d.text((X0 + 100 + xo, y + 30), op, font=F('bold', 60), fill=(255, 255, 255, fa))
            if shown and right:
                sp = ease((t - rv) / .35); icon(d, 'shield', X0 + MW - 70, y + 65, 90 * (.5 + .5 * sp), hexc(C['acc']), int(255 * sp))
            y += 160
        if t >= rv and sc.get('explain'): text_block(d, (X0, y + 10), sc['explain'], F('bold', 50), hexc(C['acc2'], int(255 * ease((t - rv - .2) / .4))), MW)
    elif kind == 'end':
        a = int(255 * ease(t / .4)); y = top + 100
        y = text_block(d, (X0, y), sc.get('title', '오늘은 여기까지'), F('black', 96), (255, 255, 255, a), MW, align='center') + 40
        if sc.get('sub'): y = text_block(d, (X0, y), sc['sub'], F('bold', 52), hexc(C['acc'], a), MW, align='center') + 50
        if sc.get('disclaimer'):
            d.rounded_rectangle([X0, y, X0 + MW, y + 230], 26, fill=(255, 255, 255, 18)); text_block(d, (X0 + 34, y + 30), sc['disclaimer'], F('medium', 40), hexc('#c8cde0', a), MW - 68, shadow=False); y += 270
        else: y += 60
        ap = ease((t - .6) / .4); press = 1 - .08 * math.sin(math.pi * min(1, max(0, (t - 1.6) / .25)))      # 1.6초에 '꾹' 눌림
        if ap > 0:
            bw, bh = 470 * press, 120 * press; cx = W / 2; by = y + 30 + 30 * (1 - ap); done = t > 1.75
            d.rounded_rectangle([cx - bw / 2, by, cx + bw / 2, by + bh], int(bh / 2), fill=(70, 74, 92, int(255 * ap)) if done else (230, 40, 50, int(255 * ap)))
            d.text((cx + 30, by + bh / 2), '구독중' if done else '구독', font=F('black', int(58 * press)), fill=(255, 255, 255, int(255 * ap)), anchor='mm')
            icon(d, 'bell', cx - bw / 2 + 80, by + bh / 2, 64 * press, (255, 255, 255), int(255 * ap))
            if 1.6 < t < 2.3:                                                            # 누른 자리에 퍼지는 원
                r = 40 + 260 * (t - 1.6) / .7; d.ellipse([cx - r, by + bh / 2 - r, cx + r, by + bh / 2 + r], outline=(255, 255, 255, int(160 * (1 - (t - 1.6) / .7))), width=6)


def caption_chunks(words, maxchars=13):
    """단어들을 화면 한 줄(한글 약 13자)씩 묶음 → [(시작, 끝, [단어...])]"""
    out = []; cur = []
    for w in words:
        pause = cur and w[0] - cur[-1][1] > .22                                     # 말이 잠깐 쉬는 곳·문장 끝에서 자막도 끊음
        over = sum(len(x[2]) + 1 for x in cur) + len(w[2]) > maxchars + (3 if w[2].endswith('\u2063') and len(w[2]) <= 4 else 0)   # 문장 끝 짧은 말('원.')은 앞 줄에 붙임
        if cur and (over or cur[-1][2].endswith('\u2063') or pause): out.append(cur); cur = []
        cur.append(w)
    if cur: out.append(cur)
    return [(c[0][0], c[-1][1], c) for c in out]


def draw_caption(d, chunks, t, cat):
    acc = hexc(CATS[cat]['acc']); f = F('black', 76); y = 1530
    for i, (s, e, ws) in enumerate(chunks):
        nxt = chunks[i + 1][0] if i + 1 < len(chunks) else e + .4
        if s - .05 <= t < max(e + .25, min(nxt, e + .6)):
            parts = []
            for ws_, we_, tx in ws: parts.append((tx.rstrip('\u2063') + ' ', acc if ws_ <= t < we_ + .05 else (255, 255, 255, 255)))
            tw = sum(f.getlength(p) for p, _ in parts); x = (W - tw) / 2
            pop = ease((t - s) / .18); yy = y + 16 * (1 - pop)
            d.rounded_rectangle([x - 34, yy - 18, x + tw + 20, yy + 112], 28, fill=(0, 0, 0, int(160 * pop)))
            cx = x
            for p_, c_ in parts:                                                          # 지금 말하는 단어 뒤에 색 띠
                wpx = f.getlength(p_.rstrip())
                if c_ == acc: d.rounded_rectangle([cx - 10, yy - 4, cx + wpx + 10, yy + 98], 18, fill=acc[:3] + (70,))
                cx += f.getlength(p_)
            rich_line(d, (x, yy), parts, f); return


def make_thumb(S, cat, bg):
    """썸네일(1080x1920): 큰 아이콘 + 큰 제목 + 핵심 숫자. 반투명은 별도 레이어에 그려 합성"""
    C = CATS[cat]; base = bg.frame(3.0); ov = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(ov); hk = S['scenes'][0]; acc = hexc(C['acc'])
    d.rectangle([0, 0, W, H], fill=(0, 0, 0, 70)); badge(d, cat, S.get('date', ''), 9)
    d.ellipse([W / 2 - 230, 300, W / 2 + 230, 760], fill=acc[:3] + (55,)); base = Image.alpha_composite(base, ov)
    ov = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(ov); icon(d, hk.get('icon', CAT_ICON.get(cat)), W / 2, 530, 320, acc)
    title = S.get('thumb_title', hk.get('title', '')).replace('\n', '\n'); lines = title.split('\n') if '\n' in title else None
    size = 160
    while True:                                                                       # 줄이 3줄 이하·화면 폭 안에 들어올 때까지 글자 크기 줄임
        fT = F('black', size); ls = []
        for part in (lines or [title]): ls += wrap(part, fT, W - 120)
        if (len(ls) <= 3 and all(fT.getlength(x) <= W - 120 for x in ls) and not any(len(x) == 1 for x in ls)) or size <= 90: break
        size -= 10
    y = 840
    for ln in ls:
        w = fT.getlength(ln); d.text(((W - w) / 2, y), ln, font=fT, fill=(255, 255, 255), stroke_width=10, stroke_fill=(0, 0, 0)); y += int(size * 1.12)
    big = S.get('thumb_big')
    if big:
        col = hexc(chg_color(big)) if cat in ('market', 'stock') and re.search(r'\d%', big) else acc; f = F('black', 180); w = f.getlength(big)
        while w > W - 200: f = F('black', f.size - 10); w = f.getlength(big)
        bx0, by0, bx1, by1 = (W - w) / 2 - 50, y + 40, (W + w) / 2 + 50, y + 40 + f.size * 1.3
        box = Image.new('RGBA', (W, H), (0, 0, 0, 0)); ImageDraw.Draw(box).rounded_rectangle([bx0, by0, bx1, by1], 40, fill=(0, 0, 0, 170), outline=col[:3] + (255,), width=8)
        ov = Image.alpha_composite(box, ov); d = ImageDraw.Draw(ov); d.text((W / 2, (by0 + by1) / 2), big, font=f, fill=col, anchor='mm')
    elif hk.get('sub'): text_block(d, (60, y + 40), hk['sub'], F('bold', 72), acc, W - 120, align='center')
    return Image.alpha_composite(base, ov).convert('RGB')


# ───────────────────────────── 제작
def make(script_path, out_dir=None, keep=False, name=None, preview=None):
    """preview=[(장면번호, 장면 안 초), ...] 이면 영상 대신 그 순간들만 PNG 로 저장 (빠른 확인용)"""
    S = script_path if isinstance(script_path, dict) else json.loads(Path(script_path).read_text(encoding='utf-8')); cat = S['category']; C = CATS[cat]
    out = Path(out_dir) if out_dir else ROOT.parent / '_out'; out.mkdir(parents=True, exist_ok=True); name = name or (Path(script_path).stem if not isinstance(script_path, dict) else S.get('name', cat)); tmp = out / f'_{name}'; tmp.mkdir(exist_ok=True)
    voice = S.get('voice', C['voice']); rate = S.get('rate', C['rate']); sr = 44100; gap = .28
    # 1) 장면별 음성 + 단어 시간
    segs = []; t0 = 0.4
    for i, sc in enumerate(S['scenes']):
        mp3 = tmp / f's{i}.mp3'; words = tts(sc['say'], voice, rate, mp3); x = read_audio(mp3, sr)
        pos = 0; marked = []
        for a, b, w in words:                                                         # 대본에서 단어 위치를 찾아 뒤에 문장부호가 오면 표시
            j = sc['say'].find(w, pos); end = False
            if j >= 0:
                pos = j + len(w); nxt = sc['say'][pos:pos + 1]; end = nxt in '.?!,…' and nxt != ''
            marked.append((a, b, w + ('\u2063' if end else '')))
        words = marked
        dur = max(len(x) / sr, sc.get('min', 0)) + gap
        segs.append(dict(sc=sc, t0=t0, dur=dur, audio=x, words=[(a + t0, b + t0, w) for a, b, w in words])); t0 += dur
        print(f'  음성 {i + 1}/{len(S["scenes"])} · {dur:.1f}초 · {sc["say"][:30]}…', flush=True)
    for g in segs:                                                                  # 퀴즈: 대본의 '정답은' 다음 단어가 나오는 순간에 정답 공개
        if g['sc']['type'] == 'quiz' and 'reveal' not in g['sc']:
            ws = g['words']; k = next((i for i, w in enumerate(ws) if '정답' in w[2]), None)
            rv = (ws[k + 1][0] if k is not None and k + 1 < len(ws) else ws[k][1] if k is not None else g['dur'] * .62) - g['t0']
            g['sc'] = dict(g['sc'], reveal=round(rv, 2))
    total = t0 + .8
    if total > 60: print(f'  ⚠ 길이 {total:.1f}초 — 쇼츠는 60초 이하가 안전합니다. 대본을 줄이세요.', flush=True)
    # 2) 오디오: 목소리 + 배경음악(말할 때 작아짐)
    n = int(total * sr); voice_tr = np.zeros(n, np.float32)
    for g in segs: i0 = int(g['t0'] * sr); voice_tr[i0:i0 + len(g['audio'])] += g['audio'][:n - i0]
    env = np.convolve((np.abs(voice_tr) > .02).astype(np.float32), np.ones(int(.25 * sr)) / int(.25 * sr), 'same')
    music = bgm(C['bgm'], total, sr, seed=len(name)) * (.16 - .09 * np.clip(env * 3, 0, 1))
    fade = np.minimum(1, np.minimum(np.arange(n) / (.5 * sr), (n - np.arange(n)) / (1.2 * sr)))
    fx_tr = np.zeros(n, np.float32); FX = {k: sfx(k, sr) for k in ('whoosh', 'pop', 'ding', 'riser', 'tick')}
    def put(k, tsec, g=1.0):
        i0 = int(tsec * sr); x_ = FX[k]; j = min(n, i0 + len(x_))
        if 0 <= i0 < n: fx_tr[i0:j] += x_[:j - i0] * g
    put('riser', 0.0, .6)
    for i, g in enumerate(segs):
        if i: put('whoosh', g['t0'] - .12, .55)
        for rt in reveal_times(g['sc'], g['dur'])[1:]: put('pop', g['t0'] + rt, .5)
        if g['sc']['type'] == 'stat': put('ding', g['t0'] + .5, .35)
        if g['sc']['type'] == 'quiz':
            rv = g['sc'].get('reveal', g['dur'] * .62)
            for k in range(3): put('tick', g['t0'] + rv - 3 + k, .5)
            put('ding', g['t0'] + rv, .6)
        if g['sc']['type'] == 'end': put('pop', g['t0'] + 1.6, .7)
    mix = voice_tr / (np.abs(voice_tr).max() + 1e-9) * .9 + music * fade + fx_tr * .5; mix = np.tanh(mix * 1.1) / 1.1
    wav = tmp / 'mix.wav'
    with wave.open(str(wav), 'wb') as wf: wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr); wf.writeframes((np.clip(mix, -1, 1) * 32000).astype('<i2').tobytes())
    # 3) 화면
    bg = Background(cat, seed=len(name)); chunks = caption_chunks([w for g in segs for w in g['words']], S.get('caption_chars', 13))
    mp4 = out / f'{name}.mp4'
    ff = None if preview else subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-', '-i', str(wav),
                           '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', '-shortest', '-movflags', '+faststart', str(mp4)], stdin=subprocess.PIPE)
    nf = int(total * FPS); parts_ = Particles(cat, len(name)); TR = .34
    def scene_layer(g, lt):
        if 'dy' not in g:
            m = Image.new('RGBA', (W, H), (0, 0, 0, 0)); draw_scene(ImageDraw.Draw(m), g['sc'], cat, g['dur'] * 5, g['dur'], g['words']); bb = m.getbbox() or (0, 300, W, 900)
            g['dy'] = int(max(260 - bb[1], min(1470 - bb[3], (260 + 1470) / 2 - (bb[1] + bb[3]) / 2)))
        sl = Image.new('RGBA', (W, H), (0, 0, 0, 0)); draw_scene(ImageDraw.Draw(sl), g['sc'], cat, lt, g['dur'], g['words'])
        if g['dy'] == 0: return sl
        out_ = Image.new('RGBA', (W, H), (0, 0, 0, 0)); out_.alpha_composite(sl, (0, g['dy']) if g['dy'] >= 0 else (0, 0), (0, 0) if g['dy'] >= 0 else (0, -g['dy'])); return out_
    want = None if not preview else sorted({int((segs[i]['t0'] + lt_) * FPS) for i, lt_ in preview})
    for fi in (want or range(nf)):
        t = fi / FPS; img = bg.frame(t); lay = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
        gi = next((i for i, g in enumerate(segs) if g['t0'] <= t < g['t0'] + g['dur']), len(segs) - 1 if t >= segs[-1]['t0'] else 0); g = segs[gi]
        lt = t - g['t0']
        parts_.draw(d, t)
        badge(d, cat, S.get('date', ''), t)
        cur = scene_layer(g, lt)
        if gi and lt < TR:                                                              # 장면 전환: 앞 장면은 왼쪽으로, 새 장면은 오른쪽에서
            u = ease(lt / TR); pg = segs[gi - 1]
            if 'last' not in pg: pg['last'] = scene_layer(pg, pg['dur'] * 5)
            sh_ = int(W * .35 * u)
            if u < 1: lay.alpha_composite(fade_layer(pg['last'].crop((sh_, 0, W, H)), 1 - u), (0, 0))
            off = int(W * .35 * (1 - u)); lay.alpha_composite(fade_layer(cur.crop((0, 0, W - off, H)), u), (off, 0))
        else: lay.alpha_composite(cur)
        draw_caption(d, chunks, t, cat)
        progress(d, segs, t, total, cat)
        ticker(d, S.get('ticker'), t, cat)
        if S.get('source_line'): d.text((60, H - 96), S['source_line'], font=F('regular', 30), fill=(255, 255, 255, 120))
        frame = Image.alpha_composite(img, lay).convert('RGB')
        if preview: frame.save(out / f'{name}_p{fi:05d}.jpg', quality=90); continue
        ff.stdin.write(frame.tobytes())
    if preview:
        make_thumb(S, cat, bg).save(out / f'{name}_pthumb.jpg', quality=90); return sorted(out.glob(f'{name}_p*.jpg'))
    ff.stdin.close(); ff.wait()
    # 4) 썸네일 · 업로드 문구
    make_thumb(S, cat, bg).save(out / f'{name}_thumb.jpg', quality=92)
    yt = S.get('yt', {}); src = '\n'.join(f'- {x}' for x in S.get('sources', []))
    disc = S.get('disclaimer', '')
    body = f"{yt.get('title', S['scenes'][0].get('title', ''))}\n\n{yt.get('desc', '')}\n\n" + (f"📌 출처\n{src}\n\n" if src else '') + (f"⚠️ {disc}\n\n" if disc else '') + \
           "이 영상의 음성은 AI 음성(Microsoft 신경망 음성)이며, 화면과 배경음악은 채널이 직접 프로그램으로 만들었습니다.\n\n" + ' '.join('#' + x.replace(' ', '') for x in yt.get('tags', [])[:8])
    (out / f'{name}_youtube.txt').write_text(body + f"\n\n[태그] {', '.join(yt.get('tags', []))}", encoding='utf-8')
    if not keep:
        for x in tmp.iterdir(): x.unlink()
        tmp.rmdir()
    print(f'완료: {mp4} · {total:.1f}초', flush=True)
    return dict(mp4=mp4, thumb=out / f'{name}_thumb.jpg', txt=out / f'{name}_youtube.txt', title=yt.get('title', ''), body=body, tags=yt.get('tags', []), sec=round(total, 1))


if __name__ == '__main__':
    for p in sys.argv[1:]: make(p)

