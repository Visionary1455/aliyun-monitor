/**
 * Cloudflare Workers Cron Trigger
 * 定时触发 GitHub Actions workflow_dispatch
 *
 * 部署后会按 wrangler.toml 中 [triggers].crons 设置的频率
 * 调用 GitHub API 触发 aliyun-monitor 仓库的 monitor.yml workflow。
 *
 * 环境变量（在 CF Dashboard 或 wrangler.toml 配置）:
 *   GH_PAT     - GitHub Fine-grained PAT (Actions: read/write)
 *   GH_REPO    - 仓库 owner/name，例如 hizzt/aliyun-monitor
 *   GH_REF     - 触发分支，默认 main
 *   GH_WORKFLOW- workflow 文件名，默认 monitor.yml
 */

export default {
  async scheduled(event, env, ctx) {
    const repo = env.GH_REPO || 'hizzt/aliyun-monitor';
    const ref = env.GH_REF || 'main';
    const workflow = env.GH_WORKFLOW || 'monitor.yml';
    const url = `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`;

    if (!env.GH_PAT) {
      console.error('GH_PAT 未配置，跳过触发');
      return;
    }

    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${env.GH_PAT}`,
          'Accept': 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
          'User-Agent': 'cf-worker-aliyun-monitor',
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
      return new Response('OK - cf-worker-aliyun-monitor\nPOST /trigger to dispatch GH workflow.', {
        status: 200,
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      });
    }

    // 简单的 token 校验，避免被人滥用
    const auth = request.headers.get('Authorization') || '';
    if (env.TRIGGER_TOKEN && auth !== `Bearer ${env.TRIGGER_TOKEN}`) {
      return new Response('Unauthorized', { status: 401 });
    }

    await this.scheduled({ cron: 'manual' }, env, ctx);
    return new Response('triggered', { status: 200 });
  },
};
