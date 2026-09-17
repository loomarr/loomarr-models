# Current planner training review packet

Review the synthetic behavior in each trace, then edit `reviews/planner-current-v1/decisions.jsonl`.
This generated packet omits the repeated system prompt and tool schema; their exact bytes remain hash-bound.

## planner-current-train-exact-key-final-01

- Draft SHA-256: `8dfd7bf7171d8d8a467eed59a76fdaeb27ce00eee782c06387b24430d83e3ca6`
- Capability: `exact-key-final`
- Intent: Build a channel: Copper Lantern

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"query":"Copper Lantern"}` → result Copper Lantern [movie:synthetic:970001] → final Copper Lantern [movie:synthetic:970001]; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-date-movie-release-01

- Draft SHA-256: `e92bf3de30bce8e61ea3328e974b5b693d2eaa5d396d1b730f8e8b57d88e0783`
- Capability: `date-movie-release`
- Intent: Build a channel: 1980s desert adventures

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[{"end":5,"field":"description","start":0}],"axes":[{"combine":"any","intervals":[{"anchor":0,"end":1989,"start":1980}],"kind":"movie_release"}],"kind":"constraints"},"genres":["Thriller"],"media_type":"movie"}` → result Citrine Fixture 01 Primary [movie:synthetic:970011] → final Citrine Fixture 01 Primary [movie:synthetic:970011]; dateMeaning `{"anchors":[{"end":5,"field":"description","start":0}],"axes":[{"combine":"any","intervals":[{"anchor":0,"end":1989,"start":1980}],"kind":"movie_release"}],"kind":"constraints"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-date-series-premiere-01

- Draft SHA-256: `01ecc73b97a6a052a1daa884b6beda10a298c0f6a2f7b22036f30f574cf19384`
- Capability: `date-series-premiere`
- Intent: Build a channel: premiered 1990s workplace comedies

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[{"end":15,"field":"description","start":10}],"axes":[{"combine":"any","intervals":[{"anchor":0,"end":1999,"start":1990}],"kind":"series_premiere"}],"kind":"constraints"},"genres":["Drama"],"media_type":"series"}` → result Citrine Fixture 02 Primary [series:synthetic:970021] → final Citrine Fixture 02 Primary [series:synthetic:970021]; dateMeaning `{"anchors":[{"end":15,"field":"description","start":10}],"axes":[{"combine":"any","intervals":[{"anchor":0,"end":1999,"start":1990}],"kind":"series_premiere"}],"kind":"constraints"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-date-series-airing-01

- Draft SHA-256: `c0ca241c9c6616b439d1d7b0606a522ee1d5365aed7f94678b7d1a9fc1351a3d`
- Capability: `date-series-airing`
- Intent: Build a channel: episodes aired in the 2000s

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[{"end":27,"field":"description","start":22}],"axes":[{"combine":"any","intervals":[{"anchor":0,"end":2009,"start":2000}],"kind":"series_airing"}],"kind":"constraints"},"genres":["Drama"],"media_type":"series"}` → result Citrine Fixture 03 Primary [series:synthetic:970031] → final Citrine Fixture 03 Primary [series:synthetic:970031]; dateMeaning `{"anchors":[{"end":27,"field":"description","start":22}],"axes":[{"combine":"any","intervals":[{"anchor":0,"end":2009,"start":2000}],"kind":"series_airing"}],"kind":"constraints"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-date-disjoint-intervals-01

- Draft SHA-256: `a3dc4ec52934b0594e3109fd566e8b1c365425668ce469dfe3aebe61e24dbd01`
- Capability: `date-disjoint-intervals`
- Intent: Build a channel: 1970s or 2010s space films

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[{"end":14,"field":"description","start":0}],"axes":[{"combine":"any","intervals":[{"anchor":0,"end":1979,"start":1970},{"anchor":0,"end":2019,"start":2010}],"kind":"movie_release"}],"kind":"constraints"},"genres":["Adventure"],"media_type":"movie"}` → result Citrine Fixture 04 Primary [movie:synthetic:970041] → final Citrine Fixture 04 Primary [movie:synthetic:970041]; dateMeaning `{"anchors":[{"end":14,"field":"description","start":0}],"axes":[{"combine":"any","intervals":[{"anchor":0,"end":1979,"start":1970},{"anchor":0,"end":2019,"start":2010}],"kind":"movie_release"}],"kind":"constraints"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-date-ambiguity-01

- Draft SHA-256: `5d650c7e30a14469805f9a4e9f6615c58969dfcfc4ff26ab9da95cb61bc1604b`
- Capability: `date-ambiguity`
- Intent: Build a channel: the early classics

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[{"end":18,"field":"description","start":4}],"axes":[],"kind":"ambiguous"},"genres":["Drama"]}` → result error `clarify_dates` → final structured abstention; dateMeaning `{"anchors":[{"end":18,"field":"description","start":4}],"axes":[],"kind":"ambiguous"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-collection-evidence-01

- Draft SHA-256: `904f34432430567a49a491d034d6a39ef6cc8f281cb08a4f98b44be3b7ca39c5`
- Capability: `collection-evidence`
- Intent: Build a channel: Aurora Saturday Showcase with exact constituent Citrine Fixture 06 Primary

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"media_type":"movie","mode":"collection","titles":["Citrine Fixture 06 Primary"]}` → result Citrine Fixture 06 Primary [movie:synthetic:970061] → final Citrine Fixture 06 Primary [movie:synthetic:970061]; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-franchise-boundary-01

- Draft SHA-256: `cc3d99481f590090442356c65d08ce45f0849354b379e9afe859a008aef0c3a9`
- Capability: `franchise-boundary`
- Intent: Build a channel: Northstar Saga

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"keywords":["Northstar Saga"],"media_type":"series"}` → result Citrine Fixture 07 Primary [series:synthetic:970071], Citrine Fixture 07 Contrast [series:synthetic:970072] → final Citrine Fixture 07 Primary [series:synthetic:970071]; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-network-editorial-epoch-01

- Draft SHA-256: `51a08ccad96da578bfcb32f75d681ced946f7e7faae72bf15db7dacd91371f67`
- Capability: `network-editorial-epoch`
- Intent: Build a channel: like Beacon Network in the 1990s

EDITORIAL NETWORK EPOCH: the reference decade ends in 1999. Discover the network's older catalog, then select factual programming that fits this era; an example title is not a one-title or one-subject limit. This is editorial context, not a playback-date restriction.
No separate playback-date restriction was submitted. Every catalog_search and final JSON must copy this exact dateMeaning object: {"kind":"none","anchors":[],"axes":[]}. Do not add anchors to kind=none, invent an airing filter, or ask to clarify the known editorial decade.

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"media_type":"series","network":"Beacon Network"}` → result Citrine Fixture 08 Primary [series:synthetic:970081] → final Citrine Fixture 08 Primary [series:synthetic:970081]; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-cast-routing-01

- Draft SHA-256: `90a8adba5d8828f480d6cdfed0c32d5c9e9fcec41968572687190479df730d67`
- Capability: `cast-routing`
- Intent: Build a channel: movies starring Rowan Vale

- Flow: call `catalog_search` `{"cast":["Rowan Vale"],"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"media_type":"movie"}` → result Citrine Fixture 09 Primary [movie:synthetic:970091] → final Citrine Fixture 09 Primary [movie:synthetic:970091]; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-creator-routing-01

- Draft SHA-256: `99823d288a653cece2ae02d9bf43b4b4f021cc622db8ef2381568e411204c7a3`
- Capability: `creator-routing`
- Intent: Build a channel: films directed by Mira Sol

- Flow: call `catalog_search` `{"creators":["Mira Sol"],"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"media_type":"movie"}` → result Citrine Fixture 10 Primary [movie:synthetic:970101] → final Citrine Fixture 10 Primary [movie:synthetic:970101]; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-exact-title-unfamiliar-01

- Draft SHA-256: `18644cadd78303f10a92c78dd8482ea3bc78898999acae7bea690158d170183f`
- Capability: `exact-title-unfamiliar`
- Intent: Build a channel: Obsidian Harbor

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"media_type":"series","query":"Obsidian Harbor"}` → result Obsidian Harbor [series:synthetic:970111] → final Obsidian Harbor [series:synthetic:970111]; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-constraint-conflict-abstention-01

- Draft SHA-256: `e1eedb3a9a0ab9d1201c4c82509715acf76e627e6fabab72ea8afb1ebdb0d54a`
- Capability: `constraint-conflict-abstention`
- Intent: Build a channel: include and exclude Amber Signal
Must include: Amber Signal
Must exclude: Amber Signal

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"media_type":"movie","query":"Amber Signal"}` → result Amber Signal [movie:synthetic:970121] → final structured abstention; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-ownership-acquisition-balance-01

- Draft SHA-256: `63f083e2c226358161dfd506365a4b6e775bc62e5f4977746920e36214a3a1e0`
- Capability: `ownership-acquisition-balance`
- Intent: Build a channel: owned mysteries plus one discovery

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"genres":["Mystery"]}` → result Citrine Fixture 13 Primary [series:synthetic:970131], Citrine Fixture 13 Contrast [series:synthetic:970132] → final Citrine Fixture 13 Primary [series:synthetic:970131], Citrine Fixture 13 Contrast [series:synthetic:970132]; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-refinement-preservation-01

- Draft SHA-256: `85e56fa5f6e2da7d27516ffcc4ebbeecd4282b782deb9f954472a256e0dcfb6b`
- Capability: `refinement-preservation`
- Intent: This channel already exists: Quartz Evenings
Its current lineup is:
  - Citrine Fixture 14 Primary (1974)
The user wants to change it: make it more international
Keep the titles that still fit, drop the ones that don't, and add new ones as needed. Re-ground EVERY title (kept or new) through the catalog tool — copy only exact catalog keys the tool returns.

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"media_type":"movie","query":"Citrine Fixture 14 Primary"}` → result Citrine Fixture 14 Primary [movie:synthetic:970141] → final Citrine Fixture 14 Primary [movie:synthetic:970141]; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-audience-ceiling-01

- Draft SHA-256: `7b0537be5101e8ba781dc32cb47ab0c160aa39d8d9787e58f55cabdb2d78b9dc`
- Capability: `audience-ceiling`
- Intent: Build a channel: family animation capped at TV-PG

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"genres":["Animation"]}` → result Citrine Fixture 15 Primary [series:synthetic:970151] → final Citrine Fixture 15 Primary [series:synthetic:970151]; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-season-window-01

- Draft SHA-256: `4bd19a06a885e52141ad37a83c3c394526a781f237514a2991e2f14986cb9200`
- Capability: `season-window`
- Intent: Build a channel: early seasons of Cedar Street

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"media_type":"series","query":"Cedar Street"}` → result Cedar Street [series:synthetic:970161] → final Cedar Street [series:synthetic:970161]; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-medium-constraint-01

- Draft SHA-256: `cab155b92f1b8df4924f9bae6aa9b0086a4bc356eec402e25e5f2375f822a7f2`
- Capability: `medium-constraint`
- Intent: Build a channel: animated ocean adventures

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"genres":["Animation"],"media_type":"series"}` → result Citrine Fixture 17 Primary [series:synthetic:970171], Citrine Fixture 17 Contrast [movie:synthetic:970172] → final Citrine Fixture 17 Primary [series:synthetic:970171]; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-language-constraint-01

- Draft SHA-256: `09925a475393bc624d90598373a7cc10a4d7d25f538e95c7ea568e1d800f3b5d`
- Capability: `language-constraint`
- Intent: Build a channel: French-language comedies

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"genres":["Comedy"],"original_language":"fr"}` → result Citrine Fixture 18 Primary [movie:synthetic:970181] → final Citrine Fixture 18 Primary [movie:synthetic:970181]; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-region-constraint-01

- Draft SHA-256: `4a706fb3ec27114496f9cb977bf55ab6483e7b6bbc775da8f511bf9678d3efd1`
- Capability: `region-constraint`
- Intent: Build a channel: mysteries from New Zealand

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"genres":["Mystery"],"origin_country":"NZ"}` → result Citrine Fixture 19 Primary [series:synthetic:970191] → final Citrine Fixture 19 Primary [series:synthetic:970191]; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-thin-results-01

- Draft SHA-256: `93b74b8802db574dd660d1c23d4a73c973074cc85c4d8636a9eb644a0a111dbe`
- Capability: `thin-results`
- Intent: Build a channel: a narrow alpine-noir result

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"keywords":["alpine-noir"]}` → result Citrine Fixture 20 Primary [movie:synthetic:970201] → final Citrine Fixture 20 Primary [movie:synthetic:970201]; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-empty-results-01

- Draft SHA-256: `a8ea6b816cdded5d1a8582c087d3c1be0136723a74c97ef8b5ca3bb56d6ab746`
- Capability: `empty-results`
- Intent: Build a channel: vanishing clockwork westerns

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"keywords":["clockwork-western"]}` → result empty → call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"query":"clockwork-western"}` → result empty → final structured abstention; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-malformed-tool-result-01

- Draft SHA-256: `5e6aa9c60fe7fcab101a0751b802372e2d0496def54b3ad96f628772e362cd36`
- Capability: `malformed-tool-result`
- Intent: Build a channel: a corrupted synthetic catalog reply

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"query":"Citrine Fixture 22 Primary"}` → result error `malformed_catalog_response` → final structured abstention; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —

## planner-current-train-observed-fault-recovery-01

- Draft SHA-256: `56c3ef4432a8e5dafe2a19131db0cf44c6579da480cdb5183cc6df051120d8eb`
- Capability: `observed-fault-recovery`
- Intent: Build a channel: recovering lunar detective stories

- Flow: call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"genres":["Mystery"]}` → result error `transient_catalog_failure` → call `catalog_search` `{"dateMeaning":{"anchors":[],"axes":[],"kind":"none"},"genres":["Mystery"]}` → result Citrine Fixture 23 Primary [series:synthetic:970231] → final Citrine Fixture 23 Primary [series:synthetic:970231]; dateMeaning `{"anchors":[],"axes":[],"kind":"none"}`
- Verdict: **pending** by `—` at `—`
- Criteria: contractConformant=None, toolAndFinalGrounded=None, constraintBehaviorCorrect=None, recoveryEvidenceCorrect=None, syntheticAndPrivateSafe=None
- Notes: —
