# CI action runtime and pins

## Trigger scope

The workflow runs for pull requests and pushes to `main`. Tag pushes remain
enabled, and `workflow_dispatch` remains declared. Feature-branch pushes rely
on an open pull request for automatic checks; a branch without one is not
checked automatically. Forks using a different default branch should update
the push branch filter.

This avoids two identical suites for one PR update. For head `8fa6e1d`, the
[push run](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/actions/runs/38772446978)
and [pull-request run](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/actions/runs/38772455947)
each completed the same ten jobs. The filter removes duplicate starts; it does
not establish a measured reduction in runtime or cost.

GitHub applies `pull_request` branch filters to the target branch; this workflow
leaves PRs unfiltered. Fork contributions remain subject to repository approval
settings. Manual dispatch requires the workflow to exist on the default branch;
keeping the declaration in an unmerged draft does not make manual execution
available there. See GitHub's [push branch and tag filters](https://docs.github.com/en/actions/writing-workflows/workflow-syntax-for-github-actions#onpushbranchestagsbranches-ignoretags-ignore)
and [manual trigger requirements](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#workflow_dispatch).

## Action runtime and pins

The CI workflow uses full commit references for these JavaScript actions:

| Action | Release | Commit |
| --- | --- | --- |
| `actions/checkout` | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `actions/setup-python` | v7.0.0 | `5fda3b95a4ea91299a34e894583c3862153e4b97` |
| `actions/upload-artifact` | v7.0.2 | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` |

Each pinned `action.yml` declares `runs.using: node24`. The previous successful
[run 38697993259](https://github.com/C4LLM3LUC4S/rechorus-patt-reproduction/actions/runs/38697993259)
warned that checkout v4 and setup-python v5 targeted deprecated Node20 and were
being forced onto Node24. This was a maintenance warning, not a failed metric or
installation check. GitHub's [Node20 removal notice](https://github.blog/changelog/2026-09-23-node-20-is-no-longer-available-in-github-actions/)
explains the runtime transition.

The Node24 actions require a runner version of at least 2.327.1. The preceding
Ubuntu and Windows jobs used 2.337.0; a self-hosted runner must be checked
separately. RankProbe currently uses GitHub-hosted runners.

All checkout steps disable persisted credentials; the jobs require no later
authenticated Git operation. The workflow uses ordinary `pull_request` events,
explicit Python versions, and no removed `pip-install` action input. Artifact
v7 defaults to `archive: true`, retaining the existing directory ZIP interface.
See the pinned [checkout](https://github.com/actions/checkout/blob/3d3c42e5aac5ba805825da76410c181273ba90b1/action.yml),
[setup-python](https://github.com/actions/setup-python/blob/5fda3b95a4ea91299a34e894583c3862153e4b97/action.yml),
and [upload-artifact](https://github.com/actions/upload-artifact/blob/cf430e030ddbb5b0abf93d22962f4752f3646cd9/action.yml)
input definitions.

For this migration, acceptance requires all ten expanded jobs on the new commit,
absence of the observed Node20 runtime warning in their logs, and verification
that the four reference/framework artifacts remain available. Inspect at least
one downloaded directory ZIP's digest, CRC, and expected report/check contents.
A prior passing run does not validate changed action code.

The Python matrix, dependency installation, metric definitions, reference source
pins, artifact names, retention, and read-only repository permissions are
unchanged. These pins identify action code; hosted runner images, Python patch
releases, and every dependency are not thereby frozen.
