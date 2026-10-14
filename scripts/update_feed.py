#!/usr/bin/env python3
"""Regenerate feed.xml from every blog post's own BlogPosting JSON-LD.

A post is anything in the repo root whose <head> has a
<script type="application/ld+json"> block with "@type": "BlogPosting".
That one marker is what scripts/og_images.py's per-post asset pass also
relies on, so adding a post never means remembering a second place to
register it.

For each post this pulls headline, url, description and datePublished
straight out of that JSON-LD block (falling back to the og:description
meta tag if a description is missing from it), rewrites the url's
https://www.vidyback.com host to the https://vidyback.netlify.app host
feed.xml has always used, and emits one <item> per post sorted oldest
to newest, matching the publish order the feed already used by hand.

It is idempotent: rerunning it with no new posts leaves feed.xml
byte-identical, so a CI step can run it on every push and only commit
when there's an actual diff.

    python3 scripts/update_feed.py           # rewrite feed.xml if needed
    python3 scripts/update_feed.py --check   # exit 1 if feed.xml is stale, don't write
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from html import unescape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEED_PATH = os.path.join(ROOT, 'feed.xml')
WWW_HOST = 'https://www.vidyback.com'
FEED_HOST = 'https://vidyback.netlify.app'

CHANNEL_TITLE = 'VidyBack Blog'
CHANNEL_LINK = f'{FEED_HOST}/blog'
CHANNEL_DESC = ("Social media strategies for Shopify & DTC brands. AI content "
                "automation, Reels generation, and ecommerce marketing tips.")

JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE)
OGDESC_RE = re.compile(
    r'<meta\s+property=["\']og:description["\']\s+content=["\'](.*?)["\']',
    re.DOTALL | re.IGNORECASE)


def escape(s):
    """Escape for XML text content only (&, <, >) - these values are never
    used inside an attribute, so quotes/apostrophes are left as-is, matching
    how the feed was always hand-written."""
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def find_posts():
    posts = []
    for name in sorted(os.listdir(ROOT)):
        if not name.endswith('.html') or not os.path.isfile(os.path.join(ROOT, name)):
            continue
        path = os.path.join(ROOT, name)
        with open(path, encoding='utf-8') as f:
            html_src = f.read()
        post = parse_post(html_src, name)
        if post:
            posts.append(post)
    return posts


def parse_post(html_src, filename):
    blog_posting = None
    for block in JSONLD_RE.findall(html_src):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get('@type') == 'BlogPosting':
            blog_posting = data
            break
    if not blog_posting:
        return None

    title = blog_posting.get('headline')
    url = blog_posting.get('url')
    date_published = blog_posting.get('datePublished')
    description = blog_posting.get('description')

    if not description:
        m = OGDESC_RE.search(html_src)
        description = unescape(m.group(1)) if m else ''

    if not (title and url and date_published):
        print(f'warning: {filename} has a BlogPosting block missing headline/url/datePublished, skipping', file=sys.stderr)
        return None

    url = url.replace(WWW_HOST, FEED_HOST).rstrip('/')
    try:
        pub_date = datetime.strptime(date_published, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except ValueError:
        print(f'warning: {filename} has an unparseable datePublished {date_published!r}, skipping', file=sys.stderr)
        return None

    return {
        'title': title,
        'link': url,
        'description': description,
        'pub_date': pub_date,
    }


def render_feed(posts):
    posts_sorted = sorted(posts, key=lambda p: (p['pub_date'], p['link']))
    now = datetime.now(timezone.utc)

    items = []
    for p in posts_sorted:
        items.append(
            '    <item>\n'
            f'        <title>{escape(p["title"])}</title>\n'
            f'        <link>{escape(p["link"])}</link>\n'
            f'        <guid>{escape(p["link"])}</guid>\n'
            f'        <description>{escape(p["description"])}</description>\n'
            f'        <pubDate>{format_datetime(p["pub_date"], usegmt=True)}</pubDate>\n'
            '    </item>'
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        '<channel>\n'
        f'    <title>{escape(CHANNEL_TITLE)}</title>\n'
        f'    <link>{escape(CHANNEL_LINK)}</link>\n'
        f'    <description>{escape(CHANNEL_DESC)}</description>\n'
        '    <language>en-us</language>\n'
        f'    <lastBuildDate>{format_datetime(now, usegmt=True)}</lastBuildDate>\n'
        '\n'
        + '\n\n'.join(items) +
        '\n\n'
        '</channel>\n'
        '</rss>\n'
    )


def current_feed_without_build_date():
    if not os.path.exists(FEED_PATH):
        return None
    with open(FEED_PATH, encoding='utf-8') as f:
        return re.sub(r'<lastBuildDate>.*?</lastBuildDate>', '<lastBuildDate/>', f.read())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true', help="exit 1 if feed.xml doesn't match the posts on disk, without writing")
    args = ap.parse_args()

    posts = find_posts()
    if not posts:
        print('error: found no BlogPosting pages, refusing to write an empty feed', file=sys.stderr)
        return 1

    new_feed = render_feed(posts)
    new_feed_normalized = re.sub(r'<lastBuildDate>.*?</lastBuildDate>', '<lastBuildDate/>', new_feed)
    old_feed_normalized = current_feed_without_build_date()

    if new_feed_normalized == old_feed_normalized:
        print(f'feed.xml already up to date ({len(posts)} posts)')
        return 0

    if args.check:
        print(f'feed.xml is stale: {len(posts)} posts on disk do not match feed.xml', file=sys.stderr)
        return 1

    with open(FEED_PATH, 'w', encoding='utf-8') as f:
        f.write(new_feed)
    print(f'feed.xml updated ({len(posts)} posts)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
