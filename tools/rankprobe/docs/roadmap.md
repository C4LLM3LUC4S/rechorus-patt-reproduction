# Roadmap and decision gates

RankProbe aims to help people explain why exported ranking results change. The next milestones connect software work to observable decisions. They are plans, not adoption or research claims.

| Milestone | Deliverable | Evidence needed before expanding |
| --- | --- | --- |
| Retrieval alpha (`0.1.0a2`) | Read TREC runs and qrels directly; preserve explicit unknown labels; demonstrate a misleading aggregate improvement | Reproducible fixtures, hand calculations, CLI regression checks, and cross-platform CI for the exact commit |
| Independent use | A five-minute trial, useful report explanations, and a small feedback record | Three people outside the implementation team try their own exports; at least two identify actionable information and choose a second use |
| Integration | Address the export or interpretation bottleneck observed in those trials | A concrete repeated request, a maintained adapter or CI recipe, and a regression example that shows the time or decision saved |
| Reproducibility study | Measure how declared evaluation choices affect run comparisons on permitted public inputs | A fixed protocol, source and license record, independent reference calculations, and reproducible results beyond synthetic examples |

Until the independent-use gate has evidence, prioritise correctness, clear reports, supported formats, and installation. New metrics, a hosted dashboard, model training, accounts, or billing need an observed reason to exist. A public CLI can remain useful without a cloud service.

Independent-use evidence and engineering work can progress in parallel. A lack of new feedback does not close the project: known gaps such as an unexecuted independent metric reference or a demonstrated export barrier can be addressed without outreach. The [trec_eval cross-check](trec-reference.md) is one bounded example. Keep each step tied to a named obstacle and an observable acceptance result; avoid rerunning completed checks or adding speculative features.

For the software to support a portfolio or later research work, keep the record auditable: associate an issue with a minimal example, document the semantic change, review the diff, and link the exact passing CI run. A synthetic diagnostic demonstrates behavior; it is not a benchmark result or a paper contribution by itself.

Possible revenue experiments should start only if a repeated need emerges, such as support integrating audits into a team's evaluation pipeline. Record willingness to pay separately from polite feedback. Neither this roadmap nor a working package establishes demand, income, or an admission advantage.

See [validation-plan.md](validation-plan.md) for the evidence to collect and [try-it.md](try-it.md) for the material a volunteer can use independently. No outreach has been performed by creating these documents.
