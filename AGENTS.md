# AI Assistant Guidelines

Identify the authoritative section for a topic before editing and avoid
duplicating its content elsewhere.

## Voice

- Expansive and professional, without undue praise or congratulatory remarks
- Use engineering precision with no banter
- Avoid trite corporate language, like production ready, maintain focus 
- Specific and actionable, with critique and suggestions, tradeoffs and alternatives
- Recommend with justification: present alternatives as analysis leading to a recommendation, not as
  a menu, and stage measures to observed issues rather than hypothetical ones
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
- Hold to the stated goal; a finding outside it becomes a work item, not work
- Verify before asserting: compare names, paths, and counts mechanically rather than by reading;
  name each entity involved and its state (exists, does not exist, will be recreated) before
  reasoning about moves or collisions; design each check so it can fail, and report contrary output

## Work Items

- `CoTasks.md` is the only list of open project work; its introduction states the identifier,
  removal, and four-part item conventions
- Verify an item's own evidence before implementing it, and correct the item's text when its
  framing is wrong rather than silently implementing something else
- For decoding or storage work, the completion bar is a real re-ingest checked with
  `tools/decode_audit.py` and `tools/field_coverage.py --fail-on-gap`, not passing tests; a new
  single-vendor column gap needs a `schema/field-coverage-baseline.json` entry with checked evidence
- An item states the durable outcome and the findings that changed the work, not the process

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

## Documentation Tiers

- **Released documents** -- README, Operations, Codess, the Co*.md set, the
  vendor schema documents, Designs, Report, CHANGELOG, and `experiments/` --
  serve daily operators and developers adapting or contributing to Codess. They
  state durable facts: how the system works, why, and what is open.
- **Internal notes** live in `.docs/`, which is ignored: review ledgers, working
  analysis, measurements that name one machine, and repository and publication
  plans. A released document never links into `.docs/`.
- **Project work and repository work are separate tracks.** CoTasks lists
  functionality and documentation work. Commits, history rewriting, merging, and
  publication are tracked in `.docs/codess-git.md`, not in any released
  document or task list.
- **No transient history in persistent documents.** Omit which session, commit,
  or push produced a change, pass/fail tallies of a particular run, and
  step-by-step narrative. State the outcome and the evidence that still holds.

## Code Comments

- State the durable fact, not the history: what the code does and why it must, not what
  it used to do, what a rejected approach would have done, or which review found it
- Do NOT cite work-item identifiers (`W54`, `W12`); completed items are removed from
  the task list, so the reference resolves to nothing for a later reader
- Keep measured evidence that justifies a constant or a mapping; drop the narrative around it
- Wrap to at least 80 characters and at most 110, the `line-length` in `pyproject.toml`;
  do not wrap narrower than 80
- A comment restating the line below it is noise; delete it

## Operator Messages

Applies to error messages, log lines, and progress events. Not to documentation,
where a reader is looking for explanation.

- State the observation and the action. Omit the explanation a reader did not
  ask for: every error is met while something is already wrong
- Put the values first and the remedy last, so the line reads as a fact followed
  by what to do about it
- The reason a rule exists belongs in a comment beside the message, where a
  maintainer needs it, rather than in the message, where an operator does not

Worked example, from the DDL version check. Before -- four lines, two of them
explanation a reader did not ask for:

```text
released DDL stamps user_version 6 while the declared CoSchema format is 7;
update schema.sql to match
```

After -- the same two facts and the same action:

```text
DDL user_version 6, declared CoSchema 7: update schema.sql
```

## Code Naming

The glossary in `Codess.md` is the terminology authority, and `CoNames.md` holds every settled
name: check a proposed rename against it and add the row in the same change.

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
  private repository is not, so released text describes its role by shape ("a
  sibling project by the same author", "an operator fork") and never by name,
  path, or origin URL. `experiments/` is tracked and released, so this section
  applies to it in full; material that must name private work goes in `.docs/`.
- **Host names and encoded forms count as disclosure.** A vendor URI embeds the
  machine: a Cursor `vscode-remote://ssh-remote%2B<hex>` authority is
  hex-encoded JSON carrying `hostName`, a Claude slug directory
  (`-Users-<user>-...`) encodes a home path, and percent-encoded or base64 values
  decode to the same thing. Scrub the decoded meaning, not only the visible
  text, and encode a synthetic example from a synthetic value
  (`{"hostName":"remote-host"}`) so decoding it shows the placeholder.
- **Identifiers from real data are replaced, not truncated.** Session, bubble,
  and tool-call UUIDs, git origins, and hexdumps taken from a real store become
  obviously synthetic values (`11111111-2222-4333-8444-555555555555`), with
  offsets and length bytes kept consistent so the example still teaches the
  format.
- **Vendor-schema documents describe the vendor's layout, not the operator's.**
  CCSchema, CodexSchema, and CursorSchema show vendor paths with placeholder
  segments (`~/.claude/projects/<slug>/<session>.jsonl`,
  `/home/user/work/<project>`). A measured count states its scale and nothing
  that identifies the machine.
- **Ignoring is not removing.** Listing a tracked file in `.gitignore` leaves it
  in the tree and in history; removal is repository work (see Git).

## Delegation to Agents

- At most three agents run at once, and none starts agents of its own: all share one usage limit,
  and a burst that exhausts it stops every agent mid-task
- Give each editing agent a disjoint set of files; read-only agents may overlap
- Each agent appends a checkpoint after every finished step -- step, files changed, result -- to
  `.agents/<task>/<agent>.md`, which is ignored, so an interrupted task resumes from the last step
- Resume a stopped agent by messaging it rather than starting a fresh one, which loses its context
- Verify an agent's factual claims before they enter a released document

## Security

- Identify security issues in system operation, code or documentation
- Document required access permissions and policies, but be mindful of OpSec
- NEVER hardcode credentials, warn before adding or committing to a repo files with keys and passwords

## Git

- Do NOT commit to git, add, rename or remove files, push or pull unless explicitly instructed
- Keep repository work apart from project work: plan and record it in `.docs/codess-git.md`,
  and do not mix commit, history, or publication steps into a functionality or documentation change
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
