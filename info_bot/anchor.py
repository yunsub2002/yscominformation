#!/usr/bin/env python3
"""가상 남성 앵커 '세모' — 채널 오리지널 캐릭터 (실존 인물 아님)
뉴스 스튜디오 + 앵커 상반신. 2배 크기로 그린 뒤 줄여서 선이 매끈함.
움직임: 입 모양 4단계(목소리 크기) · 눈 깜빡임 · 숨쉬듯 살짝 흔들림 · 말할 때 고개 끄덕임
Anchor(w, h).frame(t, mouth 0~1) → RGBA (s.panel = 오른쪽 화면 패널 영역, 호출하는 쪽에서 그림/글자를 채움)
"""
import math, os, random
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SS = 2
SKIN, SKIN_S, SKIN_D, SKIN_H = (244, 203, 170), (226, 176, 140), (200, 146, 112), (252, 222, 196)
HAIR, HAIR_M, HAIR_H = (28, 26, 32), (46, 42, 52), (88, 84, 100)
SUIT, SUIT_S, SUIT_H = (34, 50, 92), (22, 32, 62), (70, 96, 150)
SHIRT, SHIRT_S = (246, 248, 252), (210, 216, 228)
TIE, TIE_S, TIE_H = (190, 36, 52), (136, 22, 36), (226, 84, 96)


def _font(size):
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, 'fonts', 'NotoSansKR-Black.ttf'), os.path.join(here, 'fonts', 'NotoSansKR-Bold.ttf'),
              '/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc', 'C:/Windows/Fonts/malgunbd.ttf'):
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _blur_shape(size, draw_fn, r):
    """부드러운 그림자/빛 마스크"""
    m = Image.new('L', size, 0); draw_fn(ImageDraw.Draw(m)); return m.filter(ImageFilter.GaussianBlur(r))


class Anchor:
    def __init__(s, w=1080, h=640, name='AI 앵커 세모', role='세상의 모든 이야기 · 생활 지식', accent=(46, 230, 166), live='LIVE', font=None):
        global _font
        if font: _font = font
        s.w, s.h, s.name, s.role, s.acc, s.live = w, h, name, role, tuple(accent[:3]), live
        s.cx = int(w * .34); s.hy = int(h * .35)                             # 앵커 가로 위치 · 얼굴 중심 높이
        s.panel = (int(w * .62), int(h * .10), int(w * .965), int(h * .66))
        s.bg = s._studio(); s.body = s._body(); s.desk = s._desk(); s.heads = {}
    # ── 1) 스튜디오
    def _studio(s):
        k = SS; W, H = s.w * k, s.h * k; im = Image.new('RGBA', (W, H)); d = ImageDraw.Draw(im)
        for y in range(H):
            u = y / H; d.line([(0, y), (W, y)], fill=(int(8 + 18 * u), int(18 + 34 * u), int(44 + 62 * u), 255))
        R = random.Random(11); hz = int(H * .70)
        city = Image.new('RGBA', (W, H), (0, 0, 0, 0)); cd = ImageDraw.Draw(city); x = -20
        while x < W:                                                          # LED 벽의 도시 야경 (흐리게 → 깊이감)
            bw = R.randint(50, 130) * k // 2; bh = R.randint(120, 420) * k // 2
            cd.rectangle([x, hz - bh, x + bw, hz], fill=(30, 58, 118, 255))
            for wy in range(hz - bh + 16, hz - 12, 15 * k):
                for wx in range(x + 8, x + bw - 10, 12 * k):
                    if R.random() < .42: cd.rectangle([wx, wy, wx + 4 * k, wy + 5 * k], fill=(150, 205, 255, 255) if R.random() < .72 else (255, 214, 130, 255))
            x += bw + R.randint(3, 10) * k
        im.alpha_composite(city.filter(ImageFilter.GaussianBlur(2.2 * k)))
        glow = _blur_shape((W, H), lambda g: g.ellipse([W * -.05, H * .05, W * .72, H * 1.05], fill=150), 90 * k)    # 앵커 뒤 푸른 조명
        im = Image.composite(Image.new('RGBA', (W, H), (70, 130, 230, 255)), im, glow.point(lambda v: int(v * .45)))
        d = ImageDraw.Draw(im)
        for i in range(1, 8):                                                 # 세로 LED 패널 이음새
            xx = int(W * i / 8); d.line([(xx, 0), (xx, hz)], fill=(10, 20, 44, 255), width=2 * k)
        for i in range(3): d.line([(0, int(hz * (i + 1) / 4)), (W, int(hz * (i + 1) / 4))], fill=(10, 20, 44, 160), width=k)
        d.rectangle([0, hz, W, H], fill=(12, 22, 48, 255)); d.rectangle([0, hz, W, hz + 3 * k], fill=s.acc + (120,))
        for i in range(-2, 12): d.line([(W / 2 + i * 160 * k - 640 * k, H), (W / 2 + (i - 5) * 30 * k, hz)], fill=(20, 34, 68, 255), width=k)  # 바닥 원근선
        x0, y0, x1, y1 = [v * k for v in s.panel]                             # 오른쪽 화면 패널 (틀만 — 내용은 매 프레임)
        sh = _blur_shape((W, H), lambda g: g.rounded_rectangle([x0 + 6 * k, y0 + 14 * k, x1 + 6 * k, y1 + 18 * k], 22 * k, fill=200), 12 * k)
        im = Image.composite(Image.new('RGBA', (W, H), (0, 0, 0, 255)), im, sh.point(lambda v: int(v * .6))); d = ImageDraw.Draw(im)
        d.rounded_rectangle([x0 - 5 * k, y0 - 5 * k, x1 + 5 * k, y1 + 5 * k], 22 * k, fill=(14, 20, 34, 255))
        d.rounded_rectangle([x0, y0, x1, y1], 18 * k, fill=(14, 36, 80, 255))
        gl = _blur_shape((W, H), lambda g: g.ellipse([x0, y0 - (y1 - y0) * .2, x1, y1 * .9], fill=255), 40 * k)
        im = Image.composite(Image.new('RGBA', (W, H), (40, 96, 180, 255)), im, Image.composite(gl.point(lambda v: int(v * .5)), Image.new('L', (W, H), 0), _blur_shape((W, H), lambda g: g.rounded_rectangle([x0, y0, x1, y1], 18 * k, fill=255), 0)))
        return im
    # ── 2) 몸통 (어깨·양복·셔츠·넥타이)
    def _body(s):
        k = SS; W, H = s.w * k, s.h * k; im = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        P = lambda x, y: (s.cx * k + x * k, s.hy * k + y * k)
        d.polygon([P(-34, 70), P(34, 70), P(38, 150), P(-38, 150)], fill=SKIN_S)                                   # 목
        d.polygon([P(-34, 100), P(34, 100), P(36, 122), P(-36, 122)], fill=SKIN_D)
        sh = [P(-250, 400), P(-238, 230), P(-205, 182), P(-130, 156), P(-46, 138), P(46, 138), P(130, 156), P(205, 182), P(238, 230), P(250, 400)]
        d.polygon(sh, fill=SUIT)                                                                                     # 어깨·몸통
        d.line(sh[1:-1], fill=SUIT_H, width=3 * k, joint='curve')                                                    # 어깨 위 빛
        d.polygon([P(-46, 138), P(46, 138), P(0, 300)], fill=SHIRT)                                                  # 셔츠
        d.polygon([P(-46, 138), P(-14, 132), P(-4, 176), P(-30, 192)], fill=SHIRT); d.line([P(-46, 138), P(-30, 192), P(-4, 176)], fill=SHIRT_S, width=2 * k)   # 칼라
        d.polygon([P(46, 138), P(14, 132), P(4, 176), P(30, 192)], fill=SHIRT); d.line([P(46, 138), P(30, 192), P(4, 176)], fill=SHIRT_S, width=2 * k)
        d.polygon([P(-15, 150), P(15, 150), P(11, 176), P(-11, 176)], fill=TIE_S)                                    # 넥타이 매듭
        d.polygon([P(-11, 176), P(11, 176), P(26, 300), P(0, 324), P(-26, 300)], fill=TIE)
        for j in range(5): d.line([P(-20, 186 + j * 26), P(20, 200 + j * 26)], fill=TIE_H, width=2 * k)
        d.line([P(3, 178), P(10, 300)], fill=TIE_S, width=2 * k)
        for sx in (-1, 1):                                                                                           # 옷깃 (V자 라펠)
            d.polygon([P(sx * 46, 138), P(sx * 92, 152), P(sx * 70, 210), P(sx * 92, 226), P(sx * 30, 340), P(sx * 8, 320)], fill=SUIT_S)
            d.line([P(sx * 46, 138), P(sx * 92, 152), P(sx * 70, 210), P(sx * 92, 226), P(sx * 30, 340)], fill=SUIT_H, width=2 * k)
            d.line([P(sx * 150, 200), P(sx * 160, 400)], fill=SUIT_S, width=3 * k)                                   # 팔 경계선
        d.rounded_rectangle([*P(-150, 226), *P(-100, 232)], 2 * k, fill=(236, 238, 244))                             # 포켓치프
        d.ellipse([*P(112, 214), *P(126, 228)], fill=s.acc)                                                          # 배지
        d.ellipse([*P(-4, 350), *P(6, 360)], fill=SUIT_S)                                                            # 단추
        return im
    # ── 3) 책상 + 손 + 원고 (얼굴·몸 앞)
    def _desk(s):
        k = SS; W, H = s.w * k, s.h * k; im = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        dy = int(H * .86); P = lambda x, y: (s.cx * k + x * k, y)
        for sx in (-1, 1):                                                    # 팔: 어깨에서 내려와 책상 위 손으로
            arm = [P(sx * 205, s.hy * k + 182 * k), P(sx * 246, s.hy * k + 240 * k), P(sx * 236, dy + 10 * k), P(sx * 70, dy + 10 * k), P(sx * 96, dy - 40 * k), P(sx * 168, dy - 70 * k), P(sx * 176, s.hy * k + 250 * k)]
            d.polygon(arm, fill=SUIT); d.line(arm[:3], fill=SUIT_H, width=2 * k)
            d.line([P(sx * 176, s.hy * k + 250 * k), P(sx * 168, dy - 70 * k), P(sx * 96, dy - 40 * k)], fill=SUIT_S, width=3 * k, joint='curve')
            d.polygon([P(sx * 64, dy - 10 * k), P(sx * 98, dy - 30 * k), P(sx * 110, dy - 8 * k), P(sx * 74, dy + 10 * k)], fill=SHIRT)      # 커프스
        d.polygon([P(-130, dy - 20 * k), P(120, dy - 26 * k), P(138, dy + 8 * k), P(-142, dy + 12 * k)], fill=(250, 251, 253))              # 원고
        d.polygon([P(-122, dy - 28 * k), P(110, dy - 32 * k), P(120, dy - 22 * k), P(-128, dy - 18 * k)], fill=(232, 236, 244))
        for sx in (-1, 1):
            hx = s.cx * k + sx * 52 * k
            d.ellipse([hx - 30 * k, dy - 34 * k, hx + 30 * k, dy + 4 * k], fill=SKIN)
            d.ellipse([hx - 24 * k, dy - 30 * k, hx + 18 * k, dy - 8 * k], fill=SKIN_H)
            for f in range(3): d.line([(hx - 20 * k + f * 12 * k, dy - 4 * k), (hx - 16 * k + f * 12 * k, dy + 2 * k)], fill=SKIN_D, width=2 * k)
        d.rounded_rectangle([-20, dy, W + 20, H + 40], 14 * k, fill=(18, 34, 74))                                                       # 책상
        d.rectangle([-20, dy, W + 20, dy + 7 * k], fill=(110, 160, 235)); d.rectangle([-20, dy + 7 * k, W + 20, dy + 10 * k], fill=s.acc)
        for i in range(6): d.line([(W * i / 6 + 40 * k, dy + 24 * k), (W * i / 6 + 110 * k, dy + 24 * k)], fill=(40, 64, 120), width=2 * k)
        return im
    # ── 4) 얼굴 (눈 뜸/감음 × 입 0~3)
    def _face_pts(s, P, rx, rt, rb, n=72):
        pts = []
        for i in range(n):
            u = 2 * math.pi * i / n; c, sn = math.cos(u), math.sin(u)
            x = rx * c * (1 - .30 * max(0, sn) ** 2.2); y = (rb if sn > 0 else rt) * sn
            pts.append(P(x, y))
        return pts
    def _head(s, eye, mouth):
        key = (eye, mouth)
        if key in s.heads: return s.heads[key]
        k = SS; W, H = s.w * k, s.h * k; im = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        P = lambda x, y: (s.cx * k + x * k, s.hy * k + y * k); B = lambda x0, y0, x1, y1: [*P(x0, y0), *P(x1, y1)]
        rx, rt, rb = 84, 108, 112
        d.ellipse(B(-97, -140, 97, 14), fill=HAIR)                                            # 뒷머리 (관자놀이 빈틈 메움)
        for sx in (-1, 1):                                                                     # 귀
            d.ellipse(B(sx * 84 - 16, -22, sx * 84 + 16, 30), fill=SKIN_S); d.ellipse(B(sx * 84 - 8, -12, sx * 84 + 8, 20), fill=SKIN_D)
        d.polygon(s._face_pts(P, rx, rt, rb), fill=SKIN)                                       # 얼굴
        sh = Image.new('L', (W, H), 0); ImageDraw.Draw(sh).polygon(s._face_pts(lambda x, y: P(x + 18, y), rx, rt, rb), fill=255)   # 오른쪽 볼 그늘 (얼굴 안쪽만)
        fm = Image.new('L', (W, H), 0); ImageDraw.Draw(fm).polygon(s._face_pts(P, rx, rt, rb), fill=255)
        from PIL import ImageChops
        sm = ImageChops.subtract(fm, sh).filter(ImageFilter.GaussianBlur(6 * k)); sm = ImageChops.multiply(sm, fm)
        im = Image.composite(Image.new('RGBA', (W, H), SKIN_S + (255,)), im, sm.point(lambda v: int(v * .9))); d = ImageDraw.Draw(im)
        # 머리카락: 단정한 옆가르마 (왼쪽 가르마 → 오른쪽으로 넘김)
        top = [P(rx * 1.12 * math.cos(u) + 4 * math.sin(u * 2), -rt * 1.24 * abs(math.sin(u)) - 4) for u in [math.pi + i * math.pi / 30 for i in range(31)]]
        fringe = [P(94, -30), P(86, -64), P(66, -84), P(34, -90), P(4, -86), P(-26, -92), P(-46, -100), P(-62, -86), P(-80, -60), P(-94, -30)]
        d.polygon(top + fringe, fill=HAIR)
        for sx in (-1, 1): d.polygon([P(sx * 90, -30), P(sx * 86, 6), P(sx * 79, 6), P(sx * 78, -40)], fill=HAIR)   # 구레나룻
        d.line([P(-44, -130), P(-50, -98)], fill=(14, 12, 16), width=3 * k)                                       # 가르마 선
        d.line([P(-38, -128), P(10, -134), P(54, -120), P(82, -90)], fill=HAIR_M, width=6 * k, joint='curve')     # 결
        d.line([P(-24, -116), P(24, -122), P(62, -104)], fill=HAIR_H, width=4 * k, joint='curve')                  # 윤기
        d.line([P(-84, -74), P(-66, -110)], fill=HAIR_M, width=4 * k)
        # 눈썹 (살짝 각진 신뢰형)
        for sx in (-1, 1):
            d.polygon([P(sx * 14, -36), P(sx * 30, -42), P(sx * 56, -42), P(sx * 62, -36), P(sx * 56, -34), P(sx * 30, -33), P(sx * 16, -30)], fill=HAIR)
        # 눈
        for sx in (-1, 1):
            ex, ey = sx * 38, -8
            if eye:
                d.ellipse(B(ex - 17, ey - 10, ex + 17, ey + 10), fill=(255, 255, 255))
                d.ellipse(B(ex - 9, ey - 9, ex + 9, ey + 9), fill=(70, 50, 40)); d.ellipse(B(ex - 5, ey - 5, ex + 5, ey + 5), fill=(16, 12, 12))
                d.ellipse(B(ex + 1, ey - 6, ex + 5, ey - 2), fill=(255, 255, 255))
                d.arc(B(ex - 18, ey - 12, ex + 18, ey + 10), 195, 345, fill=(36, 26, 26), width=3 * k)              # 윗 속눈썹선
                d.arc(B(ex - 16, ey - 2, ex + 16, ey + 16), 220, 320, fill=SKIN_S, width=2 * k)                    # 쌍꺼풀 느낌
            else:
                d.arc(B(ex - 17, ey - 8, ex + 17, ey + 8), 15, 165, fill=(50, 34, 30), width=3 * k)
        # 코 (부드러운 그늘 + 콧볼)
        d.polygon([P(4, -6), P(12, 30), P(4, 38), P(-2, 34)], fill=SKIN_S)
        d.arc(B(-14, 26, 14, 42), 20, 160, fill=SKIN_D, width=2 * k)
        for sx in (-1, 1): d.ellipse(B(sx * 54 - 13, 22, sx * 54 + 13, 34), fill=(246, 170, 150))           # 볼 홍조
        # 입 (0 닫힘 · 1 조금 · 2 열림 · 3 크게)
        my = 64
        if mouth == 0:
            d.arc(B(-22, my - 12, 22, my + 6), 25, 155, fill=(150, 66, 60), width=3 * k)
        else:
            oh = (7, 14, 21)[mouth - 1]; ow = (16, 19, 21)[mouth - 1]
            d.chord(B(-ow, my - 8, ow, my + oh * 1.6), 0, 180, fill=(110, 34, 40)); d.rectangle(B(-ow, my - 8, ow, my - 4 + oh * .3), fill=(110, 34, 40)) if False else None
            d.rounded_rectangle(B(-ow, my - 6, ow, my + oh), 8 * k, fill=(110, 34, 40))
            d.rounded_rectangle(B(-ow + 3, my - 6, ow - 3, my - 6 + max(3, oh * .32)), 2 * k, fill=(252, 252, 252))   # 윗니
            if mouth >= 2: d.ellipse(B(-10, my + oh - 8, 10, my + oh), fill=(214, 104, 112))                           # 혀
            d.arc(B(-ow - 2, my - 12, ow + 2, my - 2), 200, 340, fill=(170, 84, 78), width=2 * k)                      # 윗입술
        d.arc(B(-16, my + 20, 16, my + 32), 20, 160, fill=SKIN_S, width=2 * k)                                         # 턱 밑 선
        s.heads[key] = im; return im
    # ── 5) 한 프레임
    def frame(s, t, mouth=0.0, talk=0.0):
        eye = 0 if ((t + .3) % 4.3) < .12 or ((t + 2.4) % 9.1) < .1 else 1
        m = 0 if mouth < .1 else 1 if mouth < .32 else 2 if mouth < .62 else 3
        breathe = 2.2 * math.sin(t * 1.25); nod = 3.0 * talk * math.sin(t * 5.3) ** 2
        k = SS; im = s.bg.copy()
        im.alpha_composite(s.body, (0, int(breathe * k * .6)))
        im.alpha_composite(s._head(eye, m), (int(1.5 * k * math.sin(t * .7)), int((breathe + nod) * k)))
        im.alpha_composite(s.desk)
        out = im.resize((s.w, s.h), Image.LANCZOS); d = ImageDraw.Draw(out)
        # 이름표 (왼쪽 아래, 책상 위)
        ly = int(s.h * .70); f1, f2 = _font(36), _font(22); nw = max(f1.getlength(s.name), f2.getlength(s.role)) + 64
        d.rounded_rectangle([28, ly + 4, 28 + nw + 6, ly + 94], 10, fill=(0, 0, 0, 90))
        d.rounded_rectangle([24, ly, 24 + nw, ly + 88], 10, fill=(255, 255, 255, 246)); d.rounded_rectangle([24, ly, 36, ly + 88], 4, fill=s.acc + (255,))
        d.text((54, ly + 6), s.name, font=f1, fill=(12, 18, 38)); d.text((54, ly + 54), s.role, font=f2, fill=(84, 92, 112))
        # LIVE 표시 (왼쪽 위)
        if s.live:
            on = (t % 1.2) < .8; f = _font(26); lw = f.getlength(s.live) + 54
            d.rounded_rectangle([24, 20, 24 + lw, 62], 8, fill=(220, 30, 44, 235))
            if on: d.ellipse([38, 34, 52, 48], fill=(255, 255, 255))
            d.text((60, 41), s.live, font=f, fill=(255, 255, 255), anchor='lm')
        return out


if __name__ == '__main__':
    a = Anchor()
    for i, (t, m) in enumerate([(0.5, 0), (1, .45), (2, .9), (4.35, .2)]): a.frame(t, m, 1).convert('RGB').save(f'/home/claude/anchor/a{i}.jpg', quality=92)
