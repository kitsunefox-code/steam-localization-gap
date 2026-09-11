# Steam Localization Gap Finder

Find Steam games whose **Japanese, Chinese, Korean, German (or any of 29 language) players are unhappier than the global player base**, and get the evidence in one row per game: the negative-review gap, translation complaints quoted straight from reviews, whether the store page is still untranslated, and the developer's public support email.

Built for localization vendors and freelance translators prospecting clients, publishers scouting regional problems before a port or a sale, and indie developers checking how their own game lands in a market they cannot read.

## What you get

One dataset row per analysed game:

| Field | Meaning |
|---|---|
| `opportunityScore` | Ranking score (see below). Higher = clearer localization problem |
| `languageNegativeRate` / `globalNegativeRate` | Share of negative reviews in the chosen language vs. all languages |
| `negativeGapPoints` | Difference in percentage points (only when the language has 5+ reviews) |
| `complaintHits` / `complaintHitsNegative` | Reviews mentioning translation, localization, machine translation, garbled text, "no X language", etc. |
| `complaintQuotes` | Up to N excerpts with `votedUp`, `playtimeHours` and the review ID, so you can cite real players |
| `storePageUntranslated` | `true` when the store page in the chosen language still shows the English short description |
| `languageListedAsSupported` | Whether the store lists that language as supported |
| `developer`, `publisher`, `supportEmail`, `supportUrl`, `website` | Public contact from the store page |
| `title`, `released`, `totalReviews`, `genres`, `priceUsd`, `isFree`, `url` | Game basics |

A `RUN_REPORT` record in the key-value store lists candidates, analysed, skipped and Steam requests made.

## How it works

1. **Discovery** (or your own `appIds`): pages Steam search for games that list your language as supported, carry the tags you choose (default `492` = Indie), were released within the last N months and have a total review count in your range. Indie-sized titles are the default because their developers still read support email.
2. **Reviews**: pulls recent reviews in your language plus the global summary from Steam's public `appreviews` endpoint.
3. **Complaint detection**: matches built-in translation-complaint keywords for the language (Japanese, Simplified/Traditional Chinese, Korean, German, French, Spanish, Portuguese, Russian, Polish, Italian, Turkish, Thai, Vietnamese, Ukrainian, Czech, Hungarian, Dutch, Nordic languages, Romanian, Greek, Bulgarian, Indonesian, Arabic). Add your own with `extraKeywords`.
4. **Store page check**: compares the short description in your language with the English one.
5. **Scoring** and output.

### Opportunity score

```
score = gap_in_points (if language has 5+ reviews)
      + 20 × negative reviews mentioning translation
      +  2 × positive reviews mentioning translation
      + 15 if the store page is untranslated
      + 0.2 × min(language reviews, 50)
```

It is a ranking aid, not a verdict. Read the quotes before you write to anyone.

## Input examples

**Japanese, recent indie releases (default):**

```json
{ "language": "japanese", "steamTagIds": ["492"], "releasedWithinMonths": 18, "minReviews": 30, "maxReviews": 4000, "maxGames": 100 }
```

**Simplified Chinese, RPGs only, bigger titles:**

```json
{ "language": "schinese", "steamTagIds": ["122"], "minReviews": 500, "maxReviews": 50000, "maxGames": 200, "reviewPagesPerGame": 3 }
```

**Check specific games:**

```json
{ "language": "koreana", "appIds": ["1145360", "2379780"], "reviewPagesPerGame": 2, "maxQuotes": 10 }
```

Common Steam tag IDs: 492 Indie, 122 RPG, 19 Action, 21 Adventure, 9 Strategy, 4182 Simulation, 599 Roguelike, 1663 FPS, 1667 Horror, 4085 Anime, 3859 Multiplayer, 1685 Co-op, 597 Casual.

## Pricing

Pay per event. You are billed once per run start and once per **game that is actually pushed to the dataset**. Games below `minOpportunityScore`, and games Steam returned no data for, are not billed. Use `maxGames` as a hard cap and set a spending limit on the run.

## Limits and good manners

- Steam rate-limits aggressively. The Actor uses one global polite delay (default 0.35 s) and low concurrency; raising `concurrency` above 3 mostly buys you HTTP 429s.
- Discovery stops after 200 search pages or when releases fall outside your window.
- Reviews are fetched with Steam's default off-topic ("review bomb") filter enabled.
- The keyword lists catch most complaints but not all; a game with `complaintHits = 0` can still have a bad translation. The gap and the quotes together are the signal.
- Data comes from Steam's public store endpoints. Respect Steam's terms when you use the output, and do not spam developers.

## Support

Open an issue on the Actor page. Feature requests for new languages or keyword lists are welcome.
