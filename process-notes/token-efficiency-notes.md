# Token Efficiency Notes: Portfolio Build Session

This documents the token usage patterns observed during the GitHub portfolio build
(brownm09, engineering-playbooks, aws-platform-demo) and answers the questions:

- What is the average spend for these operations?
- Why was spend what it was?
- Which operations were most expensive?
- Where could the most tokens have been saved?
- Where could the most time have been saved?

Use `usage_report.py` in this directory to pull actual figures from the Anthropic Admin API.

---

## Getting Actual Numbers

```bash
pip install requests
export ANTHROPIC_ADMIN_KEY=sk-ant-admin-...

# Show the session date range
python process-notes/usage_report.py --start 2026-03-27 --end 2026-03-28

# Hourly breakdown to see which part of the session was heaviest
python process-notes/usage_report.py --start 2026-03-27 --end 2026-03-28 --bucket 1h

# Raw JSON for your own analysis
python process-notes/usage_report.py --start 2026-03-27 --end 2026-03-28 --json | jq .
```

Admin keys are created at: https://console.anthropic.com -> Settings -> Admin Keys

For a quick in-session estimate without an Admin key, run `/cost` in Claude Code.

---

## What Drove Spend in This Session

### Output tokens dominated

The session produced approximately 5,500+ lines of generated text across:

| Output | Approximate lines |
|--------|------------------|
| aws-platform-demo (34 Terraform/YAML/Python files) | ~1,650 |
| engineering-playbooks (5 markdown documents) | ~1,100 |
| Conversational responses | ~500 |
| README files | ~300 |
| This file + usage_report.py | ~250 |

Output tokens cost 5x input tokens on Claude Sonnet 4.6 ($15/M vs $3/M). Sessions
heavy on code generation are output-token-dominated and cost proportionally more than
research or Q&A sessions.

### Input tokens accumulated with conversation length

Every turn re-sends the full conversation history. By the end of a session with 20+
turns and large file reads mixed in, input token counts per turn are substantially
higher than at the start. The memory files (MEMORY.md, user_profile.md, etc.) also
load on every turn.

### No prompt caching was explicitly used

The Anthropic API supports prompt caching for repeated content (system prompts,
long documents). This session did not use cache breakpoints, so repeated context
(memory files, growing conversation history) was re-billed at full input price each turn.

---

## Most Expensive Operations

In rough order:

1. **aws-platform-demo Terraform generation** — 34 files written in a single session.
   The ECS cluster module alone (~180 lines) and the prod environment main.tf (~170 lines)
   were each large output bursts. This is the single most expensive block of the session.

2. **engineering-playbooks document generation** — Five long-form markdown documents.
   The PCI-DSS checklist and on-call restructuring framework were each 200+ lines.

3. **Late-session conversational turns** — By turn 15+, the conversation history sent
   as input context was large. Even short responses had high input token counts.

4. **File reads during planning** — Reading memory files, checking git remotes, and
   verifying directory structure each added input tokens without contributing output.

---

## Where the Most Tokens Could Have Been Saved

### 1. Subagent isolation for large code generation

The Terraform repo (~1,650 lines) was generated in the main conversation context. Using
an Agent subagent for this task would have isolated the output from the main context
window. The subagent's output would still cost the same tokens, but the main conversation
would not carry the generated code in its history for subsequent turns.

Estimated savings: moderate — reduces input token growth in later turns.

### 2. Prompt caching on memory and system content

The memory files (user profile, project portfolio, feedback style) load on every turn.
Adding cache breakpoints to the system prompt and memory block would reduce repeated
billing for this content to 10% of standard input price after the first turn.

Estimated savings on a long session: meaningful — memory files are ~500-800 tokens
re-billed every turn.

### 3. Shorter clarifying rounds

The questions-before-drafting approach (fire drill, on-call, aws-platform-demo) was
correct for document quality. But some rounds had more back-and-forth than necessary.
Sending all questions in one turn instead of iterating would have compressed several
multi-turn exchanges into fewer turns with less accumulated history.

### 4. Batching file writes via a single agent call

Sequential file writes each trigger a tool use round-trip. Writing all files for a
given repo via a subagent in one call would reduce the number of turns in the main
context and trim input token growth.

---

## Where the Most Time Could Have Been Saved

### 1. Parallel subagent execution for independent repos

engineering-playbooks and aws-platform-demo were built sequentially. They share no
dependencies. Running two subagents in parallel (one per repo) would halve the wall-clock
time for that portion of the session.

### 2. gh CLI path resolution

The first attempt to use `gh` failed because the binary was not on the bash PATH.
Resolving this upfront (either by finding the binary path or adding it to PATH) would
have saved two diagnostic turns at the start.

### 3. Template reuse across regions

The aws-platform-demo prod environment duplicates module calls for primary and secondary
regions. Using Terraform `for_each` over a region map would reduce the config size and
the time spent writing the secondary block. It was written as explicit repetition for
readability, which is a reasonable tradeoff in a demo context but is slower to generate.

---

## Rule of Thumb for Future Sessions

| Operation type | Relative cost | Mitigation |
|----------------|--------------|------------|
| Long-form doc generation (per doc) | Medium | Batch questions; draft in one pass |
| Large code generation (per repo) | High | Use subagent; isolate from main context |
| Conversational Q&A | Low | Fine as-is |
| Late-session turns with long history | Medium-high | Subagents reduce context bleed |
| File reads for planning | Low-medium | Read only what is needed |

The highest-leverage habit change for cost reduction: **use subagents for any code
generation task producing more than ~200 lines**, so that output does not accumulate
in the main context window.
