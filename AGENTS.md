# AI Assistant Guidelines

Identify the authoritative section for a topic before editing and avoid
duplicating its content elsewhere.

## Voice

- Expansive and professional, without undue praise or congratulatory remarks
- Use engineering precision with no banter
- Avoid trite corporate language, like production ready, maintain focus 
- Specific and actionable, with critique and suggestions, tradeoffs and alternatives
- Explain "why" with specific "how" details
- No time, duration, or schedule estimates, unless specifically requested
- Use concise, direct confirmations for simple fact or capability questions; answer in one sentence when feasible, with the explicit values
- No concluding cheer or redundant summary

## Design and Updates

- Suggest improvements
- Explain operations
- Note Architecture
- Alert breaking changes
- Update documentation

## Editing

- Update TOC if present
- Preserve existing content; do NOT delete details and references, unless so instructed
- Do NOT run destructive file, directory, content operations without an explicit confirmation or an allow rule
- Avoid emojis unless explicitly requested

## Markdown

- ATX headers (`#`, `##`)
- Use 1. and 1.2 numbering for consistent references
- No commentary, status, dates, or parenthetical qualifications in section or
  subsection titles
- Use concise Title Case noun phrases for section and subsection titles
- Capitalize principal words and Codess entity names; lowercase short articles, conjunctions, and prepositions unless they begin or end the title
- Code blocks may specify language like bash or python

## Code Comments

- State the durable fact, not the history: what the code does and why it must, not what
  it used to do, what a rejected approach would have done, or which review found it
- Do NOT cite work-item identifiers (`W54`, `W12`); completed items are removed from
  CoPlan, so the reference resolves to nothing for a later reader
- Keep measured evidence that justifies a constant or a mapping; drop the narrative around it
- Wrap to the configured line length, not to 80; service calls like `log.warning` belong
  on one line and may extend to 120
- A comment restating the line below it is noise; delete it

## Security

- Identify security issues in system operation, code or documentation
- Document required access permissions and policies, but be mindful of OpSec
- NEVER hardcode credentials, warn before adding or committing to a repo files with keys and passwords

## Git

- Do NOT commit to git, add, rename or remove files, push or pull unless explicitly instructed
- Commit message: present-tense imperative, focus on operational and functional changes
