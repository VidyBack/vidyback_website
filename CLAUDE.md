# VidyBack website

Static marketing site for vidyback.com. There's no build step: Netlify deploys the `main` branch as-is.

## Posts published from Frekto

Frekto publishes through the MCP endpoint at `https://vidyback.com/mcp` (no `www`: that host redirects, which can break POSTs) (`netlify/functions/mcp.mjs`, tool `publish_post`). It only commits the article as `content/blog/<slug>.md`; the `publish-blog` GitHub Action then runs `scripts/publish_blog.py`, `scripts/og_images.py` and `scripts/update_feed.py` to build and push the real post. To publish an article by hand the same way, add a `.md` file there (format in the `publish_blog.py` docstring) and push.

## Adding a blog post

Each post touches these files (see commit 2c331c5 for an example):

- `<slug>.html`: the post itself, using the newest existing post as the template
- `blog.html`: a new `<article class="blog-card">` at the end of the grid
- `sitemap.xml`: a `<url>` entry
- `netlify.toml`: a `/<slug>.html` → `/<slug>` 301 redirect

After those four are in place, generate the post's social share image:

```
pip install pillow   # if it isn't installed
python3 scripts/og_images.py
```

This renders `images/og/<slug>.jpg` (1200×630, the post title on the VidyBack gradient) and points the post's `og:image`, `twitter:image` and BlogPosting JSON-LD `image` at it. It only touches posts that are new or missing tags, so commit the new image plus the post's updated `<head>` along with the four files above. Don't point posts at the generic `images/og-image.png`.
