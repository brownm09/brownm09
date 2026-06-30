# Claude Code — brownm09 (GitHub Profile)

Project-specific instructions for the `brownm09` GitHub profile repo. These extend the global
conventions in `~/.claude/CLAUDE.md`; they do not repeat them.

## Writing Style

All portfolio documents (READMEs, architecture write-ups, project descriptions) must follow:

- **Precise and substantive.** No filler. No em-dashes.
- **Practitioner voice, not consultant voice.** Documents should read like they came from someone who built the thing, not a methodology deck.
- **Understated confidence.** The work speaks for itself.
- **Specifics over adjectives.** No adjectives doing work that a fact or number should do.
- **READMEs explain architectural tradeoffs and "why this exists,"** not just what it is.

**Self-check:** Does this sentence use an adjective where a specific fact or number would be more convincing? Are there em-dashes? Does it sound like a methodology deck? If yes, rewrite.

Ask clarifying questions before drafting documents that require details only Mike would know (DR fire drill specifics, on-call structure). Generic frameworks (PCI checklist, CI/CD guide) can be drafted with less input.

## Testing

This is a content repository (profile README and portfolio documents) with no automated test suite. Verify changes manually before opening a PR:

- The README and any edited markdown render correctly on GitHub (no broken tables, headings, or code fences).
- All links resolve (LinkedIn, referenced repos, internal anchors).
- Content satisfies the Writing Style self-check above.

State what was verified in the PR body in place of a test-summary line.

## Observability

No runtime to instrument. The equivalent verification is reference integrity: links resolve, referenced repos/files exist, and contact details match the canonical bio. Note any link/reference check performed in the PR body.
