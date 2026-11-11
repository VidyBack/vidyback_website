#!/usr/bin/env python3
"""Turn Markdown articles in content/blog/ into live blog posts.

Articles arrive as content/blog/<slug>.md (written by the /mcp endpoint in
netlify/functions/mcp.mjs when Frekto publishes, or added by hand). For
every .md file whose <slug>.html doesn't exist yet, this script:

  1. applies VidyBack's brand rules to the text (no em dashes; drops
     WooCommerce, Squarespace and LinkedIn from lists) and reports any
     mention it couldn't remove safely;
  2. renders <slug>.html from the post template, the same layout as
     every other post;
  3. adds the blog.html card, the sitemap.xml entry and the
     netlify.toml .html -> clean URL redirect.

Run scripts/og_images.py and scripts/update_feed.py afterwards for the
share image and RSS entry (the publish-blog workflow does all three).

The .md file format is front matter with JSON-encoded values, then the
article as Markdown (raw HTML is passed through):

    ---
    title: "Post title"
    description: "Meta description"
    category: "social"            # social | ecommerce | automation
    image: "https://..."          # optional cover image
    tags: ["optional", "tags"]
    ---
    Article body in Markdown...

    python3 scripts/publish_blog.py            # build every unbuilt post
    python3 scripts/publish_blog.py --dry-run  # report only, write nothing

Requires the `markdown` package (pip install markdown).
"""
import argparse
import glob
import html
import json
import os
import re
import sys
from datetime import datetime, timezone

import markdown

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT_DIR = os.path.join(ROOT, 'content', 'blog')
SITE = 'https://www.vidyback.com'
# A known-good post to copy the page layout from (falls back to the newest post).
TEMPLATE = 'online-marketing-platform-for-small-businesses.html'

CATEGORIES = {
    'social': ('social', 'Social Media'),
    'ecommerce': ('ecommerce', 'Ecommerce Growth'),
    'automation': ('automation', 'Automation'),
}
# Cover photos already used on the blog, by category, for posts sent without one.
DEFAULT_IMAGES = {
    'social': ('4549413', 'Small business owner posting product content from a laptop and phone'),
    'ecommerce': ('3183150', 'Small team planning their marketing tools around a laptop'),
    'automation': ('733758', 'Laptop beside hourglass representing time saved through automation'),
}
WORDS_PER_MINUTE = 230


# ---------------------------------------------------------------- parsing

def read_article(path):
    raw = open(path, encoding='utf-8').read().lstrip('﻿')
    meta, body = {}, raw
    m = re.match(r'---\s*\n(.*?)\n---\s*\n?(.*)', raw, re.S)
    if m:
        body = m.group(2)
        for line in m.group(1).splitlines():
            if ':' not in line or line.lstrip().startswith('#'):
                continue
            key, val = line.split(':', 1)
            val = val.split(' #')[0].strip() if not val.strip().startswith(('"', '[')) else val.strip()
            try:
                meta[key.strip()] = json.loads(val)
            except ValueError:
                meta[key.strip()] = val.strip('"\'')
    return meta, body.strip()


def slugify(text):
    s = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
    return s[:80].rstrip('-') or 'post'


def norm_category(value):
    v = (value or '').lower()
    if 'ecom' in v or 'growth' in v or 'sales' in v:
        return 'ecommerce'
    if 'auto' in v:
        return 'automation'
    return 'social'


# ------------------------------------------------------------ brand rules

BANNED = r'(?:WooCommerce|Squarespace|LinkedIn)'


def brand_fix(text):
    """Apply the brand rules a machine can apply safely. Returns (text, warnings)."""
    # Em dashes (and spaced en dashes) become commas.
    text = re.sub(r'\s*—\s*', ', ', text)
    text = re.sub(r'\s+–\s+', ', ', text)
    # "A, B, C and LinkedIn" -> "A, B and C"
    text = re.sub(r', ([^,\n]+?),? (and|or) ' + BANNED + r'\b', r' \2 \1', text)
    # "Shopify and WooCommerce" -> "Shopify"
    text = re.sub(r'(\w[\w.)]*) (?:and|or|&) ' + BANNED + r'\b', r'\1', text)
    # "WooCommerce, Wix" / "Wix, WooCommerce" -> "Wix"
    text = re.sub(BANNED + r', ', '', text)
    text = re.sub(r', ' + BANNED + r'\b', '', text)
    warnings = sorted(set(re.findall(BANNED, text)))
    if warnings:
        lines = [l.strip() for l in text.splitlines() if re.search(BANNED, l)]
        warnings = ['Still mentions %s: "%s"' % (w, next((l for l in lines if w in l), '')[:160]) for w in warnings]
    return text, warnings


# --------------------------------------------------------------- building

def esc(s):
    return html.escape(s, quote=True)


def template_path():
    p = os.path.join(ROOT, TEMPLATE)
    if os.path.exists(p):
        return p
    blog = open(os.path.join(ROOT, 'blog.html'), encoding='utf-8').read()
    last = re.findall(r'<a href="([^"]+)" class="read-more-btn"', blog)[-1]
    return os.path.join(ROOT, last.split('/')[-1].replace('.html', '') + '.html')


def meta_content(s, attr, key):
    m = re.search(r'<meta %s="%s" content="([^"]*)">' % (attr, re.escape(key)), s)
    return m.group(1) if m else None


def article_html(body_md, title):
    html_body = markdown.markdown(body_md, extensions=['tables', 'sane_lists', 'fenced_code'])
    # The page already has the title as its <h1>: drop a leading duplicate,
    # and demote any other h1 so there's exactly one per page.
    html_body = re.sub(r'^\s*<h1>(.*?)</h1>\s*', lambda m: '' if html.unescape(re.sub('<[^>]+>', '', m.group(1))).strip().lower() == title.strip().lower() else m.group(0), html_body, count=1)
    html_body = re.sub(r'<(/?)h1>', r'<\1h2>', html_body)
    html_body = re.sub(r'<table>', '<div class="table-wrap"><table>', html_body)
    html_body = html_body.replace('</table>', '</table></div>')
    html_body = re.sub(r'<a href="(https?://(?!www\.vidyback\.com|vidyback\.com)[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', html_body)
    return '\n'.join('            ' + l if l.strip() else '' for l in html_body.splitlines())


def build_page(tpl, slug, title, desc, cat_key, image, image_alt, body_md, today):
    s = tpl
    old_title = meta_content(s, 'property', 'og:title')
    old_desc = meta_content(s, 'name', 'description')
    old_slug = re.search(r'<link rel="canonical" href="%s/([^"]+)">' % re.escape(SITE), s).group(1)
    old_date = re.search(r'"datePublished": "([^"]+)"', s).group(1)

    # Drop every JSON-LD block except BlogPosting (e.g. the template's FAQPage).
    s = re.sub(r'\s*<script type="application/ld\+json">\s*\{\s*"@context": "https://schema.org",\s*"@type": "(?!BlogPosting)[^"]+".*?</script>', '', s, flags=re.S)

    s = s.replace(old_slug, slug).replace(old_title, esc(title)).replace(old_desc, esc(desc))
    s = s.replace(old_date, today.strftime('%Y-%m-%d'))
    s = re.sub(r'<title>.*?</title>', '<title>%s | VidyBack</title>' % esc(title), s, count=1, flags=re.S)
    s = re.sub(r'(<meta property="og:image:alt" content=")[^"]*', lambda m: m.group(1) + esc(title), s, count=1)

    label = CATEGORIES[cat_key][1]
    s = re.sub(r'<span class="post-cat-badge">[^<]*</span>', '<span class="post-cat-badge">%s</span>' % label, s, count=1)
    s = re.sub(r'<h1>.*?</h1>', '<h1>%s</h1>' % esc(title), s, count=1, flags=re.S)
    s = re.sub(r'(<i class="fa-regular fa-calendar"></i> )[A-Z][a-z]+ \d{1,2}, \d{4}', lambda m: m.group(1) + today.strftime('%B %-d, %Y'), s, count=1)
    words = len(re.sub(r'<[^>]+>|[#*_>`|-]', ' ', body_md).split())
    minutes = max(1, round(words / WORDS_PER_MINUTE))
    s = re.sub(r'<i class="fa-regular fa-clock"></i> \d+ min read', '<i class="fa-regular fa-clock"></i> %d min read' % minutes, s, count=1)
    s = re.sub(r'<img class="post-cover" src="[^"]*" alt="[^"]*">', '<img class="post-cover" src="%s" alt="%s">' % (esc(image), esc(image_alt)), s, count=1)

    start = s.index('<article class="post-body">') + len('<article class="post-body">')
    cta = s.index('<!-- Post CTA -->', start)
    cta_end = s.index('</div>', s.index('class="btn btn-primary"', cta)) + len('</div>')
    generic_cta = '''<!-- Post CTA -->
            <div class="post-cta">
                <h3>Turn Your Products Into Ready-to-Post Videos</h3>
                <p>VidyBack turns your product catalog into short videos and posts, and schedules them across Instagram, TikTok, Facebook, YouTube and Pinterest.</p>
                <a href="https://app.vidyback.com/" target="_blank" rel="noopener" class="btn btn-primary"><span>Try VidyBack Free <i class="fa-solid fa-rocket"></i></span></a>
            </div>'''
    s = s[:start] + '\n' + article_html(body_md, title) + '\n\n            ' + generic_cta + s[cta_end:]
    return s, minutes


def add_card(slug, title, desc, cat_key, image, image_alt, minutes, today):
    p = os.path.join(ROOT, 'blog.html')
    s = open(p, encoding='utf-8').read()
    nums = [int(n) for n in re.findall(r'<!-- Card (\d+) -->', s)]
    last = list(re.finditer(r'<article class="blog-card".*?</article>\n', s, re.S))[-1]
    card_img = re.sub(r'w=\d+', 'w=800', image) if 'images.pexels.com' in image else image
    data_cat, label = CATEGORIES[cat_key]
    summary = desc if len(desc) <= 200 else desc[:197].rsplit(' ', 1)[0] + '...'
    card = '''
                <!-- Card %d -->
                <article class="blog-card" data-cat="%s">
                    <div class="blog-card-img-wrap">
                        <img class="blog-card-img" src="%s" alt="%s" loading="lazy">
                        <span class="blog-card-cat-badge cat-%s">%s</span>
                    </div>
                    <div class="blog-card-body">
                        <div class="blog-card-meta">
                            <span><i class="fa-regular fa-calendar"></i> &nbsp;%s</span>
                            <span>·</span>
                            <span>By VidyBack Team</span>
                        </div>
                        <h3>%s</h3>
                        <p>%s</p>
                    </div>
                    <div class="blog-card-footer">
                        <a href="%s" class="read-more-btn">Read More <i class="fa-solid fa-arrow-right"></i></a>
                        <span class="blog-read-time"><i class="fa-regular fa-clock"></i> &nbsp;%d min read</span>
                    </div>
                </article>
''' % ((max(nums) + 1) if nums else 1, data_cat, esc(card_img), esc(image_alt), data_cat, label,
       today.strftime('%B %-d, %Y'), esc(title), esc(summary), slug, minutes)
    s = s[:last.end()] + card + s[last.end():]
    open(p, 'w', encoding='utf-8').write(s)


def add_sitemap(slug, today):
    p = os.path.join(ROOT, 'sitemap.xml')
    s = open(p, encoding='utf-8').read()
    if '/%s</loc>' % slug in s:
        return
    entry = '''    <url>
        <loc>%s/%s</loc>
        <lastmod>%s</lastmod>
        <changefreq>monthly</changefreq>
        <priority>0.7</priority>
    </url>
''' % (SITE, slug, today.strftime('%Y-%m-%d'))
    i = s.rindex('</urlset>')
    open(p, 'w', encoding='utf-8').write(s[:i] + entry + s[i:])


def add_redirect(slug):
    p = os.path.join(ROOT, 'netlify.toml')
    s = open(p, encoding='utf-8').read()
    if 'from = "/%s.html"' % slug in s:
        return
    block = '[[redirects]]\nfrom = "/%s.html"\nto = "/%s"\nstatus = 301\n\n' % (slug, slug)
    i = s.find('[[headers]]')
    s = s[:i] + block + s[i:] if i != -1 else s.rstrip('\n') + '\n\n' + block
    open(p, 'w', encoding='utf-8').write(s)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dry-run', action='store_true', help="report what would be built, write nothing")
    args = ap.parse_args()

    today = datetime.now(timezone.utc)
    built, all_warnings = [], []
    for md_path in sorted(glob.glob(os.path.join(CONTENT_DIR, '*.md'))):
        meta, body = read_article(md_path)
        slug = slugify(meta.get('slug') or os.path.splitext(os.path.basename(md_path))[0])
        out = os.path.join(ROOT, slug + '.html')
        if os.path.exists(out):
            continue
        title = (meta.get('title') or '').strip()
        if not title or not body:
            print('SKIP %s: missing title or body' % md_path, file=sys.stderr)
            continue
        title, w1 = brand_fix(title)
        desc, w2 = brand_fix((meta.get('description') or '').strip())
        body, w3 = brand_fix(body)
        if not desc:
            first = re.sub(r'[#*_>`\[\]]|\(http[^)]*\)', '', next((p for p in body.split('\n\n') if p.strip() and not p.lstrip().startswith(('#', '|', '-', '!'))), ''))
            desc = ' '.join(first.split())
        if len(desc) > 155:
            desc = desc[:152].rsplit(' ', 1)[0].rstrip(',.;:') + '...'
        cat_key = norm_category(meta.get('category'))
        image = (meta.get('image') or '').strip()
        if not re.match(r'https?://', image):
            pid, alt = DEFAULT_IMAGES[cat_key]
            image = 'https://images.pexels.com/photos/%s/pexels-photo-%s.jpeg?auto=compress&cs=tinysrgb&w=1200' % (pid, pid)
            image_alt = meta.get('image_alt') or alt
        else:
            image_alt = meta.get('image_alt') or title
        warnings = w1 + w2 + w3
        all_warnings += ['%s: %s' % (slug, w) for w in warnings]
        print('BUILD %s  (%s)' % (slug, title))
        for w in warnings:
            print('  WARNING ' + w)
        if args.dry_run:
            continue
        tpl = open(template_path(), encoding='utf-8').read()
        page, minutes = build_page(tpl, slug, title, desc, cat_key, image, image_alt, body, today)
        open(out, 'w', encoding='utf-8').write(page)
        add_card(slug, title, desc, cat_key, image, image_alt, minutes, today)
        add_sitemap(slug, today)
        add_redirect(slug)
        built.append((slug, title))

    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary and (built or all_warnings):
        with open(summary, 'a', encoding='utf-8') as f:
            for slug, title in built:
                f.write('- Published [%s](%s/%s)\n' % (title, SITE, slug))
            for w in all_warnings:
                f.write('- :warning: %s\n' % w)
    if not built and not args.dry_run:
        print('Nothing new to publish.')


if __name__ == '__main__':
    main()
