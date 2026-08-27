// Wallet lookup: paste an address, get every published Feral File work it
// holds, plus a machine-readable pin list of their content addresses.
// Holdings come from keyless public indexers, called straight from the
// browser (Blockscout for Ethereum, TzKT for Tezos) — the page keeps its
// no-backend property. The join against our own data uses the same
// work_index.json + shards as the token-ID lookup (loadIndex/loadShard
// live in lookup.js; both scripts share the page scope).

const BLOCKSCOUT = "https://eth.blockscout.com/api/v2";
const TZKT = "https://api.tzkt.io/v1";
const PAGE_CAP = 400; // indexer pages; 400 × 50 = 20k ETH tokens, plenty

function detectWallet(q) {
  if (/^0x[0-9a-fA-F]{40}$/.test(q)) return "eth";
  if (/^(tz1|tz2|tz3)[1-9A-HJ-NP-Za-km-z]{33}$/.test(q)) return "tezos";
  return null;
}

async function fetchEthHoldings(addr, progress) {
  const held = [];
  let extra = "";
  for (let page = 0; page < PAGE_CAP; page++) {
    const r = await fetch(
      `${BLOCKSCOUT}/addresses/${addr}/nft?type=ERC-721%2CERC-1155${extra}`
    );
    if (r.status === 404) return held; // address never seen on chain
    if (!r.ok) throw new Error("Blockscout answered HTTP " + r.status);
    const d = await r.json();
    for (const it of d.items || []) {
      if (it.id && it.token && it.token.address_hash) {
        held.push({ contract: it.token.address_hash, tokenId: String(it.id) });
      }
    }
    progress(`reading Ethereum holdings from Blockscout — ${held.length} tokens…`);
    if (!d.next_page_params) return held;
    extra = "&" + new URLSearchParams(d.next_page_params).toString();
  }
  return held;
}

async function fetchTezosHoldings(addr, progress) {
  const held = [];
  const limit = 1000;
  for (let page = 0; page < PAGE_CAP; page++) {
    const r = await fetch(
      `${TZKT}/tokens/balances?account=${addr}&balance.gt=0&limit=${limit}` +
        `&offset=${page * limit}&select=token.contract.address,token.tokenId`
    );
    if (!r.ok) throw new Error("TzKT answered HTTP " + r.status);
    const rows = await r.json();
    for (const row of rows) {
      const contract = row["token.contract.address"];
      const tokenId = row["token.tokenId"];
      if (contract && tokenId != null) held.push({ contract, tokenId: String(tokenId) });
    }
    progress(`reading Tezos holdings from TzKT — ${held.length} token balances…`);
    if (rows.length < limit) return held;
  }
  return held;
}

function sameContract(kind, a, b) {
  return kind === "eth" ? a.toLowerCase() === b.toLowerCase() : a === b;
}

// Join held (contract, tokenId) pairs against the published shards.
// Returns one record per matched work.
async function matchHoldings(held, kind, progress) {
  const index = await loadIndex();
  const seen = new Set();
  const candidates = [];
  for (const h of held) {
    const key = h.contract + "/" + h.tokenId;
    if (seen.has(key)) continue;
    seen.add(key);
    if (index[h.tokenId]) candidates.push(h);
  }
  progress(`checking ${candidates.length} candidate works against the census…`);
  const exIds = new Set();
  for (const h of candidates) index[h.tokenId].forEach((id) => exIds.add(id));
  const shards = new Map();
  await Promise.all(
    [...exIds].map((id) => loadShard(id).then((s) => shards.set(id, s)))
  );
  const matches = [];
  for (const h of candidates) {
    for (const exId of index[h.tokenId]) {
      const shard = shards.get(exId);
      for (const entry of (shard && shard.works[h.tokenId]) || []) {
        if (sameContract(kind, entry.contract || "", h.contract)) {
          matches.push({ tokenId: h.tokenId, exhibition: shard.exhibition, entry });
        }
      }
    }
  }
  return matches;
}

function pinnableCids(entry) {
  const out = [];
  for (const f of entry.files || []) {
    if (f.cid && (f.host === "ipfs" || f.host === "ipfs-archival")) {
      out.push({ cid: f.cid, wholeSeries: f.host === "ipfs-archival" });
    }
  }
  return out;
}

function workLabel(m) {
  const name = m.entry.name ? m.entry.name : "token …" + m.tokenId.slice(-8);
  return name;
}

function renderWalletResult(out, addr, kind, held, matches) {
  const chainName = kind === "eth" ? "Ethereum" : "Tezos";
  out.textContent = "";

  const pinnable = [];
  const unpinnable = [];
  const cidMap = new Map(); // cid -> {wholeSeries, works: count}
  for (const m of matches) {
    const cids = pinnableCids(m.entry);
    (cids.length ? pinnable : unpinnable).push(m);
    for (const c of cids) {
      const rec = cidMap.get(c.cid) || { wholeSeries: c.wholeSeries, works: 0 };
      rec.works += 1;
      cidMap.set(c.cid, rec);
    }
  }

  out.append(
    el(
      "p",
      null,
      `This address holds ${held.length.toLocaleString()} ${chainName} ` +
        `token${held.length === 1 ? "" : "s"}; ` +
        `${matches.length.toLocaleString()} ${matches.length === 1 ? "is a" : "are"} published ` +
        `Feral File work${matches.length === 1 ? "" : "s"}.`
    )
  );

  if (!matches.length) {
    out.append(
      el(
        "p",
        { class: "lookup-state" },
        "Bitmark-era works cannot be enumerated from a wallet address — " +
          "for those, paste the work's 64-character token ID instead."
      )
    );
    return;
  }

  // The machine artifact first — with a big collection the table below is
  // long, and the pin list is what a collector came for.
  if (cidMap.size) {
    const cids = [...cidMap.keys()];
    const listText = cids.join("\n") + "\n";
    const heading = el(
      "p",
      null,
      el("strong", null, "Pin list — hold your own copies. "),
      `${cids.length.toLocaleString()} unique content address${cids.length === 1 ? "" : "es"} ` +
        "(editions of the same work share files). One CID per line; with a " +
        "local IPFS node:"
    );
    const cmd = el(
      "pre",
      { class: "pin-cmd" },
      "xargs -n1 ipfs pin add < feralfile-pins.txt"
    );
    const listBox = el("pre", { class: "pin-list" }, listText);
    const actions = el("div", { class: "wallet-actions" });
    const copyBtn = el("button", { type: "button" }, "Copy list");
    copyBtn.addEventListener("click", () => {
      navigator.clipboard.writeText(listText).then(() => {
        copyBtn.textContent = "Copied";
        setTimeout(() => (copyBtn.textContent = "Copy list"), 1500);
      });
    });
    const dl = el(
      "a",
      {
        href: "data:text/plain;charset=utf-8," + encodeURIComponent(listText),
        download: "feralfile-pins.txt",
      },
      "Download feralfile-pins.txt"
    );
    actions.append(copyBtn, dl);
    out.append(heading, cmd, listBox, actions);
    const series = [...cidMap.values()].filter((r) => r.wholeSeries).length;
    if (series) {
      out.append(
        el(
          "p",
          { class: "lookup-state" },
          `${series} of these are whole-series archival copies — large pins, ` +
            "byte-verified; co-pinning is welcome."
        )
      );
    }
  }

  // Per-work table.
  const rows = matches.map((m) => {
    const cids = pinnableCids(m.entry);
    let copies;
    if (cids.length) {
      copies = cids.length + " content-addressed file" + (cids.length === 1 ? "" : "s");
    } else {
      copies = "nothing to pin yet";
    }
    return el(
      "tr",
      null,
      el(
        "td",
        null,
        el(
          "a",
          {
            href:
              "https://feralfile.com/exhibitions/shows/" +
              (m.exhibition.slug || ""),
          },
          m.exhibition.title || m.exhibition.slug || "exhibition"
        )
      ),
      el("td", null, workLabel(m)),
      el("td", null, STATE_LABEL[m.entry.state] || m.entry.state || ""),
      el("td", { class: "num" }, copies)
    );
  });
  out.append(
    el(
      "table",
      null,
      el(
        "thead",
        null,
        el(
          "tr",
          null,
          el("th", null, "Exhibition"),
          el("th", null, "Work"),
          el("th", null, "State"),
          el("th", { class: "num" }, "Held copies")
        )
      ),
      el("tbody", null, ...rows)
    )
  );

  if (unpinnable.length) {
    out.append(
      el(
        "p",
        { class: "lookup-state" },
        `${unpinnable.length} of these work${unpinnable.length === 1 ? " has" : "s have"} ` +
          "no published content address yet — there is nothing to pin for them " +
          "until addresses are published (the reference phase above). They are " +
          "listed so they are not silently dropped."
      )
    );
  }

  out.append(
    el(
      "p",
      { class: "lookup-state" },
      "Wallet enumeration comes from " +
        (kind === "eth" ? "Blockscout" : "TzKT") +
        ", queried from your browser; this site has no server and never " +
        "sees the address. Bitmark-era works cannot be enumerated from a " +
        "wallet — paste their 64-character token IDs individually."
    )
  );
}

async function walletLookup(addr, kind, out) {
  const progress = (msg) => (out.textContent = msg);
  try {
    progress("reading holdings…");
    const held =
      kind === "eth"
        ? await fetchEthHoldings(addr, progress)
        : await fetchTezosHoldings(addr, progress);
    const matches = await matchHoldings(held, kind, progress);
    renderWalletResult(out, addr, kind, held, matches);
  } catch (e) {
    out.textContent =
      "Wallet lookup failed: " +
      e.message +
      " — the chain indexer may be briefly unavailable; the token-ID lookup " +
      "still works.";
  }
}
