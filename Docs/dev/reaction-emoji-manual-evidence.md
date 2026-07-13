# Reaction Emoji Manual Evidence

Date: 2026-07-13

Task: `Docs/tasks/arteta_reaction_emoji_system_plan.md`

Branch: `feat/chromadb-memory`

Baseline: `7a34b067d2b741e71d57627062204e88b2ef2721`

Scope: replace the old `positive_neutral` / `negative` random mood emoji path with Gate -> Reaction Classifier -> Catalog -> Selector -> History while preserving `send_mood_emoji` compatibility.

## Local Emoji Manifest

Generated with:

```powershell
python tools\build_emoji_manifest.py 表情包 --output 表情包\manifest.json
```

Result:

- Asset count: 22
- Manifest path: `表情包/manifest.json`
- Reviewed tags now cover `celebration`, `approval`, `amused`, `teasing`, `surprised`, `speechless`, `thinking`, `skeptical`, `encouraging`, `comforting`, `frustrated`, and `sad`.
- Low-confidence / unrecognized assets: none.

All current local assets are marked `reviewed=true`; assets that should not be used for serious injury contexts include `avoid_contexts: ["serious_injury"]`.

## Scenario Evidence

Generated from `decide_emoji_gate`, `classify_emoji_reaction`, `rank_emoji_candidates`, and `select_emoji_asset` against the local `表情包/manifest.json`.

| # | Scenario | Input summary | Assistant summary | Gate | Reaction | Top 3 candidates | Final asset | Why |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Win celebration | Saka scored and Arsenal won | Celebrate the energy | send: `high_social_signal` | `celebration` 0.95 | `开心:6.0` | `开心` | Strong win language maps to celebration; only celebration-tagged asset qualifies. |
| 2 | Last-minute winner | Saka scored a winner | Last second standard | send: `high_social_signal` | `celebration` 0.78 | `开心:6.0` | `开心` | Winner marker is enough for celebration; no all-directory fallback used. |
| 3 | Late equalizer | Two-goal lead was equalized | This finish is frustrating | send: `high_social_signal` | `frustrated` 0.95 | `生气1:9.0`, `生气2:9.0`, `哭泣:6.0` | `生气2` | Frustrated exact matches outrank sad secondary match; selector rotates within top candidates. |
| 4 | Bad referee | Referee call was absurd | The call is hard to accept | send: `high_social_signal` | `speechless` 0.95 | `无聊:8.0`, `生气1:5.0`, `生气2:5.0` | `生气2` | Speechless exact match wins ranking; weighted top-3 may still choose a related frustrated asset. |
| 5 | Transfer skepticism | Is this transfer reliable? | Wait for reliable sources | no send: `current_news_or_fact_check` | `skeptical` 0.95 | `-` | `-` | Current-news/fact-check gate blocks automatic emoji even though classifier detects skepticism. |
| 6 | Surprise announcement | Sudden new signing announcement | The news is sudden | send: `high_social_signal` | `surprised` 0.95 | `震惊:6.0` | `震惊` | Legacy file-name mapping now tags `震惊` as surprised, so the reaction has a direct candidate. |
| 7 | Meme reply | Meme is funny and has show effect | The reversal is funny | send: `high_social_signal,meme_mode` | `amused` 0.95 | `无聊:7.0` | `无聊` | Meme mode allows auto emoji; amused can use speechless as a related candidate. |
| 8 | Serious injury | Player has season-ending injury | Wish him recovery | send: `high_social_signal` | `sad` 0.95 | `哭泣:6.0` | `哭泣` | Sad exact match is selected; teasing assets are not eligible. |
| 9 | User cannot solve math | User is frustrated by math | Encourage step-by-step solving | no send: `technical_or_math` | `encouraging` 0.95 | `-` | `-` | First version keeps the technical-question exception closed. |
| 10 | Plain ping | "Are you there?" | "Here." | no send: `low_signal` | `none` 0.00 | `-` | `-` | Ordinary neutral replies do not auto-send emoji. |
| 11 | Explicit request | User asks for an emoji | Acknowledge | send: `explicit_request` | `approval` 0.90 | `ChatGPT Image 2026年7月3日 09_42_28 (1):9.0`, `ChatGPT Image 2026年7月3日 09_42_29 (4):9.0`, `ChatGPT Image 2026年7月3日 09_42_29 (5):9.0` | `ChatGPT Image 2026年7月3日 09_42_29 (5)` | Explicit request bypasses auto cooldown but still uses whitelist catalog and selector. |
| 12 | Explicit ban | User says do not send emoji | Acknowledge no emoji | no send: `user_disabled_emoji` | `none` 0.00 | `-` | `-` | User ban takes precedence over all other signals. |

## Verification Commands

Latest verification:

```powershell
python -m pytest tests\test_arteta_agent_mood_response.py tests\test_arteta_agent_registry.py tests\test_arteta_prompt_style.py tests\test_arteta_agent_emoji_gate.py tests\test_arteta_agent_emoji_classifier.py tests\test_arteta_agent_emoji_catalog.py tests\test_arteta_agent_emoji_selector.py -q
# 233 passed

python -m compileall plugins\arteta_agent tools\build_emoji_manifest.py
# passed

python -m pytest tests -q
# 728 passed

python -m pytest -q
# collection failed before test execution:
# deploy/test_api.py raises SystemExit("IMAGE_API_KEY is required")
# This file existed at baseline 7a34b067d2b741e71d57627062204e88b2ef2721 with the same top-level IMAGE_API_KEY guard.
```

## Current Assessment

PASS WITH FOLLOW-UP

The reaction pipeline is implemented and covered by unit/integration tests. Follow-up is manual relabeling for the five low-confidence local assets currently retained as low-weight `approval`.
