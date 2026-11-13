# -*- coding: utf-8 -*-
"""Tkinter판 레트로 아이콘 생성기.

64x64 픽셀 그리드에 레트로 윈도우(네이비 타이틀 바 + 자막 화면)를
그려 NEAREST로 확대한다. 산출물: assets/app_tk.png (256px),
assets/app_tk.ico (멀티 사이즈).

사용법: python tools/make_tk_icon.py
"""

import os

from PIL import Image, ImageDraw

NAVY = (0, 0, 128, 255)
SILVER = (192, 192, 192, 255)
SILVER_DARK = (128, 128, 128, 255)
DARK = (64, 64, 64, 255)
WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)
YELLOW = (255, 232, 0, 255)
GRAY_LINE = (96, 96, 96, 255)


def draw_icon():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # --- 창 본체 + 베벨 ---
    d.rectangle([4, 6, 59, 57], fill=SILVER)
    d.line([(4, 6), (59, 6)], fill=WHITE, width=2)
    d.line([(4, 6), (4, 57)], fill=WHITE, width=2)
    d.line([(4, 56), (59, 56)], fill=DARK, width=2)
    d.line([(58, 6), (58, 57)], fill=DARK, width=2)
    d.line([(6, 54), (57, 54)], fill=SILVER_DARK, width=1)

    # --- 타이틀 바 ---
    d.rectangle([6, 8, 57, 16], fill=NAVY)
    d.rectangle([8, 11, 10, 13], fill=WHITE)  # 다이아몬드 로고 흉내
    # 우측 버튼 2개 (최소화/닫기)
    for bx in (46, 52):
        d.rectangle([bx, 9, bx + 4, 15], fill=SILVER)
        d.line([(bx, 9), (bx + 4, 9)], fill=WHITE)
        d.line([(bx, 9), (bx, 9 + 6)], fill=WHITE)
    d.line([(53, 11), (56, 14)], fill=BLACK)  # X 표시
    d.line([(53, 14), (56, 11)], fill=BLACK)
    d.line([(47, 13), (50, 13)], fill=BLACK)  # _ 표시

    # --- 자막 화면 (흰색, 함몰) ---
    d.rectangle([7, 18, 56, 44], outline=SILVER_DARK)
    d.rectangle([8, 19, 55, 43], fill=WHITE)
    # 대사 줄 3개 (가운데는 노란 하이라이트 = 현재 자막)
    d.rectangle([12, 22, 44, 24], fill=BLACK)
    d.rectangle([11, 27, 51, 31], fill=YELLOW)
    d.rectangle([13, 28, 47, 29], fill=BLACK)
    d.rectangle([12, 34, 38, 36], fill=GRAY_LINE)
    d.rectangle([12, 39, 41, 40], fill=GRAY_LINE)

    # --- 하단 캡션 바 (검정 + 흰 자막) ---
    d.rectangle([8, 46, 55, 53], fill=BLACK)
    d.rectangle([14, 48, 49, 49], fill=WHITE)
    d.rectangle([20, 51, 43, 51], fill=WHITE)

    return img


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assets = os.path.join(base_dir, "assets")
    icon64 = draw_icon()

    png256 = icon64.resize((256, 256), Image.NEAREST)
    png_path = os.path.join(assets, "app_tk.png")
    png256.save(png_path)

    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
             (128, 128), (256, 256)]
    frames = [icon64.resize(s, Image.NEAREST) if s != (256, 256)
              else png256 for s in sizes]
    ico_path = os.path.join(assets, "app_tk.ico")
    frames[-1].save(ico_path, format="ICO", sizes=sizes,
                    append_images=frames[:-1])
    print(f"wrote {png_path} ({os.path.getsize(png_path)} bytes)")
    print(f"wrote {ico_path} ({os.path.getsize(ico_path)} bytes)")


if __name__ == "__main__":
    main()
