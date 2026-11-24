---
name: social-comments-analyzer
description: Fetches, analyzes and exports the comments of Instagram, TikTok and Facebook posts, with sentiment, topics, top authors, questions without a reply, and a report in HTML, Excel, CSV, Markdown or JSON. Use when the user asks to get, analyze, summarize or export comments from one or more social media posts, to measure audience sentiment or brand mentions in comments, or to analyze a CSV/JSON export of comments.
summary: Turn the comments of Instagram, TikTok and Facebook posts into a sentiment and topic report with Excel, CSV and HTML exports.
version: 1.0.0
tags: [social-media, instagram, tiktok, facebook, comments, sentiment-analysis, reporting]
keywords: [comments analysis, comment scraper, sentiment, social listening, community management, export comments to excel]
use_cases:
  - Report on what people say under a campaign's posts across Instagram, TikTok and Facebook
  - Find complaints and unanswered customer questions in a brand's comments
  - Measure how much of the conversation is about a brand, product or topic
  - Export all comments of a post to Excel or CSV
---

# Social Comments Analyzer

Collect the comments of social media posts, analyze them with bundled scripts plus your own reading, and deliver a report and exports.

## Tools

This skill uses these Agensi tools, chosen by the platform of each post URL:

- `Instagram Post Comments`: comments on an Instagram post or reel by URL, with cursor pagination
- `Instagram Comment Replies`: replies to one Instagram comment
- `TikTok Video Comments`: comments on a TikTok video by URL, with cursor pagination
- `TikTok Comment Replies`: replies to one TikTok comment
- `Facebook Post Comments`: comments on a Facebook post by URL, with cursor pagination
- `Facebook Comment Replies`: replies to one Facebook comment

Each tool returns one page of comments per use. A post needs one use per page. Replies cost one use per comment thread, so fetch them only when the user asks for them.

The user can skip the tools completely by giving files instead of URLs: CSV or JSON exports of the Social Comments Analyzer web app, or any CSV/JSON/JSONL of comments.

## Bundled scripts

All three scripts use Python 3.8+ and the standard library only. They make no network calls, and each one writes only the paths you pass it. Run them with `python3`. Every script supports `--help`.

| Script | Input → output |
|---|---|
| `scripts/normalize.py` | raw tool results and/or files → one canonical `comments.json` (merged, de-duplicated, replies linked) |
| `scripts/analyze.py` | `comments.json` (+ your `labels.json`) → `analysis.json`, `enriched.json`, `digest.jsonl`, and a Markdown summary on stdout |
| `scripts/export.py` | `enriched.json` + `analysis.json` (+ your `summary.md`) → `.html`, `.xlsx`, `.csv`, `.md`, `.json` |

Keep all working files in one folder in the user's current directory, `comments-analysis/` by default.

## Steps

### 1. Agree on the job

Ask only for what is missing:
- **Sources**: post URLs (Instagram, TikTok and Facebook can be mixed), or local files.
- **Focus** (optional): a criterion such as "mentions of BrandX or its delivery service". The report will then lead with the comments that match it.
- **Team accounts** (optional): the brand's own handles. Their replies are flagged, and questions without a team reply get listed.
- **Limits**: the maximum number of comments per post (default 500), and whether to include replies (default no).
- **Output**: the formats (default `html,xlsx`) and the report language (`en` or `es`; default: the user's language if it is one of them, else `en`).

### 2. Confirm the plan before paid uses

Estimate the uses: about one per 20–50 comments per post, plus one per thread if replies are wanted. Show the posts, the limits and the estimated number of uses. If more than 20 uses are expected, wait for the user's go-ahead. Never write prices: the user's agent shows them.

### 3. Fetch the comments (skip this step for local files)

For each URL:
1. Pick the tool for the platform (instagram.com → Instagram, tiktok.com → TikTok, facebook.com or fb.watch → Facebook). For any other URL, say the skill does not support it and skip it.
2. Call the comments tool with the post URL. Then call it again with the returned cursor until there is no next cursor or the comment limit is reached. Run the posts as a batch where possible.
3. Save each tool result exactly as returned (the full JSON, unmodified) to `comments-analysis/raw/<platform>-<n>-p<page>.json`. Do not retype, trim or summarize it: the normalizer handles the provider's native fields.
4. If replies were requested, call the replies tool for each comment that reports replies (at most the 50 most-liked threads per post unless the user says otherwise) as one batch. Save each result next to the others as `...-r<comment id>.json`.
5. If a call fails or comes back empty, try once more. If it fails again, note the post as "not fetched", tell the user, and continue with the others. Failed uses cost nothing. Private posts, deleted posts and region-locked videos return nothing.

### 4. Normalize

```bash
python3 scripts/normalize.py comments-analysis/raw/instagram-1-*.json::<post 1 URL> \
    comments-analysis/raw/tiktok-2-*.json::<post 2 URL> -o comments-analysis/comments.json
```

Append `::<post URL>` to every raw file so its comments are linked to their post (shell globs expand before the suffix, so pass each file separately or loop). Local exports go in as plain paths. Check the per-file counts it prints. A file with 0 comments means the result held no comment objects: open it and see why.

### 5. First analysis

```bash
python3 scripts/analyze.py comments-analysis/comments.json -o comments-analysis/analysis.json \
    --enriched comments-analysis/enriched.json --digest comments-analysis/digest.jsonl \
    --digest-size 2000 [--team "brand,@brand_support"]
```

### 6. Read and label (this is where you add value)

Read `digest.jsonl`. It holds one compact comment per line, the most liked and most negative first. Read it in chunks of about 200 lines. Do not paste it into the chat. Write `comments-analysis/labels.json`:

```json
{"17900000000000003": {"sentiment": "neutral", "focus": true, "topic": "shipping"},
 "7300000000000000003": {"sentiment": "negative", "focus": true, "topic": "refunds"}}
```

- **sentiment**: correct the lexicon estimate only where it is wrong. Typical cases are sarcasm, questions marked as complaints, slang, praise written with negative words ("insanely good"), and emoji-only comments.
- **focus**: if the user gave a criterion, add `true` or `false` for every comment you read. Judge by meaning, not keywords (misspelled brand names, replies to a brand post that talk about it implicitly).
- **topic**: group the comments into 4–8 short topics that you name from what people actually say (for example "price", "delivery delays", "product praise", "questions about stock").

If there are more comments than the digest holds, say so in the report: labels cover the digest, and the lexicon covers the rest.

### 7. Final analysis and summary

Run step 5 again with `--labels comments-analysis/labels.json` (and `--focus-name "<criterion>"` if there is a focus). Then write `comments-analysis/summary.md` in the report language, using the numbers from `analysis.json`:
- 3–5 sentences of executive summary: volume, overall tone, and what drives it.
- **Key findings**: 4–7 bullets, each backed by a number and, where useful, a short quote (author handle plus a few words; never more personal data than that).
- **Risks**: complaints that repeat, questions without an answer, misinformation.
- **Recommendations**: 3–5 concrete actions, such as replies to send, content to make, or issues to escalate.
- With several posts or platforms, compare them.

### 8. Export and deliver

```bash
python3 scripts/export.py comments-analysis/enriched.json --analysis comments-analysis/analysis.json \
    --summary comments-analysis/summary.md --formats html,xlsx --lang es \
    --title "<Report title>" --out-dir comments-analysis/report --name <short-name>
```

Add `--focus-only` to export only the focus comments. Finish with:
- the paths of the files written (the HTML opens in any browser and prints to PDF),
- the 5–7 most important lines of the summary,
- posts that could not be fetched, if any,
- the number of tool uses made.

## Rules

- Fetch only public posts the user points to. Do not crawl profiles, follow links or collect more than was asked.
- Use the comments for analysis. Do not build lists of people's personal data, and do not message commenters.
- Never ask the user for Instagram, TikTok or Facebook API keys or logins: the Agensi tools cover access.
- Do not edit the bundled scripts during a run. If one fails, show its error, fix the input (usually a mis-saved raw file), and rerun.
- Sentiment from the scripts is a lexicon estimate (Spanish, English, Portuguese). Present it as indicative, and say how many comments you labeled yourself.

## Example

User: "Analyze the comments on these two posts and tell me what people complain about: https://www.instagram.com/p/XXXX/ https://www.tiktok.com/@brand/video/123"

1. Ask for the focus (none: complaints in general), the team handle (`@brand`), and confirm 2 posts × up to 500 comments, which is about 20 uses.
2. Fetch the pages and save them to `comments-analysis/raw/`. Then normalize and analyze with `--team brand`.
3. Read the digest. Label sentiment fixes and topics such as "late delivery", "wrong size", "praise".
4. Rerun the analysis with the labels. Write a summary that leads with the complaint topics and their share, and the 12 questions without a reply.
5. Export `html,xlsx`, then reply with the paths and the top findings.
