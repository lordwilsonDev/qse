# MOONSHOT-M — the machine that can attest its own continuity

One command: `python3 moonshot_machine.py`. The code is `qse/witness/`; the tests are
`qse/tests/test_witness.py` and `qse/tests/test_moonshot_machine.py`.

This is the method the repository already has -- **AIL (Axiom Inversion Logic)** and
**MoIE** -- aimed at a machine instead of a question. It is not a claim that no one has
ever built a watchdog; it is a claim about *which* capability an always-on Mac mini is
for, derived by inverting the settled belief and then built and run so the claim can be
falsified.

## The settled belief, and why it is the one to invert

Search for what to do with an always-on Mac mini and every answer is the same shape:
run local models, host agents, serve media, be a homelab. They differ only in the
workload. The belief underneath all of them is one sentence:

> a Mac mini is worth running because it **computes**.

That belief has a structure, and it is the structure AIL inverts -- not the sentence.
Its axioms ("what would have to be true for the belief to hold") are:

| # | axiom | kind |
|---|---|---|
| 1 | a Mac mini is worth running because it computes: it serves models, media and agents | MEASUREMENT |
| 2 | the machine's health can be read from the machine's own reports | MEASUREMENT |
| 3 | a machine that is always on is one continuous process whose history is its log | TEMPORAL |
| 4 | the machine's own log is evidence of what the machine did | AUTHORITY |
| 5 | an idle machine is wasted capacity | COORDINATION |
| 6 | the failures that matter are the failures the machine observed | FAILURE |
| 7 | what a fleet gives in continuity, one node cannot | SCOPE |

Handed to the seven operators (`qse/inversion/operators.py`), 7 axioms produce 63
inversions that pass the gate (`R-INV-1`) and 7 that are refused -- one per axiom, the
`failure_attacker` candidate "the recording system itself is the problem", which has no
observable consequence as stated. The refusals are reported, not dropped: an engine
that silently discards an unconsequenced inversion is indistinguishable from one that
never produced it.

## The inversion

The inversions that carry the moonshot are the TEMPORAL, AUTHORITY, FAILURE and
MEASUREMENT ones. Read together they say the same thing four ways:

- **TEMPORAL** -- "always on is one continuous process whose history is its log" inverts
  to: a log records what happened, never what *didn't*; a gap in it is not evidence of
  continuity.
- **AUTHORITY** -- "the machine's own log is evidence of what it did" inverts to: the
  machine cannot witness itself, because the thing you most need it to report (that it
  *stopped*) is the one event it cannot write.
- **FAILURE** -- "the failures that matter are the ones it observed" inverts to: the
  failure that matters is the silent one, the recorder that died without a line.
- **MEASUREMENT** -- "its health is in its own reports" inverts to: the report is a
  measurement system, and a measurement system measuring itself is the artifact.

So the inverse capability is:

> the machine's value is not the work it does; it is the **continuity it can prove**,
> which no machine can honestly prove about itself.

## What was built

`qse/witness/` -- a hash-chained heartbeat that refuses to trust the machine:

- **A gap is a claim, not a fact.** Each beat classifies the interval before it:
  `CONTINUOUS`, `SLEPT`, `REBOOT`, or `HEARTBEAT_LOST`. Order matters and is the point:
  a boot-time change is checked first (a restart is not a sleep), then the ordinary
  interval, then the OS power log, and only if nothing explains the gap is it reported
  as lost. Nothing is assumed back to "fine".
- **The machine is not its own witness.** Sleep is established from the kernel's power
  log (`pmset -g log`, `qse/witness/power.py`), not from the process that might have
  died. Reboot is established from `kern.boottime`. Both are read, not inferred. The
  power read is cached for 30s because the log is a six-figure-line dump and a witness
  that re-shells it every beat spends more time reading about the machine than watching
  it -- and a stale cache can only delay noticing a sleep, never invent one.
- **The record is about a subject.** A heartbeat for a recorder is an answer to a
  question nobody asked; what you want to know is whether *the thing you care about*
  stopped. So every beat records the identity of a declared **subject** -- a process
  identity `(name, pid, started)` from ``subject_identity``, or anything the caller
  supplies -- and the verifier compares subjects across beats. The recorder can report a
  perfectly continuous ledger while the subject dies and returns (`SUBJECT_RESTARTED`) or
  vanishes (`SUBJECT_MISSING`), and the verdict becomes `SUBJECT_BROKE`. That is the
  discrepancy the whole moonshot turns on, and it is caught by subject identity and not
  by any gap in the recorder's clock.
- **Two witnesses, and their disagreement is the finding.** The subject is witnessed
  twice: the machine *observes* a process identity (`name`/`pid`/`started`), and the
  subject may *declare* a `token` (a run id it emits at start). Neither is authoritative
  -- a token can survive a process it should not, and a pid can be reused by a process it
  should not be -- so the record keeps both and names where they disagree:
  `SUBJECT_VOUCH_CONFLICT` (a new process, the same token: a supervisor restarted a
  crashed job with its run id preserved, a false vouch) and `SUBJECT_TOKEN_DRIFT` (the
  same process, a new token: a job re-initialising in place). This is MoIE's rule applied
  to a machine -- agreement is reported, never counted into a decision -- so no single
  witness is allowed to overrule the other, and the two are counted separately
  (`subject_witnesses`).
- **A declared policy, applied and not hidden.** A disagreement between the two witnesses
  is settled by a policy declared *before* the run (recorded on a beat) or passed to
  `verify`: `report` (the default, which settles nothing), `probe` (the machine's
  observation outranks the token), `token` (the subject's declaration outranks the
  observation), or `both` (require agreement). `verify` reports the policy it used and,
  per transition, whether that policy treated it as a break and why -- so the rule is
  visible in the record rather than buried in a verdict. A reader may restate the policy
  explicitly, which re-reads the same bytes under a different *stated* rule; nothing is
  settled silently. An unknown policy is refused, not defaulted.
- **Liveness is not progress.** A subject can be perfectly `CONTINUOUS` -- same
  identity, same token, beats on time -- while deadlocked, waiting on a lock, or looping
  over an empty queue. Each beat may therefore carry an advancing **`progress`** signal
  (a sequence number, a row count, a queue position), and the verifier compares it across
  beats: `PROGRESS_ADVANCING`, `PROGRESS_FLAT`, `PROGRESS_REGRESSED` (a monotone counter
  going backwards -- a hard discontinuity, not a standstill), or `PROGRESS_NO_SIGNAL`
  when either beat reported none. A run of consecutive flat beats at or over a
  *declared* threshold (`stall_after`, like the interval and the slack -- a convention,
  not a measurement) makes the verdict `SUBJECT_STALLED`: the subject is alive and
  advancing nothing, which is the failure no gap or identity check can see. A single flat
  pair is not yet a stall; a regression is reported as `SUBJECT_BROKE`, kept distinct
  from a stall because standing still and going backwards are different findings.
- **Progress is checked against the world, not only reported.** The counter is what the
  subject *says* it did; a `file_effect` (a file's size) or any number the recorder reads
  from a source the subject does not control is what the world *shows*. The verifier
  compares the two across beats: `EFFECT_AGREES`, `EFFECT_UNSUBSTANTIATED` (the subject
  reports an advance the observed effect does not show -- a claimed advance nothing
  substantiates, reported as a *sustained* run because a single beat may be lag), or
  `EFFECT_UNREPORTED` (the world advances while the subject reports nothing: work
  unclaimed, which is under-reporting, not a break). A sustained run of unsubstantiated
  advances makes the verdict `SUBJECT_UNSUBSTANTIATED` -- the same two-witness pattern as
  identity, now applied to advance. The second witness also *refutes a false stall*: a flat
  counter the observed effect contradicts is `EFFECT_UNREPORTED`, so the subject is silent
  rather than stalled, and the stall does not fire.
- **Independence is counted, not asserted.** A single source can be moved by whoever
  controls it, so the record reads *named* sources and reports how many agree: two or more
  advancing together is `CORROBORATION_CORROBORATED` (a forgery would have to move them
  together), one advancing alone is `CORROBORATION_SINGLE_SOURCE` (a real witness whose
  independence is unestablished), sources that contradict each other are
  `CORROBORATION_SPLIT`. A claimed advance sustained only by a lone source makes the verdict
  `SUBJECT_UNCORROBORATED`; sources that contradict each other make `SUBJECT_WITNESSES_SPLIT`.
  The record never says "independent" -- it says how many witnesses agree, so the reader
  sees the strength of the evidence rather than a boolean the caller swore to. The verdicts
  engage only when two or more sources are read, so a single-source record keeps its
  existing reading.
- **Agreement is not independence -- a declaration is recorded, never promoted to proof.**
  Corroboration counts how many named sources agree; it cannot tell two sources the subject
  could write from two it cannot. So each source may *declare* a provenance -- the reason it
  is beyond the subject's reach: `read_only` (the recorder read it and had no write path),
  `causal` (a trail back to the work, e.g. a downstream consumer's count), `external`
  (outside the subject's machine), or `within` (the subject's own counter, declared rather
  than hidden). The verifier counts the *advancing* sources declared beyond reach: two or
  more is `INDEPENDENCE_INDEPENDENT`, one alone is `INDEPENDENCE_DECLARED_ONLY`, and two or
  more agreeing sources with fewer than two beyond reach is `INDEPENDENCE_UNPROVEN` --
  sustained over the threshold it makes the verdict `SUBJECT_INDEPENDENCE_UNPROVEN`. A
  corroborated advance is therefore never called independent on agreement alone; the
  strongest verdict the evidence reaches when independence is merely declared is *unproven*.
  A ledger that declares no provenance keeps its earlier reading, an unrecognised
  declaration is ignored, and an unknown provenance kind is refused rather than believed.
- **A declaration can be checked, not only recorded.** The reach above is the caller's
  word; the next level makes it something the recorder reads for itself. Name each effect
  source's *path* and `beat()` stats it -- the owner write bit and its own `os.access` --
  and records the observation (`REACH_READ_ONLY` / `REACH_WRITABLE` / `REACH_UNKNOWN`).
  Two advancing sources the recorder observed to be read-only are `INDEPENDENCE_ATTESTED`:
  independence *observed*, not sworn. A source the recorder can write cannot be beyond reach
  however it was declared, so marking a writable source `read_only` is
  `INDEPENDENCE_CONTRADICTED` -- sustained over the threshold it makes the verdict
  `SUBJECT_INDEPENDENCE_CONTRADICTED`, and the defeated declaration is named in
  `contradicted_sources`. The two reach classes are counted apart, so one *checked* source
  plus one merely *declared* stays `INDEPENDENCE_UNPROVEN`: a neighbour's check does not
  vouch for a source it never looked at. A ledger that names no paths keeps its prior
  reading, exactly as one that declares no provenance.
- **A value can be measured, not only reported.** Reach is a fact about a source's
  *permissions*; the value is a fact about its *contents*. Name each effect source's path and
  `beat()` **reads** it -- the byte count becomes the source's `effect` and a checksum over
  those bytes (`measure`, `content_digest`) pins which bytes it read -- so the number an
  advance rests on is a function of the file, not a number the caller typed, and two files of
  the *same size* with different contents no longer read alike. A source named with a
  reported value is *checked* against the read: a number the bytes confirm is
  `VALUE_MEASURED`, one they refute is `VALUE_CONTRADICTED` -- sustained over the threshold,
  the verdict `SUBJECT_VALUES_CONTRADICTED` -- and a source with no path to read is
  `VALUE_REPORTED`. Two advancing sources the recorder both checks read-only *and* measures
  are `INDEPENDENCE_MEASURED`: independence observed at the value, one level past the reach
  check. And an advance whose agreeing sources are all still reported is
  `SUBJECT_VALUES_REPORTED` when a measurement was made anywhere -- reach checked, but the
  number the claim rests on is still the caller's. A ledger that names no path keeps its
  prior reading, and a path the recorder cannot read is `VALUE_UNKNOWN`, left unfilled.
- **Absence is evidence.** A watched metric that never moved is computed and reported
  with the same standing a change would get, because "the disk did not fill" is exactly
  what a log of changes can never show.

The ledger is `qse.ledger.chain`'s hash-chained JSONL, reused rather than reinvented,
so tampering is detectable by the same code that guards the engine's own history.

## Run

```text
$ python3 moonshot_machine.py
1. THE MACHINE, READ FROM THE MACHINE   Apple M4, arm64, 10 cores, 16.0 GB RAM
2. AXIOM INVERSION   7 axioms -> 63 inversions passed the gate, 7 refused
3. THE MOONSHOT   invert "its value is what it computes" -> "what it can attest"
4. THE WITNESS, RUN
   real ledger: 4 beats, verdict CONTINUOUS, chain_ok True
   tampered line rewritten -> verdict TAMPERED
   injected history, a machine that slept    -> SLEPT
   injected history, a machine that rebooted -> REBOOT
   injected history, a recorder that died    -> HEARTBEAT_LOST
   subject, witnessed twice (the machine's probe vs the subject's token)
     a real process we started, then ended -> SUBJECT_BROKE (SUBJECT_OK, SUBJECT_MISSING)
     injected: a new process, the same token -> SUBJECT_VOUCH_CONFLICT
     injected: same process, a new token     -> SUBJECT_TOKEN_DRIFT
     injected: a new process, a new token    -> SUBJECT_RESTARTED
   progress (liveness is not advance): a flat counter -> SUBJECT_STALLED (3 flat beats, threshold 3); an advancing counter -> CONTINUOUS
   side effect (the counter vs the world): a real growing file -> CONTINUOUS; a claimed advance the world does not show -> SUBJECT_UNSUBSTANTIATED (3 beats); an unclaimed advance -> CONTINUOUS
   corroboration (agreement counted, not asserted): 2 sources agreeing -> CONTINUOUS; one source -> SUBJECT_UNCORROBORATED; sources that contradict -> SUBJECT_WITNESSES_SPLIT
   independence (agreement is not independence): 2 source(s) declared beyond reach -> CONTINUOUS; the same agreement with every source within reach -> SUBJECT_INDEPENDENCE_UNPROVEN
   independence, CHECKED not declared: two sources the recorder stats as read-only -> CONTINUOUS (2 attested); two writable sources marked read-only -> SUBJECT_INDEPENDENCE_CONTRADICTED (2 contradicted)
   values, MEASURED not reported: two read-only sources the recorder reads itself (a checksum over the bytes) -> CONTINUOUS (2 measured, 3 independence beats); a reported number the bytes refute -> SUBJECT_VALUES_CONTRADICTED (2 contradicted); reach checked, values still the caller's -> SUBJECT_VALUES_REPORTED (2 reported)
   OS power witness: 0 sleep interval(s) in the log
```

Exit `0` when every demonstration holds, `1` when one does not, `2` for unusable input.

## Honest limits

- **It attests a declared subject's continuity, watched twice -- and reports the two
  witnesses separately rather than merging them.** The probed identity is whatever the
  caller supplies (by default a process `(name, pid, started)` from `ps`); the declared
  token is whatever the subject emits, or nothing. What it still does not attest: that
  the subject *did* anything, or that a subject neither witness can see exists at all --
  an unreadable subject reads as `SUBJECT_MISSING`, an honest "I could not see it", never
  "it is fine". The token is optional and caller-supplied, so a subject that never 
  declares one is watched by its process identity alone; identity durability is therefore
  *reported when detectable* (the disagreements above) but not *solved* -- making a job
  emit a durable run id, and deciding what to do when two witnesses disagree, is the open
  question below, not a control shipped here.
- **The sleep witness is the OS power log.** On a node whose log is rotated, suppressed,
  or on a non-Mac, a sleep becomes `HEARTBEAT_LOST` -- an honest "unknown", never a
  false "continuous". That direction is deliberate: the failure mode of the witness is
  to under-claim.
- **The wall/monotonic pair is recorded but not yet used to classify.** `beat()` writes
  both, so a frozen-versus-slow process is distinguishable in the record, but the
  classifier currently leans on the OS witnesses. Using the clock divergence as a third
  witness is the next step.
- **The chain cannot vouch for its own last line** (`qse.ledger.chain`'s structural
  limit, inherited). A tampered final beat is undetectable by design; `tail()` publishes
  its hash so a later reader can notice a change.
- **The axioms are written by hand.** AIL inverts what it is given; it did not discover
  that people run Mac minis for compute. The inversion is only as good as the axiom,
  and the axiom here is a summary of a common story, not a measured belief.
- **The demo's `SLEPT` and `REBOOT` are injected, not observed.** This machine is
  sleep-prevented (`pmset -g` reports `sleep 0 (sleep prevented by powerd)`), so it
  produced no real sleep to classify. The classification of a real sleep is exercised by
  construction, not by having witnessed one; that is stated rather than hidden.

- **The progress signal is supplied by the subject, and the side effect is chosen by the
  caller.** The stall check compares whatever number the caller wrote into `progress`, and
  the side-effect check compares it with whatever number the caller chose to read. Neither
  establishes that the number *is* the subject's real work. A side effect the subject also
  controls is not independent, and a subject that loops while incrementing a counter while
  also touching the watched file would read as agreeing. Corroboration raises the cost of a
  forgery -- a second source must be moved consistently -- but it does not *prove*
  independence: the record reports how many sources agree, not that they could not have been
  moved together, and the choice of sources is still the caller's. Progress itself is still
  the subject's own number. But a source's *value* is now measured rather than taken on
  trust: naming its path makes the recorder read the bytes, so the number is one it read, and
  a reported number is *checked* against that read. What a measurement still does not do is
  prove the subject did not author those bytes, and the read is the recorder's own access --
  so a subject running as a *different* user is not covered, and as root nothing is: the
  measurement, like `read_only`, is for the recorder's uid. So the strongest word a
  *declaration* reaches is still `SUBJECT_INDEPENDENCE_UNPROVEN`; `ATTESTED` and `MEASURED`
  are earned by observations the recorder made, not by a promise -- they can withhold credit
  for independence, never manufacture it.

## Next question (the one the build produced)

The vulnerable edge has moved again, not closed. Reach is checkable (the recorder stats a
source) and now the *value* is too (it reads the bytes and checks a reported number against
the read), but both observations are still the recorder's own access on its own machine.
`INDEPENDENCE_MEASURED` means "two sources the recorder could not write *and* read itself
agreed", which is stronger than a declaration and still not "two sources the subject could
not influence at all": a measured value proves what the bytes *say*, not who *wrote* them,
and a subject that owns the file the recorder only reads still influences its contents.
Two gaps remain, and they are the next builds, one limitation at a time. First: the read,
like the reach check, is uid-local -- a subject running as a different user, or the recorder
running as root, is not covered, and the record should say so rather than imply more.
Second, and deeper: the recorder reads bytes the subject *did not author* only by
convention, not by construction. The next question is whether a value can be witnessed on a
channel the subject cannot write at all -- a count read from a socket the subject never
opened, a counter the recorder increments in its own store, a third party's record -- so
that authorship, and not only reach and reading, is what the independence rests on. The
same move once more: the strongest claim is the one the record can *falsify* about itself,
and "the subject could not have produced this value" is still the thing no report can
simply assert.
