import logging
from threading import Event, Thread

from app.processing.service import process_next, recover_interrupted

logger = logging.getLogger(__name__)


class ProcessingWorker:
    def __init__(self):
        self.stop_requested = Event()
        self.thread = Thread(target=self.run, name='credit-processing', daemon=True)

    def start(self):
        recover_interrupted()
        self.thread.start()

    def stop(self):
        self.stop_requested.set()
        self.thread.join()

    def run(self):
        while not self.stop_requested.is_set():
            try:
                if process_next():
                    continue
            except Exception:
                logger.exception('Не удалось выполнить обработку заявки')
            self.stop_requested.wait(0.5)
