# The Rameen Times

Private morning paper for Hash. One Python pipeline on this Linux box gathers news, Trello, and today's calendar. Tavily searches and extracts the stories. A newsroom of Claude Sonnet 5 sub-agents writes the edition. Jinja fills a LaTeX template. pdfLaTeX prints an A4 PDF. SMTP sends a short note with that PDF attached. Not a product.

The previous TypeScript pipeline is gone. Do not revive it. Write new code in Python 3.

When this works, the 07:00 Asia/Karachi email replaces Instagram.

## Locked decisions

- Language: **Python 3**. No TypeScript pipeline.
- Masthead: **The Rameen Times**
- Timezone: `Asia/Karachi`
- Send **from** `rameenbabarr04@gmail.com` using SMTP + `RAMEEN_APP_PASSWORD`. Send **to** `nadeemhashim7@gmail.com`.
- The email body is a short text note: date, lead headline, "paper attached". The paper itself is a **PDF attachment**. Do not send the newspaper as an HTML email body. Gmail clips and breaks images. Print is LaTeX. No agent writes `.tex`.
- LLM: Anthropic Messages API (`ANTHROPIC_API_KEY`). Structured output is a forced `submit` tool. Do not send `temperature`. Thinking is disabled. NewsChief, Writer, Desk, Diary, CopyChief, and the query agent use `claude-sonnet-5`. Topic quality gates use `claude-opus-5`, one call per beat. OpenRouter is gone.
- Search and extract: Tavily REST (`TVLY_API_KEY`). A query agent reads `config/user.md` and emits 4 queries per standing beat. Search is top 5 per query. RSS is latest 5 per feed in `config/feeds.json`. One Opus gate per beat picks 4 stories from title, snippet, and URLs. Extract fills `article_text` on those picks before NewsChief. Do not scrape HTML for body or og:image.
- Tasks: Trello board **My Trello Board**, lists **To-Do** and **In-Progress**. `TRELLO_API_KEY` and `TRELLO_TOKEN` are in `.env` or the environment. `TRELLO_SECRET` is not needed at runtime.
- Calendar: secret iCal in `GOOGLE_ICAL`. Fetch, expand RRULE, honor UNTIL, keep Karachi-local today, skip cancelled. No Cloud OAuth. Do not use `markazprod`.
- Dedup: `data/seen.json`, about 45 days. Art and crafts must not repeat.
- Browser-history mining stays out of v1.

Do not put tokens, app passwords, API keys, or the iCal URL in git, in this file, or in sample editions.

## Commands

```
python -m src.cli preview          # gather, compose, write A4 PDF, open it
python -m src.cli preview --sample # render config/sample-edition.json to PDF
python -m src.cli send             # same as preview, then SMTP with the PDF attached
```

A systemd user timer calls `scripts/run-morning.sh` at 07:00 Asia/Karachi:

```
cp scripts/rameen-times.{service,timer} ~/.config/systemd/user/
systemctl --user enable --now rameen-times.timer
systemctl --user list-timers rameen-times     # confirm the next elapse
journalctl --user -u rameen-times -n 50       # read the last run
```

The units hardcode `%h/Desktop/personal-newspaper`; edit both if the checkout moves. `OnCalendar` names `Asia/Karachi` explicitly, so the edition lands at 07:00 Karachi whatever the machine's zone is, and `Persistent=true` sends a missed edition on the next boot instead of skipping the day.

The script sources no shell profile, because systemd user services do not read `~/.zshrc` or `~/.bashrc`. Secrets come from the environment, or from `.env` at the repo root, which `src/config.py` loads for any variable that is not already set. Read env from the process. Never hardcode secrets.

Needs a TeX install that provides `pdflatex`: `sudo apt install texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended`.

## Layout

```
config/user.md          standing beats, angles, preferred voices
config/feeds.json       RSS URLs grouped by topic
config/paper.yaml       name, send addresses, Trello list names
src/models.py           shared Pydantic state and every agent In/Out schema
src/gather/             news, Tavily, Trello, ICS
src/seen.py             URL and title history
src/agents/             queries, topic gates, NewsChief, Writer, DeskEditor, DiaryClerk, CopyChief
src/render/             Jinja TeX, then pdfLaTeX A4 PDF
templates/              edition.tex.j2, macros from inspo/template.tex
inspo/                  visual source only, not an edition input
src/deliver/            Gmail SMTP, short note plus PDF attachment
src/cli.py              preview and send
scripts/run-morning.sh  systemd wrapper, with .service and .timer beside it
editions/               dated JSON, TeX, and PDF (gitignored)
data/seen.json          gitignored
```

If leftover TypeScript (`src/*.ts`, `package.json`) is still on disk, remove it. Do not keep two pipelines.

## Why LaTeX then PDF

Putting the paper in the Gmail body failed the "looks like a newspaper" test. Chrome-print HTML was the next try. The visual source of truth is now `inspo/template.tex`.

The path is:

1. Sub-agents produce `Edition` JSON. That is the last editorial object. No agent writes TeX.
2. Python escapes copy and fills `templates/edition.tex.j2` using macros ported from `inspo/template.tex`.
3. Image URLs download to a local cache. A missing image drops the figure. It does not fail the paper.
4. `pdflatex` runs twice. No `-shell-escape`. Python fetches images, not `\write18`.
5. Archive `editions/YYYY-MM-DD.json`, `.tex`, and `.pdf`.
6. SMTP attaches the PDF. Email body stays a short note.

`preview` compiles and opens the PDF with `xdg-open`. If there is no viewer, as on a headless box, the run says where the file is and still succeeds. `send` is the only step that emails. `project.md` is what agents read. `inspo/` is visual only. The Cursor plan is not an edition input.

## Interests

`config/user.md` is the taste file. `config/feeds.json` is the RSS list. Both are grouped by the five standing beats. Edit `user.md` by hand when interests shift. The pipeline only reads it.

- **Palestine:** prefer the last 24 hours, humanitarian, culture, Palestinian voices. Al Jazeera, Middle East Eye, +972, Drop Site. No US-cable tone.
- **Art and crafts:** desi crafts, short things to do. Must not repeat.
- **Islamabad folk:** artistic and city-culture only. Search only. Not political. Code still drops political/security keywords.
- **Space:** missions, astronomy, science, sky events. NASA Image of the Day is a normal RSS feed.
- **Tech and AI:** research, open source, local models. Simon Willison, Hugging Face, 404 Media, Ars, IEEE Spectrum. Still no US-cable tone.

Dawn and Tribune are not the house voice. Adding a sixth interest is a code change, not a markdown heading.

## Visual system

A4, multiple pages. Furniture from `inspo/template.tex`: cream paper, Charter body, Palatino headlines, red kickers, hairline and thick rules, drop caps, boxed sidebars, lead and secondary photographs. Do not use the template's 11x17 tabloid size. Do not pull Playfair, Libre Baskerville, or UnifrakturMaguntia in v1.

Page 1 in `news-spread` is masthead, kicker, lead headline, lead photo, lead body. Later pages hold This Day, The Desk plus the desk editor column, remaining secondaries with photos, and briefs.

When `page_mode` is `thin`, This Day and The Desk sit higher, including on page 1. Do not pad empty columns to look like the Herald dummy. Flow with `multicol` and `\clearpage`.

Do not send the newspaper as an HTML email body.

## Schema

Exact fields live in `src/models.py`. News lives in `articles`. Meetings live in `diary`. Tasks live in `desk`. The desk editor column lives in `desk_column`. If Calendar or Trello fails, `diary_note` / `desk_note` say so and the paper still sends.

Shared records that gather code builds (agents read these; Writers and the Chief do not invent new candidates):

- `NewsCandidate`: id, interest, title, snippet, source, optional image, optional article text
- `Meeting`: id, title, start, end, location, all-day
- `TaskItem`: id, title, status (`pending` or `in-progress`), optional due and url
- `Article`: id, headline, dek, byline, section, `body` as a list of paragraphs (never one blob with `\\n\\n`), role (`lead` / `secondary` / `brief`), optional image, source
- `DeskColumn`: headline plus `body` as a list of paragraphs
- `Desk`: pending cards, in-progress cards, `ranked_ids` most urgent first
- `Edition`: masthead fields, date, volume, diary, desk, desk_column, articles, `page_mode` (`news-spread` or `thin`)

The orchestrator holds one `PipelineState` and fills fields as agents finish.

## Newsroom

This is not one prompt that dumps a newsletter. It is a small newsroom. Each role is a Python function that calls Anthropic with its own system prompt and a forced `submit` tool. The tool input must parse into that role's `*Out` Pydantic model. Reject and retry once on validation failure. Run writers in parallel with `asyncio`. Do not add LangGraph, CrewAI, or extra agent frameworks.

### NewsChief

Applies the set policy below, then emits a slate. Code clamps the slate after the model returns. No prose except `kicker` and each assignment's one-sentence brief.

These rules are the Chief. The model may not invent a sixth rule to "make the page look full." `balanced_assignments` / `clamp_slate` enforce the cap and the photos even if the model ignores them.

1. **Lead test (section does not matter).** The lead is the story Hash would actually stop and read this morning, **and** it has a real photograph (`image_url` on the candidate). If several pass the "I would stop" test, pick the one with the better photo. If the chosen lead has no photo and another candidate does, swap. `use_image=false` on the lead is only legal if no candidate has a photo. Do not reserve the front page for Palestine or rotate by weekday.

2. **Fresh only.** Candidates are already filtered against `seen.json`. Do not bring a story back because the page looks thin. Same-day duplicates (same URL, or near-identical titles) stay omitted.

3. **Try for all five standing sections.** Palestine, art and crafts, Islamabad folk, space, tech and AI. After the lead, walk the other beats for secondaries. Omit a beat only if gather returned nothing usable. Never pad.

4. **At most two stories from one interest.** Extra Palestine (or any) candidates are omitted, not briefs.

5. **Photos on the news spread.** Every secondary must have a photograph. If a beat's only fresh story has no image, skip it. After Tavily extract, drop a secondary that still has no image. Briefs may be text-only.

6. **Thin paper is honest.** If the slate is small, print a smaller paper. Do not hunt for a sixth brief. Desk and diary may sit higher on page 1 when `page_mode="thin"`.

7. **Hard rejects** (omit even if they passed gather): political Islamabad; US-cable tone; Dawn or Tribune as the voice of the piece; anything the Chief cannot explain in one sentence without inventing facts.

8. **Kicker** is one factual weather-or-day line, not a joke and not a headline reprint.

Target size when copy exists: 1 lead plus about one secondary per other beat that has an imaged story, then briefs under the cap. Legal size when it does not: 1 lead and whatever else is fresh. `assignments` may be as short as 1.

`use_image` is true for the lead when that candidate has `image_url`, and true for every secondary. `page_mode="thin"` when there are fewer than 6 assignments.

### Writer (one call per assignment)

The Writer does not decide the slate. NewsChief already picked this item. Tavily extract fills `article_text` before the Writer runs. Rewrite that text. Do not paste. Do not invent quotes, death tolls, or diplomacy.

- Lead body: 6 to 10 short paragraphs. Secondary: 4 to 6. Brief: 2 to 3.
- Finish the story on the page. Ban: "read more", "full story at", "see the linked report", "click", URL-as-copy.
- If `article_text` is empty, write shorter from title and snippet. Still no link-out language.
- `article.id` equals `candidate.id`. Copy `source_name`, `source_url`, `image_url` from the candidate. The model may clear `image_url` if it is unrelated. It may not invent a URL.

If a Writer call fails validation twice, drop that assignment. The paper still sends.

### DiaryClerk

Meetings stay as gathered. The model may sort them and write a one-line `intro`. It may not rename titles or invent events. If `meetings` is empty, `diary` is empty and `intro` says so.

### DeskEditor

This is the column, not a Trello dump.

Keep every open card in `desk.pending` / `desk.in_progress`. Rank all of them. Top two or three get real `next_moves` (at most two each) and a `when` of `now`, `after-lunch`, or `can-wait`.

`desk_column` is 3 to 5 sentences: what matters this morning, what can wait, and the next move on the urgent cards. Write it as an editor, not a productivity influencer. Do not joke-rewrite card titles. Use the calendar and `busy_hours` so the advice fits the day.

If Trello fails at gather time, set `desk_note` and skip this agent. The paper still sends.

### CopyChief

One review pass. This is the only editorial drop after the Chief. Must leave exactly one lead. The lead and every secondary must have a photograph. Do not trim a finished story just to hit 2 pages. `edition.tagline` may use the Chief's `kicker`. Print `Source: outlet`, not a URL.

Issue codes: invented-fact, wrong-voice, islamabad-politics, missing-source, no-lead-image, missing-image, too-long, too-thin, link-out, unbalanced, duplicate-lead.

## Compose rules that every agent shares

- Short newspaper English. First sentence carries the news. Keep the reader on the paper.
- Every news story has `source_name` and `source_url`. The printed credit is `Source: name` only.
- After a successful send, append used URLs and titles to `data/seen.json`.
- If Calendar or Trello fails at gather time, set `diary_note` / `desk_note` on `PipelineState` and skip that agent. The paper still sends.

## Agent notes

- Read this file and `src/` before changing the pipeline.
- If you change the `Edition` shape, update this file and `config/sample-edition.json` in the same change.
- Verify the PDF in Preview, then send one email and open the attachment, before calling delivery done.
- Confirm each news story was written by a Writer call, not one blob prompt. Log role plus story id.
- Confirm The Desk is ranked with next moves, not a raw Trello list.
- Do not scrape Instagram. Do not put the newspaper in the Gmail body.
