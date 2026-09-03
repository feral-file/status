# Media verification record — acceptance run 2026-09-01

`tools/metadata-regen/verify-media.py plan.csv` over the 436 distinct media CIDs the
regenerated metadata points at. Requirement: 200/206 on `ipfs.feralfile.com` AND on ≥1 public
gateway (ipfs.io / dweb.link / gateway.pinata.cloud).

Result: **436/436 pass**. The raw csv of the final run was not kept; 415 CIDs passed directly,
and the 21 that failed the automated pass were each re-verified by hand the same day (all
transient/gateway-policy, none a content problem):

- `ipfs.io` 504 "no providers": cold cache / gateway load. Slow retry (≤3 attempts, 5 s apart):
  20/21 → 200/206; the last (`QmQimfP7NkNheaA7…`, a –GRAPH preview directory) → 200 on the
  second try of `<cid>/index.html` and on `<cid>/` directly.
- `dweb.link` 403 on all 21: rate-limiting of our probing IP (the same CIDs served 200/301 via curl).
- `gateway.pinata.cloud` 403/404: pinata's public gateway now serves only its own pinned
  content — dropped as a meaningful probe (verify-media.py `--public` should not rely on it).
- DHT/IPNI check via `cid.contact /routing/v1/providers/<cid>`: every one of the 21 has 2–4
  provider records (prod-02 and `bitswap.filebase.io` among them).

The 21 CIDs:
QmQimfP7NkNheaA7knMCqKU4QCM5gnycLqGzCcE4AtwpYr QmWcjuC3RJqhaR5WVnLcjNnNf9RXqTa6YsaxZbyDvF6AG8
QmbTnbbntuoXF87t1FQw92PqBj7xfYY4hKALAV3YDwH1Ey Qmc5b84zNCKGhwJ1GbBNujue4xNm1Wjc4NywXCHjkALJPe
QmcTXXsqT6aVb1Gn8X7aV5iRsLsWZ6Z1u7ACQkuZ6ZzwDE QmcVAJKCe81czs8A3Zh8unfdqse8ccuBux27moyuGZFVru
QmcpHB3hmncT4AnNv4F8DMMkNnS3d2ZENHdC6PiLY5dpLv Qmd7Skrv7NqLv4tSFq3sMW8teTywpG4b14WucwYVatT8iA
QmdNCZ4LorpRrbRBzbYtJHUhAv7LGNDnhPe1CBZVFpSnjD QmdXLY2RwdXMc3PBssx6gHe84wKC69WrPE1XdkBuBT1E2E
Qmdm3piNoE7ugpsQaXLzr2Qsd5TkGEH7WX9rbfR1tD1Pw1 QmdoAemWU9Gh6JzWxvJNFb8bkhkZ43LfrweX39BNusu6nE
Qme6kpHfLLQcY8d6UCsUp3vfJMt9VKTq1jktmT6hJ4Db7c QmeCREV6mMupH6tUQEtk9EDQD47SNj83vQ9GciWcThkwMg
QmeMFFcqjrjtRgMPBfEzMbua3cWUHgBTh6enE6umxBV6on QmeZMR28Zmz9q54oCgJRUrMoKrjb1KTQGF7T3s1F7w7SbW
QmeaMhcDbizQ5KfbJGMq2NK6HMAbxE1gBfYyoBa9JtVY8Y QmecAyNe2jK7cAz1vB9hf52vf2SAkX6T35MUfB5agxq18N
Qmeg2NRTk9R2fTUmWnxqmjS4zXjYdYYrL4DaGbdrTxL8VF QmfKmWmrPM1utqRuWobE2SgUCAz6sYDaDAnecDmrovLDCB
QmfVqRstCZLzFyVnjbGnF6Vc9mzjU3ML52C8rgPW4gbZzX
