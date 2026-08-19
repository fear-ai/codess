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
  the task list, so the reference resolves to nothing for a later reader
- Keep measured evidence that justifies a constant or a mapping; drop the narrative around it
- Wrap to at least 80 characters, up to 120 where keeping a call on one line needs it;
  do not wrap narrower than 80
- A comment restating the line below it is noise; delete it

## Code Naming

Applies to Python identifiers. Domain designators -- vendors, columns, keys --
are [CoNames](CoNames.md); this is how the code spells things.

- A parameter never reuses the name of a module-level function or constant in the
  same file. Nothing in ruff detects this and mypy does, so run it.
- A local never rebinds a parameter or an earlier local to a value of a different
  type. Introduce a second name instead: both stay readable, and the type checker
  keeps its grip on each.
- Where a local derives from a multi-word parameter, shorten to the **subject**,
  which is usually the last word rather than the first: `raw_records` and
  `raw_store` become `records` and `store`, because `raw` qualifies them and is
  not what they are. Measured over this codebase, the subject word resolves all 47
  functions whose parameters would otherwise collide.
- Scope decides whether a general single word is acceptable. A **local** may be
  `path`, `file`, or `records` -- it is read within a few lines of its binding, and
  the qualifier is redundant there. A **field, attribute, or parameter** may not:
  it is read far from where it was set, so `ChildInvocation.source` became
  `vendor_selector` because Codess has a Source entity and the field held neither.
  Measured: 309 of 725 multi-word parameters end in a general word, so this rule
  is about where the name is read rather than about the word itself.
- Prefer a qualifier that states the value's **role** over one that states its
  container or type: `redaction_roots`, not `roots_dict`. Measured across 6,310
  installed third-party files, role qualifiers outnumber PEP 8's trailing
  underscore 4,977 to 109, and the standard library agrees (`parser_class`,
  `action_class`).
- Reserve the trailing underscore (`type_`) for the case a qualifier cannot
  express: a parameter that genuinely is the builtin's subject.
- Do NOT introduce a second case style to separate locals from parameters. PEP 8
  fixes one style for the language, and the hazard is a name that does not say
  what the value is for, which a case convention does not address.

## Environment Separation

The repository must not disclose the machine it was developed on. Nothing in
released documentation, source, or tests may carry an operator's account name,
host name, home directory layout, or the names of their repositories,
employers, clients, or private projects.

- **Ship empty, discover at runtime.** Any list describing one machine's tree
  -- grouping directories, review or vendored trees, excluded locations --
  defaults to empty and is supplied by an environment variable. A shipped
  default derived from one tree silently misclassifies directories on every
  other machine, and the operator cannot see why.
- **Documentation states the rule, never the instance.** Where a real path
  motivated a decision, describe the shape that caused it: a directory name
  containing the separator character, a container holding many repositories.
  A reader on another machine can check a rule and cannot check a path.
- **Examples are synthetic and obviously so.** Use placeholder segments
  (`<user>`, `<project>`, `/home/user/work`) rather than plausible real names,
  so a reader cannot mistake an example for a required value.
- **Measurements may keep their shape and lose their identity.** A corpus
  table establishes vendor coverage and scale; label rows by shape or with
  stable anonymous identifiers. The name adds nothing a reader can verify.
- **Tests assert the mechanism, not a layout.** A test naming a real
  directory tests that machine. Configure the input explicitly and assert the
  rule -- which segment matched, whether position mattered.
- **Operator state stays out of version control.** Reviewed selections,
  policies, and catalogs that name real locations are local data. If a
  workflow needs them committed, the location is a placeholder resolved from
  configuration at load.
- **Third-party projects are citable; private ones are not.** A published
  tool evaluated as an integration candidate is verifiable by any reader. A
  private repository is not, so its role belongs in developer notes under
  `experiments/`, with the released text carrying the requirement and the
  evidence.

## Security

- Identify security issues in system operation, code or documentation
- Document required access permissions and policies, but be mindful of OpSec
- NEVER hardcode credentials, warn before adding or committing to a repo files with keys and passwords

## Git

- Do NOT commit to git, add, rename or remove files, push or pull unless explicitly instructed
- Commit message: present-tense imperative, focus on operational and functional changes
- NEVER discard uncommitted work: `checkout --`, `restore`, `reset --hard`, and
  `clean` destroy changes that exist nowhere else, including changes made
  earlier in the same session that the operator has not reviewed
- To undo an edit, edit forward, or copy the file aside first and restore from
  that copy. `stash` is acceptable as temporary storage because it is
  recoverable; a discard is not
- When a restore is unavoidable, name the specific files. A path argument
  (`checkout -- src`) reverts every uncommitted change beneath it, not the one
  that was wrong
- Read-only inspection (`status`, `log`, `diff`, `show`, `reflog`) needs no
  instruction
