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

## Next question (the one the build produced)

The declared policy settles *identity* disagreements, which exposes the next gap: the
record attests **liveness, not progress.** A subject can be perfectly `CONTINUOUS` -- same
process, same token, heartbeats on time -- while it is deadlocked, waiting on a lock, or
looping over an empty queue and doing nothing. That is the same shape as the inversion that
started this moonshot: the failure you can see (a process that stopped) is the one you
already catch; the failure that matters is the one the record cannot see (a process that
kept running and made no progress). The next question is whether a beat should carry a
*progress* signal -- a value the subject advances (a sequence number, a row count, a queue
position) -- so the witness can report `CONTINUOUS but not advancing`, which no liveness
check can. That is a new failure class, not a parameter of the current one.
