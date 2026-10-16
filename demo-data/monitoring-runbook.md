# Document verification monitoring runbook

Synthetic operations document. Service: document-verification. Deployment: v2.3.

When accuracy changes, compare releases on the same sample strata. Inspect
deployment configuration, preprocessing changes, warning distributions, latency,
model hashes and decision thresholds. Input drift and code regressions are
competing hypotheses, not interchangeable explanations.

The stroke_preservation warning measures lost high-frequency image structure in
low-resolution scans. A warning does not independently prove a causal regression.
Re-run affected samples with both preprocessing configurations to validate a fix.

Write actions, including issue creation or rollback, require explicit approval.
