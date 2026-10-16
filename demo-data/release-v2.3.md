# Release v2.3 rollout notes

Synthetic deployment record. Service: document-verification. Deployment: v2.3.
Repository: demo/document-verification. Model: verifier-2026-09.

Release v2.3 includes request tracing, a thumbnail-path optimization, updated
dashboard labels and a dependency lock refresh. The model checkpoint remains
verifier-2026-09 with SHA256 weights-4b17ac. Decision threshold remains 0.85.
Document traffic still contains 70 percent high-resolution and 30 percent
low-resolution scans. No model retraining or new training corpus was deployed.

The rollout completed on 2026-10-10 at 10:00 UTC. Compare subgroup metrics and
image preprocessing parity before deciding whether the model itself changed.
