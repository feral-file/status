Subject: Re: Feral File collection audit — the 2 v4s are frozen and correct; the 17 v5s are a separate contract class, stabilization plan coming next week

Hi Ryan,

Thanks for the file and the full-audit findings — with it we've traced every one of the 19 to its exact origin. Short version: the two v4 rows are correct and already permanently frozen; the 17 v5 rows are a different class of contract entirely, and I owe you a stabilization plan for them next week. Details below.

**The two v4 rows are correct — bind and resume freely.**
`study-for-unsupervised-by-refik-anadol` (`88397634-9974-40fa-ab9b-b9632410229e`) and `monopoly-set-by-peter-burr` (`7b70df63-d20f-44bb-9026-be9e824f0cf8`) are regular Feral File platform series. Those uuids are in the frozen mapping CSV I'm attaching (440 series → 294 collections), stored as explicit values as of 2026-09-04 — they can no longer drift. The values your API sees today are the values forever.

**The 17 v5 rows are a special class — deliberately not in that CSV.**
Those tokens live on contracts we deployed but that were never published through the Feral File exhibition system (they're the Aorist-era special projects, plus [[chromatophores]]). They have no series records in our database — which is why they're absent from the mapping CSV — and our API serves their metadata straight from the on-chain `tokenURI` documents. For this class, `collection_uuid` is currently computed by a special derivation: a deterministic UUIDv5 of the `collection_name` embedded in each token's metadata document (that's the scheme change you detected — it went live 2025-07-21). We've verified all 17 of your v5 values reproduce exactly from this derivation.

**On `uuid_previously_returned`: there is nothing to fill in.** Before 2025-07-21 our API returned no `collection_uuid` at all for this contract class, and the metadata documents themselves carry none — so the v4 values you have bound for these 17 never came from us. There's no old→new mapping to hand you; the reconciliation is simply old-bound-value → nothing-from-us, current v5 → what our API returns now.

**Your two questions:**

1. *Is v5 the permanent scheme?* It's not a rollout — it's a class split, and it's complete. Platform-published series (the CSV) return frozen stored values and always will; only this non-platform contract class uses the v5 derivation. No further series will flip.
2. *Is the v5 stable?* More stable than a title-derived value — it comes from the immutable IPFS metadata the on-chain `tokenURI` points at, so renames on our side can't touch it — but I wouldn't call it stable enough to be a permanent join key, because it's derived **per token**: any inconsistency in the embedded name across a project's tokens forks the collection. Your two `coral-arena` rows are exactly that, live: the tokens' embedded names differ only in capitalization ("CORAL ARENA by …" vs "Coral Arena by …"), producing two v5s and two collections.

**One question back before we freeze:** does the uuid *version* matter to your side — is there anything in your pipeline (validation, parsing, dedupe) that expects v4 and would choke on a v5 value? When we pin this class next week we can just as easily store the values as random v4 uuids instead of keeping the v5-derived ones, but that choice is one-way once you rebind — so tell us which shape your system prefers and we'll freeze to that.

**So please hold off rebinding the 17.** I'm taking the freeze question for this contract class to the team — the right fix is a pinned, stored uuid per collection rather than per-token derivation — and I'll come back to you with frozen values for all 17, target next week. Keep refreshes paused on them until then; that also covers the coral-arena split. In the meantime, everything that flows out of the Feral File system proper is frozen and safe — let's stabilize that majority first: the CSV is the authoritative mapping, the two v4s above can be bound now, Infinite Entropy stays on `71513905-f7b2-4ac1-b617-0d41123b3639`, and the resume/pause split from your last mail stands otherwise.

Thanks also for the corrections — 36 Points / Venuses sitting healthy in the exhibition-level collections, and the metadata-URL column being history rather than prediction. Both noted, and good to have re-confirmed the IPFS migration is unrelated.

Best,
Brandon
