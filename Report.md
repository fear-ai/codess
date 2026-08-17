# Report

Report is the design for Codess operational reporting: tracing, logging,
errors and warnings, counters, benchmarks, and summaries. It states the
problems, the measurements that constrain any solution, the requirements
those imply, and a partitioned set of designs that satisfy them.

CoPlan [9.6.1](CoPlan.md#961-future-logging-task) states the event contract,
[9.6.2](CoPlan.md#962-what-w18-must-cover-beyond-status-and-errors) the scope
beyond status and errors, and
[9.6.3](CoPlan.md#963-reporting-architecture) the primitives. This document
is the engineering design under those, and is the authority for structure,
cost, and lifecycle. Where it disagrees with a sketch in CoPlan, this is
current and CoPlan should be corrected to match.

## Table of Contents

1. [Problem Statements](#1-problem-statements)
1. [Measurements](#2-measurements)
1. [Requirements](#3-requirements)
1. [Design Partition](#4-design-partition)
1. [Event Structure](#5-event-structure)
1. [Capability Detection and Limits](#6-capability-detection-and-limits)
1. [Time Sources](#7-time-sources)
1. [Buffering and Flush](#8-buffering-and-flush)
1. [Pre-Initialization](#9-pre-initialization)
1. [Backends](#10-backends)
1. [Use Profiles](#11-use-profiles)
1. [Adoption and Sequencing](#12-adoption-and-sequencing)
1. [Readiness](#13-readiness)
1. [Error Boundary](#14-error-boundary)
1. [Privacy](#15-privacy)

## 1. Problem Statements

### 1.1 Four Facilities, No Contract

Operational output leaves Codess four ways, and none of them agree:

```text
  command modules ──► print()          159 sites  ─┐
  scattered       ──► logging          31 sites   ─┤
  ingest          ──► ProgressTrace    52 sites   ─┼──► stderr, uncoordinated
  adapters        ──► diagnostics{}    62 sites   ─┘     (counters: stderr only,
                                                          then discarded)
```

A reader cannot subscribe to one stream, a script cannot parse one format,
and a counter cannot be compared between runs. W47 established the cost
concretely: the diagnostic counters were the only record of refused records,
so record-level loss read as zero and that zero was unfalsifiable.

### 1.2 The Facility Charges for Output Nobody Wants

`ProgressTrace.__call__` builds a dict, formats an ISO 8601 timestamp, and
appends to a deque **before** testing whether output is enabled. A run with
progress disabled pays the full construction cost to discard the result.

### 1.3 One Cost for Every Frequency

A per-record site and a per-phase site call the same function. Record counts
reach six figures per Project; phase counts reach tens. Charging both the
same is what makes a facility either too slow for the first or too poor for
the second.

### 1.4 Immediacy and Permanence Are Conflated

`ProgressTrace` renders *and* retains in one call, so a caller cannot ask for
one without the other. A validation run wants retention without noise; an
interactive run wants the reverse.

### 1.5 One Configuration for Unlike Uses

Debugging, validation, deployment, and benchmarking want different volumes,
destinations, and overheads. There is one setting, `enabled`.

## 2. Measurements

All figures are Python 3.12.12, arm64, Darwin. Reproduce with
`tools/reporting_bench.py`. They are stated first because they, not
preference, decide the design.

### 2.1 Where the Current 1.245 us Goes

| Component | Cost | Share |
|---|---:|---:|
| `datetime.now(UTC).isoformat(timespec="ms")` | 723 ns | **58%** |
| `print(..., flush=True)` per call | 184 ns | 15% |
| dict build, 4 keys plus `**fields` | 108 ns | 9% |
| `datetime.now(UTC)` alone | 124 ns | 10% |
| deque append | 23 ns | 2% |
| Remainder (call, branch) | ~83 ns | 6% |

```text
  isoformat   ████████████████████████████████████████████  723 ns
  print+flush ███████████                                   184 ns
  now(UTC)    ████████                                      124 ns
  dict build  ███████                                       108 ns
  deque       ██                                             23 ns
```

**The single largest cost is formatting a timestamp nobody has asked to
see.**

### 2.2 Event Structure

| Structure | Cost | Relative |
|---|---:|---:|
| plain tuple | **14.8 ns** | 1.0x |
| dict literal, 4 keys | 67.0 ns | 4.5x |
| `dataclass(slots=True)` | 101.8 ns | 6.9x |
| `dataclass` | 110.4 ns | 7.5x |
| `__slots__` class | 119.5 ns | 8.1x |
| `NamedTuple` | 148.7 ns | 10.0x |

`NamedTuple` is the slowest to construct despite being a tuple subclass, and
a plain tuple is the fastest thing available. This inverts the intuition that
a named structure is free.

### 2.3 Counters

| Structure | Cost |
|---|---:|
| `list[index] += 1` | **66.5 ns** |
| `dict.get(k, 0) + 1` (current) | 79.5 ns |
| `array("q")[index] += 1` | 86.4 ns |
| `Counter[k] += 1` | 87.3 ns |

`array` is slower than `list` because each access boxes and unboxes a Python
integer. `Counter` is a dict with overhead.

### 2.4 Guards

| Guard | Cost | Note |
|---|---:|---|
| `if False:` literal | **0 ns** | folded at compile time; bytecode is empty |
| module global `if DEBUG:` | 1.9 ns | emits `LOAD_GLOBAL`, not folded |
| attribute `if self.enabled:` | 14.5 ns | |
| bare function call | 14.3 ns | the floor for any callable |

A literal `False` compiles to nothing. A module global does not, because
Python cannot assume it is not rebound.

### 2.5 Clocks

| Source | Cost | Resolution |
|---|---:|---|
| `time.time_ns()` | 23.8 ns | 1000 ns |
| `time.perf_counter_ns()` | 24.8 ns | 42 ns |
| `time.monotonic_ns()` | 25.2 ns | 42 ns |
| `time.monotonic()` | 26.1 ns | 42 ns |
| `time.process_time_ns()` | 203.4 ns | CPU time, not wall |

All wall and monotonic clocks cost the same ~25 ns. **There is nothing to
gain from a hardware tick counter**: `perf_counter_ns` already reads the
platform's high-resolution counter (`mach_absolute_time` on Darwin,
`clock_gettime(CLOCK_MONOTONIC_RAW)` on Linux) through one syscall-free vDSO
path. A raw `rdtsc` would trade 25 ns for perhaps 5 ns while giving up
frequency scaling correctness, core migration safety, and portability. The
25 ns is not the problem; the 723 ns of formatting is.

### 2.6 Deferred Formatting and Batching

| Approach | Per event |
|---|---:|
| Eager `isoformat` at the call site | 709 ns |
| **Deferred**: store `monotonic_ns`, format at flush | **35 ns** |
| Resolve one tick to ISO text at flush | 816 ns |
| Per-call `write` + `flush` | 184 ns |
| **Batched** write, 256 events | **74 ns** |

Deferring is 20x cheaper at the call site, and only events that are actually
rendered pay the resolution cost. Anchoring one wall-clock reading to one
monotonic reading and offsetting reproduces the timestamp to the millisecond,
verified against a direct `datetime.now(UTC)` reading.

## 3. Requirements

Derived from 1 and 2, each traceable to a measurement:

| # | Requirement | From |
|---|---|---|
| R1 | A disabled site costs no more than a bare call (14 ns) | 1.2, 2.4 |
| R2 | A compile-time-disabled site costs zero | 2.4 |
| R3 | Per-record facts use a primitive with no allocation | 1.3, 2.3 |
| R4 | No timestamp is formatted unless it is rendered | 2.1, 2.6 |
| R5 | Output is batched; flush is a policy, not a per-call act | 2.6 |
| R6 | Immediacy and permanence are selected independently | 1.4 |
| R7 | A call site cannot know which sinks exist | 1.1 |
| R8 | Profiles configure volume, destination, and overhead together | 1.5 |
| R9 | stdout carries only the requested result | CoPlan 9.6.1 |
| R10 | A reporting call never raises into the operation it reports on | CoPlan 9.6.1 |
| R11 | `mapping_diagnostics` stays in CoSchema, outside this facility | CoPlan 13.4.6 |

## 4. Design Partition

Six modules, each independently testable, with a strict dependency direction:

```text
                    ┌─────────────────────────────┐
   call sites ─────►│  api      count/event/span  │   R1 R2 R3
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  levels   capability gates  │   R2 R8
                    └──────────────┬──────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
      ┌───────────────┐   ┌───────────────┐   ┌───────────────┐
      │ clock         │   │ buffer        │   │ registry      │
      │ tick + anchor │   │ ring + flush  │   │ sink table    │
      │ R4            │   │ R5            │   │ R6 R7         │
      └───────────────┘   └───────┬───────┘   └───────┬───────┘
                                  └─────────┬─────────┘
                                            ▼
                                  ┌───────────────────┐
                                  │ sinks             │  R9 R10
                                  │ human/jsonl/      │
                                  │ collector/bridge  │
                                  └───────────────────┘
```

No module imports one above it. `clock`, `buffer`, and `registry` are leaves
with no Codess dependency, which is what lets the facility be imported by
`fileio` and the adapters without a cycle.

## 5. Event Structure

**An event is a tuple, not a dict or a dataclass.** 2.2 measures a plain
tuple at 14.8 ns against 67 ns for a dict, and the field names are known at
the sink rather than needed at the call site.

```text
  event tuple layout, fixed positions
  ┌────┬──────┬───────┬────────┬────────────────┐
  │  0 │  1   │   2   │   3    │       4        │
  │code│ tick │ level │ scope  │  fields tuple  │
  │ int│  ns  │  int  │  int   │ (k,v,k,v,...)  │
  └────┴──────┴───────┴────────┴────────────────┘
```

Three decisions follow from the measurements:

- **`code` is an interned integer, not a string.** Event codes are a closed
  set known at import; an integer compares and dispatches faster and keeps
  the tuple uniform. The dotted name lives in one table the sink consults.
- **`tick` is `monotonic_ns()`, never formatted here** (R4). Resolution to
  wall-clock text happens at flush, for rendered events only.
- **`fields` is a flat tuple of alternating key and value**, not a dict.
  Building `("n", 5, "path", p)` costs less than `{"n": 5, "path": p}` and
  the sink materializes a mapping only if it needs one.

A named accessor layer exists for readability at *sink* sites, where cost is
irrelevant:

```python
CODE, TICK, LEVEL, SCOPE, FIELDS = range(5)
```

This is the same trade CoPlan 3.5.5 makes for CoSchema field names: the
literal position is the documentation, and an indirection that costs a lookup
on the hot path buys nothing.

**Counters are not events.** A counter is an index into a preallocated list
(2.3), because a per-record fact answers *how many*, not *when*:

```text
  counters: list[int], one slot per registered name, sized at import
  ┌────┬────┬────┬────┬─────┐
  │ 0  │ 1  │ 2  │ 3  │ ... │   COUNT_REFUSED = 2  ← module constant
  └────┴────┴────┴────┴─────┘
     ▲
     └── count(COUNT_REFUSED) → counters[2] += 1     66 ns, no allocation
```

## 6. Capability Detection and Limits

Three gates, applied in this order, so the cheapest rejection happens first:

```text
  call site
     │
     ├─ (a) compile-time    `if REPORT_DEBUG:`  literal False → code removed   0 ns
     │
     ├─ (b) import-time     level < MIN_LEVEL   → api binds a no-op function   14 ns
     │
     └─ (c) run-time        `if not _sinks:`    → return before constructing   16 ns
```

**(a) Compile-time.** A build constant that is a literal `False` folds away
entirely (2.4): the bytecode is empty. This is for sites that must not exist
in a deployment build at all -- per-record trace points inside the decode
loop.

**(b) Import-time binding.** `api` inspects the active profile once at import
and binds each primitive to either the working implementation or a module-level
no-op. A site calling a no-op pays one call (14 ns) and no branch, and the
decision is made once per process rather than per call.

**(c) Run-time sink check.** The last gate, for levels that are enabled but
have no sink attached. It must precede *all* construction (R1) -- the current
defect is that it follows it.

**Limits are declared, not discovered:**

| Limit | Purpose | Default |
|---|---|---|
| `MIN_LEVEL` | drop below this at import | profile-set |
| `MAX_RETAINED` | ring capacity for the collector | 2,000 events |
| `MAX_FIELD_BYTES` | per-value bound before truncation | 4 KiB |
| `MAX_FIELDS` | per-event field count | 24 |
| `FLUSH_EVENTS` | batch size | 256 |
| `FLUSH_SECONDS` | latency ceiling | 0.5 s |

Exceeding a limit is recorded as a dropped-event count, never a raise (R10),
which is what CoPlan 9.6.1 already requires of the collector.

## 7. Time Sources

**Take one wall reading and one monotonic reading at startup; thereafter read
only the monotonic tick.**

```text
  startup:   anchor_wall = time.time_ns()        ← once
             anchor_tick = time.monotonic_ns()   ← once

  per event: tick = time.monotonic_ns()          ← 25 ns

  at flush:  wall = anchor_wall + (tick - anchor_tick)
             text = format(wall)                 ← 816 ns, rendered events only
```

Verified accurate to the millisecond against a direct reading (2.6).

| Question | Answer | Evidence |
|---|---|---|
| Use a hardware tick counter (`rdtsc`)? | **No** | `perf_counter_ns` is already 25 ns through a syscall-free vDSO path. A raw counter saves ~20 ns and gives up frequency-scaling correctness, core-migration safety, and portability (2.5) |
| Use wall clock per event? | No | Monotonic cannot move backwards; wall can, and 14.4 already records that a backward NTP step would report a negative duration |
| Format at the call site? | No | 723 ns, 58% of current cost, for output usually discarded (2.1) |
| Cache the formatted second? | Optional | A second-granularity cache makes the resolution cost amortize across events within one second. Worth it only if flush volume proves high |

Durations use the tick difference directly and never involve the anchor:
`span` records two ticks and the sink subtracts.

## 8. Buffering and Flush

```text
   count(i)   ──────────────────────────────► counters[i] += 1      (never buffered)

   event(...) ──► ring buffer (preallocated) ──► flush policy ──► sinks
                  ┌──┬──┬──┬──┬──┬──┬──┬──┐
                  │  │  │  │  │  │  │  │  │   fixed slots, no growth
                  └──┴──┴──┴──┴──┴──┴──┴──┘
                   ▲              ▲
                   write index    flush index
```

Flush triggers, whichever comes first: `FLUSH_EVENTS` reached (256, batching
at 74 ns/event against 184 ns unbatched), `FLUSH_SECONDS` elapsed, a
`warning`-or-worse event, a phase boundary, or process exit.

**An error flushes immediately.** Batching is for throughput; a message a
reader needs in order to act must not wait behind 255 others. This is also
what keeps a crash from losing the events explaining it.

**Counters are never buffered** — they are already an aggregate, and they are
summarized into an event at each phase boundary, which is the one place the
full envelope is affordable and the only place counters and their summary can
be made to agree.

## 9. Pre-Initialization

Everything that can be built once is built at import, so the hot path
allocates nothing:

| Structure | When | Why |
|---|---|---|
| Counter slot list | import | fixed size, index known as a module constant |
| Event code table | import | code integer to dotted name and level |
| Ring buffer | first use | fixed capacity, never grows |
| Clock anchor | process start | one wall and one monotonic reading (7) |
| Sink table | profile resolution | frozen tuple; empty is the fast path |
| Field-name interning | import | keys are from a closed set, so identity comparison suffices |
| Level thresholds | import | bound into the primitive, not consulted per call |

The measured effect: a disabled `event` costs 16 ns (2.4) versus 1,245 ns
today, and an enabled one defers 709 ns of formatting to flush (2.6).

## 10. Backends

Sinks share one interface and are selected per run. A call site never knows
which are attached (R7).

| Sink | Channel | Immediate | Durable | Use |
|---|---|:--:|:--:|---|
| `human` | stderr | yes | no | interactive |
| `jsonl` | stderr | yes | no | machine-parsed runs |
| `collector` | memory, bounded | no | via report | ingest and refresh reports |
| `file` | JSONL file | no | yes | benchmarking, long runs |
| `bridge` | stdlib `logging` | yes | depends | library call sites that cannot receive a reporter |
| `null` | — | no | no | benchmarking the operation, not the reporting |

**stdout is never a sink** (R9). It carries the requested result and nothing
else, which is what lets `--output-format jsonl` be piped safely.

Future backends fit without changing the call sites: an OpenTelemetry
exporter or a SQLite sink is a new entry in this table, because the event is
already a structure rather than a rendered string. That is the argument for
tuples over formatted text at the call site, beyond cost.

## 11. Use Profiles

One named profile sets all limits together (R8):

| Profile | Compile gate | `MIN_LEVEL` | Sinks | Flush | Cost per disabled site |
|---|---|---|---|---|---|
| **debug** | on | `debug` | human + file | 32 events | full |
| **validation** | on | `info` | collector + file | phase | ~16 ns |
| **deployment** | **off** | `warning` | human | 256 events | **0 ns** (folded) |
| **benchmark** | off | `error` | null | — | **0 ns** |

```text
  volume ▲
         │  debug        ████████████████████████  everything
         │  validation   ████████████              phases, counters, errors
         │  deployment   ███                       warnings and errors
         │  benchmark    ▌                         errors only
         └──────────────────────────────────────►  overhead
```

**benchmark exists to measure the operation, not the facility.** With the
compile gate off and the null sink, reporting contributes zero to a timing
run — which is what makes W08's workloads measure ingest rather than ingest
plus instrumentation.

## 12. Adoption and Sequencing

### 12.1 Adopted, Written, Rejected

| Source | Adopted | Rejected |
|---|---|---|
| stdlib `logging` | The `bridge` sink only, so a library call site that cannot receive a reporter still reaches the contract | As the primary path. `LogRecord` has no place for a counter, and `basicConfig` is process-global state a bounded command should not depend on |
| stdlib `time` | `monotonic_ns` for ticks, `time_ns` for the anchor (2.5) | `process_time_ns` at 203 ns, and raw hardware counters (7) |
| stdlib `json` | The `jsonl` sink's encoder | — |
| External metrics or tracing library | — | A dependency and a wire format for a local tool that emits to stderr and one JSON report |

Three formatter mechanics are adopted from a reviewed precedent and are
stated here as requirements rather than by citation, because a released
document should stand on its own argument: a reserved-attribute exclusion
separating standard fields from caller extras, an encoding fallback degrading
an unserializable value to `str()` and then to a fixed placeholder, and R10.

### 12.2 Proving It In Situ

Validated against uses that already exist, not fixtures:

| Use | Exercises | Compared against |
|---|---|---|
| Ingest of a real Project | `span` per source, `count` per record, phase summary | The 11 counters ingest prints today, which must still agree |
| Cursor cohort preflight | `span` nesting, three cache statuses | W46's statuses, unit tested |
| Record refusals | `count` beside the durable half | W47's `mapping_diagnostics` rows, which must not move (R11) |
| `query --output-format jsonl` | Channel separation under load | **stdout byte-identical before and after** |
| W08 workload under `benchmark` | Zero instrumentation overhead | Timing with the facility compiled out |

The fourth is the acceptance test for the whole item, and is the comparison
that verified W06 step 6 and W42.

### 12.3 Order

```text
  1  clock + buffer + registry   leaves, no Codess dependency, unit testable
  2  api + levels                the three primitives and their gates
  3  sinks                       human, jsonl, collector, null
  4  ProgressTrace adapted       existing ingest events keep working
  5  ingest routed               counters and spans replace diagnostics{}
  6  scan/query/admin routed     print() replaced, channels enforced
  7  file + bridge sinks         benchmarking and library call sites
  8  transitional paths removed  ProgressTrace deleted
```

Steps 1 to 3 land without touching a call site, so they are verifiable in
isolation. Step 4 is the compatibility bridge that keeps ingest working while
5 and 6 proceed. Step 8 is the only irreversible one and comes last.

## 13. Readiness

### 13.1 What Is Settled and What Is Not

| Area | State | What remains |
|---|---|---|
| Cost model | **Settled.** Every figure measured and reproducible (`tools/reporting_bench.py`) | Re-run on a target platform; the design follows ratios, which are stable, but absolutes are not |
| Event structure | **Settled.** Tuple, positional, interned code (5) | The code table's initial contents -- currently the 52 `ProgressTrace` event names |
| Counter primitive | **Settled.** Preallocated slot list, module-constant index (5) | The registered name set, derivable from the 62 existing sites |
| Gates | **Settled.** Three, cheapest first (6) | Which sites take the compile-time gate: a judgment per site, not a rule |
| Time source | **Settled.** Anchor plus monotonic tick, deferred format (7) | None |
| Buffering | **Settled.** Ring, batched, immediate on warning (8) | `FLUSH_EVENTS` and `FLUSH_SECONDS` defaults are estimates, not measurements |
| Sinks | **Specified** (10) | `file` and `bridge` are described, not designed in detail |
| Profiles | **Specified** (11) | How a profile is selected -- environment variable, CLI flag, or both -- is undecided |
| Error boundary | **Designed** (14). One base, three families, five exit codes; verified non-breaking | Assigning an event code to each of the 13 existing types |
| Privacy enforcement | **Designed** (15). Three field classes, allowlist, structural path redaction | Registering the ~20 field names in use, and the root table |

**No gap now blocks a complete implementation.** The error boundary (14) and
privacy enforcement (15) were the two, and both are designed. What remains in
each is enumeration rather than design: assigning an event code to thirteen
existing exception types, and registering roughly twenty field names that are
already in use. Both are mechanical and checkable -- an unregistered field
renders as `<unregistered>`, and an exception without a code fails a test.

### 13.2 Where It Lands

```text
  src/codess/reporting/            new package, no Codess dependency in its leaves
  ├── __init__.py                  public surface: count, event, span, profile
  ├── clock.py                     anchor + tick                       (7)
  ├── buffer.py                    ring + flush policy                 (8)
  ├── codes.py                     event code table, counter slots     (9)
  ├── levels.py                    gates and limits                    (6)
  ├── api.py                       the three primitives                (5)
  └── sinks/
      ├── human.py                 stderr, concise
      ├── jsonl.py                 stderr, one object per line
      ├── collector.py             bounded, into reports
      ├── file.py                  JSONL file
      ├── bridge.py                stdlib logging
      └── null.py                  benchmarking
```

A package rather than a module: 5 to 8 are separable concerns with different
test shapes, and `clock`, `buffer`, and `codes` must be importable by
`fileio` and the adapters without a cycle, which a single module mixing them
with sinks could not offer.

`codess/progress.py` is retained during the transition and deleted at step 8.
It has **2 importers and 83 lines**, so the compatibility bridge is small --
`ProgressTrace.__call__` becomes a shim over `event()`, and its existing
event names become the first entries in the code table.

### 13.3 When It Can Enter Codess

Entry is gated on evidence, not on completeness:

| Gate | Requirement | Verified by |
|---|---|---|
| **G1** | The package exists with `clock`, `buffer`, `codes`, `levels`, `api` and no Codess import | Import-boundary test; `tools/reporting_bench.py` reproduces R1-R5 against the real implementation rather than the prototypes measured in 2 |
| **G2** | Three sinks (`human`, `jsonl`, `null`) round-trip an event | Contract tests over the envelope, including the encoding fallback and R10 |
| **G3** | `ProgressTrace` is a shim and ingest still emits identical progress | The existing 3 progress test modules pass unchanged |
| **G4** | Ingest routed; the 11 printed counters still agree with the summary | A real Project ingest, counters compared before and after |
| **G5** | Channels enforced across scan, query, and admin | **stdout byte-identical** for `query --output-format jsonl`, captured separately before and after |
| **G6** | `benchmark` profile contributes zero measurable overhead | W08's workload timed with the facility compiled out and in |

**G1 to G3 add a facility without removing one**, so they land first and
independently. The exception hierarchy (14) can also land at any point, since
it is verified non-breaking and touches no call site. G4 onward changes what
an operator sees, and wants the field registry (15.4) populated first --
routing a command family before the fields it emits are classified would mean
classifying them afterwards, against output already in use.

**The earliest safe entry is after G3**, which is steps 1 to 4 of 12.3: a new
package, its tests, and a shim that leaves every existing call site behaving
as it does now. That is a self-contained change with no behavioral surface,
and it is where a reviewer can check the cost claims against the real code
rather than against a benchmark harness.

## 14. Error Boundary

### 14.1 What Is There Now

Thirteen exception types, with **no common base**, split between `ValueError`
and `RuntimeError` on no stated principle:

```text
  ValueError                     RuntimeError
  ├── CandidateReviewError       ├── HashMismatchError
  ├── ContentValidationError     ├── RawCaptureError
  ├── HashContractError          ├── ResourceLimitError
  ├── QueryContractError         ├── SchemaContractError
  ├── ResourcePolicyError        │   └── UnsupportedStoreError
  └── SourceCompatibilityError   └── SnapshotError
                                     └── SnapshotContractMismatchError
```

`ContentValidationError` and `RawCaptureError` are the same kind of fault --
input Codess will not accept -- and inherit from different bases. A caller
wanting "any Codess failure" must name all thirteen or catch `Exception`.

`console_main` handles `BrokenPipeError` and nothing else, so any other
uncaught exception reaches the operator as a traceback.

**Exit codes, measured:**

| Failure | Exit |
|---|---:|
| Missing Project directory | 1 |
| Corrupt store | 1 |
| Malformed argument | 2 (argparse) |
| Unknown command | 2 (argparse) |

Everything at runtime is `1`. A script cannot distinguish "your request was
wrong" from "the data is damaged" from "the disk is full", which are three
different responses: fix the command, rebuild the store, free space.

### 14.2 Design

**One base, three families, five exit codes.**

```text
  CodessError                     ← catch this for "any Codess failure"
  │
  ├── RequestError      exit 2    the caller asked for something invalid
  │   ├── QueryContractError      unparseable or contradictory request
  │   ├── ResourcePolicyError     policy document rejected
  │   └── CandidateReviewError    selection input rejected
  │
  ├── EvidenceError     exit 3    the data is not what it must be
  │   ├── SchemaContractError     released contract mismatch
  │   │   └── UnsupportedStoreError
  │   ├── SnapshotError           publication or verification failed
  │   │   └── SnapshotContractMismatchError
  │   ├── HashMismatchError       integrity claim failed
  │   ├── ContentValidationError  content policy rejected a value
  │   └── SourceCompatibilityError  a vendor record cannot be mapped
  │
  └── LimitError        exit 4    a declared bound was reached
      ├── ResourceLimitError      size, count, or time bound
      └── HashContractError       unsupported width requested
```

| Exit | Meaning | Operator response |
|---:|---|---|
| 0 | Success | — |
| 1 | Unexpected failure | Report it; this is a defect |
| 2 | Request invalid | Fix the command or the policy |
| 3 | Evidence unusable | Rebuild the store, or investigate the Source |
| 4 | Bound reached | Raise the limit, or accept the truncation |

**Why three families and not thirteen codes.** An exit code is read by a
script, and a script can act on three distinctions. Thirteen would encode the
implementation's exception hierarchy into a public interface, which is what
makes an exit code impossible to change later. Two would collapse the one
distinction that matters most in practice: a `RequestError` means the operator
made a mistake, and an `EvidenceError` means they did not.

**`1` stays "unexpected".** Anything not deriving from `CodessError` is a
defect in Codess, and it exits `1` with a bounded message and no traceback in
ordinary mode. That keeps `1` meaningful rather than the default for
everything, which is its current failure.

**Argparse keeps `2`.** It already uses it for a malformed command line,
which is exactly `RequestError`'s meaning, so aligning them costs nothing and
avoids a second convention.

### 14.3 How It Reaches the Reporter

Every raise carries an event code; the boundary renders it once:

```text
  domain raises   ──►  CodessError(code="store.contract.mismatch",
                                   message="...", exit_status=3)
                            │
  command boundary ─────────┤  catches CodessError
                            ├─► event(code, level=error, **scope)   ── to sinks
                            ├─► human message on stderr             ── R9
                            └─► return exit_status
```

Three properties this gives that the current shape cannot:

- **The event code is stable while the message is not.** A script matches
  `store.contract.mismatch`; a human reads the sentence. Today the only
  machine-readable signal is the message text, which is why
  `project_catalog` matched on a substring and my rewording broke it -- the
  defect W56 step 4 records.
- **The traceback is a debug-mode field, not a channel.** Ordinary mode emits
  a bounded message; `--debug` adds bounded exception detail as an event
  field, so it is subject to the same limits as any other field.
- **The boundary is one place.** `console_main` becomes the single handler,
  and the per-command `except` blocks that print and return `1` are removed
  rather than duplicated.

### 14.4 The Change Is Not Breaking, Verified

Each family inherits from `CodessError` **and** the base its members already
had, so every existing handler keeps working:

```python
class RequestError(CodessError, ValueError): ...
class EvidenceError(CodessError, RuntimeError): ...
```

Confirmed by construction: a `RequestError` is caught by `except ValueError`,
an `EvidenceError` by `except RuntimeError`, and both by `except CodessError`.
The 14 `except ValueError` and 22 `except OSError` sites in the tree are
unaffected, so the hierarchy can land before any call site is touched -- which
is what lets it precede the routing work rather than block on it.

### 14.5 What This Does Not Do

It does not introduce a deep hierarchy: three families is the whole of it, and
CoPlan 9.6.1 explicitly does not require more. It does not change which
exceptions are raised where -- the existing thirteen keep their names and
their raise sites, and only their bases and a `code` attribute change. And it
does not catch `OSError` or `sqlite3.Error` at the boundary: those are wrapped
at the layer that knows what the operation was, which is W56 step 4's subject.

## 15. Privacy

### 15.1 The Concrete Problem

One real progress line, unmodified:

One real progress line, with the disclosing parts replaced by what they are:

```text
codess: progress 2026-…T…Z +0.032s source.start
  project=/Users/<user>/<path>/<project>
  vendor=Claude
  source=/Users/<user>/.claude/projects/-Users-<user>-<path>-<project>/<uuid>.jsonl
  source_bytes=31059
```

The unmodified line carries a real operating-system username, the real home
directory layout, the real project name, and a real vendor session UUID in
each of those positions. None of that is transcript content -- which 9.6.1
already excludes -- and all of it is disclosure. This document substitutes
placeholders for the same reason the `shared` profile below exists.

**This is the gap the requirement misses.** 9.6.1 forbids "transcript bodies,
tool input or output, raw request data, secrets, or unbounded exception text".
Every field above passes that rule and is still sensitive.

### 15.2 Decomposition

Five distinct concerns, which need different mechanisms:

| # | Concern | Example | Real-world risk |
|---|---|---|---|
| P1 | **Identity disclosure** | `/Users/<user>/…` | A pasted log identifies the user; usernames are frequently real names |
| P2 | **Environment disclosure** | Home layout, vendor install paths | Reveals the machine's shape to anyone reading a bug report |
| P3 | **Subject disclosure** | Project and repository names | A project name can be commercially sensitive before it is public |
| P4 | **Correlation identifiers** | Session UUIDs, composer IDs | Links a log to specific retained records elsewhere |
| P5 | **Content leakage** | Transcript text, tool output, secrets | The one 9.6.1 already addresses |

P1 to P4 are what the current facility discloses. P5 is what it is written to
prevent.

### 15.3 Precedent

The relevant standards are about *categories* rather than a fixed list:

| Source | Principle | Applied here |
|---|---|---|
| **GDPR Art. 5(1)(c)**, data minimisation | Collect only what the purpose requires | A progress event's purpose is "which source, how big, how long" -- the *identity* of the source is needed, its absolute path is not |
| **OWASP Logging Cheat Sheet** | Exclude PII and secrets; log identifiers, not values | Names the practice this section implements: an identifier that resolves to the value, rather than the value |
| **OpenTelemetry semantic conventions** | Attributes are typed and named from a registry; values are bounded | Report 5's interned code table and field allowlist are the same shape |
| **Structured-logging practice generally** | Redaction belongs at the sink, not the call site | A call site that must remember to redact will eventually forget |

The common conclusion, and the one Codess should adopt: **the call site passes
the true value; the sink decides what a reader may see.** Redaction at the
call site distributes a policy decision across 183 places.

### 15.4 Design

**A three-tier field classification, declared once in the code table:**

```text
  field registry, one entry per known field name
  ┌──────────────┬──────────┬─────────────────────────────────────┐
  │ field        │ class    │ rendering under `shared` profile    │
  ├──────────────┼──────────┼─────────────────────────────────────┤
  │ source_bytes │ open     │ 31059                               │
  │ vendor       │ open     │ Claude                              │
  │ events       │ open     │ 412                                 │
  ├──────────────┼──────────┼─────────────────────────────────────┤
  │ project      │ located  │ project:7f3a1c                      │
  │ source       │ located  │ <cc-projects>/…/000e346c.jsonl      │
  │ state_path   │ located  │ <store>/ingest_state.json           │
  ├──────────────┼──────────┼─────────────────────────────────────┤
  │ session_id   │ linking  │ session:2f02ab65                    │
  │ project_id   │ linking  │ project:59466663                    │
  └──────────────┴──────────┴─────────────────────────────────────┘
```

| Class | Contains | Local profile | Shared profile |
|---|---|---|---|
| `open` | Counts, sizes, durations, vendor names, event codes | verbatim | verbatim |
| `located` | Anything naming a filesystem position | verbatim | root-relative, with the root as a token |
| `linking` | Identifiers correlating to retained records | verbatim | truncated digest |

**Three mechanisms, in order of strength:**

1. **An allowlist, not a denylist.** A field name absent from the registry is
   rendered as `<unregistered>` under any non-local profile. A denylist fails
   open -- the field nobody classified is the one that leaks -- and this is
   the same argument CoPlan 13.1.1 makes for accepting a coverage gap only
   with evidence.
2. **Type restriction.** A field value must be a scalar: `int`, `float`,
   `str`, `bool`, or `None`. A dict or a list is where a transcript body
   enters an operational field by accident, and rejecting the type is
   cheaper and more certain than inspecting the value.
3. **A bound.** `MAX_FIELD_BYTES` (4 KiB) truncates with a marker, so an
   unexpectedly large scalar is visible as truncated rather than emitted.

**Path redaction is structural, not textual.** A regex over `/Users/[^/]+`
would miss `/home`, `C:\Users`, a mounted volume, and a custom
`CODESS_CC_PROJECTS`. Instead the known roots are registered at startup --
home, the three vendor storage roots, the registry, the Project root -- and a
`located` field is rendered relative to whichever root contains it:

```text
  /Users/<user>/.claude/projects/-Users-<user>-…-<project>/<uuid>.jsonl
  └───────────────┬──────────────┘
          registered as <cc-projects>
                                  ▼
  <cc-projects>/-Users-<user>-…-<project>/<uuid>.jsonl
```

The remaining slug still encodes the original path, because Claude's directory
naming does -- so under `shared` a `located` field keeps only its final two
segments, which is exactly `identity.source_key`'s existing rule (W31).

### 15.5 Profiles

Privacy joins the profile table in 11, because it is the same kind of
choice -- what this run is for:

| Profile | `open` | `located` | `linking` | Use |
|---|---|---|---|---|
| `local` (default) | verbatim | verbatim | verbatim | The operator's own machine, their own data |
| `shared` | verbatim | root-relative | truncated digest | A log pasted into an issue or sent to a colleague |
| `strict` | verbatim | root token only | omitted | A log leaving the organisation |

**`local` is the default deliberately.** Codess reads a developer's own data
on their own machine, and a facility that redacts by default would make the
ordinary case harder to read for a risk the ordinary case does not carry --
which is the same reasoning CoPlan 8.4 uses for integrity checks. The profile
exists so that *sharing* is a choice with a mechanism, rather than a hope.

### 15.6 What Stays Out

`mapping_diagnostics` is not covered by any of this. It is evidence about
decoded data, stored in CoSchema and queried beside it (CoPlan 13.4.6), and it
is subject to the content policy that already governs stored content. Applying
an operational redaction profile to it would redact the evidence a reader
opened the store to see.

