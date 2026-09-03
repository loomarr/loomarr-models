# Planner smoke v1 review packet

Generated from `corpus/planner-smoke-v1/drafts.jsonl`. The repeated frozen system prompt and tool schema
are intentionally represented by their hashes here; their complete bytes remain in every source trace.
Edit review decisions in `reviews/planner-smoke-v1.jsonl`, not this generated packet.

## planner-smoke-title-search-01

- Axis: `title-search`
- Intent: Build a channel around the synthetic title Cobalt Voyage 01.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"query": "Cobalt Voyage 01"}` → result candidates: `Cobalt Voyage 01` → final picks: `Cobalt Voyage 01`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-title-search-02

- Axis: `title-search`
- Intent: Build a channel around the synthetic title Juniper Voyage 02.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"query": "Juniper Voyage 02"}` → result candidates: `Juniper Voyage 02` → final picks: `Juniper Voyage 02`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-title-search-03

- Axis: `title-search`
- Intent: Build a channel around the synthetic title Lunar Voyage 03.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"query": "Lunar Voyage 03"}` → result candidates: `Lunar Voyage 03` → final picks: `Lunar Voyage 03`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-title-search-04

- Axis: `title-search`
- Intent: Build a channel around the synthetic title Velvet Voyage 04.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"query": "Velvet Voyage 04"}` → result candidates: `Velvet Voyage 04` → final picks: `Velvet Voyage 04`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-title-search-05

- Axis: `title-search`
- Intent: Build a channel around the synthetic title Amber Harbor 05.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"query": "Amber Harbor 05"}` → result candidates: `Amber Harbor 05` → final picks: `Amber Harbor 05`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-genre-discovery-01

- Axis: `genre-discovery`
- Intent: Build an adventure channel from the synthetic 1980s catalog.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"era": "1980s", "genres": ["Adventure"], "media_type": "movie"}` → result candidates: `Cobalt Harbor 06` → final picks: `Cobalt Harbor 06`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-genre-discovery-02

- Axis: `genre-discovery`
- Intent: Build a comedy channel from the synthetic 1990s catalog.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"era": "1990s", "genres": ["Comedy"], "media_type": "series"}` → result candidates: `Juniper Harbor 07` → final picks: `Juniper Harbor 07`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-genre-discovery-03

- Axis: `genre-discovery`
- Intent: Build a mystery channel from the synthetic 2000s catalog.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"era": "2000s", "genres": ["Mystery"], "media_type": "movie"}` → result candidates: `Lunar Harbor 08` → final picks: `Lunar Harbor 08`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-genre-discovery-04

- Axis: `genre-discovery`
- Intent: Build an animation channel from the synthetic 2010s catalog.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"era": "2010s", "genres": ["Animation"], "media_type": "series"}` → result candidates: `Velvet Harbor 09` → final picks: `Velvet Harbor 09`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-genre-discovery-05

- Axis: `genre-discovery`
- Intent: Build a documentary channel from the synthetic 2020s catalog.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"era": "2020s", "genres": ["Documentary"], "media_type": "movie"}` → result candidates: `Amber Signal 10` → final picks: `Amber Signal 10`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-keyword-discovery-01

- Axis: `keyword-discovery`
- Intent: Build a synthetic channel about clockwork.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"keywords": ["clockwork"], "media_type": "movie"}` → result candidates: `Cobalt Signal 11` → final picks: `Cobalt Signal 11`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-keyword-discovery-02

- Axis: `keyword-discovery`
- Intent: Build a synthetic channel about paper moons.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"keywords": ["paper moons"], "media_type": "series"}` → result candidates: `Juniper Signal 12` → final picks: `Juniper Signal 12`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-keyword-discovery-03

- Axis: `keyword-discovery`
- Intent: Build a synthetic channel about hidden gardens.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"keywords": ["hidden gardens"], "media_type": "movie"}` → result candidates: `Lunar Signal 13` → final picks: `Lunar Signal 13`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-keyword-discovery-04

- Axis: `keyword-discovery`
- Intent: Build a synthetic channel about midnight trains.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"keywords": ["midnight trains"], "media_type": "series"}` → result candidates: `Velvet Signal 14` → final picks: `Velvet Signal 14`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-keyword-discovery-05

- Axis: `keyword-discovery`
- Intent: Build a synthetic channel about glass oceans.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"keywords": ["glass oceans"], "media_type": "movie"}` → result candidates: `Amber Archive 15` → final picks: `Amber Archive 15`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-must-include-01

- Axis: `must-include`
- Intent: Build a varied channel that must include the synthetic title Cobalt Archive 16.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"query": "Cobalt Archive 16"}` → result candidates: `Cobalt Archive 16` → final picks: `Cobalt Archive 16`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-must-include-02

- Axis: `must-include`
- Intent: Build a varied channel that must include the synthetic title Juniper Archive 17.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"query": "Juniper Archive 17"}` → result candidates: `Juniper Archive 17` → final picks: `Juniper Archive 17`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-must-include-03

- Axis: `must-include`
- Intent: Build a varied channel that must include the synthetic title Lunar Archive 18.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"query": "Lunar Archive 18"}` → result candidates: `Lunar Archive 18` → final picks: `Lunar Archive 18`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-must-include-04

- Axis: `must-include`
- Intent: Build a varied channel that must include the synthetic title Velvet Archive 19.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"query": "Velvet Archive 19"}` → result candidates: `Velvet Archive 19` → final picks: `Velvet Archive 19`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-must-include-05

- Axis: `must-include`
- Intent: Build a varied channel that must include the synthetic title Amber Parade 20.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"query": "Amber Parade 20"}` → result candidates: `Amber Parade 20` → final picks: `Amber Parade 20`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-must-exclude-01

- Axis: `must-exclude`
- Intent: Build synthetic adventure programming but exclude horror and Cobalt Parade 521 After Dark.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"genres": ["Adventure"]}` → result candidates: `Cobalt Parade 21`, `Cobalt Parade 521 After Dark` → final picks: `Cobalt Parade 21`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-must-exclude-02

- Axis: `must-exclude`
- Intent: Build synthetic adventure programming but exclude horror and Juniper Parade 522 After Dark.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"genres": ["Adventure"]}` → result candidates: `Juniper Parade 22`, `Juniper Parade 522 After Dark` → final picks: `Juniper Parade 22`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-must-exclude-03

- Axis: `must-exclude`
- Intent: Build synthetic adventure programming but exclude horror and Lunar Parade 523 After Dark.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"genres": ["Adventure"]}` → result candidates: `Lunar Parade 23`, `Lunar Parade 523 After Dark` → final picks: `Lunar Parade 23`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-must-exclude-04

- Axis: `must-exclude`
- Intent: Build synthetic adventure programming but exclude horror and Velvet Parade 524 After Dark.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"genres": ["Adventure"]}` → result candidates: `Velvet Parade 24`, `Velvet Parade 524 After Dark` → final picks: `Velvet Parade 24`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-must-exclude-05

- Axis: `must-exclude`
- Intent: Build synthetic adventure programming but exclude horror and Amber Voyage 525 After Dark.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"genres": ["Adventure"]}` → result candidates: `Amber Voyage 25`, `Amber Voyage 525 After Dark` → final picks: `Amber Voyage 25`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-ambiguous-intent-01

- Axis: `ambiguous-intent`
- Intent: Build something synthetic that feels quiet, without inventing titles.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"keywords": ["quiet"]}` → result candidates: `Cobalt Voyage 26` → final picks: `Cobalt Voyage 26`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-ambiguous-intent-02

- Axis: `ambiguous-intent`
- Intent: Build something synthetic that feels bright, without inventing titles.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"keywords": ["bright"]}` → result candidates: `Juniper Voyage 27` → final picks: `Juniper Voyage 27`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-ambiguous-intent-03

- Axis: `ambiguous-intent`
- Intent: Build something synthetic that feels restless, without inventing titles.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"keywords": ["restless"]}` → result candidates: `Lunar Voyage 28` → final picks: `Lunar Voyage 28`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-ambiguous-intent-04

- Axis: `ambiguous-intent`
- Intent: Build something synthetic that feels curious, without inventing titles.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"keywords": ["curious"]}` → result candidates: `Velvet Voyage 29` → final picks: `Velvet Voyage 29`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-ambiguous-intent-05

- Axis: `ambiguous-intent`
- Intent: Build something synthetic that feels windswept, without inventing titles.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"keywords": ["windswept"]}` → result candidates: `Amber Harbor 30` → final picks: `Amber Harbor 30`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-conflicting-intent-01

- Axis: `conflicting-intent`
- Intent: Build an all-horror synthetic channel that excludes every horror title in fixture group 0.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"genres": ["Horror"]}` → result candidates: none → call `catalog_search` `{"query": "synthetic horror group 0"}` → result candidates: none → final picks: none (abstain)
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-conflicting-intent-02

- Axis: `conflicting-intent`
- Intent: Build an all-horror synthetic channel that excludes every horror title in fixture group 1.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"genres": ["Horror"]}` → result candidates: none → call `catalog_search` `{"query": "synthetic horror group 1"}` → result candidates: none → final picks: none (abstain)
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-conflicting-intent-03

- Axis: `conflicting-intent`
- Intent: Build an all-horror synthetic channel that excludes every horror title in fixture group 2.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"genres": ["Horror"]}` → result candidates: none → call `catalog_search` `{"query": "synthetic horror group 2"}` → result candidates: none → final picks: none (abstain)
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-conflicting-intent-04

- Axis: `conflicting-intent`
- Intent: Build an all-horror synthetic channel that excludes every horror title in fixture group 3.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"genres": ["Horror"]}` → result candidates: none → call `catalog_search` `{"query": "synthetic horror group 3"}` → result candidates: none → final picks: none (abstain)
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-conflicting-intent-05

- Axis: `conflicting-intent`
- Intent: Build an all-horror synthetic channel that excludes every horror title in fixture group 4.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"genres": ["Horror"]}` → result candidates: none → call `catalog_search` `{"query": "synthetic horror group 4"}` → result candidates: none → final picks: none (abstain)
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-empty-results-01

- Axis: `empty-results`
- Intent: Build a channel about the nonexistent synthetic motif absent-synthetic-motif-0.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"keywords": ["absent-synthetic-motif-0"]}` → result candidates: none → call `catalog_search` `{"query": "absent-synthetic-motif-0"}` → result candidates: none → final picks: none (abstain)
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-empty-results-02

- Axis: `empty-results`
- Intent: Build a channel about the nonexistent synthetic motif absent-synthetic-motif-1.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"keywords": ["absent-synthetic-motif-1"]}` → result candidates: none → call `catalog_search` `{"query": "absent-synthetic-motif-1"}` → result candidates: none → final picks: none (abstain)
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-empty-results-03

- Axis: `empty-results`
- Intent: Build a channel about the nonexistent synthetic motif absent-synthetic-motif-2.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"keywords": ["absent-synthetic-motif-2"]}` → result candidates: none → call `catalog_search` `{"query": "absent-synthetic-motif-2"}` → result candidates: none → final picks: none (abstain)
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-empty-results-04

- Axis: `empty-results`
- Intent: Build a channel about the nonexistent synthetic motif absent-synthetic-motif-3.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"keywords": ["absent-synthetic-motif-3"]}` → result candidates: none → call `catalog_search` `{"query": "absent-synthetic-motif-3"}` → result candidates: none → final picks: none (abstain)
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-empty-results-05

- Axis: `empty-results`
- Intent: Build a channel about the nonexistent synthetic motif absent-synthetic-motif-4.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"keywords": ["absent-synthetic-motif-4"]}` → result candidates: none → call `catalog_search` `{"query": "absent-synthetic-motif-4"}` → result candidates: none → final picks: none (abstain)
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-tool-error-recovery-01

- Axis: `tool-error-recovery`
- Intent: Build a synthetic adventure channel and recover from a fixture timeout 0.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"genres": ["Adventure"]}` → result error: `synthetic fixture timeout` → call `catalog_search` `{"genres": ["Adventure"]}` → result candidates: `Cobalt Archive 41` → final picks: `Cobalt Archive 41`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-tool-error-recovery-02

- Axis: `tool-error-recovery`
- Intent: Build a synthetic adventure channel and recover from a fixture timeout 1.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"genres": ["Adventure"]}` → result error: `synthetic fixture timeout` → call `catalog_search` `{"genres": ["Adventure"]}` → result candidates: `Juniper Archive 42` → final picks: `Juniper Archive 42`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-tool-error-recovery-03

- Axis: `tool-error-recovery`
- Intent: Build a synthetic adventure channel and recover from a fixture timeout 2.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"genres": ["Adventure"]}` → result error: `synthetic fixture timeout` → call `catalog_search` `{"genres": ["Adventure"]}` → result candidates: `Lunar Archive 43` → final picks: `Lunar Archive 43`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-tool-error-recovery-04

- Axis: `tool-error-recovery`
- Intent: Build a synthetic adventure channel and recover from a fixture timeout 3.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"genres": ["Adventure"]}` → result error: `synthetic fixture timeout` → call `catalog_search` `{"genres": ["Adventure"]}` → result candidates: `Velvet Archive 44` → final picks: `Velvet Archive 44`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-tool-error-recovery-05

- Axis: `tool-error-recovery`
- Intent: Build a synthetic adventure channel and recover from a fixture timeout 4.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"genres": ["Adventure"]}` → result error: `synthetic fixture timeout` → call `catalog_search` `{"genres": ["Adventure"]}` → result candidates: `Amber Parade 45` → final picks: `Amber Parade 45`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-malformed-final-repair-01

- Axis: `malformed-final-repair`
- Intent: Build a channel around the synthetic title Cobalt Parade 46 and repair malformed output.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"query": "Cobalt Parade 46"}` → result candidates: `Cobalt Parade 46` → malformed assistant turn: `{not-json` → repair instruction: Return only valid proposal JSON using the already surfaced id. → final picks: `Cobalt Parade 46`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-malformed-final-repair-02

- Axis: `malformed-final-repair`
- Intent: Build a channel around the synthetic title Juniper Parade 47 and repair malformed output.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"query": "Juniper Parade 47"}` → result candidates: `Juniper Parade 47` → malformed assistant turn: `{not-json` → repair instruction: Return only valid proposal JSON using the already surfaced id. → final picks: `Juniper Parade 47`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-malformed-final-repair-03

- Axis: `malformed-final-repair`
- Intent: Build a channel around the synthetic title Lunar Parade 48 and repair malformed output.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"query": "Lunar Parade 48"}` → result candidates: `Lunar Parade 48` → malformed assistant turn: `{not-json` → repair instruction: Return only valid proposal JSON using the already surfaced id. → final picks: `Lunar Parade 48`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-malformed-final-repair-04

- Axis: `malformed-final-repair`
- Intent: Build a channel around the synthetic title Velvet Parade 49 and repair malformed output.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"query": "Velvet Parade 49"}` → result candidates: `Velvet Parade 49` → malformed assistant turn: `{not-json` → repair instruction: Return only valid proposal JSON using the already surfaced id. → final picks: `Velvet Parade 49`
- Decision: **pending**; reviewer `—`; notes: —

## planner-smoke-malformed-final-repair-05

- Axis: `malformed-final-repair`
- Intent: Build a channel around the synthetic title Amber Voyage 50 and repair malformed output.
- Contract: `c825bb321636ee756635167828bd252e46c550692835e56950951b7c5269ae61` / `16a9f228864ae8286df2fbe5439fe121922a35402f7168f1a42319652bf30853`
- Flow: call `catalog_search` `{"query": "Amber Voyage 50"}` → result candidates: `Amber Voyage 50` → malformed assistant turn: `{not-json` → repair instruction: Return only valid proposal JSON using the already surfaced id. → final picks: `Amber Voyage 50`
- Decision: **pending**; reviewer `—`; notes: —
