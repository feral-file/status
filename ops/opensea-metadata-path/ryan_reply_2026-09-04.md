# Reply from Ryan (OpenSea), 2026-09-04 — answers `reply_to_ryan_2026-09-04.md`

*Attachment: `opensea_ff_collections_full_2026-09-04.csv` (410 rows, their full
list of Feral File collections with category / bound uuid / our current API uuid).
Recorded verbatim below; our follow-up state is in README.md and
`ops/cdn-retirement-phase2/STATUS.md`.*

---

Hi Brandon,

This is exactly what we needed. Answers below, plus the full collection list you asked for and one finding that expands the scope of your freeze plan.

**Your question: does the uuid version matter to us?**

No. Pick whichever is more stable on your side and we will take it.

We store collection_uuid as an opaque string. It is never parsed as a UUID, never version-checked, and has no format validation beyond being non-empty. The strongest evidence is what is already in the field: of 4,000 live values we sampled, only 327 are UUID-shaped at all. The rest are Bitcoin inscription ids, because the same field is used for Bitcoin collections. And 7 of the UUID-shaped values are already v5 today, working normally.

So keeping the v5-derived values costs us nothing, and moving to random v4 costs us nothing either. The version is not the property we care about. The two that matter are that the value is stable for the life of the collection, and that it is one value per collection rather than derived per token. Your plan to store a pinned uuid per collection gives us both, whichever shape you pick.

**Done on our side**

Infinite Entropy is fixed, not in progress. It is bound to 71513905-f7b2-4ac1-b617-0d41123b3639, all 24 tokens are back in the verified collection, and the duplicate is empty. The two stale uuids no longer resolve to anything.

We also bound five collections, not the two you called out. All five appear in your authoritative CSV with matching uuids, so we believe they are all correct, but flag it if any look wrong to you:

```
  Infinite Entropy by Rafael Rozendaal          71513905-...
  Study for Unsupervised by Refik Anadol        88397634-...
  MONOPOLY SET by Peter Burr                    7b70df63-...
  Peer to Peer Launch Party Exclusive           053acd9a-...
  Inaugural SuperBridge Summit                  d80846db-...
```

Separately, we moved 198 tokens that were sitting in exhibition-level groupings into their correct series. That covers 36 Points and Venuses from your first mail, which are now in their own verified collections rather than the exhibition bucket.

The 17 are on hold as you asked, and refreshes stay paused on them.

**The special-project class is larger than 17**

This is the part worth your attention before you freeze.

We hold 57 collections that belong to this non-platform class, not 17. The 17 you have are the ones still unbound. Another 15 are already bound to v5-derived values from earlier refreshes, including a2p-v1, a2p-v2, artificial-natural-history, breathing-language, neural-zoo, self-contained, take-over-madrid, take-over-miami, temporally-uncaptured and three Machine Hallucinations collections. The rest are unbound variants of the same projects.

More importantly, coral-arena is not the only live split. Five projects have already forked into duplicate sets on our side, from the same per-token derivation:

```
  a2p-v1                     2 collections
  a2p-v2                     2 collections
  aorist-art                 3 collections
  artificial-natural-history 2 collections
  temporally-uncaptured      2 collections
```

So when you pin this class, the mapping needs to cover all 57 and decide which collection wins for each of those five, not just the 17 and coral-arena. The full list is in the attachment so you can see exactly which is which.

**Your 408 question, and a correction to that number**

It is 410, not 408. My earlier count keyed on collections whose owner is your deployer address, and two of them have no owner set on our side, so my own query missed them. Both are legitimate: Peer to Peer Launch Party Exclusive and Inaugural SuperBridge Summit.

The full breakdown, attached as opensea_ff_collections_full.csv:

```
  291  live series matching your mapping
   39  bound to a uuid not in your mapping (23 are Infinite Entropy duplicates we
       created and have now emptied; 15 are the v5 special-project class above)
   33  exhibition-level groupings that exist only on our side, one per exhibition,
       not series (these are ours, not yours, and are expected)
   25  unbound, almost all the special-project class
   17  the v5 rows you already have
    5  duplicates we auto-created, now empty
  ---
  410
```

So the roughly 95 you could not identify are, in short: our own exhibition groupings, our own duplicates from the uuid drift, and the special-project class showing up under more collections than the 17.
