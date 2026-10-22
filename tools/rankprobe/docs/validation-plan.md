# Establishing practical value

This is a plan, not a list of completed outcomes. An installable package and correct synthetic examples are necessary, but they do not prove users need it.

The bounded [initial engineering delivery](initial-delivery.md) is complete. Independent use is a separate practical-value gate, not a reason to require an experiment from someone who does not currently have one. Such readers may use the included walkthrough for onboarding feedback, without that practice being counted as real-work adoption.

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

Copy this record into a local note for each trial. Write the question and existing judgment before opening the report. Record failures, no useful information and incorrect findings as well as useful results. Share only a reviewed, de-identified copy with the participant's consent; private inputs and full reports are unnecessary.

Use `not measured` for unrecorded times, rather than zero. Keep participant active time, unattended waiting and author assistance distinct. A measured zero is valid; missing measurements are not zeros.

For report understanding, choose one metric or finding and explain its value and coverage in your own words, using the [metric semantics](metrics.md) when needed. No screenshot or private query IDs are required.

```text
Anonymous trial ID / date:
Did the participant help implement RankProbe? yes / no:
RankProbe version / source commit (if available):
Python and operating system:
Existing framework / task / input format (no private identifiers):
Input category: synthetic example / public real export / participant's own real export:
Is the participant permitted to inspect these inputs locally? yes / no / uncertain:
Specific question and what would count as answering it:
Before the report: existing judgment and supporting evidence:

Installation: participant active minutes / unattended waiting minutes:
Export preparation: participant active minutes / unattended waiting minutes:
Report interpretation: participant active minutes / unattended waiting minutes:
Author help: participant assisted active minutes / participant waiting minutes (both already included above) / author active minutes:
Machine audit runtime in seconds (only if recorded):
Could the participant finish without help? Blocker / error / help provided:

New information / already known / not useful / incorrect finding:
Selected metric or finding, explained in your own words; eligible / submitted query coverage when applicable:
Finding code and minimal synthetic reproduction, if needed:
Actual action taken and whether the original judgment changed; why:
Actual second use: not yet / no / yes; date and task if yes:
Intention to use again and reason (separate from actual use):
Consent to retain this de-identified feedback: yes / no:
```

Synthetic-example feedback checks onboarding; it does not establish adoption on real exports. An implementation author's use is developer validation. An intention to return is not a second use. These records remain blank until an actual participant completes a trial.

## Interpreting human time

Without a human comparison, report only the time spent completing this task. Machine runtime alone does not measure human time saved. Do not add assisted participant minutes to the participant stage totals again; report author effort separately.

For a comparison, first fix the question, completion criteria and which time components count. Use two permitted cases of similar difficulty, one with the participant's existing tools and one with RankProbe; vary the order across participants. Record whether the question was fully answered, help was needed, or the answer was already known. Repeating the same problem can benefit from familiarity with its answer, which must not be credited to the tool.

With few participants or cases of uncertain equivalence, show individual recorded times and limitations, not a general percentage saving. Keep timing on synthetic tasks separate from adoption on real inputs. This is a practical trial record, not evidence already collected or a formal research study.
