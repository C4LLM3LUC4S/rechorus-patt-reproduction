# Establishing practical value

This is a plan, not a list of completed outcomes. An installable package and correct synthetic examples are necessary, but they do not prove users need it.

## Gate 1: Reproducible local behavior

- Install a built wheel into a fresh environment and run the bundled demo outside the source directory.
- Check small fixtures against hand-computed MRR, NDCG, and tie envelopes.
- Verify malformed inputs fail clearly; unknown labels and conflicting judgments are not converted into reassuring scores.
- Run the optional NPZ exporter on a permitted local experiment without changing the source files. Save aggregate validation only after reviewing for identifiers and licensing constraints.
- Open HTML reports and inspect them visually, including narrow layouts and escaped identifiers.

Record the exact commit, Python version, checks run, failures, and limitations. A configured remote CI matrix counts as planned coverage until those jobs actually run.

## Gate 2: Independent use

The initial goal is three people who are not implementation authors trying their own prediction exports. Recruiting or messaging people requires a separate explicit instruction; this document itself does not authorize outreach.

Give each participant the README, not a guided installation session first. Record:

| Question | Evidence to collect |
| --- | --- |
| Can they start? | Install result, time to first useful report, blocker text |
| Is export work acceptable? | Extra preparation time and unsupported output shape |
| Is the report understandable? | Which finding they can explain without the author |
| Is it useful? | A new, actionable observation; or a concrete reason it adds nothing |
| Will they return? | A second use or voluntary integration, rather than a favorable comment |

Aim for at least two participants who obtain useful new information and choose to use it again. These numbers are decision targets, not adoption claims. Never require sharing private predictions; a synthetic reduced case is enough to investigate a bug.

## Gate 3: Decide what to build next

Continue if users repeatedly encounter a supported problem and the audit changes a decision. Add only the adapters or checks those cases justify. If people only want metric computation, investigate whether existing evaluators already serve them better. If exporting costs more time than the audit saves, improve the interface before expanding metrics.

Possible research questions include how evaluation choices change model ordering on permitted public datasets. Any study needs a fixed protocol, independent baselines, and results beyond these synthetic fixtures. No paper acceptance, admission advantage, paid service demand, or revenue is assumed.

## Feedback form

Use these fields in a local note or a repository issue after removing sensitive information:

```text
RankProbe version / commit:
Python and operating system:
Input source and format (no private identifiers):
Time spent exporting / installing / interpreting:
Expected behavior:
Observed behavior:
New information or decision changed:
Would use again? Why?
Minimal synthetic reproduction:
```
