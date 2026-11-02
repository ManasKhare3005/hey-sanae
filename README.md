# Sanae — a private, local AI companion

[![tests](https://github.com/ManasKhare3005/hey-sanae/actions/workflows/tests.yml/badge.svg)](https://github.com/ManasKhare3005/hey-sanae/actions/workflows/tests.yml)

Say **"Hey Sanae"** and she listens, thinks with a local LLM, does things on your laptop and phone, and answers out loud. She's a friend first and an assistant second: a small 3D character in the corner of the screen who reacts while you talk, remembers your days, and now and then speaks first.

**Nothing goes to the cloud.** The wake word, speech recognition, the LLMs, her voice, the image model and her memory all run on one Windows laptop (RTX 3050, 4 GB VRAM). The phone reaches it over a private Tailscale link.

> Her name, wake phrase, character and voice come from `persona.yaml`. She was first built as "Max", a Jarvis-style assistant; some internal ids (the Android package, `C:\max-android`) still use that name.

## What she can do

| | |
|---|---|
| **Talk** | Wake word or Ctrl+Alt+Y, one running conversation (no wake word needed for follow-ups), interrupt her mid-sentence, a soft "mm-hm" while you think out loud, her voice follows her mood |
| **Be a friend** | Learns what you like and what's coming up, asks how the exam went, keeps a diary of your days, notices when you sound flat, listens when you vent, studies with you, plays games, comments on your music, reads about your interests while you're away |
| **Do things on the laptop** | Apps, media, volume, files, notes, screenshots, power, reading your screen when asked, web search that reads the pages, driving her own Chrome window |
| **Keep you on track** | Reminders (one-off and repeating), her own calendar, Canvas due dates and classes, a morning digest email, deadline alerts, lecture and meeting notes, questions about your course files |
| **Code with you** | Knows your git projects: what changed, GitHub issues / PRs / CI, what's running and its errors. "Ask Claude to fix the login bug in Flock": Claude Code makes it on a branch, you approve, then "push it" |
| **Phone** | Android app: push-to-talk, approvals, chat, today, notes, photos ("what plant is this?"), acting on the phone (calls, texts, maps, alarms); reminders, calendar, todo list (with a home-screen widget) and lecture recording keep working with the laptop off |
| **Watch** | Galaxy Watch app: tap her face and talk, her face in the reply's mood and her voice, approvals on the wrist, what's next, a tile and a complication |
| **Be safe** | Risky actions need your "yes" (silence = no), voice ID, a privacy page that exports or deletes everything, sensitive topics never stored |

## How it works

```
 mic ─► sherpa-onnx keyword spotter ("Hey Sanae", 4 staggered streams, CPU)
          │ wake (or Ctrl+Alt+Y, avatar click, phone)
          ▼
  record until you're done ── end-of-turn model (Namo) ── faster-whisper small.en (CPU)
          │                                                  │  + tone of voice (wav2vec2, ONNX)
          ▼                                                  ▼
 ┌──────────────────────────── Agent ───────────────────────────────────┐
 │ qwen3:4b-instruct, 100% on the GPU   ──think_harder──► qwen3:8b      │
 │ persona + one running chat (recent turns + background summary)       │
 │ notes in the request: memories, friend facts, diary, mood, tone      │
 │ only the tool families a request needs · safety gate · claim checks  │
 └───────────┬──────────────────────────────────────────────┬───────────┘
             ▼                                              ▼
   tools: laptop · web · browser · memory · reminders    Piper voice (CPU) ─► speakers
          calendar · Canvas · notes · phone · games          │ loudness + mouth shapes
             │                                               ▼
             ▼                                  3D avatar (three.js + VRM, iGPU)
   FastAPI + WebSocket on 127.0.0.1:8765 ─► dashboard · desktop app · overlay
             │
             └─ Tailscale ─► Android app (sync, approvals, photos ─► gemma3:4b)
                                  └─ Wear OS Data Layer ─► Galaxy Watch app

 background: initiative (talking first) · friend memory · diary · reading · reminders
```

Design notes worth knowing:

- **A 4B model as the brain.** Most of the engineering is about making a small model reliable. Each request gets only the tool families it needs (~50 tools don't fit in 4k tokens). A command the model kept fumbling ("forget…", "start studying", "play twenty questions") is routed straight to its tool. A reply that claims "I've set a reminder" with no tool call gets one "System check" nudge. A rewritten tool result is only kept if every time, date and number survived.
- **One GPU, 4 GB.** The chat model lives fully in VRAM; Whisper, the voice, tone and turn models run on the CPU. The avatar renders on the Intel iGPU and is pinned to efficiency cores while Whisper works. For a photo, the chat model is swapped out for gemma3:4b and back.
- **Checked in code, not trusted to the model.** Learned facts must use your own words. Follow-ups must be still ahead of you, on the day you named. Opening lines that start like a recent one are redone. Deadline times in notes are quoted verbatim from the transcript.

## Setup

Windows 10/11 with an NVIDIA GPU (4 GB is enough), 16 GB RAM, ~12 GB of disk.

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

It installs Python 3.11 and Ollama if missing, creates `.venv`, installs packages, and downloads everything else:

- the models: the voice, wake word, Whisper, tone and turn models, and the LLMs (`qwen3:4b-instruct`, `qwen3:8b`, `gemma3:4b`);
- the avatar runtime;
- the dashboard build, if Node.js is installed;
- the private search engine, started if Docker Desktop is running.

| Command | What it does |
|---|---|
| `.\run.bat` | Voice mode: say "Hey Sanae" and talk |
| `.\run.bat --text` | Type instead of talking (no mic needed) |
| `.\run.bat --tray` | Background mode with a tray icon (what the shortcuts use) |
| `.\run.bat --enroll-voice` | Record your voice once for voice ID |
| `.\run.bat --wake-test` | Live wake word scores, for tuning |
| `.\run.bat --list-devices` | Mic and speaker ids for `config.yaml` |
| `install_shortcuts.ps1` | Desktop and Start Menu "Sanae" shortcuts (opens the app, starts her if needed) |
| `install_autostart.ps1` | Start at login, restart on crash (`-Uninstall` removes it) |

Ollama must be running. Settings live in `config.yaml`, and her personality in `persona.yaml`. Passwords and feed links go in `secrets.yaml`, which is never committed.

## Things to try

- "What time is it?" · "Open Spotify" · "Next song" · "Set the volume to 30" · "Go to sleep" (frees the GPU for gaming)
- "Who won the most recent Super Bowl?" → searches and reads the top pages
- "Open YouTube" → "Search for lofi music" → "Play the second video"
- "Remind me every month on the 5th to pay the insurance" · "Add a study group tomorrow at 3pm"
- First "Hey Sanae" of the morning → weather, classes, what's due, first event, todos ("skip" ends it) · "Brief me" · "Is it going to rain today?"
- "How did I sleep?" · "How many steps today?" · "What's my heart rate?" (the watch measures it) — after turning on Health in the phone app
- "Goodnight" (music off, tomorrow's calendar, quiet for the night, laptop locked) · "Study time" · "Gaming time"
- "Add milk, eggs and bread to my list" · "What's on my todo list?" · "I bought the milk, check it off" · "Clear the done ones"
- "What's due this week?" · "What did the professor say about RDF schema?" · "Take notes" … "Stop taking notes"
- "Study with me for an hour on networks" · "Let's play twenty questions" · "What song is this?"
- Play a League game: she cheers your kills and Baron, then gives a recap · "How did my last game go?"
- "Ugh, today was a lot" (she listens) · "What did I do last Tuesday?" · "Not now" (she stays quiet for a while)
- On the phone: share a photo of a flyer → "add this to my calendar"
- "What changed in Flock this week?" · "Any open issues on Sanae?" · "Start Flock" … "Any errors?" · "Ask Claude to add dark mode to my resume builder" … "Merge it" · "Push it"

## Talking with her

- **One running chat** (`conversation.py`). The last few turns go to the model word for word, and everything earlier is kept as a summary she updates in the background while idle. It survives restarts. After a 4-hour gap a new chat starts, and she can pick the last one back up.
- **Conversation mode.** After each reply she listens for 20 s, so follow-ups need no wake word. Only your voice counts (voice ID): a video or someone else in the room ends it instead of getting an answer.
- **Knowing when you're done** (`turn.py`). When Whisper leaves a sentence open ("so I was thinking that maybe"), a small end-of-turn model decides whether to wait. If you've talked a while and pause mid-thought, she says one soft "mm-hm".
- **Fast and interruptible.** She starts speaking the first sentence while the rest is still being written. Say "stop" to cut her off, or "Hey Sanae…" to ask something new; her own voice doesn't trigger it.
- **Emotion tags** (`tags.py`). Every reply starts with something like `[happy]`, `[shy][cover_face]` or `[sad]`, which sets the avatar's face and gesture and her voice's speed, pitch and softness. The tag is removed before she speaks. Voice: Piper `en_US-hfc_female`, softened; Kokoro is available as `tts.engine: kokoro`.

## A companion, not just an assistant

- **Talking first** (`initiative.py`). She talks first in these moments:
  - hello at the start of the day;
  - picking the chat back up after you've been away 45+ min;
  - a break nudge after 2 h;
  - a heads-up before events and classes;
  - an evening "how did today go?" and a Sunday look back;
  - small talk about what you're into;
  - asking how something went;
  - gentle bedtime nudges after 00:30.

  `chattiness` sets the gaps and a daily cap. Lines too close to one from the last two weeks are dropped.
- **Do not disturb** (`dnd.py`). She never starts a conversation:
  - during fullscreen games, videos or presentations;
  - during calls (another app using the mic or camera);
  - during quiet hours;
  - after "not now".
- **Getting to know you** (`friend.py`). A few minutes after a chat, the small model picks out what a friend would remember: likes, people, plans, projects and routines, plus things to ask about later. Only your own words count (not hers, not a video). Health, money, credentials, religion, politics and the like are never kept. If she asks about something that never happened ("I didn't have a quiz"), she drops it and apologises. Everything is on the dashboard's **About you** tab, where you can edit or delete it.
- **Her diary** (`diary.py`). Each morning she writes a few lines about the day before, plus shared moments: running jokes, nicknames, birthdays. "What did I do last Tuesday?" finds it. It's editable on the **Diary** tab.
- **How you sound** (`tone.py`). A speech-emotion model compares your energy with your own usual level, so a flat "I'm fine." gets "you sound a bit quiet, everything okay?". It stays silent until it has learned your normal voice. Only daily counts are kept.
- **A good listener** (`support.py`). When you vent, she takes your side and reflects what you feel; she asks "ideas, or just vent?" once and switches to advice when you ask. When you're stressed, she offers a one-minute breathing exercise and talks you through it.
- **When you're not okay** (`comfort.py`). "I'm not okay", "I feel so alone", or worse, and she becomes a friend sitting with you:
  - no teasing, a soft face and voice, and no talking first in the background;
  - she names what you feel, asks gently, and reminds you of real things about you (only ones she actually knows);
  - she offers small comforts such as breathing together, your music or a minute outside, and gives no advice unless you ask;
  - if you talk about hurting yourself, she also asks once whether there's someone you could be with tonight;
  - she never brings up helplines and never calls anyone.

  Everyday phrases ("this homework is killing me") don't count.

  When you say you feel better, she eases back to her cheerful self over 30–60 minutes. The next day she asks once how you're doing; if you're still not great, she keeps things warm and light. The ways she comforts you are listed under `support.comfort` in `persona.yaml`, and friend memory never learns from those conversations.
- **Every day's mood in her diary.** Each diary entry records how the day felt (great, good, okay, stressed, tired, low, mixed, or "a hard day, felt better by the end"), counted from your messages. Only daily counts are stored, never the messages themselves.
- **She learns how you like to be talked to.** "Too long", laughing at her teasing, "stop asking" and cutting her off tune three dials: reply length, teasing and questions. They're on the Diary tab, with a reset.
- **Her mood** (`mood.py`). Her energy follows the time of day; her cheer rises with nice moments and dips with rudeness. Her mood sets the avatar's resting face.
- **A life of her own.** While you're away, she reads one thing related to your interests (`reading.py`). She also studies with you in 25/5 rounds (`study.py`), plays twenty questions, trivia (on any topic or your course files) and would-you-rather (`games.py`), and comments on the song you're playing (`music.py`, title and artist only).
- **Photos** (`vision.py`). Share a picture to her on the phone, or use the camera button. The laptop swaps in gemma3:4b to look, then she answers and can act on it: a flyer becomes a calendar event. The swap starts when the camera opens, and she reacts as soon as you send. The answer takes ~25 s, because two models don't fit in 4 GB together. Photos are re-encoded without location data on the phone, and are never written to disk on the laptop.

## Getting things done

- **Laptop.** She can:
  - open apps (from config aliases or a Start Menu fuzzy match);
  - control media and volume;
  - work with files and notes;
  - show battery status;
  - take screenshots, lock the laptop and handle power (cancellable);
  - free the GPU.

  "What does this error mean?" captures the front window into memory, reads it with Windows OCR and answers. That only happens when you ask.
- **Web.** Search uses [SearXNG](https://github.com/searxng/searxng) in Docker (falling back to DuckDuckGo if it isn't running). Each search reads the top 4 pages and ranks the passages, so answers come from the pages and not from guesses. Websites open in **her own Chrome window** (Playwright, with a separate profile), where she can click things by name or position ("the second video"), type, scroll, read the page and manage tabs.
- **Memory and reminders.** "Remember that…" stores a fact, and she finds it again by meaning (SQLite + bge-small embeddings). Every conversation is searchable. Reminders understand natural times and repeats ("every weekday at 7", "the 5th of every month"). They're spoken when she's idle and shown as Windows notifications; ones missed while she was off are announced at the next start.
- **Her calendar** (`agenda.py`). "Add the dentist Friday at 10". The phone shows it as a local "Sanae" calendar.
- **Health from the watch** (`health.py`). Off until you turn on **Settings → Health** in the phone app. Then the phone reads sleep, steps, resting heart rate and the latest heart rate from Health Connect (where Samsung Health puts the Galaxy Watch's data) and sends one row per day to the laptop. "How did I sleep?" ("You slept 5 hours 40 minutes, 2:10 AM to 7:50 AM, less than your usual 7 hours 35 minutes."), "how many steps today?", and "what's my heart rate?", which has the watch measure it there and then. Last night's sleep is also in the morning briefing. It only goes to your laptop and the Privacy tab deletes it.
- **Screen time** (`screentime.py`). After 2 hours of gaming you get a notification on the phone (which the watch mirrors) and a line from her; after 3 hours on the laptop she tells you to get off for a bit (voice and a Windows notification). It repeats hourly while you keep going. A 10-minute break resets the clock, and "not now" keeps her voice out of it. The limits are in `screen_time`.
- **Game mode on its own** (`gamemode.py`). When Valorant starts (the game itself, not the Riot Client) she says a quick "have fun", unloads the language models so the GPU is all the game's, and stays quiet; when it closes the chat model loads back and the avatar returns. "Hey Sanae" still works mid-game. Other games: `game_mode.games` in `config.yaml`.
- **Valorant recaps** (`valorant.py`). After each match, back in the menus, one line: "GG, 13 to 9 on Ascent!", plus a rank change after competitive. Nothing during a match. Read from the Riot Client's own presence on this laptop (map, queue, team scores, rank), nothing sent anywhere. "How did my last game go?", "how did my last 5 matches go?", "what's my rank?".
- **League of Legends companion** (`league.py`). During a game she reads Riot's [Live Client Data API](https://developer.riotgames.com/docs/lol#game-client-api) on the laptop (read-only, only up during a game) and reacts out loud: your kills, first blood, multikills, aces, Baron, dragons and inhibitors. At most one line a minute (big moments after 20 s), never mid-fight (a kill in the last 8 s or your health dropping fast), and stale lines are dropped. Lines come from templates, not the model, so the GPU stays free. When the game ends: a recap (result, KDA, CS per minute, champion), kept for "how did my last game go?". "Not now" silences the reactions; `league.chatter: false` keeps only the recap.
- **Routines** (`routines.py`). One phrase, several steps, defined in `config.yaml` (`routines.list`): a step says a line or calls any of her tools with fixed arguments. Risky steps (closing an app, power) still ask first, and a "no" only skips that step. The starter set: **goodnight** (stop the music, read tomorrow's calendar, stay quiet for the night, lock the laptop), **study time** (close Discord if it's open, start a 50-minute study session) and **gaming time** (open League, free the GPU). The phrase alone runs it without the model ("okay, goodnight!"); "run my goodnight routine" works too.
- **Morning briefing** (`briefing.py`). The first time you wake her after 5 AM (until noon) she runs through the day, one short sentence each: the weather ([Open-Meteo](https://open-meteo.com), no key; set `briefing.location`), classes still ahead, what's due, the first thing on the calendar, reminders and the todo list. If the first thing you say is a request, she answers it first and the briefing follows. "Skip" or "stop" ends it. "Brief me" gives it any time, and "what's the weather?" reads the same forecast.
- **Todo list** (`todos.py`). Things to get done with no alarm: "add milk and eggs to my list", "what do I still need to do?", "check off laundry", "clear the done ones". Ticked items stay (crossed out) until cleared. It's on the dashboard (Reminders & todos), the phone and its home-screen widget, and the watch's Next up.
- **Canvas and digest.** From your Canvas calendar feed she knows what's due and when classes are (with Zoom links). Every morning she emails a digest, and phone alerts come 24 h and 3 h before deadlines.
- **Course material** (`course.py`, `docnotes.py`). Slides, PDFs and Word files in `Documents\Sanae Course Material` are indexed page by page. Answers name the file and page. "Summarise my course files" writes study notes.
- **Lecture and meeting notes** (`notes.py`):
  - The mic, or the mic plus laptop audio, is captioned live.
  - Whisper's more accurate text replaces the captions as it goes.
  - At the end she writes Summary / Key points / Action items notes, plus a "Deadlines (exact quotes)" section taken straight from the transcript.
  - Notes are saved to `Documents\Sanae Notes`, and no audio is kept.
- **Your code projects** (`projects.py`, `tools/code.py`). Every git repo in `Desktop\My Projects` (set `projects.folders`):
  - **Asking:** branch, uncommitted files and recent commits; open issues, pull requests and the last CI run from GitHub (the [gh](https://cli.github.com) tool; sign in once with `gh auth login`). "It" means the project open in your editor or terminal.
  - **Running:** she sees dev servers working inside a project and their ports. Ones she starts herself ("start Flock" runs `npm run dev`, or `projects.run`) have their output kept, so "any errors?" reads it.
  - **Changes by Claude Code** (`devloop.py`). "Ask Claude to …" starts a `claude -p` session in a separate work copy on its own branch (`sanae/<id>`). It can edit and run the tests, but can't commit, push or delete. She runs the tests again, then tells you it's ready (voice, Windows notification, phone). "Merge it" merges into the branch you're on (refused if you've switched branch or have unsaved edits to the same files); "reject it" deletes the branch. Pushing to GitHub is a separate step that always asks first.

## Phone app (Android)

Native Kotlin + Jetpack Compose (`android/`), connected to the laptop's API over [Tailscale](https://tailscale.com):

- **Talk.** Push-to-talk, with replies in her own voice. A listening sheet opens from the side key (set her as the digital assistant), a Quick Settings tile, a widget or the app shortcut.
- **Chat, Today, Memory, Notes, Settings.** Pairing is by QR code from the dashboard.
- **Approvals.** Risky actions started from the phone wait for your Approve / Deny tap (90 s, silence = no).
- **She acts on the phone.** She can:
  - open apps and call contacts (asks first);
  - text or WhatsApp (opens ready to send);
  - set alarms and timers, and give Maps directions;
  - play music;
  - answer "what did I miss?" from recent notifications.

  Each permission is off until you grant it.
- **Health (off until you turn it on).** Settings → Health reads the watch's sleep, steps and heart rate from Health Connect, read-only, and sends them to your laptop with each sync. When she asks the watch for your heart rate, it comes through here. Gaming nudges also arrive here as notifications.
- **Today & todos widget.** A home-screen widget with what's next today, your todo list with checkboxes, and a Talk button. Ticks work offline and sync later.
- **Works with the laptop off.** Reminders fire from the phone's own exact alarms, and her calendar and todo list live on the phone too. Lectures can be recorded on the phone, and are uploaded and turned into notes when the laptop is back. Both sides sync by id: a finished item beats an open one, and otherwise the later edit wins (`sync.py`, `OfflineLogic.kt`).
- **Code changes from the phone** (`devloop.py`). Pick Sanae or one of your projects and describe a change: Claude Code makes it on a separate branch and runs the tests (and builds, for Sanae). You can read the diff, then Approve merges it (Sanae restarts if her code changed) and Reject throws it away. For projects, **Push to GitHub** follows the merge. **App update** installs the newest build.

The API stays on `127.0.0.1`. `tailscale serve --bg 8765` publishes it inside your tailnet only, and anything not from the laptop needs the phone token. Build the app with `android\build.ps1` (no Android Studio needed).

## Galaxy Watch app (Wear OS)

`android/wear`: Compose for Wear OS. It talks to the laptop only through the phone app, over Wear OS's own link, so the watch needs no pairing or Tailscale of its own.

- **Tap her face and talk.** It stops when you stop talking. The phone sends the recording to `/api/voice`, and the reply comes back as text with her face rendered from the 3D avatar in the reply's emotion. If you turn on "Her voice", she also speaks on the watch. When she asks something back, it listens again.
- **Approvals** show up with ✓ / ✗ buttons.
- **Heart rate on request.** "What's my heart rate?" makes the watch take a reading (Health Services). It asks for the sensor permission the first time you open the app after turning on Health on the phone.
- **Next up:** your reminders, events, classes and due items, then open todos, from the phone's own copies, so it works with the laptop off.
- **A Today tile** with a Talk button, and **a complication** that opens her already listening.

Setup (Wi-Fi debugging, installing, adding the tile) is in [`android/WATCH.md`](android/WATCH.md).

## Avatar

Sanae is a 3D VRM character in a transparent, always-on-top window in the bottom-right corner (`dashboard/avatar.html`, three.js + @pixiv/three-vrm).

- **Alive.** She breathes, makes small eye movements, glances around and follows the mouse. She looks up when you say her name, nods in your pauses, looks thoughtful while thinking and dozes when the models sleep.
- **Talks like a person.** Her lip sync comes from the voice's loudness and two band-energy ratios (mouth shapes without a phoneme model). Her nods, brow raises and hand beats fall on stressed words, and her face is mixed from separate brow, eye and mouth morphs so smiles don't gape.
- **Emotions and gestures** come from her tags (wave, cheer, cover face, nod, shrug), queued one after another. A speech bubble shows her words in step with the voice.
- **Polite on the desktop:**
  - Clicks land only on her; the window clips itself to her outline 10× a second.
  - Drag her past a screen edge and she tucks in, peeking.
  - She hides for fullscreen games, and on "hide" (she waves goodbye) or a held Ctrl+Alt+Y.
- **Her look.** `python -m sanae.avatar.lookalike` builds her from VRoid's AvatarSample_A: long dark wavy hair, a charcoal "NOW" sweater and over-ear headphones with glowing cyan rings, all made by editing the file. The output isn't committed. A Live2D version (`avatar.renderer: live2d`) also exists.
- **Seasonal looks** (`dashboard/src/avatar/season.ts`). Small extras built in three.js on her head bone, and recoloured headphone rings: a ghost hair clip for Halloween week, a Santa hat at Christmas, a party hat at New Year, a heart clip for Valentine's, and otherwise a seasonal hair clip (flower, sunflower, leaf, snowflake). From 11 PM her hair goes up in a bun, and after midnight her eyes get heavy and her blinks slow. `avatar.seasonal: false` turns it off; `scripts/season_renders.py` renders every look headless for checking.
- **Cost.** She renders on the Intel iGPU (0 MB of the 3050's VRAM). While Whisper transcribes she drops to 60 fps on the efficiency cores; measured, Whisper takes 1.95 s without her and ~2.1 s with her.

## Dashboard, desktop app and overlay

- **Dashboard** (`dashboard/`, React + Vite + TypeScript, http://127.0.0.1:8765). It's a "mission control" view with:
  - a live voice orb;
  - the conversation, with tools per answer, and typed commands;
  - approvals;
  - live activity;
  - memories and reminders;
  - the About you, Diary and Notes tabs;
  - command accuracy;
  - the privacy page.
- **Desktop app** (`sanae/app`). A window around the dashboard that starts her if she's off.
- **Overlay** (`sanae/overlay`). A small draggable pill with push-to-talk, record, quick panels, and start/stop.

## Privacy and safety

- **Risky actions** (closing apps, power, sending, deleting, buying) need a clear spoken or tapped "yes"; silence or anything ambiguous counts as no. In the browser, buy / pay / send / delete clicks ask first. She never types into password fields.
- **Voice ID** (`voiceid.py`). A risky request or a "yes" in a voice that isn't yours goes to the phone for approval instead. Only a voiceprint is stored, never audio.
- **The window in front** is read only when needed and kept in memory only: never saved, logged or sent anywhere. Password managers, banking, private windows, sign-in pages and secrets files are never read (`window.py`, plus your own `context.blocklist`).
- **Nothing sensitive is learned.** Health, money, credentials, religion, politics, sexuality and addresses are filtered out of friend memory and out of her reading searches.
- **Privacy page** (dashboard). Lists everything she keeps, exports it as one zip, or deletes any category.

## Measured

- **Command accuracy** (`python -m sanae.evals`). About 90 realistic commands, with every tool stubbed: **99% right action, 99% right details, median 1.4 s**, up from 90% / 84% on the first run. Results are on the dashboard's Accuracy tab.
- **Speed.** The chat model prompts at ~1,600 tok/s and writes at ~50 tok/s fully on the GPU. If it ever loads half into shared memory, she notices the slow prompts and reloads it.
- **Wake word.** 100% of normal-volume calls on synthetic speech, with no false triggers in testing. "Hey Mac" also fires, because it sounds almost the same.

## Tuning (`config.yaml` / `persona.yaml`)

- **Wake word misses or false triggers.** Adjust `wake_word.sherpa.threshold` and check with `--wake-test`.
- **She cuts you off.** Raise `audio.silence_s`.
- **She doesn't notice you talking.** Lower `audio.vad_sensitivity`.
- **Chattiness** (`quiet` / `normal` / `chatty`), quiet hours, bedtime window and topics are all in `persona.yaml`.
- **App shortcuts.** Add `spoken name: command` under `apps:`.
- **Different LLMs.** Any Ollama model with tool support works (`llm.fast_model`).

## Troubleshooting

- **"Can't reach Ollama"**: open the Ollama app, or run `ollama serve`.
- **"Model isn't downloaded"**: run the `ollama pull` command it prints.
- **No wake detection**: run `--list-devices` and set `audio.input_device`. Check that Windows privacy settings allow desktop apps to use the mic.
- **Robotic voice**: the Piper voice file is missing; re-run `setup.ps1`.
- **Slow first answer**: the model is loading into VRAM. Close GPU-heavy apps.
- **Logs**: `logs/sanae.log`. A heartbeat is logged every 30 s; if she's stuck, thread stacks go to `logs/stacks.log`.

## Project layout

```
sanae/
  main.py         entry point: voice loop, text mode, tray mode; the shared Context
  agent.py        tool-calling loop, direct routes, claim checks, safety gate
  llm.py          Ollama client (chat, preload/unload, slow-load detection)
  conversation.py one running chat: recent turns + background summary
  audio.py, wakeword.py, stt.py, turn.py, tone.py, tts.py, speech.py, voiceid.py
  persona.py, tags.py, initiative.py, dnd.py, mood.py, support.py, comfort.py
  friend.py, diary.py, reading.py, study.py, games.py, music.py, vision.py
  memory.py       SQLite + embeddings: facts, turns, actions
  reminders.py, agenda.py, todos.py, briefing.py, routines.py, league.py, health.py, screentime.py, sync.py, alerts.py, canvas.py, digest.py, mail.py
  course.py, docnotes.py, notes.py, live.py, phone_notes.py
  web.py, browser.py, window.py, toolselect.py
  server.py, events.py, remote.py, phone.py, privacy.py, devloop.py, projects.py, evals.py
  avatar/         avatar window, click-through, edge peek, core pinning, lookalike builder
  app/, overlay/, tray.py, hotkey.py
  tools/          the tools the model can call (registry.py: @reg.tool)
dashboard/        React dashboard + avatar pages (src/avatar, src/live2d)
android/          Kotlin + Jetpack Compose phone app (app/) and Galaxy Watch app (wear/)
scripts/          persona_lab, companion_lab, tts_audition, export_tone, watch_faces
tests/            pytest suite: no mic, GPU, Ollama or Windows needed
persona.yaml      who she is
config.yaml       everything else
```

## Development

```powershell
.\.venv\Scripts\python -m pytest -q          # 222 tests
cd dashboard; npm run build                   # dashboard
android\build.ps1 -NoInstall                  # phone + watch apps -> data/app/sanae.apk, sanae-wear.apk
android\gradlew testDebugUnitTest             # Kotlin logic + screen snapshots (phone and watch)
```

Adding a tool:

```python
@reg.tool("Describe it for the LLM.", params={"city": {"type": "string"}}, risky=False)
def my_tool(city: str):
    return f"Result for {city}"
```

Mark anything destructive or outward-facing `risky=True` with a `confirm` message. `scripts/persona_lab.py` and `scripts/companion_lab.py` try her with the real model on a throwaway database; set `SANAE_LAB=1`, and the real `data/sanae.db` is refused.

## Roadmap

- Google Calendar / Tasks through the Google APIs (mail already works through an app password)
- Demo video

## Credits and licences

- **LLMs:** Qwen3 (Apache 2.0) and Gemma 3 (Gemma terms), via [Ollama](https://ollama.com).
- **Speech:**
  - [faster-whisper](https://github.com/SYSTRAN/faster-whisper);
  - [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) for the keyword spotting and live captions;
  - [Piper](https://github.com/rhasspy/piper);
  - Namo Turn Detector (Apache 2.0).
- **Tone of voice:** audeering's `wav2vec2-large-robust-12-ft-emotion-msp-dim`, **CC BY-NC-SA 4.0: non-commercial use only**.
- **Avatar:**
  - VRoid AvatarSample_A (VRoid sample terms). You download it yourself from VRoid Hub; the edited model is not committed or redistributed.
  - Live2D's Hiyori sample and Cubism Core (Live2D terms). `setup.ps1` downloads them; they are not committed.

## License

Copyright © 2026 Manas Khare. All rights reserved. This code is shared for viewing only; see [LICENSE](LICENSE). Please don't use, copy or redistribute it without written permission.
