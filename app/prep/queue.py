"""Serial batch queue. One worker thread: the GPU and the render pipeline are shared,
so jobs run one after another in submission order."""
import logging
import queue
import threading

from app.prep import store
from app.prep.errors import PrepCancelled, PrepError
from app.prep.paths import video_root

logger = logging.getLogger(__name__)


class BatchQueue:

    def __init__(self, root=None, provider_factory=None):
        self._root = root
        self._provider_factory = provider_factory
        self._provider = None
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._cancel_events = {}
        self._worker = threading.Thread(target=self._loop, name='prep-queue', daemon=True)
        self._worker.start()

    def submit(self, pid: str) -> None:
        with self._lock:
            self._cancel_events[pid] = threading.Event()
        self._queue.put(pid)

    def cancel(self, pid: str) -> str:
        """Cancel a queued job immediately, or signal a running job to stop."""
        with self._lock:
            manifest = store.load(pid, self._root)
            if manifest['status'] == 'queued':
                manifest['status'] = 'cancelled'
                manifest['stage'] = '已取消'
                store.save(manifest, self._root)
                return 'cancelled'
            if manifest['status'] == 'running':
                event = self._cancel_events.get(pid)
                if event is None:
                    raise PrepError('無法取消這個工作，請稍後再試。')
                event.set()
                return 'cancelling'
        raise PrepError('這個工作已經結束，無法取消。')

    def _loop(self) -> None:
        while True:
            pid = self._queue.get()
            try:
                self._process(pid)
            except Exception:
                logger.exception('Unexpected failure in batch queue for %s', pid)
            finally:
                self._queue.task_done()

    def _provider_instance(self):
        if self._provider is None:
            if self._provider_factory is not None:
                self._provider = self._provider_factory()
            else:
                from app.transcriber import FasterWhisperProvider
                self._provider = FasterWhisperProvider()
        return self._provider

    def _process(self, pid: str) -> None:
        from app.prep import pipeline

        with self._lock:
            manifest = store.load(pid, self._root)
            if manifest['status'] != 'queued':
                self._cancel_events.pop(pid, None)
                return
            manifest['status'] = 'running'
            manifest['stage'] = '開始處理'
            store.save(manifest, self._root)
            cancel = self._cancel_events.setdefault(pid, threading.Event())

        try:
            transcript = manifest['params'].get('transcript', {}).get('enabled')
            provider = self._provider_instance() if transcript else None
            pipeline.run(manifest, provider, cancel, self._root)
            manifest['status'] = 'done'
        except PrepCancelled:
            manifest['status'] = 'cancelled'
            manifest['stage'] = '已取消'
            _mark_running_steps(manifest, 'cancelled')
        except PrepError as exc:
            manifest['status'] = 'failed'
            manifest['error'] = str(exc)
            manifest['stage'] = '處理失敗'
            _mark_running_steps(manifest, 'failed')
            logger.warning('Prep job %s failed: %s', pid, exc)
        except Exception:
            manifest['status'] = 'failed'
            manifest['error'] = '處理時發生未預期的錯誤，詳細資訊已寫入紀錄。'
            manifest['stage'] = '處理失敗'
            _mark_running_steps(manifest, 'failed')
            logger.exception('Prep job %s crashed', pid)
        finally:
            with self._lock:
                self._cancel_events.pop(pid, None)
                store.save(manifest, self._root)


def _mark_running_steps(manifest: dict, state: str) -> None:
    for step, value in manifest['steps'].items():
        if value == 'running':
            manifest['steps'][step] = state


_queue = None
_queue_lock = threading.Lock()


def get_queue() -> BatchQueue:
    global _queue
    with _queue_lock:
        if _queue is None:
            _queue = BatchQueue(video_root())
        return _queue
