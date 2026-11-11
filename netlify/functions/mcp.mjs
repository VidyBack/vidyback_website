// MCP endpoint that lets Frekto (or any MCP client) publish blog posts to
// vidyback.com.  Served at https://www.vidyback.com/mcp.
//
// It speaks MCP's Streamable HTTP transport (plain JSON responses, no SSE
// stream) and exposes one tool, publish_post.  The tool never edits the
// site directly: it commits the article as content/blog/<slug>.md to the
// repo, and the publish-blog GitHub Action turns that into the real post
// (page, blog card, sitemap, redirect, share image, RSS) a minute later.
//
// Netlify environment variables (Site settings -> Environment variables):
//   BLOG_MCP_TOKEN      required. Shared secret; paste the same value into
//                       Frekto's "Auth Token" field.
//   GITHUB_BLOG_TOKEN   required. Fine-grained GitHub token for this repo
//                       only, with "Contents: Read and write".
//   GITHUB_REPO         optional, default VidyBack/vidyback_website
//   GITHUB_BRANCH       optional, default main

export const config = { path: '/mcp' };

const SITE = 'https://www.vidyback.com';
const SERVER_INFO = { name: 'vidyback-blog', version: '1.0.0' };
const PROTOCOL_VERSIONS = ['2025-06-18', '2025-03-26', '2024-11-05'];
const MAX_ARTICLE_CHARS = 200000;

const PUBLISH_TOOL = {
  name: 'publish_post',
  title: 'Publish blog post',
  description:
    'Publish an article to the VidyBack blog (vidyback.com/blog). The post goes live ' +
    'about two minutes after this call, with its own page, blog card, share image and ' +
    'sitemap entry. Write the article in Markdown (HTML is also accepted). Do not repeat ' +
    'the title as a heading at the top of the article.',
  inputSchema: {
    type: 'object',
    properties: {
      title: { type: 'string', description: 'Post title, also used as the page <h1> and SEO title.' },
      content: { type: 'string', description: 'The full article body in Markdown (or HTML).' },
      description: { type: 'string', description: 'Meta description / excerpt, ideally under 155 characters.' },
      category: {
        type: 'string',
        enum: ['social', 'ecommerce', 'automation'],
        description: 'Blog category: social (Social Media), ecommerce (Ecommerce Growth) or automation.',
      },
      image_url: { type: 'string', description: 'Optional cover image URL (https). A stock image is used if omitted.' },
      tags: { type: 'array', items: { type: 'string' }, description: 'Optional tags.' },
      slug: { type: 'string', description: 'Optional URL slug. Generated from the title if omitted.' },
    },
    required: ['title', 'content'],
  },
};

// ------------------------------------------------------------------ helpers

const json = (body, status = 200, headers = {}) =>
  new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });

const rpcResult = (id, result) => ({ jsonrpc: '2.0', id, result });
const rpcError = (id, code, message) => ({ jsonrpc: '2.0', id: id ?? null, error: { code, message } });
const toolText = (text, isError = false, structured) => ({
  content: [{ type: 'text', text }],
  ...(structured ? { structuredContent: structured } : {}),
  ...(isError ? { isError: true } : {}),
});

function safeEqual(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function authorized(req) {
  const expected = process.env.BLOG_MCP_TOKEN;
  if (!expected) return false;
  const auth = req.headers.get('authorization') || '';
  const bearer = auth.replace(/^(Bearer|Token|ApiKey)\s+/i, '').trim();
  const apiKey = (req.headers.get('x-api-key') || '').trim();
  return safeEqual(bearer, expected) || safeEqual(apiKey, expected);
}

const slugify = (s) =>
  String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80).replace(/-+$/, '') || 'post';

const pick = (args, ...keys) => {
  for (const k of keys) if (typeof args[k] === 'string' && args[k].trim()) return args[k].trim();
  return '';
};

function normCategory(v) {
  const s = String(v || '').toLowerCase();
  if (s.includes('ecom') || s.includes('growth') || s.includes('sales')) return 'ecommerce';
  if (s.includes('auto')) return 'automation';
  return 'social';
}

// --------------------------------------------------------------- GitHub API

function gh(path, init = {}) {
  const repo = process.env.GITHUB_REPO || 'VidyBack/vidyback_website';
  return fetch(`https://api.github.com/repos/${repo}/${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${process.env.GITHUB_BLOG_TOKEN}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'vidyback-blog-mcp',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
    },
  });
}

async function getFile(path) {
  const branch = process.env.GITHUB_BRANCH || 'main';
  const res = await gh(`contents/${path}?ref=${encodeURIComponent(branch)}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`GitHub read failed (${res.status})`);
  const data = await res.json();
  return Buffer.from(data.content || '', 'base64').toString('utf8');
}

async function putFile(path, text, message) {
  const branch = process.env.GITHUB_BRANCH || 'main';
  const res = await gh(`contents/${path}`, {
    method: 'PUT',
    body: JSON.stringify({ message, branch, content: Buffer.from(text, 'utf8').toString('base64') }),
  });
  if (!res.ok) throw new Error(`GitHub write failed (${res.status}): ${(await res.text()).slice(0, 200)}`);
}

// ------------------------------------------------------------- publish_post

async function publishPost(args = {}) {
  const title = pick(args, 'title', 'headline', 'name');
  const content = pick(args, 'content', 'article', 'body', 'markdown', 'html', 'text');
  if (!title) return toolText('Missing "title".', true);
  if (!content) return toolText('Missing "content" (the article body).', true);
  if (content.length > MAX_ARTICLE_CHARS) return toolText('Article is too long.', true);
  if (!process.env.GITHUB_BLOG_TOKEN) return toolText('Server is not configured (GITHUB_BLOG_TOKEN missing).', true);

  const description = pick(args, 'description', 'excerpt', 'summary', 'meta_description');
  const image = pick(args, 'image_url', 'image', 'picture', 'featured_image', 'cover_image', 'thumbnail');
  let tags = args.tags;
  if (typeof tags === 'string') tags = tags.split(',');
  tags = Array.isArray(tags) ? tags.map((t) => String(t).trim()).filter(Boolean).slice(0, 20) : [];

  // Pick a free slug. Re-sending the same article (a retry) returns the
  // existing post instead of publishing a duplicate.
  const base = slugify(pick(args, 'slug') || title);
  let slug = null;
  for (let n = 1; n <= 20 && !slug; n++) {
    const candidate = n === 1 ? base : `${base}-${n}`;
    const existingMd = await getFile(`content/blog/${candidate}.md`);
    if (existingMd !== null) {
      if (existingMd.includes(`title: ${JSON.stringify(title)}`)) {
        const url = `${SITE}/${candidate}`;
        return toolText(`Already published: ${url}`, false, { url, slug: candidate, status: 'already_published' });
      }
      continue;
    }
    if ((await getFile(`${candidate}.html`)) !== null) continue;
    slug = candidate;
  }
  if (!slug) return toolText('Could not find a free URL slug for this title.', true);

  const frontMatter = [
    '---',
    `title: ${JSON.stringify(title)}`,
    `description: ${JSON.stringify(description)}`,
    `category: ${JSON.stringify(normCategory(args.category))}`,
    `image: ${JSON.stringify(/^https?:\/\//.test(image) ? image : '')}`,
    `tags: ${JSON.stringify(tags)}`,
    `source: "frekto"`,
    `received: ${JSON.stringify(new Date().toISOString())}`,
    '---',
    '',
  ].join('\n');

  try {
    await putFile(`content/blog/${slug}.md`, frontMatter + content.trim() + '\n', `Add blog post from Frekto: ${title}`);
  } catch (err) {
    return toolText(`Publishing failed: ${err.message}`, true);
  }
  const url = `${SITE}/${slug}`;
  return toolText(`Published. The post will be live at ${url} in about 2 minutes.`, false, { url, slug, status: 'published' });
}

// ------------------------------------------------------------ JSON-RPC core

async function handleMessage(msg) {
  if (!msg || msg.jsonrpc !== '2.0' || typeof msg.method !== 'string') {
    return rpcError(msg && msg.id, -32600, 'Invalid Request');
  }
  const isNotification = msg.id === undefined || msg.id === null;
  const params = msg.params || {};
  switch (msg.method) {
    case 'initialize': {
      const requested = params.protocolVersion;
      return rpcResult(msg.id, {
        protocolVersion: PROTOCOL_VERSIONS.includes(requested) ? requested : PROTOCOL_VERSIONS[0],
        capabilities: { tools: { listChanged: false } },
        serverInfo: SERVER_INFO,
        instructions: 'Use publish_post to publish an article to the VidyBack blog.',
      });
    }
    case 'ping':
      return isNotification ? null : rpcResult(msg.id, {});
    case 'tools/list':
      return rpcResult(msg.id, { tools: [PUBLISH_TOOL] });
    case 'tools/call':
      if (params.name !== PUBLISH_TOOL.name) return rpcError(msg.id, -32602, `Unknown tool: ${params.name}`);
      return rpcResult(msg.id, await publishPost(params.arguments || {}));
    default:
      if (isNotification) return null; // e.g. notifications/initialized
      return rpcError(msg.id, -32601, `Method not found: ${msg.method}`);
  }
}

export default async (req) => {
  if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: { Allow: 'POST, OPTIONS' } });
  if (req.method !== 'POST') return json(rpcError(null, -32000, 'Use POST'), 405, { Allow: 'POST, OPTIONS' });
  if (!authorized(req)) return json(rpcError(null, -32001, 'Unauthorized'), 401, { 'WWW-Authenticate': 'Bearer' });

  let payload;
  try {
    payload = await req.json();
  } catch {
    return json(rpcError(null, -32700, 'Parse error'), 400);
  }
  const batch = Array.isArray(payload);
  const replies = (await Promise.all((batch ? payload : [payload]).map(handleMessage))).filter(Boolean);
  if (!replies.length) return new Response(null, { status: 202 });
  return json(batch ? replies : replies[0]);
};
