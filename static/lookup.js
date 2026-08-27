// Per-work lookup: token ID -> exhibition shard(s) -> file-by-file states.
// Same data as the tiles; no backend, everything fetched same-origin.

const STATE_LABEL = {
  independent: "resolves without Feral File",
  gateway_gap: "content-addressed, but failing on a public gateway",
  dependent: "depends entirely on Feral File",
  third_party: "depends on a third-party platform",
};

let indexPromise = null;
const shardCache = new Map();

function loadIndex() {
  if (!indexPromise) {
    indexPromise = fetch("data/work_index.json").then((r) => {
      if (!r.ok) throw new Error("index unavailable");
      return r.json();
    });
  }
  return indexPromise;
}

function loadShard(exId) {
  if (!shardCache.has(exId)) {
    shardCache.set(
      exId,
      fetch(`data/works/${exId}.json`).then((r) => {
        if (!r.ok) throw new Error("shard unavailable");
        return r.json();
      })
    );
  }
  return shardCache.get(exId);
}

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v;
    else if (k === "href") node.setAttribute("href", v);
    else node.setAttribute(k, v);
  }
  for (const c of children) {
    node.append(c);
  }
  return node;
}

function fileRow(f) {
  let where;
  let result;
  if (f.host === "ipfs") {
    where = "IPFS " + f.cid.slice(0, 10) + "…";
    result = ["ipfs.io", "ipfs.feralfile.com", "dweb.link"]
      .map((gw) => `${gw}: ${f[gw]}`)
      .join(" · ");
  } else if (f.host === "ipfs-archival") {
    where = "IPFS " + f.cid.slice(0, 14) + "… (whole series)";
    result = "byte-verified archival copy — co-pin welcome";
  } else {
    where = (f.host || "") + (f.domain ? " (" + f.domain + ")" : "");
    result = f.status ? "HTTP " + f.status : "not probed individually";
  }
  return el(
    "tr",
    null,
    el("td", null, f.res),
    el("td", null, where),
    el("td", { class: "num" }, result)
  );
}

function renderMatch(shard, tokenId, entry) {
  const ex = shard.exhibition;
  const box = el("div", { class: "lookup-match" });
  const title = el(
    "p",
    null,
    el(
      "a",
      { href: "https://feralfile.com/exhibitions/" + (ex.slug || "") },
      ex.title || ex.slug || "exhibition"
    ),
    ` · ${entry.chain}` + (entry.name ? ` · ${entry.name}` : "")
  );
  const state = el(
    "p",
    { class: "lookup-state" },
    "This work " + (STATE_LABEL[entry.state] || entry.state) + "."
  );
  const table = el(
    "table",
    null,
    el(
      "thead",
      null,
      el(
        "tr",
        null,
        el("th", null, "File"),
        el("th", null, "Kept where"),
        el("th", { class: "num" }, "Last check")
      )
    ),
    el("tbody", null, ...entry.files.map(fileRow))
  );
  box.append(title, state, table);
  return box;
}

async function lookup(q) {
  const out = document.getElementById("lookup-result");
  out.textContent = "";
  q = q.trim();
  if (!q) return;
  const walletKind = detectWallet(q);
  if (walletKind) return walletLookup(q, walletKind, out);
  out.textContent = "checking…";
  try {
    const index = await loadIndex();
    const exIds = index[q];
    if (!exIds || !exIds.length) {
      out.textContent =
        "No work with that token ID in the current data. Token IDs are exact — check for a missing or extra character.";
      return;
    }
    out.textContent = "";
    for (const exId of exIds) {
      const shard = await loadShard(exId);
      for (const entry of shard.works[q] || []) {
        out.append(renderMatch(shard, q, entry));
      }
    }
  } catch (e) {
    out.textContent = "Lookup data could not be loaded: " + e.message;
  }
}

document.getElementById("lookup-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  lookup(document.getElementById("lookup-input").value);
});
