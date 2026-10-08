#!/usr/bin/env python3
"""Generate per-post Open Graph images and wire them into each blog post.

For every card in blog.html this script:
  1. renders images/og/<slug>.jpg (1200x630, VidyBack gradient + post title)
     if it doesn't exist yet (or always, with --force);
  2. makes the post's <head> point og:image / twitter:image at it, and adds
     any missing og:image:width/height/alt, og:url and twitter:* tags plus
     an "image" entry in the BlogPosting JSON-LD.

It is idempotent: run it after adding a post and only the new post changes.

    python3 scripts/og_images.py            # new posts only
    python3 scripts/og_images.py --force    # re-render every image

Requires Pillow (pip install pillow). The Outfit font (SIL OFL) is bundled
in scripts/fonts so no network access is needed.
"""
import argparse
import html
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = 'https://www.vidyback.com'
FONT = os.path.join(ROOT, 'scripts', 'fonts', 'Outfit-Variable.ttf')
LOGO = os.path.join(ROOT, 'images', 'logo.png')
OUT_DIR = os.path.join(ROOT, 'images', 'og')
W, H = 1200, 630
PAD = 72

# Same stops as the site's hero gradients (#1d5175 -> #7a42f4).
GRAD_FROM = (29, 81, 117)
GRAD_TO = (122, 66, 244)
GOLD = (245, 166, 35)


def font(size, weight):
    f = ImageFont.truetype(FONT, size)
    f.set_variation_by_axes([weight])
    return f


def gradient():
    # Diagonal blend: build a 1-D ramp and stretch it, cheaper than per-pixel.
    ramp = Image.linear_gradient('L').resize((W, H))
    diag = Image.linear_gradient('L').rotate(90).resize((W, H))
    mask = Image.blend(ramp, diag, 0.5).point(lambda v: min(255, int(v * 1.15)))
    img = Image.composite(Image.new('RGB', (W, H), GRAD_TO), Image.new('RGB', (W, H), GRAD_FROM), mask)
    # Soft decorative circles, like the site's hero sections.
    glow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((W - 380, -220, W + 220, 380), fill=(255, 255, 255, 22))
    g.ellipse((W - 250, H - 170, W + 130, H + 210), fill=(245, 166, 35, 34))
    img.paste(glow, (0, 0), glow)
    return img


def wrap(draw, text, fnt, max_w):
    words, lines, line = text.split(), [], ''
    for w in words:
        trial = (line + ' ' + w).strip()
        if draw.textlength(trial, font=fnt) <= max_w or not line:
            line = trial
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def fit_title(draw, title, max_w, max_h):
    for size in range(76, 39, -2):
        fnt = font(size, 800)
        lines = wrap(draw, title, fnt, max_w)
        line_h = int(size * 1.18)
        if len(lines) <= 4 and len(lines) * line_h <= max_h:
            return fnt, lines, line_h
    # Very long title: clamp to 4 lines at the minimum size.
    fnt = font(40, 800)
    lines = wrap(draw, title, fnt, max_w)
    if len(lines) > 4:
        lines = lines[:4]
        while draw.textlength(lines[3] + '...', font=fnt) > max_w and ' ' in lines[3]:
            lines[3] = lines[3].rsplit(' ', 1)[0]
        lines[3] += '...'
    return fnt, lines, int(40 * 1.18)


def render(title, category, path):
    img = gradient()
    d = ImageDraw.Draw(img)

    # Brand row: logo + wordmark
    logo = Image.open(LOGO).convert('RGBA')
    lh = 52
    logo = logo.resize((int(logo.width * lh / logo.height), lh), Image.LANCZOS)
    tile = Image.new('RGBA', (logo.width + 20, lh + 20), (255, 255, 255, 0))
    td = ImageDraw.Draw(tile)
    td.rounded_rectangle((0, 0, tile.width - 1, tile.height - 1), 14, fill=(255, 255, 255, 255))
    tile.paste(logo, (10, 10), logo)
    img.paste(tile, (PAD, PAD - 10), tile)
    word = font(40, 700)
    wx = PAD + tile.width + 18
    d.text((wx, PAD + 16), 'VidyBack', font=word, fill='white', anchor='lm')

    # Category pill (top right)
    if category:
        pf = font(24, 600)
        label = category.upper()
        tw = d.textlength(label, font=pf)
        x1 = W - PAD
        x0 = x1 - tw - 40
        d.rounded_rectangle((x0, PAD - 6, x1, PAD + 38), 22, fill=GOLD)
        d.text(((x0 + x1) / 2, PAD + 16), label, font=pf, fill=(26, 37, 53), anchor='mm')

    # Title, vertically centred in the space between brand row and footer
    top, bottom = PAD + 90, H - PAD - 70
    fnt, lines, line_h = fit_title(d, title, W - PAD * 2 - 40, bottom - top)
    y = top + (bottom - top - line_h * len(lines)) // 2
    for ln in lines:
        d.text((PAD, y), ln, font=fnt, fill='white')
        y += line_h

    # Footer
    ff = font(26, 500)
    d.line((PAD, H - PAD - 34, PAD + 64, H - PAD - 34), fill=GOLD, width=5)
    d.text((PAD, H - PAD + 4), 'vidyback.com/blog', font=ff, fill=(255, 255, 255), anchor='ls')
    d.text((W - PAD, H - PAD + 4), 'Social media automation for ecommerce', font=ff, fill=(225, 225, 245), anchor='rs')

    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, 'JPEG', quality=88, optimize=True, progressive=True)


def blog_cards():
    src = open(os.path.join(ROOT, 'blog.html'), encoding='utf-8').read()
    for art in re.findall(r'<article class="blog-card"[^>]*>(.*?)</article>', src, re.S):
        href = re.search(r'<a href="([^"]+)" class="read-more-btn"', art)
        title = re.search(r'<h3>(.*?)</h3>', art, re.S)
        cat = re.search(r'blog-card-cat-badge[^"]*">([^<]+)<', art)
        if not href or not title:
            continue
        slug = href.group(1).split('/')[-1]
        slug = slug[:-5] if slug.endswith('.html') else slug
        yield slug, html.unescape(re.sub(r'\s+', ' ', title.group(1)).strip()), (cat.group(1).strip() if cat else '')


def meta_re(attr, key):
    return re.compile(r'([ \t]*)<meta\s+%s="%s"\s+content="([^"]*)"\s*/?>' % (attr, re.escape(key)))


def get_meta(s, attr, key):
    m = meta_re(attr, key).search(s)
    return m.group(2) if m else None


def set_meta(s, attr, key, value, after):
    """Replace a meta tag's content, or insert it after the first tag in `after` that exists."""
    tag = '<meta %s="%s" content="%s">' % (attr, key, value)
    m = meta_re(attr, key).search(s)
    if m:
        return s[:m.start()] + m.group(1) + tag + s[m.end():]
    for a_attr, a_key in after:
        a = meta_re(a_attr, a_key).search(s)
        if a:
            return s[:a.end()] + '\n' + a.group(1) + tag + s[a.end():]
    # Fall back to just before </head>
    i = s.index('</head>')
    return s[:i] + '    ' + tag + '\n' + s[i:]


def patch_post(path, slug, title):
    s = open(path, encoding='utf-8').read()
    orig = s
    img_url = '%s/images/og/%s.jpg' % (SITE, slug)
    canon = re.search(r'<link rel="canonical" href="([^"]+)"', s)
    page_url = canon.group(1) if canon else '%s/%s' % (SITE, slug)
    og_title = get_meta(s, 'property', 'og:title') or html.escape(title, quote=True)
    og_desc = get_meta(s, 'property', 'og:description') or get_meta(s, 'name', 'description') or ''
    alt = html.escape(title, quote=True)

    s = set_meta(s, 'property', 'og:image', img_url, [('property', 'og:site_name'), ('property', 'og:type')])
    s = set_meta(s, 'property', 'og:image:width', '1200', [('property', 'og:image')])
    s = set_meta(s, 'property', 'og:image:height', '630', [('property', 'og:image:width')])
    s = set_meta(s, 'property', 'og:image:alt', alt, [('property', 'og:image:height')])
    if not get_meta(s, 'property', 'og:url'):
        s = set_meta(s, 'property', 'og:url', page_url, [('property', 'og:description'), ('property', 'og:title')])
    if not get_meta(s, 'name', 'twitter:card'):
        s = set_meta(s, 'name', 'twitter:card', 'summary_large_image', [('property', 'og:url')])
    if not get_meta(s, 'name', 'twitter:site'):
        s = set_meta(s, 'name', 'twitter:site', '@vidyback', [('name', 'twitter:card')])
    if not get_meta(s, 'name', 'twitter:title'):
        s = set_meta(s, 'name', 'twitter:title', og_title, [('name', 'twitter:site'), ('name', 'twitter:card')])
    if og_desc and not get_meta(s, 'name', 'twitter:description'):
        s = set_meta(s, 'name', 'twitter:description', og_desc, [('name', 'twitter:title')])
    s = set_meta(s, 'name', 'twitter:image', img_url, [('name', 'twitter:description'), ('name', 'twitter:title')])

    # BlogPosting JSON-LD: add "image" right after "headline" if it's missing.
    def add_ld_image(m):
        block = m.group(0)
        if '"BlogPosting"' not in block or re.search(r'"image"\s*:', block):
            return block
        return re.sub(r'(\n([ \t]*)"headline"\s*:\s*"(?:[^"\\]|\\.)*",)',
                      lambda h: h.group(1) + '\n' + h.group(2) + '"image": "' + img_url + '",', block, count=1)
    s = re.sub(r'<script type="application/ld\+json">.*?</script>', add_ld_image, s, flags=re.S)

    if s != orig:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(s)
        return True
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--force', action='store_true', help='re-render images that already exist')
    args = ap.parse_args()

    missing = []
    for slug, title, cat in blog_cards():
        path = os.path.join(ROOT, slug + '.html')
        if not os.path.exists(path):
            missing.append(slug)
            continue
        out = os.path.join(OUT_DIR, slug + '.jpg')
        made = False
        if args.force or not os.path.exists(out):
            render(title, cat, out)
            made = True
        patched = patch_post(path, slug, title)
        if made or patched:
            print('%-60s %s%s' % (slug, 'image ' if made else '', 'head' if patched else ''))
    if missing:
        print('WARNING: blog.html links to missing files: ' + ', '.join(missing), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
