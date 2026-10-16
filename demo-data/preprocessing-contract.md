# Document preprocessing contract

Synthetic reference document. Service: document-verification. Model: verifier-2026-09.
Repository: demo/document-verification. Deployment: v2.2.

The verifier accepts 224 by 224 RGB tensors. Production document thumbnails must
use bicubic interpolation before normalization. Training and evaluation both used
bicubic interpolation. Fine character strokes in low-resolution scans are sensitive
to resampling. Nearest-neighbor is intended only for segmentation masks, not RGB
document thumbnails. Normalization mean/std and decision threshold are versioned.

Validate preprocessing parity, stratified accuracy and source-image quality before
approving a release. A global score can hide subgroup-specific failures.
