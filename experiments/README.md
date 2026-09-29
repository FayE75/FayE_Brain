# FayE experiment registry

This directory is the audit trail for engine-development hypotheses.

- `FAYE-xxxx-*.json`: experiment manifests.
- `patches/`: experimental source patches that are applied only to candidate builds until accepted.

A feature should normally move through:

`planned -> training/offline validation -> candidate-vs-parent -> tuning (optional) -> confirmation -> accepted/rejected`.

Accepted changes can then be integrated into `main`; rejected patches stay here as research history instead of contaminating the production engine.

Create a new manifest locally with:

```bash
python3 scripts/register_experiment.py \
  --id FAYE-0002 \
  --title "Tiny uncertainty head" \
  --feature "Use learned instability prediction to guide search" \
  --candidate-ref my-feature-branch \
  --parent-ref main
```
