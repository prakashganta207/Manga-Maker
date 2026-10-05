"""One GPU, one user at a time: drawing (job worker) and LoRA training share this lock."""

import threading

GPU_LOCK = threading.RLock()
