"""Capture a stack trace if a first-time native-library load stalls."""
import faulthandler
faulthandler.dump_traceback_later(30, repeat=True)
import torch
print(torch.__version__, flush=True)
print(torch.ones(2).sum(), flush=True)
faulthandler.cancel_dump_traceback_later()
