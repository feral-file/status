#!/usr/bin/env python3
"""Build witness.feralfile.com from data/witness/ into public-witness/.

A witness entry is a signed statement of what each public reader says one
address holds and what the chain says, at one block (tools/witness/README.md).
This page lists the entries, says how to verify one, and how to append one.
No number on it is typed by hand.

    python3 build_witness.py       # writes public-witness/
"""

import glob
import html
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data" / "witness"
OUT = ROOT / "public-witness"
SITE_URL = "https://witness.feralfile.com"
REPO_URL = "https://github.com/feral-file/status"
TOOL_URL = f"{REPO_URL}/tree/main/tools/witness"

CHAIN_NAMES = {"eip155:1": "Ethereum", "tezos:NetXdQprcVkpaWU": "Tezos"}


def esc(s):
    return html.escape(str(s), quote=True)


def n(v):
    return f"{v:,}" if isinstance(v, int) else esc(v)


def load_entries():
    entries = []
    for path in sorted(glob.glob(str(DATA / "holdings_*.json"))):
        if path.endswith(".lists.json"):
            continue
        e = json.loads(Path(path).read_text())
        check = e.get("chain_check", {})
        readers = []
        for r in e.get("readers", []):
            sample = next((x for x in check.get("samples", []) if x["reader"] == r["name"]), None)
            only = [d for d in check.get("differences", []) if d["listed_by"] == r["name"]]
            readers.append(
                {
                    "name": r["name"],
                    "operator": r.get("operator"),
                    "listed": r["count"]["total"],
                    "sample_checked": sample["checked"] if sample else 0,
                    "sample_held": sample["held"] if sample else 0,
                    "sample_unanswerable": sample.get("unanswerable", 0) if sample else 0,
                    "only_listed_here": sum(d["checked"] for d in only),
                    "only_listed_here_chain_held": sum(d["held"] for d in only),
                    "only_listed_here_unanswerable": sum(d.get("unanswerable", 0) for d in only),
                }
            )
        rc = check.get("rpc_recheck") or {}
        subj = e["subject"]
        entries.append(
            {
                "file": "data/witness/" + Path(path).name,
                "lists_file": "data/witness/" + e["lists"]["file"] if e.get("lists") else None,
                "observed_at": e["observed_at"],
                "date": e["observed_at"][:10],
                "chain": subj["chain"],
                "chain_name": CHAIN_NAMES.get(subj["chain"], subj["chain"]),
                "address": subj["address"],
                "name": subj.get("name") or subj.get("ens"),
                "block": e["chain_state"]["block"],
                "readers": readers,
                "rpc_recheck": {"rechecked": rc.get("rechecked", 0), "confirmed": rc.get("confirmed", rc.get("rechecked", 0)), "disagreements": len(rc.get("rpc_disagreements") or [])},
                "signers": [{"kid": sg["kid"], "role": sg.get("role")} for sg in e.get("signatures", [])],
            }
        )
    entries.sort(key=lambda e: (e["name"] or e["address"], e["chain"], e["observed_at"]), reverse=False)
    return entries


def group_by_name(entries):
    """Entries grouped by the person behind them: the name stem (thefunnyguys for
    thefunnyguys.eth and thefunnyguys.tez), else the address."""
    groups = {}
    for e in entries:
        stem = (e["name"] or "").rsplit(".", 1)[0] or e["address"]
        groups.setdefault(stem, []).append(e)
    return groups


def short_kid(kid):
    return kid if len(kid) <= 28 else kid[:16] + "\u2026" + kid[-8:]


def entry_html(e):
    rows = "".join(
        f"<tr><td>{esc(r['name'])}<span class=\"operator\">{esc(r['operator'] or '')}</span></td>"
        f"<td class=\"num\">{n(r['listed'])}</td>"
        f"<td class=\"num\">{n(r['sample_held'])} of {n(r['sample_checked'])}</td>"
        f"<td class=\"num\">{n(r['only_listed_here'])} &middot; {n(r['only_listed_here_chain_held'])}</td></tr>"
        for r in e["readers"]
    )
    signers = ", ".join(f'<abbr title="{esc(sg["kid"])}">{esc(short_kid(sg["kid"]))}</abbr>' for sg in e["signers"]) or "unsigned"
    rc = e["rpc_recheck"]
    if rc["rechecked"] == 0:
        rc_line = ""
    elif rc["disagreements"] == 0 and rc["confirmed"] == rc["rechecked"]:
        rc_line = f" A second node confirmed all {n(rc['rechecked'])} not-held verdicts."
    else:
        rc_line = f" A second node re-read {n(rc['rechecked'])} not-held verdicts: {n(rc['confirmed'])} confirmed, {n(rc['disagreements'])} differed (in the entry)."
    unans = sum(r["sample_unanswerable"] + r["only_listed_here_unanswerable"] for r in e["readers"])
    unans_line = f" {n(unans)} token{'s' if unans != 1 else ''} could not be asked this way and count{'s' if unans == 1 else ''} for neither reader." if unans else ""
    lists = f' &middot; <a href="{esc(e["lists_file"])}">Both readers&rsquo; full lists</a>' if e.get("lists_file") else ""
    return f"""
    <article class="entry">
      <p class="entry-meta">{esc(e["date"])} &middot; {esc(e["chain_name"])} &middot; block {n(e["block"])}</p>
      <p class="entry-address"><a href="{esc(e["file"])}">{esc(e["address"])}</a></p>
      <table>
        <thead><tr><th>Reader</th><th class="num">Lists</th><th class="num">Sample held</th><th class="num">Only here &middot; held</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
      <p class="entry-foot">Signed by {signers}.{rc_line}{unans_line}</p>
      <p class="entry-foot"><a href="{esc(e["file"])}">Entry</a> (JSON, every checked token with the chain&rsquo;s answer){lists}</p>
    </article>"""


def render(entries, generated_at):
    groups = group_by_name(entries)
    blocks = []
    for stem, es in groups.items():
        names = sorted({e["name"] for e in es if e["name"]})
        sub = f'\n      <p class="names">{esc(" &middot; ".join(names))}</p>'.replace("&amp;middot;", "&middot;") if names and names != [stem] else ""
        blocks.append(f'\n    <section class="person" id="{esc(stem)}">\n      <h2>{esc(stem)}</h2>{sub}' + "".join(entry_html(e) for e in es) + "\n    </section>")
    count = len(entries)
    people = len(groups)
    chains = sorted({e["chain_name"] for e in entries})
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Witness</title>
<meta name="description" content="Signed observations of who holds what, checked against the chain. One address, one block, every disagreement between readers settled on chain, signed by whoever looked.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Space+Mono&display=swap">
<link rel="stylesheet" href="static/style.css">
</head>
<body>
<main>
  <header>
    <p class="brand"><a href="https://feralfile.com">Feral File</a></p>
    <h1>Witness</h1>
    <p class="lede">Signed observations of who holds what, checked against the chain. One address, one block, two readers, every disagreement settled by the chain itself, signed by whoever looked. {(f"{n(count)} entries, {n(people)} people, " + esc(" and ".join(chains)) + ".") if entries else ""}</p>
  </header>

  <section id="what">
    <h2>What an entry is</h2>
    <p>A published work is a chain of references, and the chain starts with who holds the token. Every reader of a blockchain, ours included, can be wrong about that: an index lags, drops a token standard, or keeps listing a token after it moved. A witness entry records, for one address at one block, what each public reader returned, where the readers differ, and what the chain itself says about a random sample from each list and about every token the readers disagree on. The chain decides. A reader is right or wrong per token, never in general.</p>
    <p>Each entry is a JSON file signed by whoever ran the check, in the same signature envelope the <a href="https://github.com/display-protocol/dp1">DP-1</a> playlist format uses. The signature covers the content, so an entry stays valid wherever it is served. Anyone can produce one, from their own readers, their own node, and their own key.</p>
  </section>

  <section id="entries">
    <h2>Entries</h2>
{(
    '<p class="legend">Lists: how many tokens the reader says the address holds. Sample held: of a random 120 from that list, how many the chain says are held. Only here &middot; held: tokens this reader lists and the other omits, and how many of those the chain says are held.</p>'
    + "".join(blocks)
) if entries else '    <p>No entries are published yet.</p>'}
  </section>

  <section id="method">
    <h2>How a check runs</h2>
    <p>Ask each reader for the address&rsquo;s holdings. Pin a block. Compare the two lists per token standard. Then ask the chain, at that block, about a seeded random sample from each list and about every token only one reader lists. On Ethereum the question is <code>ownerOf(tokenId)</code> for ERC-721 and <code>balanceOf(address, tokenId)</code> for ERC-1155, by <code>eth_call</code>; on Tezos it is the contract&rsquo;s own <code>%ledger</code> big map, read from a node by key hash. A token the reader lists that the chain says is held elsewhere, or that no longer exists, is a reader error or lag. A token the chain says is held that a reader omits is an under-count. A contract that cannot be asked this way is recorded as unanswerable and counts for neither side. Every not-held verdict is re-read on a second node.</p>
    <p>Readers today: Ethereum, the Feral File indexer and Blockscout; Tezos, TzKT and objkt. The readers are the ones we and the apps around us depend on. None of them is treated as the truth.</p>
  </section>

  <section id="verify">
    <h2>Verify an entry</h2>
    <p>No install beyond Node. The script recomputes the canonical bytes, checks the payload hash, and checks the Ed25519 signature against the public key in the signer&rsquo;s <code>did:key</code>.</p>
    <pre><code>git clone {esc(REPO_URL)}.git &amp;&amp; cd status
curl -s {esc(SITE_URL)}/data/witness/&lt;entry&gt;.json | node tools/witness/verify.mjs -</code></pre>
  </section>

  <section id="append">
    <h2>Append an entry</h2>
    <p>Run the same check from your own vantage point: your readers, your node, your key. Keep the schema and name your reader and its operator. Publish the file wherever you publish things, or open a pull request that adds it under <code>data/witness/</code> in <a href="{esc(REPO_URL)}">feral-file/status</a>; this page lists every entry it finds there. The method, the schema, and the signing and verifying scripts are in <a href="{esc(TOOL_URL)}">tools/witness</a>.</p>
    <p>Every entry here so far was written by Feral File. The point of the shape is that the next one need not be.</p>
  </section>

  <section id="data">
    <h2>Data</h2>
    <ul>
      <li><a href="data/entries.json">entries.json</a> &mdash; every entry on this page, summarized, with its URL and signers</li>
      <li><a href="data/witness/">data/witness/</a> &mdash; the entries and the readers&rsquo; full lists, as published</li>
      <li><a href="witness.md">witness.md</a> &mdash; this page as plain Markdown</li>
      <li><a href="llms.txt">llms.txt</a> &mdash; for agents</li>
    </ul>
    <p class="dated">Data is served with open CORS. The page is regenerated by <code>build_witness.py</code> in the same repository as the status page.</p>
  </section>
</main>

<footer>
  <p>Generated {esc(generated_at)} &middot; <a href="https://status.feralfile.com">status.feralfile.com</a> &middot; <a href="https://feralfile.com">feralfile.com</a></p>
</footer>
</body>
</html>
"""


def render_md(entries, generated_at):
    out = ["# Witness", "", "Signed observations of who holds what, checked against the chain. One address, one block, two readers, every disagreement settled by the chain itself, signed by whoever looked.", ""]
    for stem, es in group_by_name(entries).items():
        out.append(f"## {stem}")
        out.append("")
        for e in es:
            out.append(f"### {e['date']} — {e['chain_name']} · {e['address']} at block {e['block']:,}")
            out.append("")
            out.append("| Reader | Lists | Random sample: chain says held | Lists, other reader omits | …of which chain says held |")
            out.append("| :-- | --: | --: | --: | --: |")
            for r in e["readers"]:
                out.append(f"| {r['name']} | {r['listed']:,} | {r['sample_held']:,} / {r['sample_checked']:,} | {r['only_listed_here']:,} | {r['only_listed_here_chain_held']:,} |")
            out.append("")
            signers = ", ".join(sg["kid"] for sg in e["signers"]) or "unsigned"
            out.append(f"Signed by {signers}. Entry: {SITE_URL}/{e['file']}")
            out.append("")
    out += [f"Method, schema, verify and append: {TOOL_URL}", "", f"Generated {generated_at}", ""]
    return "\n".join(out)


def render_llms(entries):
    lines = "".join(
        f"- [{e['date']} {e['chain_name']} {e['address']}]({SITE_URL}/{e['file']}): block {e['block']}, "
        + "; ".join(f"{r['name']} lists {r['listed']}, chain confirms {r['sample_held']}/{r['sample_checked']} sampled" for r in e["readers"])
        + "\n"
        for e in entries
    )
    return f"""# Witness

> Signed observations of who holds what, checked against the chain. Each entry
> is one address at one block: what each public reader lists, where the readers
> differ, and the chain's own answer on a random sample and on every
> disagreement. Signed by whoever ran it (DP-1 signature envelope, Ed25519,
> did:key). Anyone can append one. Served with open CORS.

## Read this first

- [witness.md]({SITE_URL}/witness.md): the whole page as Markdown
- [entries.json]({SITE_URL}/data/entries.json): every entry, summarized, with URLs
- Schema, method, verify and append: {TOOL_URL}

## Entries

{lines}"""


def main():
    entries = load_entries()
    now = datetime.now(timezone.utc)
    generated_at = now.strftime("%Y-%m-%d %H:%M UTC")
    if OUT.exists():
        for item in OUT.iterdir():
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    (OUT / "data" / "witness").mkdir(parents=True)
    shutil.copytree(ROOT / "static", OUT / "static")
    for f in glob.glob(str(DATA / "holdings_*.json")):
        shutil.copy(f, OUT / "data" / "witness" / Path(f).name)
    (OUT / "data" / "witness" / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>data/witness</title><ul>"
        + "".join(f'<li><a href="{esc(Path(f).name)}">{esc(Path(f).name)}</a></li>' for f in sorted(glob.glob(str(DATA / "holdings_*.json"))))
        + "</ul>"
    )
    (OUT / "data" / "entries.json").write_text(
        json.dumps(
            {"generated_at": now.isoformat(timespec="seconds"), "site": SITE_URL, "entries": [{**e, "url": f"{SITE_URL}/{e['file']}"} for e in entries]},
            indent=2,
            ensure_ascii=False,
        )
    )
    (OUT / "index.html").write_text(render(entries, generated_at))
    (OUT / "witness.md").write_text(render_md(entries, generated_at))
    (OUT / "llms.txt").write_text(render_llms(entries))
    (OUT / "robots.txt").write_text("User-agent: *\nAllow: /\n")
    (OUT / "_headers").write_text("/*\n  Access-Control-Allow-Origin: *\n\n/witness.md\n  Content-Type: text/markdown; charset=utf-8\n\n/llms.txt\n  Content-Type: text/plain; charset=utf-8\n")
    print(f"built public-witness/ ({len(entries)} entries)")


if __name__ == "__main__":
    main()
