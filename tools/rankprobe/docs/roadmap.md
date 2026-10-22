# Maintenance roadmap and decision gates

RankProbe aims to help people explain why exported ranking results change. The bounded [initial implementation](initial-delivery.md) is complete at `0.1.0a4`; the project now prioritises maintenance and evidence from actual use. The remaining gates concern practical value and justified expansion, not unfinished requirements for that first engineering scope.

| Milestone | Deliverable | Evidence needed before expanding |
| --- | --- | --- |
| Initial engineering delivery (`0.1.0a4`) | Local core, auditable input/metric contracts, readable reports, bounded adapters, public cases and installation/recovery paths | Scope complete; exact source snapshots, distribution/install checks and current-commit CI remain the acceptance record |
| Independent use | A complete local walkthrough, useful report explanations, and a small feedback record | Three people outside the implementation team try their own exports; at least two identify actionable information and choose a second use |
| Integration | Address the export or interpretation bottleneck observed in those trials | A concrete repeated request, a maintained adapter or CI recipe, and a regression example that shows the time or decision saved |
| Reproducibility study | Measure how declared evaluation choices affect run comparisons on permitted public inputs | A fixed protocol, source and license record, independent reference calculations, and reproducible results beyond synthetic examples |

Maintenance prioritises reproducible correctness failures, broken installation/export paths, report ambiguities and compatibility regressions. Preserve the failing input or a minimal original synthetic reproduction; make the smallest repair, document semantic changes and follow the changed commit's CI. Do not rerun unchanged passing gates or create features merely to produce activity.

Independent use does not require the project owner to start a new experiment. Keep the onboarding path available for readers without exports; assess practical value when someone already has a permitted task. New metrics, a hosted dashboard, model training, accounts, or billing need an observed reason to exist. A public CLI can remain useful without a cloud service.

Independent-use evidence and engineering work can progress in parallel. A lack of new feedback does not close the project: known gaps such as an unexecuted independent metric reference or a demonstrated export barrier can be addressed without outreach. The [trec_eval cross-check](trec-reference.md) is one bounded example. Keep each step tied to a named obstacle and an observable acceptance result; avoid rerunning completed checks or adding speculative features.

For the software to support a portfolio or later research work, keep the record auditable: associate an issue with a minimal example, document the semantic change, review the diff, and link the exact passing CI run. A synthetic diagnostic demonstrates behavior; it is not a benchmark result or a paper contribution by itself.

Possible revenue experiments should start only if a repeated need emerges, such as support integrating audits into a team's evaluation pipeline. Record willingness to pay separately from polite feedback. Neither this roadmap nor a working package establishes demand, income, or an admission advantage.

See [validation-plan.md](validation-plan.md) for the evidence to collect and [try-it.md](try-it.md) for the material a volunteer can use independently. No outreach has been performed by creating these documents.
