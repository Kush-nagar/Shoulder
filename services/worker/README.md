# Worker boundary

The CPU worker claims jobs from `app.processing_job` (`jobs.py`) and runs the
handlers in `media.py`, `delivery.py` and `retention.py`.

- Local: `python -m services.worker.main` runs until stopped.
- Production (ADR 0028): `.github/workflows/worker.yml` runs
  `python -m services.worker.main --drain`, which exits once the queue has
  been empty for 90 s. A database trigger (migration 0021) wakes it when a job
  is queued; a 6-hourly schedule is the safety net and the retention sweep.
