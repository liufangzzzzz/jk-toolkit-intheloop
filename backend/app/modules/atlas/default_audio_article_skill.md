---
name: interview-transcript-editor
description: "Edit raw interview transcripts, shorthand notes, ASR/subtitle outputs, or mixed Chinese/English spoken material into Chinese editorial copy. Use when the user provides a transcript or 速记 and asks for 中文可读版, 个人使用版, 极客公园版本, 访谈稿版本, polished Q&A, Founder Park/极客公园-style article, public-facing founder interview, or publish-ready Chinese founder story while preserving speaker intent, transcript feel, technical details, reporting value, and founder voice."
---

# Interview Transcript Editor

Edit raw ASR / subtitle transcripts, shorthand notes, or mixed Chinese/English spoken material into Chinese interview text. By default for `速记` requests, produce two versions: `【中文可读版】` and `【个人使用版】`. Produce `【极客公园版本】` only when the user explicitly asks for FP/Founder Park/极客公园/访谈稿/对话稿/成稿/发表/公众号 output.

When writing files, default to `.docx` Word documents for all requested versions. Use Markdown only as an internal drafting format or when the user explicitly asks for Markdown. If creating `.docx`, use the documents skill workflow when available; if render QA is unavailable, still create the `.docx` and state the limitation.

## Workflow

Use a two-version default workflow unless the user asks for only one output or explicitly requests a publishable interview draft. Avoid repeating the same cleanup work across versions: make `【中文可读版】` the factual base, then derive `【个人使用版】` from it. Keep the 极客公园/publishable interview workflow available as an optional third stage.

### Coverage and Section Completeness

When a transcript contains both front-loaded solo remarks / keynote-style introductions and later interview, Q&A, media questions, audience questions, or roundtable dialogue, process the full source in chronological order unless the user explicitly asks to exclude a section. If the user gives instructions such as `前面的单人讲话部分在可读版不要压缩，在给我读的版本适当压缩`, treat that as a style rule for the solo-remarks section only, not as permission to omit later interview/Q&A sections. Both `【中文可读版】` and `【个人使用版】` must still include the later interview/Q&A content, with clear section headings and speaker labels.

For solo-remarks sections:
- In `【中文可读版】`, preserve the speaker's full reasoning path, topic order, technical terms, numbers, product names, and examples. Clean filler and ASR errors, but do not turn the section into an outline or compressed summary.
- In `【个人使用版】` / `给我读的版本`, compress repeated setup, throat-clearing, and duplicate transitions, while retaining the full logical chain, named concepts, technical claims, numbers, release details, and scene examples needed for reporting.

For later interview/Q&A sections:
- Do not omit questions or answers merely because the user emphasized the preceding solo remarks.
- In `【中文可读版】`, polish Q&A into readable speaker turns while preserving all substantive questions, answers, examples, figures, and caveats.
- In `【个人使用版】`, questions and answers may be tightened for quick reading, but every substantive topic and speaker turn must remain represented unless the user explicitly asks for a selective digest.

0. **Stage 0 - Chinese normalization**: For English or mixed-language source material, first translate the source into coherent Chinese while preserving speaker order, timestamps, technical terms, numbers, and named concepts. For Chinese source material, keep it in Chinese and proceed directly.
1. **Stage 1 - Chinese readable version**: Clean the Chinese-normalized transcript into `【中文可读版】`. Preserve it as the canonical fact layer for factual checking.
2. **Stage 2 - Personal-use version**: Derive `【个人使用版】` primarily from `【中文可读版】`, restoring useful timestamp ranges, speaker turns, technical density, demo details, and overview blocks from the raw source only where the readable version compressed them too much.
3. **Optional Stage 3 - 极客公园 version**: Only when the user asks for 访谈稿/对话稿/极客公园/Founder Park/FP/成稿/发表/公众号, reshape `【中文可读版】` into `【极客公园版本】`, usually a 极客公园-style publishable interview article.

Default to direct full output. Do not announce a plan unless the user asks for one or the input is missing/ambiguous. If the input is too long or structurally difficult to process reliably in one pass, split by natural timestamp ranges, speaker turns, or topic blocks; recombine into one continuous, ordered output before responding.

### Derivation Order

1. If the source includes English, translate it into Chinese first while preserving order, technical specificity, and speaker attribution. Treat this Chinese-normalized material as the working source.
2. Build `【中文可读版】` from the Chinese-normalized source first. This is the canonical fact layer.
3. Build `【个人使用版】` from `【中文可读版】` plus targeted raw-source checks for:
   - Useful timestamps or chronological section ranges.
   - Speaker attribution that was unclear or compressed.
   - Dense technical passages, demos, operations, numeric details, comparisons, and named concepts.
   - Long single-topic stretches that justify a `（概览/总结）` block.
4. Build `【极客公园版本】` only on explicit request, using `【中文可读版】` as the article base and `【个人使用版】` as a reporting-detail reservoir when technical detail, timeline, or source texture is needed.
5. Return to the raw source only for verification, missing details, timestamps, speaker labels, original English terms, or high-risk claims. Do not re-clean the entire raw transcript for each version.

### Stage 0 - Chinese Normalization

Use this step for all English or mixed-language inputs before Stage 1.

- Translate English transcript lines into natural Chinese while preserving the original time order, speaker attribution, numbers, units, technical terms, proper nouns, and named concepts.
- For mixed Chinese/English, translate English portions and polish Chinese portions into one coherent Chinese working transcript.
- Keep important English technical terms in parentheses only when they are useful for accuracy or later reporting, for example `强化学习（reinforcement learning）`.
- Do not summarize during translation. Preserve the transcript's informational density and speaker intent.

### Stage 1 - Chinese Readable Version

1. **Pre-process**: Strip timecodes, SRT formatting, and stray line breaks. Identify speakers.
2. **Proofread**: Fix ASR errors - homophones, proper nouns, numbers, foreign terms.
3. **Polish**: Convert spoken style to written style; add/correct punctuation; split into natural paragraphs.
4. **Trim**: Remove zero-information fillers (呃、那个、就是说、对对对, repeated phrases) without losing meaning.
5. **Review**: Read each paragraph aloud mentally; ensure flow, coherence, and factual accuracy.

### Stage 2 - Personal-use Transcript Polisher

Use this version as the technology journalist's working copy. Start from `【中文可读版】`, then selectively enrich it with timeline, speaker, and detail checks from the raw source. It should remain closer to the transcript than Stage 3, but be usable for reporting, quoting, and later article development.

#### Input Modes

- **English transcript**: Use Stage 0 first, then derive this version from the Chinese-readable base.
- **Chinese transcript**: Rewrite into normal, natural spoken Chinese.
- **Timestamped Chinese or English**: Keep the original time order and process according to the timeline; use raw timestamps to enrich `【个人使用版】` after Stage 1.
- **Mixed Chinese/English**: Translate English portions and polish Chinese portions into one coherent Chinese transcript.

#### Reporting Priorities

Prioritize information most valuable to a technology reporter:

- Technical principles and mechanisms.
- R&D strategy and design tradeoffs.
- Testing methods and reliability data.
- Quantitative figures and constraints.
- Operation flows, demos, actions, and scenes.
- Team decisions and iteration process.
- Manufacturing, supply chain, thermal, control, AI, software, and hardware details.
- Innovation points and industry comparisons.
- Metaphors, analogies, named concepts, and strategic framing.

#### Transcript Style

- Translate or polish sentence by sentence inside each paragraph where possible.
- Keep natural pauses, oral rhythm, and meaningful repetition.
- Remove or merge pure filler such as `um`, `uh`, `yeah`, repeated greetings, repeated questions, and empty transitions.
- Merge consecutive short sentences when this improves Chinese readability without losing information.
- Preserve actions, operations, scenes, technical details, numbers, terms, comparisons, and named concepts.
- Do not add the assistant's own conclusions inside the transcript body.
- Do not over-compress dense technical passages.

#### Speakers

- Mark speakers clearly when identifiable, for example `主持人：`, `Brett：`, `Mortz：`.
- If the speaker cannot be reliably identified, keep the natural dialogue order without inventing a name.
- Do not assign all content to one speaker by default.
- Keep meaningful host questions that introduce technical, operational, or strategic information.
- Delete or merge redundant host prompts, repeated confirmations, and purely social chatter.

#### Timeline Handling

- Preserve the original chronological order.
- If timestamps are present, keep useful timestamp markers or section ranges.
- For Chinese drafts with timestamps, polish according to the timeline instead of treating the text as unordered prose.
- Do not insert a summary for every timestamp range.

#### Overview / Summary Blocks

Insert an embedded block labeled `（概览/总结）` only when a long continuous discussion, roughly 5-10 minutes or more, stays on one main topic. Do not add overview blocks for short Q&A, scattered topics, or ordinary timestamp changes.

When used, the overview must be based only on the source material and may include:

- The host's core concern.
- The speaker's apparent strategy, intent, or method.
- Important information gaps, labeled clearly as `信息缺口`.

Keep strategy and priority analysis in the overview block, not inside the transcript body.

Example:

```markdown
（概览/总结）
这一段主要围绕机器人换电与连续运行展开。主持人关注的是系统能否稳定 24/7 工作，发言者强调的是通过机器人自主脱离充电座、快速换位和周期性补能来维持连续作业。

信息缺口：原文没有提供电池容量、单次充电时间、换位失败率、故障恢复流程或长期运行测试样本量。
```

Only mark missing information as `信息缺口` in overview blocks. Useful gaps include missing sample size, test duration, failure rate, hardware specifications, control algorithm details, manufacturing process details, or comparison baseline.

#### Strategy and Tradeoffs

For design choices and tradeoffs, such as hand dexterity versus reliability:

- In the transcript body, keep only what speakers actually said.
- In overview blocks, explain the strategy, priority, and logic only if the source supports it.
- Never insert inferred strategy into ordinary transcript lines.

#### Personal-use Output Shape

Use the simplest structure that fits the source:

```markdown
【个人使用版】

[timestamp or section if present]
主持人：...
Brett：...

（概览/总结）
...

[next timestamp or section]
...
```

If there are no timestamps, use speaker turns and paragraphs only. Do not append a generic summary unless the user asks for one.

If the user provides a successful example or asks for calibration against an example, read `references/success-example.md` if it exists and use it as the house-style sample for how much filler to remove, how aggressively to merge short exchanges, and how to keep timestamps while preserving technical detail.

### Stage 3 - 极客公园 Publishable Article

Build on the `【中文可读版】`; do not return to the raw transcript except to verify uncertain facts.

1. **Extract the central founder-facing thesis**: Identify the product/company, founder, core non-consensus view, why now, and why founders/operators should care.
2. **Choose the article center of gravity**: For startup founder interviews, do not default to a complete product checklist. Decide whether the article should be person-driven, organization/team-driven, challenge-driven, core-abstraction-driven, scene-contrast-driven, or product-first.
3. **Collect evidence from the transcript**: Pull out concrete numbers, team background, product milestones, user data, financing/revenue/ARR/MRR, technical route, GTM, market timing, and first-hand quotes. Mark missing or uncertain facts with `[待核实]`.
4. **Write an editor lead**: Open with product/event, striking data, founder quote, phenomenon, MVP validation, or a sharp reader challenge. In 800-1,500 Chinese characters for a full article, establish product definition, industry tension, team credibility, key data, and the reason this conversation matters now.
5. **Reorganize by reader attention, not chronology or product completeness**: Group Q&A into 6-10 numbered sections (`## 01`, `## 02`, ...). Put early the material that explains why this founder/team/product belief exists: founder path, failure, pivot, non-consensus thesis, user validation, or the main challenge readers will naturally ask.
6. **Write judgment-style section titles**: Use titles that compress a claim, tension, or decision rule, not generic labels like `团队介绍` or `商业模式`.
7. **Edit Q&A for publication**: Preserve founder voice and first-person perspective, but remove repetition, filler, detours, and unclear logic. Merge fragmented answers when needed; split overlong answers when clarity improves. Follow the Q&A voice preservation rules below so answers remain alive, specific, and recognizably spoken by this founder.
8. **Add extractable golden sentences**: Bold short, memorable claims from the founder or editor when they crystallize the argument.
9. **Close with founder implications**: End around commercialization, moat, product route, team/organization, market timing, or what other founders can learn.
10. **Keep the intermediates**: If writing files, save all requested versions separately as Word documents by default, for example `_readable_codex.docx`, `_personal_codex.docx`, and `_geekpark_codex.docx`, so the user can compare facts against the cleaned transcript. Create Markdown files only when explicitly requested or as temporary internal drafts.

### Founder Interview Center Of Gravity

Before outlining a founder interview, choose the strongest narrative driver:

- **Person-driven founder judgment**: Use the founder's path, inflection points, prior explorations, and operating philosophy to explain why this product belief grew out of this person. Product details are evidence of judgment, not a checklist.
- **Organization/team-driven**: Use when the team's collaboration model, AI-native workflow, hiring bar, development speed, or pivot ability explains why the product can exist. Multi-person interviews may have the team judgment as the protagonist.
- **Challenge-driven**: Use when the product is controversial or counterintuitive. Start from the reader's likely doubts, then answer them through validation, technical route, form factor, business model, and moat.
- **Core abstraction / interaction paradigm-driven**: Use when the product introduces a strong new abstraction such as `只记录意图`, `视觉是操作系统`, `Agent 的躯体`, `上下文中心`. Structure the piece around why the old abstraction is insufficient and how the new abstraction changes product form.
- **Scene-contrast-driven**: Use when the product enters a category with a strong stereotype. Establish what the category usually does, then show why this team goes the other way, e.g. not a learning machine, not a tool, not full recording.
- **Product-first**: Use only when the user explicitly asks for product teardown, technical explainer, launch article, feature/architecture analysis, or when the product itself is the news hook and the founder path is thin.

For founder interviews, `人物感` does not only mean biography. It can come from founder history, team habits, product personality, taste, non-consensus choices, or a logic loop revealed under challenge. The key question is: why would this subject make this product choice?

### Founder Interview Selection Rules

Prioritize Q&A that:

1. Explains why the founder/team formed this judgment.
2. Turns product philosophy into a startup choice: battlefield, timing, route, moat, organization, commercialization, or risk.
3. Contains non-consensus views, weak consensus bets, pivots, failed attempts, user validation, or path-dependence corrections.
4. Preserves long-form founder reasoning and speech texture; do not over-compress every answer into short polished sentences.
5. Supports credibility with MVPs, real scenes, user interviews, benchmarks, revenue, financing, customers, team size, or usage data.
6. Responds to a reader challenge when the product looks counterintuitive.
7. Defines a new abstraction and explains why the old one is not enough.

Deprioritize Q&A that:

1. Only fills out a product feature list without advancing the main thesis.
2. Adds technical details that can be folded into a larger founder judgment.
3. Shows pure background biography unless it explains the current product belief, risk preference, operating style, or non-consensus view.
4. Describes a big end state without MVP validation, user behavior, concrete scene, or business route.
5. Lists hardware/model parameters without returning to user value, cost structure, trust, supply chain, compliance, or commercialization.

### Q&A Voice Preservation

For publishable Q&A, the goal is to help the founder say things more clearly in their own voice, not to replace them with a standard media voice.

Do:

1. Preserve reasoning chains: keep how the founder moved from attempt, observation, failure, correction, to current belief.
2. Keep useful spoken texture: words such as `其实`, `当时`, `后来`, `回头看`, `我们发现`, `我自己会觉得` can show thinking posture when used sparingly.
3. Preserve concrete scenes, time nodes, internal moments, user feedback, failed experiments, and rough but accurate original phrases. These details often create trust and `活人感`.
4. Allow core answers to be longer when the logic needs room. Mix long and short answers instead of making every answer equally polished and compact.
5. Keep distinctive founder phrases when they are accurate and vivid, even if they are less formal. For example, do not flatten a line like `自己做出来的产品，自己人都用不起来` into generic business language.
6. Expand answers slightly when the original logic is under-explained, but expand through the founder's existing examples and reasoning, not invented claims.

Avoid:

1. Turning every answer into conclusion-first consulting prose.
2. Removing all hedges, self-corrections, and reflective phrases; this can erase the sense of a person thinking in real time.
3. Converting specific scenes into abstract summaries, e.g. replacing MVP/user details with `验证了需求`.
4. Over-producing short golden sentences. Not every answer should sound like a quote card.
5. Translating vivid founder language into bland media language.

### Founder Interview Structure Patterns

Use these as starting shapes, not fixed templates:

- **Person-driven**: founder path -> inflection point -> battlefield choice -> product belief -> user/scene validation -> technology/moat -> commercialization/organization -> risk/advice.
- **Organization/team-driven**: failure or pivot -> organization changes first -> product changes because of the organization -> technical foundation -> growth/commercialization -> organization speed or pivot speed as moat.
- **Challenge-driven**: reader doubt -> proof that it is not just an idea -> core belief -> answers across value, technology, form factor, business model, and moat -> end-state judgment.
- **Core abstraction / interaction paradigm-driven**: external signal -> new abstraction definition -> old paradigm's limit -> mechanism and architecture -> user aha moment -> end state as entrance, infrastructure, or platform.
- **Scene-contrast-driven**: category stereotype -> opposing choice -> theory or founder experience behind it -> real user scene -> product form -> trust/cost/supply chain -> real moat.

Before finalizing, run a center-of-gravity audit:

- What is the protagonist: founder, team, product personality, technical route, new abstraction, scene contrast, or a challenged non-consensus bet?
- Does the first third explain why this subject thinks this way, why now, and what choice other founders can learn from?
- Are the selected Q&A blocks revealing the founder's logic, or merely filling in product modules?
- If there is a strong abstraction, does the whole piece orbit that abstraction instead of drifting into a feature list?
- If there is strong validation, are MVP/user data/benchmark/revenue/external scenes placed early enough to make the belief credible?
- Does the ending return to a founder decision: battlefield, product route, moat, organization, commercialization, timing, or failure risk?

## Editing Rules

### Error Correction
- Fix homophone errors common in ASR (e.g., 在→再, 做→作, 的→地/得).
- Correct proper nouns: person names, place names, brand names, technical terms. Mark uncertain items with `[待核实]`.
- Normalize numbers and units: use Arabic numerals + Chinese units (e.g., 3 公里, 50%, 200 万).
- Correct foreign abbreviations and acronyms (e.g., AI, GPU, API).

### Punctuation & Formatting
- Use standard modern Chinese punctuation: `，。！？；：「」『』……《》（）`.
- Prefer `，` within clauses, `。` at sentence ends.
- Use traditional Chinese corner quotes for all Chinese copy: single quotes use `「」`; double or nested quotes use `『』`.
- Convert straight quotes `"..."`, `'...'`, and curly English quotes into `「」` or `『』`, unless they are part of code, file names, URLs, or literal technical syntax.
- Avoid em dashes unless structurally necessary. Prefer commas, colons, semicolons, or sentence breaks.
- Place a space between Chinese and English / numbers (e.g., 使用 AI 技术).

### Speaker Labels
- If the source contains speaker tags (主持人 / 嘉宾 / names), preserve and normalize them.
- Format: `**张三：**` (bold name + Chinese colon) at the start of each speaker turn.
- Group consecutive utterances by the same speaker into one block.

### Spoken → Written Conversion
- Remove pure fillers: 呃、嗯、那个、就是、就是说、然后、对对对、反正、OK 那.
- Collapse stammers and repetitions into clean phrasing.
- Keep characteristic expressions that reflect speaker personality; do not over-formalize.
- Preserve rhetorical questions, humor, and emphasis that carry meaning.

### Paragraph Structure
- One topic per paragraph; insert a blank line between paragraphs.
- Keep paragraphs under ~200 characters for readability.
- Maintain chronological or logical order of the conversation.

### Content Integrity
- Never add information not present in the original.
- Never delete substantive content; only remove redundant fillers.
- If a passage is ambiguous, keep it close to the original wording and add `[待核实]` if needed.

## Output Format

For Stage 1, output a single clean document with the header `【中文可读版】`, followed by the polished text in paragraphs:

```
【中文可读版】

**主持人：** 大家好，我是张三。今天我们来讨论一下 AI 应用。

**嘉宾：** 谢谢邀请。我认为 AI 在未来 3 到 5 年会深刻改变内容创作行业。
```

Do NOT include timecodes, SRT sequence numbers, or any subtitle formatting in the output.

For Stage 2, output a working transcript with the header `【个人使用版】`. Keep useful timestamps or section ranges, speaker turns, technical details, scenes, and optional `（概览/总结）` blocks for long single-topic discussions.

Only when explicitly requested, output Stage 3 as a publishable interview article with the header `【极客公园版本】` and:

1. A clear title or 5-10 title candidates if the title is not fixed.
2. An editor lead before the Q&A.
3. `以下是极客公园与 XXX 的对话，经编辑整理。`
4. Numbered sections using `## 01`, `## 02`, ...
5. Judgment-style section titles.
6. Q&A blocks using `**问：**` and `**答：**`. Do not label the interviewer as `Founder Park` or `极客公园` inside Q&A turns.

Avoid importing newsletter/footer clutter such as `更多阅读`, `继续滑动`, QR-code copy, tracking images, or placeholder images.

Before delivering Stage 3, run a punctuation pass: convert Chinese-prose quotes to `「」`/`『』`, and replace unnecessary em dashes with commas, colons, semicolons, or sentence breaks.

## Example

**Input:**
```
00:00:01,200 --> 00:00:04,300
呃 大家好 我是那个张三呃今天我们来 讨 讨论一下AI呃 应用

00:00:05,000 --> 00:00:09,500
嗯 对 那个 我觉得就是说AI在未来的话 那个3到5年吧 会那个深刻改变那个内容创作行业
```

**Output:**
```
【中文可读版】

大家好，我是张三。今天我们来讨论一下 AI 应用。

我觉得 AI 在未来 3 到 5 年会深刻改变内容创作行业。
```

## Processing Long Transcripts

### Short transcripts (< 8,000 characters)

Process in a single pass using the standard workflow above.

### Long transcripts (8,000–50,000+ characters)

Use the following multi-phase approach. The key principle: **scan first, edit second, reconcile last.**

#### Phase 0 — Preparation

1. Ask the user for the output path when needed. Default to sibling Word files with `_codex` before the extension: `_readable_codex.docx` for Stage 1 and `_personal_codex.docx` for Stage 2. Create `_geekpark_codex.docx` only when the user explicitly requests Stage 3 / FP / Founder Park / 极客公园 output. Create Markdown files only if the user explicitly asks for them or if they are temporary drafts used to build the Word documents.
2. Determine total character count of the source file.
3. Estimate the number of segments needed (target ~3,000–5,000 chars per segment).

#### Phase 1 — Scan & Index

Read through the entire transcript quickly (without editing) to build:

- **Speaker list**: All identified speakers and their normalized labels.
- **Terminology glossary**: Proper nouns, brand names, technical terms, abbreviations encountered. Record the chosen standard form for each (e.g., `寻影 → 寻影科技`). Mark uncertain terms with `[待核实]`.
- **Topic outline**: List major topic shifts with approximate positions (line numbers or percentage). This will guide segmentation.

Write the glossary and topic outline as a comment block at the top of the Stage 1 output file for reference:

```markdown
<!-- 术语表
寻影 → 寻影科技
Founder Park / FP → 极客公园（触发词；输出版本仍命名为 `【极客公园版本】`）
...
-->
<!-- 话题大纲
1. 开场介绍 (0%-5%)
2. 产品定位 (5%-20%)
3. 技术架构 (20%-45%)
...
-->
```

#### Phase 2 — Segment & Edit

1. **Segment by topic boundaries** identified in Phase 1, not by fixed character count. Each segment should cover one coherent topic block (~3,000–5,000 chars of source text). Prefer splitting at speaker turns or natural pauses.
2. **Process each segment** following the standard workflow (pre-process → proofread → polish → trim → review).
3. **Context bridging**: Before editing each segment, re-read the last 2–3 paragraphs of already-edited output to maintain tone, terminology, and flow.
4. **Append incrementally**: Write each finished segment to the output file immediately after completion. This prevents data loss if the process is interrupted.
5. **Reference the glossary** from Phase 1 to ensure consistent terminology throughout.

#### Phase 3 — Reconcile & Final Review

After all Stage 1 segments are processed:

1. **Speaker label audit**: Verify all speaker labels are consistent (no `张总` in one place and `张三` in another unless intentional).
2. **Terminology audit**: Grep the output for all glossary terms; confirm uniform usage.
3. **Transition smoothness**: Review the boundaries between segments — ensure no abrupt jumps, repeated introductions, or lost context.
4. **Remove the comment block** (glossary + outline) from the top of the file, or keep it if the user wants it as metadata.

#### Phase 4 — Personal-use Reshape and Optional Interview Reshape

Run the personal-use reshape by default after Stage 1. Run the 极客公园 reshape only when the user requests FP/Founder Park/极客公园/访谈稿/对话稿/成稿/发表/公众号 output.

1. Re-read the full `【中文可读版】`, glossary, and topic outline.
2. For `【个人使用版】`, restore useful timeline markers, speaker turns, technical density, demo/operation details, and overview blocks where appropriate.
3. For optional `【极客公园版本】`, choose the article center of gravity before outlining: person, team/organization, challenge, core abstraction, scene contrast, or product-first.
4. Create an article outline with 6-10 sections. Each section should answer a founder-facing question: product route, technology route, user insight, commercialization, team, moat, growth, market timing, or founder judgment.
5. Draft the editor lead before the Q&A. Use first-hand details from the interview instead of generic industry commentary. For challenge-driven pieces, surface the reader's doubt early; for validation-driven pieces, place MVP/user data/benchmark/revenue early.
6. Move Q&A blocks into the new section order. Preserve meaning; do not invent transitions or claims.
7. Add section titles that read like judgments, for example `纯记录 Context 工具卖不出钱，AI 产品必须能交付结果` or `硬件只是商业化的第一步，核心是成为人和 AI 世界之间的中枢`.
8. Remove raw transcript residue, repeated questions, accidental duplicate answers, and publication clutter.
9. Run the center-of-gravity audit above, then compare high-risk claims and all numbers against the Stage 1 readable transcript.

#### Handling interruptions

If the process is interrupted mid-way:
- The Stage 1 output file already contains all completed readable segments.
- Resume by identifying the last completed segment, re-reading its final paragraphs for context, and continuing from the next source segment.
- Note which segment number to resume from in a comment at the end of the Stage 1 output file: `<!-- 待续：从第 N 段继续 -->`.
- If Stage 2 was interrupted, resume from the last completed timestamp range or speaker turn in `_personal_codex.docx` or its temporary draft, then re-check chronology against `_readable_codex.docx`.
- If Stage 3 was interrupted, resume from the article outline and completed sections in `_geekpark_codex.docx` or its temporary draft, then re-check facts against `_readable_codex.docx`.
