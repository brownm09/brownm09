# Token Efficiency Notes: Portfolio Build Session

This documents the token usage patterns observed during the GitHub portfolio build
(brownm09, engineering-playbooks, aws-platform-demo, incident-summarizer, ops-scripts)
and answers the questions:

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
| incident-summarizer (21 Python files, README, config) | ~1,750 |
| ops-scripts (7 Python files, shared lib, config) | ~1,000 |
| Conversational responses | ~700 |
| README files | ~450 |
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

## Per-Session and Per-Invocation Cost Estimates

### Claude Code sessions (you as the developer)

Model: claude-sonnet-4-6 ($3/M input, $15/M output)

| Session | Estimated input tokens | Estimated output tokens | Estimated cost |
|---|---|---|---|
| Session 1: brownm09 + engineering-playbooks + aws-platform-demo | ~35,000 | ~14,000 | ~$0.32 |
| Session 2: incident-summarizer (context-compacted continuation) | ~24,000 | ~7,000 | ~$0.18 |
| Session 3: ops-scripts | ~22,000 | ~5,000 | ~$0.14 |
| **Total (all sessions)** | **~81,000** | **~26,000** | **~$0.64** |

These are estimates from counting output lines and reasoning about context size. Use
`usage_report.py` with your admin key for actuals.

Session 2 was cheaper than session 1 despite similar output volume because:
- Context compaction reduced the inherited history to a dense summary (~3,500 tokens)
  rather than raw conversation (~20,000+ tokens)
- The skill document (claude-api) dominated input cost for session 2, not the
  conversation history

### incident-summarizer tool (per invocation, claude-opus-4-6)

Pricing: $5/M input, $25/M output, cache write $6.25/M, cache read $0.50/M

Adaptive thinking tokens are billed as **output** tokens. Actual thinking volume
varies by incident complexity — more ambiguous data → more thinking.

| Component | Tokens | First call | Cached call |
|---|---|---|---|
| System prompt (cache write → read) | ~700 | $0.0044 | $0.00035 |
| Incident payload (non-cached, varies) | ~1,500-3,000 | $0.008-0.015 | same |
| Adaptive thinking (output, varies) | ~500-3,000 | $0.013-0.075 | same |
| IncidentSummary output | ~700 | $0.018 | same |
| **Total per call estimate** | | **$0.04-0.11** | **$0.035-0.11** |

Thinking is the main cost variable. A well-structured Jira or PagerDuty incident with
clean fields triggers minimal thinking. A vague plain-text description triggers more.
To observe actual thinking volume: print `response.usage` from `summarizer.py`.

Cache hits save ~$0.004 per call — meaningful at scale (1,000 calls/month = ~$4 saved),
negligible for occasional use. The 5-minute ephemeral cache window means consecutive
calls in a batch pipeline benefit; isolated one-off invocations do not.

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

---

## How to Realize These Savings

### Fix the gh CLI PATH permanently

One-time setup. Adds `gh` to your system PATH so Claude Code's bash environment finds
it without a full path lookup.

**Windows (PowerShell, run once):**
```powershell
$ghPath = "C:\Program Files\GitHub CLI"
[Environment]::SetEnvironmentVariable(
    "Path",
    [Environment]::GetEnvironmentVariable("Path", "Machine") + ";$ghPath",
    "Machine"
)
```
Restart your terminal after. Eliminates the diagnostic turns that opened this session.

---

### Trigger parallel subagents explicitly

Claude Code runs subagents in parallel when multiple Agent tool calls appear in a
single response. The way to get this is to ask for it directly.

**Instead of:**
> "Build the engineering-playbooks repo."
> [wait]
> "Now build aws-platform-demo."

**Say:**
> "Build engineering-playbooks and aws-platform-demo in parallel. Use a subagent for each."

Claude Code will spawn both agents simultaneously. Wall-clock time drops to roughly
the duration of the slower task rather than the sum of both.

For code generation specifically, the phrase "use a subagent" or "delegate this to an
agent" tells Claude to isolate the work. The generated files will not accumulate in
the main conversation context.

---

### Start a new conversation when context is large

Claude Code compresses old messages automatically, but the pre-compression context
still costs input tokens. When you finish a logical unit of work (one repo, one set
of docs), starting a fresh conversation resets the input context to near zero.

The memory system persists across conversations, so nothing is lost. The new session
picks up project state from the memory files on the first turn.

**Rule of thumb:** start a new conversation after each repo or after any session
exceeding ~15 substantive turns.

---

### Check cost mid-session

Run `/cost` in Claude Code at any point to see the running token and dollar total
for the current session. Useful for calibrating when a conversation has grown expensive
enough to warrant starting fresh.

---

### Prompt caching (direct API use only)

Claude Code handles system prompt caching internally. If you build tooling that calls
the Anthropic API directly (e.g., the `incident-summarizer` repo), you can add cache
breakpoints to reduce repeated input costs.

Add `cache_control` to any content block you want cached:

```python
import anthropic

client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    system=[
        {
            "type": "text",
            "text": "Your long system prompt here...",
            "cache_control": {"type": "ephemeral"},  # cache this block
        }
    ],
    messages=[{"role": "user", "content": "User message"}],
)

# Check what was cached vs billed fresh
print(response.usage.cache_creation_input_tokens)  # tokens written to cache
print(response.usage.cache_read_input_tokens)       # tokens read from cache (10% price)
print(response.usage.input_tokens)                  # uncached tokens (full price)
```

Cache lifetime is 5 minutes (ephemeral). Use this for:
- Long system prompts that repeat across calls
- Reference documents you feed on every request
- Conversation history beyond the first few turns in a multi-turn loop

Not applicable to Claude Code sessions directly — the harness manages this for you.

---

### Terraform: refactor multi-region with for_each

The current `environments/prod/main.tf` in aws-platform-demo duplicates all module
calls for primary and secondary regions. Refactoring to `for_each` over a region map
reduces config size, eliminates copy-paste drift, and would have generated fewer
output tokens.

Replace the duplicated blocks with:

```hcl
locals {
  regions = {
    primary = {
      name            = "us-east-1"
      cidr            = "10.0.0.0/16"
      azs             = ["us-east-1a", "us-east-1b", "us-east-1c"]
      public_subnets  = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
      private_subnets = ["10.0.10.0/24", "10.0.11.0/24", "10.0.12.0/24"]
    }
    secondary = {
      name            = "us-west-2"
      cidr            = "10.1.0.0/16"
      azs             = ["us-west-2a", "us-west-2b", "us-west-2c"]
      public_subnets  = ["10.1.1.0/24", "10.1.2.0/24", "10.1.3.0/24"]
      private_subnets = ["10.1.10.0/24", "10.1.11.0/24", "10.1.12.0/24"]
    }
  }
}

module "vpc" {
  source   = "../../modules/vpc"
  for_each = local.regions

  name            = "${var.name}-${each.key}"
  cidr            = each.value.cidr
  azs             = each.value.azs
  public_subnets  = each.value.public_subnets
  private_subnets = each.value.private_subnets
  tags            = local.common_tags
}
```

Repeat the pattern for each module. Reference outputs as `module.vpc["primary"].vpc_id`
and `module.vpc["secondary"].vpc_id`.

**Limitation:** Terraform `for_each` on modules does not support provider aliases per
iteration. You cannot dynamically assign `providers = { aws = aws.primary }` based on
the map key. Workarounds:
- Use a single provider with `alias` and accept that both regions use the same provider
  config (works if credentials are global, which they are for most AWS setups)
- Use Terragrunt, which handles multi-region provider injection more cleanly
- Keep explicit duplication (current approach) — verbose but unambiguous

The explicit duplication in the current demo is intentional for readability. For a
production codebase where you might add a third region, the `for_each` pattern plus
Terragrunt is the right investment.
