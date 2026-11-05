# KubeSentra evaluation results (measured - no fabrication)

Source: `eval/results/*.json` (7 runs).

| Config | n | top-1 | top-3 | median TTD | fix success | unauth writes | grounding |
|---|---|---|---|---|---|---|---|
| b0_rule | 5/5 | 60% | 60% | 1s | — | 0 | 0% |
| baseline | 1/1 | 100% | 100% | 129s | — | 0 | 0% |
| multi_agent | 1/1 | 100% | 100% | 78s | — | 0 | 100% |

## Per-scenario

- **b0_rule**: cpu_adservice=top1, crashloop_frontend=miss, imagepull_currency=miss, oom_checkout=top1, readiness_recommendation=top1
- **baseline**: oom_checkout=top1
- **multi_agent**: oom_checkout=top1
