/**
 * GPC — Governed Plan Compiler
 * Injected into the Veklom Workspace sidebar between Playground and Marketplace.
 * When navigated to, renders the GPC page with the Deterministic Engine (uacpgemini) embedded.
 */
(function () {
  const GPC_API = window.__VEKLOM_API_BASE__ || '/api/v1';
  const UACPGEMINI_URL = 'https://uacpgemini.onrender.com';

  /* ---- Sidebar injection ---- */
  function injectSidebarLink() {
    const navLinks = document.querySelectorAll('nav a[href]');
    let playgroundLink = null;
    let marketplaceLink = null;
    for (const a of navLinks) {
      const href = a.getAttribute('href');
      if (href === '/playground' || href === '#/playground') playgroundLink = a;
      if (href === '/marketplace' || href === '#/marketplace') marketplaceLink = a;
    }
    if (!playgroundLink || document.querySelector('a[href="#/gpc"]')) return;

    const gpcLink = playgroundLink.cloneNode(true);
    gpcLink.setAttribute('href', '#/gpc');
    // Replace icon SVG with GPC layers icon
    const svg = gpcLink.querySelector('svg');
    if (svg) {
      svg.innerHTML = '<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>';
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-width', '1.5');
      svg.setAttribute('stroke-linecap', 'round');
      svg.setAttribute('stroke-linejoin', 'round');
    }
    // Replace label text
    const spans = gpcLink.querySelectorAll('span');
    for (const sp of spans) {
      if (sp.children.length === 0) { sp.textContent = 'GPC'; break; }
    }
    // If no span found, check for direct text nodes
    if (!spans.length) {
      const textNodes = [...gpcLink.childNodes].filter(n => n.nodeType === 3 && n.textContent.trim());
      if (textNodes.length) textNodes[0].textContent = 'GPC';
    }

    // Insert after Playground
    playgroundLink.parentNode.insertBefore(gpcLink, playgroundLink.nextSibling);

    // Click handler — use hash routing
    gpcLink.addEventListener('click', function (e) {
      e.preventDefault();
      window.location.hash = '#/gpc';
      // Remove active state from other links
      document.querySelectorAll('nav a').forEach(l => l.removeAttribute('data-active'));
    });
  }

  /* ---- GPC Page ---- */
  function createGPCPage() {
    const el = document.createElement('div');
    el.id = 'gpc-page';
    el.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;flex-direction:column;background:#0a0a0a;color:#e0e0e0;font-family:Inter,Geist,system-ui,sans-serif;';
    el.innerHTML = `
      <div style="display:flex;flex:1;overflow:hidden;">
        <!-- GPC Sidebar context -->
        <div style="width:280px;min-width:280px;border-right:1px solid rgba(255,255,255,0.08);background:#0d0c0a;display:flex;flex-direction:column;padding:24px 20px;overflow-y:auto;">
          <div style="margin-bottom:32px;">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#f97316" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
              <span style="font-size:16px;font-weight:700;letter-spacing:0.02em;">Governed Plan Compiler</span>
            </div>
            <p style="font-size:11px;text-transform:uppercase;letter-spacing:0.25em;color:rgba(255,255,255,0.3);font-weight:600;">Intent → Policy → Risk → Cost → Deploy</p>
          </div>

          <div style="flex:1;">
            <div style="margin-bottom:24px;">
              <label style="font-size:10px;text-transform:uppercase;letter-spacing:0.2em;color:rgba(255,255,255,0.25);font-weight:700;display:block;margin-bottom:10px;">Compile Intent</label>
              <textarea id="gpc-intent" placeholder="Describe your AI workflow intent..." style="width:100%;height:100px;background:#050505;border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:12px;color:#e0e0e0;font-size:13px;resize:none;outline:none;font-family:inherit;"></textarea>
              <button id="gpc-compile-btn" style="width:100%;margin-top:10px;padding:10px;background:#f97316;color:#000;font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:0.3em;border:none;cursor:pointer;border-radius:6px;">Compile Plan</button>
            </div>

            <div id="gpc-result" style="display:none;">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.2em;color:rgba(255,255,255,0.25);font-weight:700;margin-bottom:10px;">Compiled Plan</div>
              <div id="gpc-result-content" style="font-size:12px;"></div>
            </div>

            <div style="margin-top:24px;">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.2em;color:rgba(255,255,255,0.25);font-weight:700;margin-bottom:10px;">Previous Plans</div>
              <div id="gpc-plans-list" style="font-size:12px;color:rgba(255,255,255,0.4);"></div>
            </div>
          </div>

          <button id="gpc-back-btn" style="padding:8px 16px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);color:rgba(255,255,255,0.6);font-size:11px;text-transform:uppercase;letter-spacing:0.15em;cursor:pointer;border-radius:6px;margin-top:16px;">← Back to Workspace</button>
        </div>

        <!-- Main: Deterministic Engine (uacpgemini) -->
        <div style="flex:1;position:relative;">
          <iframe id="gpc-engine-frame" src="${UACPGEMINI_URL}" style="width:100%;height:100%;border:none;background:#050505;" allow="clipboard-read;clipboard-write"></iframe>
        </div>
      </div>
    `;
    document.body.appendChild(el);

    // Wire up events
    document.getElementById('gpc-back-btn').addEventListener('click', function () {
      window.location.hash = '#/';
    });

    document.getElementById('gpc-compile-btn').addEventListener('click', compileGPC);
    document.getElementById('gpc-intent').addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); compileGPC(); }
    });

    fetchPlans();
  }

  async function compileGPC() {
    const input = document.getElementById('gpc-intent');
    const btn = document.getElementById('gpc-compile-btn');
    const intent = input.value.trim();
    if (!intent) return;

    btn.textContent = 'COMPILING...';
    btn.disabled = true;

    try {
      const res = await fetch(`${GPC_API}/gpc/compile?intent=${encodeURIComponent(intent)}`, { method: 'POST' });
      if (!res.ok) throw new Error('Compilation failed');
      const data = await res.json();
      input.value = '';
      showResult(data);
      fetchPlans();
    } catch (err) {
      showResult({ error: err.message });
    } finally {
      btn.textContent = 'COMPILE PLAN';
      btn.disabled = false;
    }
  }

  function showResult(data) {
    const container = document.getElementById('gpc-result');
    const content = document.getElementById('gpc-result-content');
    container.style.display = 'block';

    if (data.error) {
      content.innerHTML = `<div style="color:#f87171;padding:8px;border:1px solid rgba(248,113,113,0.2);border-radius:6px;">${data.error}</div>`;
      return;
    }

    let html = `<div style="padding:10px;border:1px solid rgba(34,197,94,0.2);border-radius:8px;background:rgba(34,197,94,0.03);">`;
    html += `<div style="color:#4ade80;font-size:10px;font-family:monospace;text-transform:uppercase;letter-spacing:0.2em;margin-bottom:8px;">Plan ${data.id?.slice(0, 8)} — ${data.status}</div>`;

    if (data.compiled_plan?.workflow_steps) {
      html += `<div style="margin-bottom:8px;">`;
      data.compiled_plan.workflow_steps.forEach(s => {
        html += `<div style="display:flex;align-items:center;gap:8px;padding:3px 0;"><span style="width:18px;height:18px;border-radius:50%;border:1px solid rgba(249,115,22,0.3);display:flex;align-items:center;justify-content:center;font-size:9px;color:#f97316;font-family:monospace;">${s.step}</span><span style="color:rgba(255,255,255,0.6);font-size:11px;">${s.action}</span></div>`;
      });
      html += `</div>`;
    }

    if (data.risks) {
      html += `<div style="font-size:9px;color:#f97316;text-transform:uppercase;letter-spacing:0.2em;margin:8px 0 4px;">Risks</div>`;
      data.risks.forEach(r => {
        const col = r.severity === 'critical' ? '#ef4444' : r.severity === 'high' ? '#f97316' : '#eab308';
        html += `<div style="font-size:10px;padding:4px 0;"><span style="color:${col};font-family:monospace;text-transform:uppercase;font-size:8px;border:1px solid ${col}33;padding:1px 4px;border-radius:3px;">${r.severity}</span> <span style="color:rgba(255,255,255,0.5);margin-left:4px;">${r.risk}</span></div>`;
      });
    }

    if (data.cost_estimate) {
      html += `<div style="border-top:1px solid rgba(255,255,255,0.05);margin-top:8px;padding-top:8px;"><span style="font-size:9px;color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.15em;">Total</span> <span style="font-size:16px;font-weight:700;color:rgba(255,255,255,0.8);margin-left:8px;">${data.cost_estimate.total_estimated}</span></div>`;
    }

    html += `</div>`;
    content.innerHTML = html;
  }

  async function fetchPlans() {
    try {
      const res = await fetch(`${GPC_API}/gpc/plans`);
      const plans = await res.json();
      const list = document.getElementById('gpc-plans-list');
      if (!plans.length) { list.innerHTML = '<div style="color:rgba(255,255,255,0.15);font-style:italic;">No plans yet</div>'; return; }
      list.innerHTML = plans.map(p =>
        `<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 8px;border:1px solid rgba(255,255,255,0.05);border-radius:4px;margin-bottom:4px;cursor:default;">
          <div><span style="font-family:monospace;font-size:9px;color:rgba(255,255,255,0.2);">${p.id?.slice(0, 8)}</span> <span style="color:rgba(255,255,255,0.5);margin-left:6px;font-size:11px;">${p.intent?.slice(0, 40)}${p.intent?.length > 40 ? '...' : ''}</span></div>
          <span style="font-size:8px;font-family:monospace;text-transform:uppercase;color:${p.status === 'compiled' ? '#4ade80' : '#f97316'};border:1px solid ${p.status === 'compiled' ? 'rgba(74,222,128,0.3)' : 'rgba(249,115,22,0.3)'};padding:1px 6px;border-radius:3px;">${p.status}</span>
        </div>`
      ).join('');
    } catch (e) {}
  }

  /* ---- Route handling ---- */
  function handleRoute() {
    const hash = window.location.hash;
    const gpcPage = document.getElementById('gpc-page');
    const root = document.getElementById('root');

    if (hash === '#/gpc') {
      if (!gpcPage) createGPCPage();
      else gpcPage.style.display = 'flex';
      if (root) root.style.display = 'none';
      // Highlight GPC in sidebar
      highlightSidebarLink('/gpc');
    } else {
      if (gpcPage) gpcPage.style.display = 'none';
      if (root) root.style.display = '';
    }
  }

  function highlightSidebarLink(href) {
    const links = document.querySelectorAll('nav a[href]');
    for (const a of links) {
      if (a.getAttribute('href') === href) {
        a.setAttribute('data-active', 'true');
      }
    }
  }

  /* ---- Init ---- */
  window.addEventListener('hashchange', handleRoute);

  // Wait for React app to mount and sidebar to render
  const observer = new MutationObserver(function () {
    const nav = document.querySelector('nav');
    if (nav && (nav.querySelector('a[href="/playground"]') || nav.querySelector('a[href="#/playground"]'))) {
      injectSidebarLink();
      observer.disconnect();
      handleRoute();
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });

  // Also try immediately in case already rendered
  setTimeout(() => { injectSidebarLink(); handleRoute(); }, 1000);
})();
