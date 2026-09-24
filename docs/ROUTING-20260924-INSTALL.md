Task: Repair first-use installation after Python candidate error and shortcut collision.
Complexity: TRIVIAL initial installer guard; SMALL shortcut and launcher integration.
Work packages: 1 (INSTALL-SHORTCUT-01).
DeepSeek calls/tokens/estimated cost: 1 / 0 / USD 0 (blocked before run).
Retries/splits: 0 / 0.
Escalation: Worker lock under AppData returned EPERM in sandbox; local implementation continued.
Validation: Windows PowerShell syntax; failed Python candidate skipped; real Python/dependency/CUDA installation succeeded; shortcut collision/idempotency test passed; installed app returned HTTP 200; local upload reached HTTP 415 and foreign origin was HTTP 403; live server identity test passed.
Final acceptance: Accepted locally after independent checks. Portable ZIP rebuilt; first model transcription on another computer remains untested.
