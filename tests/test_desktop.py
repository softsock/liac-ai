import importlib.util
import os
import tempfile
import time
import unittest
from pathlib import Path

if importlib.util.find_spec('PySide6') is None:
    raise unittest.SkipTest('Install the optional desktop extra')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from vtuber.app import Config
from vtuber.desktop.bridge import RuntimeWorker

APP = QApplication.instance() or QApplication([])


def tearDownModule():
    from PySide6.QtCore import QCoreApplication, QEvent
    # close() hides a test window but does not destroy its widgets/popups.
    for widget in APP.topLevelWidgets():
        worker = getattr(widget, 'worker', None)
        if worker is not None:
            worker.command('stop')
            worker.wait(5000)
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    APP.shutdown()


def until(predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while not predicate():
        APP.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError('Desktop operation timed out')
        time.sleep(.005)
    APP.processEvents()


class BridgeTests(unittest.TestCase):
    def test_stream_cancel_retry_and_graceful_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            worker = RuntimeWorker(Config(db=root / 'journal.db', fast_delay=.01, deep_delay=0), root / 'traces')
            outputs, records, errors, ready = [], [], [], []
            worker.output.connect(outputs.append)
            worker.record.connect(records.append)
            worker.failed.connect(errors.append)
            worker.ready.connect(ready.append)
            worker.start()
            try:
                until(lambda: ready)
                worker.command('submit', 'first ' * 40)
                until(lambda: any(o.kind == 'reply.delta' for o in outputs))
                worker.command('cancel')
                until(lambda: any(o.kind == 'reply.cancelled' for o in outputs))
                worker.command('retry')
                worker.command('submit', 'second')
                until(lambda: any(o.kind == 'reply.completed' for o in outputs))
                self.assertTrue(any(r['row']['kind'] == 'fast.finished' for r in records))
            finally:
                worker.command('stop')
                until(lambda: not worker.isRunning())
            self.assertEqual(errors, [])
            # The same database can be owned again after a complete shutdown.
            reopened = RuntimeWorker(Config(db=root / 'journal.db'), root / 'traces')
            reopened.start()
            reopened.command('stop')
            until(lambda: not reopened.isRunning())

    def test_invalid_setup_reports_failure_and_thread_exits(self):
        with tempfile.TemporaryDirectory() as folder:
            worker = RuntimeWorker(Config(db=Path(folder)), Path(folder) / 'traces')
            errors = []
            worker.failed.connect(errors.append)
            worker.start()
            until(lambda: not worker.isRunning())
            self.assertTrue(errors)


class WindowTests(unittest.TestCase):
    def test_paged_model_and_stale_detail_completion(self):
        from vtuber.desktop.window import MainWindow
        window = MainWindow()
        rows = [dict(turn_id=str(i),role='user',origin='simulated',text=str(i)) for i in range(10000)]
        window.chat.conversation.reset(rows)
        self.assertEqual(window.chat.conversation.rowCount(),1000)
        window.chat.conversation.reset(rows[:200])
        self.assertEqual(window.chat.conversation.rows[0]['text'],'0')
        window.reader.token = 9
        window.raw.setPlainText('current selection')
        window._loaded(8,{'records':[]},'stale failure')
        self.assertEqual(window.raw.toPlainText(),'current selection')
        window.close()

    def test_lab_controls_and_replay_origin(self):
        from vtuber.desktop.window import MainWindow
        from vtuber.tracing import TraceRecorder
        with tempfile.TemporaryDirectory() as folder:
            trace = TraceRecorder(Path(folder))
            trace('conversation.input','t',{'text':'hello','origin':'simulated','session':2})
            trace('fast.started','t',{'message':{'text':'hello','turn_id':'t'}})
            trace('fast.finished','t',{'text':'hi','status':'completed'})
            window = MainWindow(root=Path(folder))
            window.show()
            self.assertFalse(window.initiative.isChecked())
            window.load_history(trace.path)
            until(lambda: 'hello' in window.chat.toPlainText())
            self.assertIn('Simulated user',window.chat.toPlainText())
            self.assertIsNone(window.worker)
            window.close()

    def test_luna_response_retains_parsing_failure(self):
        from vtuber.desktop.window import MainWindow
        with tempfile.TemporaryDirectory() as folder:
            window = MainWindow(root=Path(folder))
            window._loaded(window.reader.token, {'selected': 2, 'records': [
                {'kind':'deep.response','sequence':1,'data':{'text':'{bad json'}},
                {'kind':'deep.failed','sequence':2,'data':{'error':'ValueError','reason':'Invalid JSON'}}]}, '')
            self.assertIn('Invalid JSON', window.output.toPlainText())
            self.assertIn('{bad json', window.output.toPlainText())
            window.close()

    def test_luna_context_is_readable_without_escaped_json(self):
        from vtuber.desktop.window import format_omp_context
        text = format_omp_context({'system_prompt':'role\nidentity', 'session_messages':[],
            'current_prompt':'{"events":[{"payload_json":"{\\"text\\":\\"green\\"}"}]}',
            'model':'luna', 'session_id':'session', 'history_error':None})
        self.assertIn('role\nidentity', text)
        self.assertIn('"text": "green"', text)
        self.assertNotIn('\\"', text)

    def test_chat_context_selection_and_offline_history(self):
        from vtuber.desktop.window import MainWindow
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            window = MainWindow(root=root)
            window.show()
            window.backend.setCurrentText('fake / fake')
            window.db.setText(str(root / 'journal.db'))
            window.start_runtime()
            try:
                until(lambda: window.send.isEnabled())
                window.composer.setPlainText('green hat')
                window.send_message()
                until(lambda: 'You said: green hat' in window.chat.toPlainText())
                until(lambda: any(r['row']['kind'] == 'deep.decision' for r in window.records))
                index = next(i for i, r in enumerate(window.records) if r['row']['kind'] == 'deep.started')
                window.requests.setCurrentRow(index)
                until(lambda: 'green hat' in window.context.toPlainText())
                path = window.trace_path
                window.worker.command('stop')
                until(lambda: not window.worker.isRunning())
                window.load_history(path)
                until(lambda: window.requests.count() > 0)
                window.search.setText('no-such-request')
                self.assertTrue(all(window.requests.item(i).isHidden() for i in range(window.requests.count())))
            finally:
                if window.worker and window.worker.isRunning():
                    window.worker.command('stop')
                    until(lambda: not window.worker.isRunning())
                window.close()
                until(lambda: not window.isVisible())
