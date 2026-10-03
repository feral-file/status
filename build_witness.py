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


def tally(rows):
    return {
        "checked": len(rows),
        "held": sum(1 for t in rows if t["held"] is True),
        "not_held": sum(1 for t in rows if t["held"] is False),
        "unanswerable": sum(1 for t in rows if t["held"] is None),
    }


STANDARD_NAMES = {"erc721": "ERC-721", "erc1155": "ERC-1155", "fa2": "FA2", "fa1.2": "FA1.2"}


def plain_sentences(e):
    """What the entry says, in words, with the counting unit stated."""
    out = []
    names = [r["name"] for r in e["readers"]]
    for r in e["readers"]:
        other = next(x for x in names if x != r["name"]) if len(names) == 2 else "the other reader"
        for ps in r["per_standard"]:
            sn = STANDARD_NAMES.get(ps["standard"], ps["standard"])
            oh = ps["only_here"]
            if oh["held"]:
                out.append(f"{other} omits {oh['held']:,} {sn} token{'s' if oh['held'] != 1 else ''} the chain says the address holds.")
            if oh["not_held"]:
                out.append(f"{r['name']} lists {oh['not_held']:,} {sn} token{'s' if oh['not_held'] != 1 else ''} the chain says the address does not hold.")
    both = {(b["contract"], b["token_id"]) for r in e["readers"] for b in r["both_listed_not_held"]}
    if both:
        out.append(f"{len(both)} token{'s' if len(both) != 1 else ''} both readers list {'are' if len(both) != 1 else 'is'} not held at this block: two readers can agree and both be wrong.")
    return out


def load_entries():
    entries = []
    for path in sorted(glob.glob(str(DATA / "holdings_*.json"))):
        if path.endswith(".lists.json"):
            continue
        e = json.loads(Path(path).read_text())
        check = e.get("chain_check", {})
        standards = [k for k in e["readers"][0]["count"] if k != "total"] if e.get("readers") else []
        diff_keys = {(t["contract"].lower(), t["token_id"]) for d in check.get("differences", []) for t in d["tokens"]}
        readers = []
        for r in e.get("readers", []):
            sample = next((x for x in check.get("samples", []) if x["reader"] == r["name"]), None)
            only = [d for d in check.get("differences", []) if d["listed_by"] == r["name"]]
            per_std = []
            for std in standards:
                srows = [t for t in (sample["tokens"] if sample else []) if t["standard"] == std]
                orows = [t for d in only if d["standard"] == std for t in d["tokens"]]
                per_std.append(
                    {
                        "standard": std,
                        "listed": r["count"].get(std, 0),
                        "sample": tally(srows),
                        "only_here": tally(orows),
                    }
                )
            # Tokens this reader listed that are not held, both from the sample and the differences, as distinct tokens.
            not_held_distinct = len({(t["contract"].lower(), t["token_id"]) for rows in ([sample["tokens"]] if sample else []) + [d["tokens"] for d in only] for t in rows if t["held"] is False})
            unans_distinct = len({(t["contract"].lower(), t["token_id"]) for rows in ([sample["tokens"]] if sample else []) + [d["tokens"] for d in only] for t in rows if t["held"] is None})
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
                    "per_standard": per_std,
                    "not_held_distinct": not_held_distinct,
                    "unanswerable_distinct": unans_distinct,
                    # Tokens in this reader's sample that the other reader also lists and the chain says are not held: both readers wrong.
                    "both_listed_not_held": [
                        {"contract": t["contract"], "token_id": t["token_id"], "owner": t["chain"].get("owner")}
                        for t in (sample["tokens"] if sample else [])
                        if t["held"] is False and (t["contract"].lower(), t["token_id"]) not in diff_keys
                    ],
                }
            )
        rc = check.get("rpc_recheck") or {}
        # Distinct tokens behind the recheck count: the recheck re-reads every not-held row, and a token can sit in a sample and in the differences.
        rc_distinct = len({(t["contract"].lower(), t["token_id"]) for x in check.get("samples", []) + check.get("differences", []) for t in x["tokens"] if t["held"] is False})
        unans_distinct = len({(t["contract"].lower(), t["token_id"]) for x in check.get("samples", []) + check.get("differences", []) for t in x["tokens"] if t["held"] is None})
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
                "rpc_recheck": {"rechecked": rc.get("rechecked", 0), "distinct_tokens": rc_distinct, "confirmed": rc.get("confirmed", rc.get("rechecked", 0)), "disagreements": len(rc.get("rpc_disagreements") or [])},
                "standards": standards,
                "unanswerable_distinct": unans_distinct,
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


def cell3(t):
    """held / not held / unanswerable, as one mono cell; zeros stay visible."""
    return f"{n(t['held'])} / {n(t['not_held'])} / {n(t['unanswerable'])}"


def entry_html(e):
    rows = ""
    for r in e["readers"]:
        for k, ps in enumerate(r["per_standard"]):
            if ps["listed"] == 0 and ps["only_here"]["checked"] == 0:
                continue
            reader_cell = f"{esc(r['name'])}<span class=\"operator\">{esc(r['operator'] or '')}</span>" if k == 0 else ""
            rows += (
                f"<tr><td>{reader_cell}</td><td>{esc(STANDARD_NAMES.get(ps['standard'], ps['standard']))}</td>"
                f"<td class=\"num\">{n(ps['listed'])}</td>"
                f"<td class=\"num\">{cell3(ps['sample'])}</td>"
                f"<td class=\"num\">{cell3(ps['only_here'])}</td></tr>"
            )
    signers = ", ".join(f'<abbr title="{esc(sg["kid"])}">{esc(short_kid(sg["kid"]))}</abbr>' for sg in e["signers"]) or "unsigned"
    rc = e["rpc_recheck"]
    if rc["rechecked"] == 0:
        rc_line = ""
    elif rc["disagreements"] == 0 and rc["confirmed"] == rc["rechecked"]:
        rc_line = f" A second node confirmed all {n(rc['rechecked'])} not-held results ({n(rc['distinct_tokens'])} distinct tokens)."
    else:
        rc_line = f" A second node re-read {n(rc['rechecked'])} not-held results: {n(rc['confirmed'])} confirmed, {n(rc['disagreements'])} differed (in the entry)."
    unans = e["unanswerable_distinct"]
    unans_line = f" {n(unans)} distinct token{'s' if unans != 1 else ''} could not be asked this way (no standard ledger call, or a standard this check does not cover) and count{'s' if unans == 1 else ''} for neither reader." if unans else ""
    lists = f' &middot; <a href="{esc(e["lists_file"])}">Both readers&rsquo; full lists</a>' if e.get("lists_file") else ""
    plain = "".join(f"<li>{esc(x)}</li>" for x in plain_sentences(e))
    plain_html = f'\n      <ul class="plain">{plain}</ul>' if plain else ""
    return f"""
    <article class="entry">
      <p class="entry-meta">{esc(e["date"])} &middot; {esc(e["chain_name"])} &middot; block {n(e["block"])}</p>
      <p class="entry-address"><a href="{esc(e["file"])}">{esc(e["address"])}</a></p>
      <table>
        <thead><tr><th>Reader</th><th>Standard</th><th class="num">Lists</th><th class="num">Sample<br>held / not / unanswered</th><th class="num">Only here<br>held / not / unanswered</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>{plain_html}
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
<meta name="description" content="Signed checks of what public indexers say an address holds, against the chain itself at one block. Every disagreement the chain can answer is answered; the rest stays marked unanswered. Anyone can add one.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Space+Mono&display=swap">
<link rel="stylesheet" href="static/style.css">
</head>
<body>
<main>
  <header>
    <p class="brand"><a href="https://feralfile.com">Feral File</a></p>
    <h1>Witness</h1>
    <p class="lede">Signed checks of what public indexers say an address holds, against the chain itself at one block. Every disagreement the chain can answer is answered; the rest stays marked unanswered. Signed by whoever looked. {(f"{n(count)} entries, " + esc(" and ".join(chains)) + ".") if entries else ""}</p>
  </header>

  <section id="why">
    <h2>Why this exists</h2>
    <p>Every app that shows you your collection, ours included, trusts an indexer to say what your address holds. Indexers disagree, by hundreds of tokens for a large collection, and each company corrects its own in private, so the errors are never visible and never shared. When two apps show you two different collections, you have no way to tell which one is wrong without taking a company&rsquo;s word for it.</p>
    <p>This page publishes the check instead. Two indexers are asked what an address holds, the chain is asked to settle every disagreement it can, and the result is signed by whoever ran it and published with every checked token. The aim is a record of who holds what that is kept by more than one party, so that a collector never has to trust any one of us for it. Feral File runs an indexer and sells the FF1 Art Computer; the checks here include our own indexer&rsquo;s errors, and the shared record is an aim, not yet a fact.</p>
  </section>

  <section id="what">
    <h2>What an entry is</h2>
    <p>A published work is a chain of references, and the chain starts with who holds the token. Every reader of a blockchain (an indexer: a service that reads the chain and lists what an address holds) can be wrong about that: an index lags, drops a token standard, or keeps listing a token after it moved. A witness entry records, for one address at one block, what each reader returned, where the readers differ, and what the chain itself says about a random sample from each list and about every token only one reader lists. Each answer is one of three: held, not held, or unanswerable. A reader is right or wrong per token, never in general.</p>
    <p>Each entry is a JSON file signed by whoever ran the check, in the same signature envelope the <a href="https://github.com/display-protocol/dp1">DP-1</a> playlist format uses. The signature covers the content, so an entry stays valid wherever it is served. Anyone can produce one, from their own readers, their own node, and their own key.</p>
    <p>What an entry does not establish: a token no reader lists is never asked of the chain, so two readers can agree and both be wrong. A token held is a token id, not an artwork or a playable work; unviewable and moderated tokens are counted, so totals differ from what an app shows. A check is a snapshot at one block, and the reader lists were fetched shortly before it, so a transfer in that window appears as a disagreement. One signature is one witness, not a corroboration. A later check does not show that an earlier app problem was fixed.</p>
  </section>

  <section id="entries">
    <h2>Entries</h2>
{(
    '<p class="legend">Lists: how many tokens of that standard the reader says the address holds. Sample: of a random 120 from the reader&rsquo;s whole list, how many of this standard the chain says are held, not held, and could not be asked. Only here: tokens this reader lists and the other omits, with the chain&rsquo;s answer the same three ways. The sentences under each table say the same in words, counting distinct tokens.</p>'
    + "".join(blocks)
) if entries else '    <p>No entries are published at the moment.</p>'}
  </section>

  <section id="method">
    <h2>How a check runs</h2>
    <p>Ask each reader for the address&rsquo;s holdings. Pin a block. Compare the lists per token standard. Then ask the chain, at that block, about a seeded random sample from each list and about every token only one reader lists. On Ethereum the question is <code>ownerOf(tokenId)</code> for ERC-721 and <code>balanceOf(address, tokenId)</code> for ERC-1155, by <code>eth_call</code>; on Tezos it is the contract&rsquo;s own <code>%ledger</code> big map, read from a node by key hash. A listed token the chain says is not held at that block is recorded as not held; the entry alone does not say whether the cause was the index, a standard it does not cover, or a transfer between the fetch and the block. A token the chain says is held that a reader omits is an omission. A contract that cannot be asked this way is recorded as unanswerable and counts for neither side. Every not-held result is re-read on a second node.</p>
    <p>Readers checked so far: on Ethereum, the Feral File indexer and Blockscout; on Tezos, TzKT and objkt. Our own indexer also depends on other indexes that are not yet readers here. None of the readers is treated as the truth, ours least of all.</p>
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
{"    <p>Every entry here so far was written by Feral File. The point of the shape is that the next one need not be.</p>" if entries else "    <p>The first entries will be Feral File&rsquo;s. The point of the shape is that the next ones need not be.</p>"}
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
    out = [
        "# Witness",
        "",
        "Signed checks of what public indexers say an address holds, against the chain itself at one block. Every disagreement the chain can answer is answered; the rest stays marked unanswered. Signed by whoever looked.",
        "",
        "Every app that shows a collection trusts an indexer to say what an address holds. Indexers disagree, and each company corrects its own in private. These entries publish the check instead: two indexers asked, the chain asked to settle every disagreement it can, the result signed by whoever ran it, with every checked token. The aim is a record of who holds what kept by more than one party. Feral File runs an indexer and sells the FF1 Art Computer; the checks include our own indexer's errors, and the shared record is an aim, not yet a fact.",
        "",
        "Each chain answer is one of three: held, not held, unanswerable (a contract that cannot be asked this way; counts for neither reader). A token no reader lists is never asked, so two readers can agree and both be wrong. A check is a snapshot at one block; a listed token not held at that block is a discrepancy whose cause the entry alone does not give.",
        "",
    ]
    for stem, es in group_by_name(entries).items():
        out.append(f"## {stem}")
        out.append("")
        for e in es:
            out.append(f"### {e['date']} — {e['chain_name']} · {e['address']} at block {e['block']:,}")
            out.append("")
            out.append("| Reader | Standard | Lists | Sample: held / not held / unanswerable | Only here: held / not held / unanswerable |")
            out.append("| :-- | :-- | --: | --: | --: |")
            for r in e["readers"]:
                for ps in r["per_standard"]:
                    if ps["listed"] == 0 and ps["only_here"]["checked"] == 0:
                        continue
                    out.append(f"| {r['name']} | {STANDARD_NAMES.get(ps['standard'], ps['standard'])} | {ps['listed']:,} | {cell3(ps['sample'])} | {cell3(ps['only_here'])} |")
            out.append("")
            for x in plain_sentences(e):
                out.append(f"- {x}")
            if plain_sentences(e):
                out.append("")
            signers = ", ".join(sg["kid"] for sg in e["signers"]) or "unsigned"
            rc = e["rpc_recheck"]
            rc_line = f" A second node confirmed all {rc['rechecked']:,} not-held results ({rc['distinct_tokens']:,} distinct tokens)." if rc["rechecked"] and rc["disagreements"] == 0 else ""
            unans = e["unanswerable_distinct"]
            unans_line = f" {unans} distinct token{'s' if unans != 1 else ''} could not be asked this way and count for neither reader." if unans else ""
            out.append(f"Signed by {signers}.{rc_line}{unans_line} Entry: {SITE_URL}/{e['file']}")
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

> Signed checks of what public indexers say an address holds, against the chain
> itself at one block: what each reader lists, where the readers differ, and the
> chain's own answer (held / not held / unanswerable) on a random sample and on
> every disagreement it can answer. Signed by whoever ran it (DP-1 signature
> envelope, Ed25519, did:key). Feral File runs one of the readers; the aim is a
> record kept by more than one party, not yet a fact. Anyone can append one.
> Served with open CORS.

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
