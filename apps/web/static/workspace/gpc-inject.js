/**
 * GPC — Governed Plan Compiler
 * 1. Injects a "GPC" link into the sidebar between Playground and Marketplace.
 * 2. When #/gpc is active, HIDES the <main> children and appends a GPC div.
 *    The sidebar (aside) and header stay exactly as on every other page.
 * 3. When navigating away, removes the GPC div and un-hides the originals.
 */
(function () {
  'use strict';
  var GPC_API = window.__VEKLOM_API_BASE__ || '/api/v1';
  var UACPGEMINI_URL = 'https://uacpgemini.onrender.com';

  /* ================================================================
   *  Sidebar injection — add GPC link between Playground & Marketplace
   * ================================================================ */
  function injectSidebarLink() {
    var navLinks = document.querySelectorAll('nav a[href]');
    var playgroundLink = null;
    for (var i = 0; i < navLinks.length; i++) {
      var href = navLinks[i].getAttribute('href');
      if (href === '#/playground' || href === '/playground') {
        playgroundLink = navLinks[i];
        break;
      }
    }
    if (!playgroundLink || document.querySelector('a[href="#/gpc"]')) return;

    var gpcLink = playgroundLink.cloneNode(true);
    gpcLink.setAttribute('href', '#/gpc');

    var svg = gpcLink.querySelector('svg');
    if (svg) {
      svg.innerHTML = '<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>';
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-width', '1.5');
      svg.setAttribute('stroke-linecap', 'round');
      svg.setAttribute('stroke-linejoin', 'round');
    }

    var spans = gpcLink.querySelectorAll('span');
    var labelSet = false;
    for (var j = 0; j < spans.length; j++) {
      var sp = spans[j];
      if (sp.children.length === 0 && sp.textContent.trim()) {
        if (sp.textContent.trim().toLowerCase() === 'live') continue;
        sp.textContent = 'GPC';
        labelSet = true;
        break;
      }
    }
    if (!labelSet) {
      var textNodes = [];
      for (var k = 0; k < gpcLink.childNodes.length; k++) {
        var n = gpcLink.childNodes[k];
        if (n.nodeType === 3 && n.textContent.trim()) textNodes.push(n);
      }
      if (textNodes.length) textNodes[0].textContent = 'GPC';
    }

    playgroundLink.parentNode.insertBefore(gpcLink, playgroundLink.nextSibling);

    gpcLink.addEventListener('click', function (e) {
      e.preventDefault();
      window.location.hash = '#/gpc';
    });
  }

  /* ================================================================
   *  GPC page — hide/show approach (keeps React alive)
   * ================================================================ */
  function getMain() { return document.querySelector('main'); }

  function showGPC() {
    var main = getMain();
    if (!main) return;
    if (document.getElementById('gpc-page')) return; // already showing

    // Hide all existing children of <main>
    for (var i = 0; i < main.children.length; i++) {
      main.children[i].setAttribute('data-gpc-hidden', '');
      main.children[i].style.display = 'none';
    }

    // Create GPC container
    var gpc = document.createElement('div');
    gpc.id = 'gpc-page';
    gpc.style.cssText = 'display:flex;flex:1;height:100%;min-height:0;background:#0a0a0a;';

    gpc.innerHTML =
      '<div style="width:300px;min-width:300px;border-right:1px solid rgba(255,255,255,0.08);background:#0d0c0a;display:flex;flex-direction:column;padding:24px 20px;overflow-y:auto;">' +
        '<div style="margin-bottom:32px;">' +
          '<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">' +
            '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#f97316" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>' +
            '<span style="font-size:16px;font-weight:700;letter-spacing:0.02em;color:#e0e0e0;">Governed Plan Compiler</span>' +
          '</div>' +
          '<p style="font-size:10px;text-transform:uppercase;letter-spacing:0.25em;color:rgba(255,255,255,0.3);font-weight:600;">Intent \u2192 Policy \u2192 Risk \u2192 Cost \u2192 Deploy</p>' +
        '</div>' +
        '<div style="flex:1;">' +
          '<div style="margin-bottom:24px;">' +
            '<label style="font-size:10px;text-transform:uppercase;letter-spacing:0.2em;color:rgba(255,255,255,0.25);font-weight:700;display:block;margin-bottom:10px;">Compile Intent</label>' +
            '<textarea id="gpc-intent" placeholder="Describe your AI workflow intent..." style="width:100%;height:100px;background:#050505;border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:12px;color:#e0e0e0;font-size:13px;resize:none;outline:none;font-family:inherit;box-sizing:border-box;"></textarea>' +
            '<button id="gpc-compile-btn" style="width:100%;margin-top:10px;padding:10px;background:#f97316;color:#000;font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:0.3em;border:none;cursor:pointer;border-radius:6px;">Compile Plan</button>' +
          '</div>' +
          '<div id="gpc-result" style="display:none;">' +
            '<div style="font-size:10px;text-transform:uppercase;letter-spacing:0.2em;color:rgba(255,255,255,0.25);font-weight:700;margin-bottom:10px;">Compiled Plan</div>' +
            '<div id="gpc-result-content" style="font-size:12px;"></div>' +
          '</div>' +
          '<div style="margin-top:24px;">' +
            '<div style="font-size:10px;text-transform:uppercase;letter-spacing:0.2em;color:rgba(255,255,255,0.25);font-weight:700;margin-bottom:10px;">Previous Plans</div>' +
            '<div id="gpc-plans-list" style="font-size:12px;color:rgba(255,255,255,0.4);"></div>' +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div style="flex:1;position:relative;overflow:hidden;">' +
        '<iframe id="gpc-engine-frame" src="' + UACPGEMINI_URL + '" style="width:300%;height:100%;border:none;background:#050505;position:absolute;left:-100%;" allow="clipboard-read;clipboard-write"></iframe>' +
      '</div>';

    main.appendChild(gpc);

    // Adjust main styles for flex fill
    main.style.flex = '1';
    main.style.display = 'flex';
    main.style.flexDirection = 'column';
    main.style.overflow = 'hidden';

    // Wire events
    var compileBtn = document.getElementById('gpc-compile-btn');
    var intentInput = document.getElementById('gpc-intent');
    if (compileBtn) compileBtn.addEventListener('click', compileGPC);
    if (intentInput) intentInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); compileGPC(); }
    });

    fetchPlans();
  }

  function hideGPC() {
    var gpc = document.getElementById('gpc-page');
    if (!gpc) return;

    var main = getMain();
    // Remove GPC container
    gpc.parentNode.removeChild(gpc);

    // Un-hide original children
    if (main) {
      var hidden = main.querySelectorAll('[data-gpc-hidden]');
      for (var i = 0; i < hidden.length; i++) {
        hidden[i].style.display = '';
        hidden[i].removeAttribute('data-gpc-hidden');
      }
      // Reset main styles
      main.style.flex = '';
      main.style.display = '';
      main.style.flexDirection = '';
      main.style.overflow = '';
    }
  }

  /* ================================================================
   *  GPC compile / results / plans
   * ================================================================ */
  function compileGPC() {
    var input = document.getElementById('gpc-intent');
    var btn = document.getElementById('gpc-compile-btn');
    if (!input || !btn) return;
    var intent = input.value.trim();
    if (!intent) return;

    btn.textContent = 'COMPILING\u2026';
    btn.disabled = true;

    fetch(GPC_API + '/gpc/compile?intent=' + encodeURIComponent(intent), { method: 'POST' })
      .then(function (res) { if (!res.ok) throw new Error('Compilation failed'); return res.json(); })
      .then(function (data) { input.value = ''; showResult(data); fetchPlans(); })
      .catch(function (err) { showResult({ error: err.message }); })
      .finally(function () { btn.textContent = 'COMPILE PLAN'; btn.disabled = false; });
  }

  function showResult(data) {
    var container = document.getElementById('gpc-result');
    var content = document.getElementById('gpc-result-content');
    if (!container || !content) return;
    container.style.display = 'block';

    if (data.error) {
      content.innerHTML = '<div style="color:#f87171;padding:8px;border:1px solid rgba(248,113,113,0.2);border-radius:6px;">' + data.error + '</div>';
      return;
    }

    var html = '<div style="padding:10px;border:1px solid rgba(34,197,94,0.2);border-radius:8px;background:rgba(34,197,94,0.03);">';
    html += '<div style="color:#4ade80;font-size:10px;font-family:monospace;text-transform:uppercase;letter-spacing:0.2em;margin-bottom:8px;">Plan ' + (data.id ? data.id.slice(0, 8) : '\u2014') + ' \u2014 ' + data.status + '</div>';

    if (data.compiled_plan && data.compiled_plan.workflow_steps) {
      html += '<div style="margin-bottom:8px;">';
      data.compiled_plan.workflow_steps.forEach(function (s) {
        html += '<div style="display:flex;align-items:center;gap:8px;padding:3px 0;"><span style="width:18px;height:18px;border-radius:50%;border:1px solid rgba(249,115,22,0.3);display:flex;align-items:center;justify-content:center;font-size:9px;color:#f97316;font-family:monospace;">' + s.step + '</span><span style="color:rgba(255,255,255,0.6);font-size:11px;">' + s.action + '</span></div>';
      });
      html += '</div>';
    }

    if (data.risks) {
      html += '<div style="font-size:9px;color:#f97316;text-transform:uppercase;letter-spacing:0.2em;margin:8px 0 4px;">Risks</div>';
      data.risks.forEach(function (r) {
        var col = r.severity === 'critical' ? '#ef4444' : r.severity === 'high' ? '#f97316' : '#eab308';
        html += '<div style="font-size:10px;padding:4px 0;"><span style="color:' + col + ';font-family:monospace;text-transform:uppercase;font-size:8px;border:1px solid ' + col + '33;padding:1px 4px;border-radius:3px;">' + r.severity + '</span> <span style="color:rgba(255,255,255,0.5);margin-left:4px;">' + r.risk + '</span></div>';
      });
    }

    if (data.cost_estimate) {
      html += '<div style="border-top:1px solid rgba(255,255,255,0.05);margin-top:8px;padding-top:8px;"><span style="font-size:9px;color:rgba(255,255,255,0.3);text-transform:uppercase;letter-spacing:0.15em;">Total</span> <span style="font-size:16px;font-weight:700;color:rgba(255,255,255,0.8);margin-left:8px;">' + data.cost_estimate.total_estimated + '</span></div>';
    }

    html += '</div>';
    content.innerHTML = html;
  }

  function fetchPlans() {
    fetch(GPC_API + '/gpc/plans')
      .then(function (res) { return res.json(); })
      .then(function (plans) {
        var list = document.getElementById('gpc-plans-list');
        if (!list) return;
        if (!plans.length) { list.innerHTML = '<div style="color:rgba(255,255,255,0.15);font-style:italic;">No plans yet</div>'; return; }
        list.innerHTML = plans.map(function (p) {
          return '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 8px;border:1px solid rgba(255,255,255,0.05);border-radius:4px;margin-bottom:4px;cursor:default;">' +
            '<div><span style="font-family:monospace;font-size:9px;color:rgba(255,255,255,0.2);">' + (p.id ? p.id.slice(0, 8) : '') + '</span> <span style="color:rgba(255,255,255,0.5);margin-left:6px;font-size:11px;">' + (p.intent ? (p.intent.length > 40 ? p.intent.slice(0, 40) + '...' : p.intent) : '') + '</span></div>' +
            '<span style="font-size:8px;font-family:monospace;text-transform:uppercase;color:' + (p.status === 'compiled' ? '#4ade80' : '#f97316') + ';border:1px solid ' + (p.status === 'compiled' ? 'rgba(74,222,128,0.3)' : 'rgba(249,115,22,0.3)') + ';padding:1px 6px;border-radius:3px;">' + p.status + '</span>' +
          '</div>';
        }).join('');
      })
      .catch(function () {});
  }

  /* ================================================================
   *  Route handling
   * ================================================================ */
  var currentRoute = null;

  function handleRoute() {
    var hash = window.location.hash || '#/';
    if (hash === currentRoute) return;

    var wasGPC = currentRoute === '#/gpc';
    currentRoute = hash;

    if (hash === '#/gpc') {
      showGPC();
    } else if (wasGPC) {
      hideGPC();
    }
  }

  /* ================================================================
   *  Init
   * ================================================================ */
  window.addEventListener('hashchange', function () {
    setTimeout(handleRoute, 60);
  });

  var observer = new MutationObserver(function () {
    var nav = document.querySelector('nav');
    if (nav && (nav.querySelector('a[href="#/playground"]') || nav.querySelector('a[href="/playground"]'))) {
      injectSidebarLink();
      observer.disconnect();
      setTimeout(handleRoute, 200);
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });

  setTimeout(function () { injectSidebarLink(); handleRoute(); }, 1500);
})();
