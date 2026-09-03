(() => {
  if (window.__TMALL_AI_SAFE_REVIEW_HOOK__) return;
  window.__TMALL_AI_SAFE_REVIEW_HOOK__ = true;

  const MAX_RECORDS = 100;
  const MAX_TEXT = 1200000;
  const MATCH = /review|rate|comment|feedback|evaluate|buyer|remark|ratedetail|ask|question|wdj|评价|评论|问大家/i;

  window.__TMALL_AI_CAPTURE__ = Array.isArray(window.__TMALL_AI_CAPTURE__)
    ? window.__TMALL_AI_CAPTURE__ : [];
  window.__TMALL_AI_SOURCE_SNAPSHOTS__ = Array.isArray(window.__TMALL_AI_SOURCE_SNAPSHOTS__)
    ? window.__TMALL_AI_SOURCE_SNAPSHOTS__ : [];

  function pushCapture(rec) {
    try {
      if (!rec || !MATCH.test(String(rec.url || ""))) return;
      const text = String(rec.text || "").slice(0, MAX_TEXT);
      const key = [rec.method || "", rec.url || "", text.slice(0, 240)].join("|");
      const list = window.__TMALL_AI_CAPTURE__;
      if (list.some(x => x && x.__safeKey === key)) return;
      list.push({...rec, text, __safeKey:key, capturedAt:Date.now(), captureMode:"passive_network"});
      while (list.length > MAX_RECORDS) list.shift();
    } catch (_) {}
  }

  // Passive fetch interception: clones only the response the page already requested.
  try {
    const originalFetch = window.fetch;
    if (typeof originalFetch === "function") {
      window.fetch = async function(...args) {
        const response = await originalFetch.apply(this, args);
        try {
          const req = args[0];
          const opt = args[1] || {};
          const url = String(req?.url || req || "");
          if (MATCH.test(url)) {
            const clone = response.clone();
            clone.text().then(text => {
              pushCapture({
                url,
                method:String(opt.method || req?.method || "GET"),
                status:response.status,
                text
              });
            }).catch(() => {});
          }
        } catch (_) {}
        return response;
      };
    }
  } catch (_) {}

  // Passive XHR interception: reads response after normal page request completes.
  try {
    const open = XMLHttpRequest.prototype.open;
    const send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url, ...rest) {
      this.__tmall_ai_url = String(url || "");
      this.__tmall_ai_method = String(method || "GET");
      return open.call(this, method, url, ...rest);
    };
    XMLHttpRequest.prototype.send = function(...args) {
      if (MATCH.test(this.__tmall_ai_url || "")) {
        this.addEventListener("load", () => {
          try {
            const txt = typeof this.responseText === "string" ? this.responseText : "";
            pushCapture({
              url:this.__tmall_ai_url,
              method:this.__tmall_ai_method || "XHR",
              status:this.status,
              text:txt
            });
          } catch (_) {}
        }, {once:true});
      }
      return send.apply(this, args);
    };
  } catch (_) {}

  // Page-code snapshots. Only read script text already present in the DOM.
  function snapshotScripts() {
    try {
      const out = [];
      const scripts = document.scripts ? Array.from(document.scripts) : [];
      for (const s of scripts) {
        const txt = String(s.textContent || "");
        if (txt.length < 20) continue;
        if (!/review|rate|comment|evaluate|feedback|question|ask|评价|评论|问大家/i.test(txt)) continue;
        out.push({
          source:"inline_script",
          text:txt.slice(0, MAX_TEXT),
          capturedAt:Date.now()
        });
        if (out.length >= 12) break;
      }
      window.__TMALL_AI_SOURCE_SNAPSHOTS__ = out;
    } catch (_) {}
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", snapshotScripts, {once:true});
  } else {
    snapshotScripts();
  }

  // Mutation is only used to refresh already-present inline JSON snapshots.
  try {
    let timer = 0;
    const mo = new MutationObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(snapshotScripts, 1200);
    });
    mo.observe(document.documentElement, {childList:true, subtree:true});
  } catch (_) {}

  window.__TMALL_AI_SAFE_CAPTURE_STATUS__ = () => ({
    mode:"passive_code_and_network",
    networkRecords:(window.__TMALL_AI_CAPTURE__ || []).length,
    sourceSnapshots:(window.__TMALL_AI_SOURCE_SNAPSHOTS__ || []).length,
    extraRequestsCreated:0,
    installed:true
  });
})();
