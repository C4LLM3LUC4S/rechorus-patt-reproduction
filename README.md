# PAtt reproduction in ReChorus

Course project on sequential recommendation. **Work in progress: experiments have not been run; no reproduction results are claimed.**

## Paper

Yuli Liu, Christian Walder, Lexing Xie, and Yiqun Liu. *Probabilistic Attention for Sequential Recommendation*. KDD 2024, pp. 1956–1967.

- Paper: https://doi.org/10.1145/3637528.3671733
- Author implementation: https://github.com/l-lyl/PAtt
- Target framework: https://github.com/THUwangcy/ReChorus

## Planned experiments

- Port PAtt into ReChorus and check numerical agreement with the author implementation.
- Compare against SASRec and GRU4Rec under a shared evaluation protocol.
- Use Grocery and MovieLens-1M through ReChorus-provided data or preprocessing, subject to metadata validation.
- Report ranking accuracy, recommendation diversity, runtime, and controlled ablations.
- Record seeds, configurations, dataset statistics, and original logs before reporting results.

## Current status

Paper selected; author code inspected. Full-paper review, data/kernel preparation, framework integration, and experiments remain pending. The default author configuration references an item-kernel file that is not bundled in the inspected checkout; CUDA-specific operations also require checking before execution.

## Attribution

This repository is not the official implementation. Third-party code and data will retain their source attribution and applicable license notices.
