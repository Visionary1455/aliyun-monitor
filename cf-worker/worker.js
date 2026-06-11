/**
 * Cloudflare Workers Cron Trigger
 * 定时触发 GitHub Actions workflow_dispatch
 *
 * 部署后会按 wrangler.toml 中 [triggers].crons 设置的频率
 * 调用 GitHub API 触发指定仓库的 workflow。
 *
 * 环境变量（必须在 CF Dashboard 配置，不要写到代码或 wrangler.toml 提交到公开仓库）:
 *   GH_PAT       - GitHub Fine-grained PAT (Actions: read/write)         [Secret, 必填]
 *   GH_REPO      - 仓库 owner/name，例如 yourname/your-repo               [Secret, 必填]
 *   GH_REF       - 触发分支                                                [Variable, 默认 main]
 *   GH_WORKFLOW  - workflow 文件名                                         [Variable, 默认 monitor.yml]
 *   TRIGGER_TOKEN - 可选，保护 /trigger HTTP 入口                          [Secret, 可选]
 */

export default {
  async scheduled(event, env, ctx) {
    if (!env.GH_PAT) {
      console.error('GH_PAT 未配置，跳过触发');
      return;
    }
    if (!env.GH_REPO) {
      console.error('GH_REPO 未配置，跳过触发');
      return;
    }

    const repo = env.GH_REPO;
    const ref = env.GH_REF || 'main';
    const workflow = env.GH_WORKFLOW || 'monitor.yml';
    const url = `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`;

    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${env.GH_PAT}`,
          'Accept': 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
          'User-Agent': 'cf-worker-gh-dispatcher',
        },
        body: JSON.stringify({ ref }),
      });

      if (resp.status === 204) {
        console.log(`[OK] dispatch ${repo}@${ref} ${workflow} (cron=${event.cron})`);
      } else {
        const body = await resp.text();
        console.error(`[FAIL] HTTP ${resp.status}: ${body}`);
      }
    } catch (e) {
      console.error(`[ERROR] ${e.message}`);
    }
  },

  // 同时支持手动 HTTP 调用（用于浏览器/curl 立即测试）
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname !== '/trigger') {
      return new Response('OK - cf-worker-gh-dispatcher\nPOST /trigger to dispatch GH workflow.', {
        status: 200,
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      });
    }

    // 必须配置 TRIGGER_TOKEN 才能用 HTTP 触发（防止公开 URL 被任意访问）
    if (!env.TRIGGER_TOKEN) {
      return new Response('TRIGGER_TOKEN not configured', { status: 403 });
    }
    const auth = request.headers.get('Authorization') || '';
    if (auth !== `Bearer ${env.TRIGGER_TOKEN}`) {
      return new Response('Unauthorized', { status: 401 });
    }

    await this.scheduled({ cron: 'manual' }, env, ctx);
    return new Response('triggered', { status: 200 });
  },
};
