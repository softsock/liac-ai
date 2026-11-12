"""Local developer chat and request inspector built from standard Qt widgets."""
import difflib
import json
import os
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Slot
from PySide6.QtGui import QDesktopServices, QFont, QTextCursor
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QPlainTextEdit,
    QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from vtuber.app import Config
from vtuber.desktop.bridge import RuntimeWorker
from vtuber.desktop.reader import TraceReader, details, history
from vtuber.minds.lmstudio import LMStudioSettings
from vtuber.minds.omp import OMPSettings

PREVIEW_CHARS = 200_000


def pretty(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)


def decoded(value):
    """Readable view only; immutable raw JSON remains available separately."""
    if isinstance(value, list):
        return [decoded(item) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key == 'payload_json' and isinstance(item, str):
                try:
                    result['payload'] = decoded(json.loads(item))
                    continue
                except ValueError:
                    pass
            result[key] = decoded(item)
        return result
    return value


def format_omp_context(data):
    parts = ['OMP adapter context; this is not the provider HTTP body.',
             f"Model: {data.get('model')} · Session: {data.get('session_id')}",
             'System instructions\n' + data['system_prompt'], 'OMP history before this request']
    messages = data.get('session_messages')
    if messages is None:
        parts.append('Unavailable: ' + str(data.get('history_error')))
    elif not messages:
        parts.append('(empty session)')
    else:
        for message in messages:
            parts.append('[' + message.get('role', 'unknown') + ']')
            content = message.get('content', '')
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') in ('thinking', 'redactedThinking'):
                        parts.append('(reasoning block omitted)')
                    else:
                        text = block.get('text', pretty(block)) if isinstance(block, dict) else pretty(block)
                        try:
                            text = pretty(decoded(json.loads(text)))
                        except (ValueError, TypeError):
                            pass
                        parts.append(text)
            else:
                parts.append(pretty(content))
    prompt = data['current_prompt']
    try:
        prompt = pretty(decoded(json.loads(prompt)))
    except ValueError:
        pass
    parts.append('Current request · readable JSON view\n' + prompt)
    return '\n\n'.join(parts)


class MainWindow(QMainWindow):
    def __init__(self, root: Path | None = None):
        super().__init__()
        self.root = (root or Path.cwd()).resolve()
        self.worker = None
        self.trace_path = None
        self.records = []
        self._closing = False
        self._reading_history = False
        self._pending_text = ''
        self._journal = []
        self.setWindowTitle('LIAC · Runtime inspector')
        self.resize(1500, 900)
        self.setMinimumSize(1000, 650)
        self.reader = TraceReader(self)
        self.reader.loaded.connect(self._loaded)
        self._build()
        self.flush_timer = QTimer(self)
        self.flush_timer.setInterval(40)
        self.flush_timer.timeout.connect(self._flush)
        self.flush_timer.start()

    def _button(self, text, callback):
        button = QPushButton(text)
        button.clicked.connect(callback)
        return button

    def _view(self):
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setFont(QFont('Consolas', 10))
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        return view

    def _build(self):
        container = QWidget()
        self.setCentralWidget(container)
        layout = QVBoxLayout(container)
        top = QHBoxLayout()
        title = QLabel('LIAC  /  Runtime inspector')
        title.setStyleSheet('font-size: 18px; font-weight: 600;')
        top.addWidget(title)
        top.addStretch()
        self.start = self._button('Start', self.start_runtime)
        self.stop = self._button('Stop', self.stop_runtime)
        self.stop.setEnabled(False)
        self.settings_button = self._button('Settings', self._toggle_settings)
        self.open_history = self._button('Open trace…', self._choose_history)
        for widget in (self.open_history, self.settings_button, self.start, self.stop):
            top.addWidget(widget)
        layout.addLayout(top)
        self.settings = QGroupBox('Connection')
        form = QFormLayout(self.settings)
        self.backend = QComboBox()
        self.backend.addItems(['lmstudio / luna', 'fake / fake', 'lmstudio / fake', 'fake / luna'])
        self.endpoint = QLineEdit('http://127.0.0.1:1230')
        self.model = QLineEdit('liac-nemotron')
        self.tokenizer = QLineEdit(str(self.root / '.data/tokenizers/nemotron.json'))
        candidate = Path(os.environ.get('LOCALAPPDATA', '')) / 'omp/omp.exe'
        self.omp = QLineEdit(str(candidate) if candidate.is_file() else 'omp')
        self.luna_model = QLineEdit('openai-codex/gpt-6-luna')
        self.db = QLineEdit(str(self.root / '.data/desktop/character.sqlite3'))
        for label, field in [('Fast / Deep', self.backend), ('LM Studio', self.endpoint),
                ('Fast model', self.model), ('Tokenizer', self.tokenizer), ('OMP', self.omp),
                ('Luna model', self.luna_model), ('SQLite', self.db)]:
            form.addRow(label, field)
        layout.addWidget(self.settings)
        notice = QLabel('Local developer mode: full contexts and responses are recorded in .data/traces/. Keep this data private.')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        split = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(split, 1)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel('Requests and events'))
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search by ID or event kind')
        self.search.textChanged.connect(self._filter)
        self.category = QComboBox()
        self.category.addItems(['All processes', 'Fast', 'Luna', 'Runtime'])
        self.category.currentTextChanged.connect(self._filter)
        left_layout.addWidget(self.search)
        left_layout.addWidget(self.category)
        self.requests = QListWidget()
        self.requests.currentRowChanged.connect(self._select)
        left_layout.addWidget(self.requests, 1)
        split.addWidget(left)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.addWidget(QLabel('Conversation'))
        self.chat = QPlainTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setMaximumBlockCount(5000)
        self.chat.setPlaceholderText('Start Runtime to chat. Previous messages will be restored from the selected SQLite database.')
        center_layout.addWidget(self.chat, 1)
        self.composer = QPlainTextEdit()
        self.composer.setMaximumHeight(100)
        self.composer.setPlaceholderText('Message the character · Ctrl+Enter to send')
        center_layout.addWidget(self.composer)
        controls = QHBoxLayout()
        self.retry = self._button('Retry Deep', lambda: self.worker.command('retry'))
        self.cancel = self._button('Cancel Fast', lambda: self.worker.command('cancel'))
        self.send = self._button('Send', self.send_message)
        self.send.setDefault(True)
        for button in (self.retry, self.cancel, self.send):
            button.setEnabled(False)
            controls.addWidget(button)
        center_layout.addLayout(controls)
        split.addWidget(center)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.selection = QLabel('Select an event to inspect its request')
        self.selection.setTextFormat(Qt.TextFormat.PlainText)
        self.selection.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right_layout.addWidget(self.selection)
        tools = QHBoxLayout()
        tools.addWidget(self._button('Copy tab', self._copy))
        tools.addWidget(self._button('Open JSON', self._open_json))
        right_layout.addLayout(tools)
        self.tabs = QTabWidget()
        self.input = self._view()
        self.output = self._view()
        self.context = self._view()
        self.context.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.changes = self._view()
        self.metrics = self._view()
        self.raw = self._view()
        self.state_view = self._view()
        self.events_view = self._view()
        for name, view in [('Input', self.input), ('Response', self.output), ('Context', self.context),
                ('Changes', self.changes), ('Metrics', self.metrics), ('JSON', self.raw),
                ('Runtime state', self.state_view), ('Journal', self.events_view)]:
            self.tabs.addTab(view, name)
        self.tabs.setCurrentWidget(self.context)
        right_layout.addWidget(self.tabs, 1)
        split.addWidget(right)
        split.setSizes([280, 430, 650])
        self.statusBar().showMessage('Runtime stopped · open a saved trace or start a conversation')
        from PySide6.QtGui import QKeySequence, QShortcut
        shortcut = QShortcut(QKeySequence('Ctrl+Return'), self.composer)
        shortcut.activated.connect(self.send_message)

    def _toggle_settings(self):
        self.settings.setVisible(not self.settings.isVisible())

    def start_runtime(self):
        if self.worker and self.worker.isRunning():
            return
        try:
            fast, deep = self.backend.currentText().split(' / ')
            tokenizer = Path(self.tokenizer.text()).expanduser().resolve()
            if fast == 'lmstudio' and not tokenizer.is_file():
                raise ValueError('tokenizer.json is missing. Set its path in Settings or follow the tokenizer setup in README.')
            config = Config(db=Path(self.db.text()).expanduser().resolve(), fast_backend=fast, deep_backend=deep,
                deep_timeout=90, tokenizer=tokenizer,
                lmstudio=LMStudioSettings(endpoint=self.endpoint.text().strip(), model=self.model.text().strip()),
                omp=OMPSettings(self.omp.text().strip(), self.luna_model.text().strip(),
                                self.root / '.data/desktop/luna', request_timeout=85))
        except (ValueError, OSError) as error:
            self._error(str(error))
            return
        self.chat.clear()
        self.records.clear()
        self.requests.clear()
        self._journal.clear()
        self.worker = RuntimeWorker(config, self.root / '.data/traces')
        self.worker.ready.connect(self._ready)
        self.worker.output.connect(self._output)
        self.worker.record.connect(self._record)
        self.worker.status.connect(self._status)
        self.worker.journal_events.connect(self._events)
        self.worker.history.connect(self._restore_chat)
        self.worker.failed.connect(self._error)
        self.worker.finished.connect(self._stopped)
        self.settings.setEnabled(False)
        self.start.setEnabled(False)
        self.stop.setEnabled(True)
        self.open_history.setEnabled(False)
        self.statusBar().showMessage('Connecting Runtime…')
        self.worker.start()

    @Slot(str)
    def _ready(self, path):
        self.trace_path = Path(path)
        self.settings.hide()
        for button in (self.send, self.cancel, self.retry):
            button.setEnabled(True)
        self.composer.setFocus()

    @Slot()
    def _stopped(self):
        self.worker.wait()  # finished was emitted; join native thread-local teardown.
        self._flush()
        for button in (self.send, self.cancel, self.retry, self.stop):
            button.setEnabled(False)
        self.settings.setEnabled(True)
        self.start.setEnabled(True)
        self.open_history.setEnabled(True)
        self.statusBar().showMessage('Runtime stopped · recorded traces are saved')
        if self._closing:
            self.close()

    @Slot()
    def stop_runtime(self):
        if self.worker:
            for button in (self.send, self.cancel, self.retry, self.stop):
                button.setEnabled(False)
            self.worker.command('stop')
            self.statusBar().showMessage('Stopping Fast, Luna and OMP…')

    @Slot()
    def send_message(self):
        text = self.composer.toPlainText()
        if text.strip() and self.worker and self.send.isEnabled():
            self._flush()
            self._append_chat('\nYou\n' + text + '\n')
            self.composer.clear()
            self.worker.command('submit', text)

    def _append_chat(self, text):
        scrollbar = self.chat.verticalScrollBar()
        following = scrollbar.value() >= scrollbar.maximum() - 4
        cursor = QTextCursor(self.chat.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        if following:
            scrollbar.setValue(scrollbar.maximum())

    @Slot(object)
    def _restore_chat(self, events):
        for event in events:
            payload = json.loads(event['payload_json'])
            role = 'You' if event['kind'] == 'user.message.completed' else 'Fast'
            self._append_chat(f"\n{role} · restored\n{payload['text']}\n")

    @Slot(object)
    def _output(self, output):
        if output.kind == 'reply.delta':
            self._pending_text += output.text
        else:
            self._flush()
            if output.kind == 'reply.started':
                self._append_chat(f'\nFast · {output.turn_id}\n')
            elif output.kind.startswith('reply.'):
                self._append_chat(f'\n[{output.kind}: {output.text if output.kind != "reply.completed" else "done"}]\n')
            else:
                self.statusBar().showMessage(f'{output.kind} · {output.text}')

    def _flush(self):
        if self._pending_text:
            self._append_chat(self._pending_text)
            self._pending_text = ''

    @Slot(object)
    def _record(self, record):
        self.records.append(record)
        row = record['row']
        item = QListWidgetItem(f"{row['time'][11:23]}  {row['kind']}\n{row['request_id']}")
        item.setToolTip(row['request_id'])
        self.requests.addItem(item)
        self._filter()
        selected = self.requests.currentRow()
        if selected < 0:
            self.requests.setCurrentRow(0)
        elif self.records[selected]['row']['request_id'] == row['request_id']:
            self._select(selected)

    def _filter(self):
        text = self.search.text().lower()
        prefix = {'Fast': ('fast.',), 'Luna': ('deep.', 'omp.'), 'Runtime': ('runtime.',)}.get(self.category.currentText())
        for i, record in enumerate(self.records):
            row = record['row']
            matches = text in (row['request_id'] + ' ' + row['kind']).lower()
            matches &= prefix is None or row['kind'].startswith(prefix)
            self.requests.item(i).setHidden(not matches)

    def _select(self, index):
        if not 0 <= index < len(self.records):
            return
        record = self.records[index]
        key = record['row']['request_id']
        self.selection.setText(record['row']['kind'] + '\n' + key)
        related = [r for r in self.records if r['row']['request_id'] == key and r['path'] == record['path']]
        self._reading_history = False
        self.reader.load(lambda: {'records': details(related), 'selected': record['row']['sequence']})

    @Slot(int, object, str)
    def _loaded(self, token, result, error):
        if token != self.reader.token or self._closing:
            return
        if error:
            self._error(error)
            return
        if self._reading_history:
            self.records = []
            self.requests.clear()
            for record in result:
                # Build once, avoiding repeated filtering/selection while importing.
                self.records.append(record)
                row = record['row']
                self.requests.addItem(f"{row['time'][11:23]}  {row['kind']}\n{row['request_id']}")
            self._reading_history = False
            self._filter()
            if self.records:
                self.requests.setCurrentRow(0)
            self.statusBar().showMessage('Saved trace · unfinished requests may have been interrupted')
            return
        rows = result['records']
        by_kind = {r['kind']: r['data'] for r in rows}
        first = by_kind.get('fast.started', {})
        deep = by_kind.get('deep.started', {})
        self._set(self.input, first.get('message', deep.get('request', 'Input is unavailable in this record.')))
        finish = by_kind.get('fast.finished')
        response = by_kind.get('deep.response')
        terminal = by_kind.get('deep.failed') or by_kind.get('deep.cancelled')
        decision_data = by_kind.get('deep.decision', {}).get('decision')
        self._set(self.output, finish or {'response': response, 'terminal': terminal,
                  'decision': decision_data} if finish or response or terminal or decision_data else
                  'No terminal record: this request is still running or was interrupted.')
        fast_context = by_kind.get('fast.context')
        omp_context = by_kind.get('omp.context')
        if fast_context:
            self._set(self.context, 'Exact Fast prompt\n\n' + fast_context['prompt'] +
                      '\n\nMessages before template rendering\n\n' + pretty(fast_context['messages']))
        elif omp_context:
            self._set(self.context, format_omp_context(omp_context))
        else:
            self._set(self.context, by_kind.get('deep.prompt') or deep or
                      {'notice': 'Exact prompt was not captured (fake backend or old trace).', **first})
        decision = by_kind.get('deep.decision')
        if decision:
            before, after = decision['before'], decision['after']
            old = pretty({'note': before['state']['context_note'], 'epoch': before['epoch']}).splitlines()
            new = pretty({'note': after['state']['context_note'], 'epoch': after['epoch']}).splitlines()
            diff = '\n'.join(difflib.unified_diff(old, new, fromfile='Before', tofile='After', lineterm=''))
            self._set(self.changes, pretty(decision['decision']) + '\n\n' + (diff or 'Context did not change.'))
        else:
            self._set(self.changes, by_kind.get('runtime.epoch', 'No context change decision was recorded.'))
        self._set(self.metrics, {'fast': (finish or {}).get('metrics'),
                  'context': (fast_context or {}).get('metadata'), 'omp': by_kind.get('omp.completed'),
                  'deep': (decision or {}).get('metrics'),
                  'lifecycle': [r['kind'] for r in rows]})
        selected = next((r for r in rows if r['sequence'] == result['selected']), rows[-1])
        self._set(self.raw, selected)

    def _set(self, view, value):
        text = pretty(value)
        if len(text) > PREVIEW_CHARS:
            text = text[:PREVIEW_CHARS] + '\n\n[Preview truncated. Use Open JSON to view the complete record.]'
        if view.toPlainText() != text:
            view.setPlainText(text)

    @Slot(object)
    def _status(self, data):
        self._set(self.state_view, data)
        deep = data['deep']
        lag = data['journal_sequence'] - data['deep_cursor']
        error = data.get('trace_error') or deep.get('error')
        self.statusBar().showMessage(f"Fast: {data['fast'].get('generation', {}).get('status', 'ready')}  |  "
            f"Luna: {deep.get('lifecycle', deep.get('backend', ''))}  |  lag {lag}  |  "
            f"epoch {data['epoch']['version']}" + (f'  |  {error}' if error else ''))

    @Slot(object)
    def _events(self, events):
        self._journal = (self._journal + events)[-500:]
        self._set(self.events_view, self._journal)

    @Slot(str)
    def _error(self, message):
        self.statusBar().showMessage('Error: ' + message)
        self._append_chat('\n[Error: ' + message + ']\n')

    def _choose_history(self):
        folder = QFileDialog.getExistingDirectory(self, 'Select a run-* folder containing index.jsonl', str(self.root / '.data/traces'))
        if folder:
            self.load_history(Path(folder))

    def load_history(self, path):
        if self.worker and self.worker.isRunning():
            self._error('Stop Runtime before opening another trace.')
            return
        self.trace_path = Path(path)
        self.records = []
        self.requests.clear()
        self.selection.setText('Loading saved trace…')
        self._reading_history = True
        self.reader.load(lambda: history(path))

    def _copy(self):
        from PySide6.QtWidgets import QApplication
        view = self.tabs.currentWidget()
        QApplication.clipboard().setText(view.textCursor().selectedText() or view.toPlainText())

    def _open_json(self):
        index = self.requests.currentRow()
        if 0 <= index < len(self.records):
            record = self.records[index]
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(record['path']) / record['row']['file'])))

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self._closing = True
            self.worker.command('stop')
            self.setEnabled(False)
            self.statusBar().showMessage('Stopping Fast, Luna and OMP…')
            event.ignore()
        elif self.reader.busy:
            self._closing = True
            self.reader.stop()
            QTimer.singleShot(20, self.close)
            event.ignore()
        else:
            self._closing = True
            self.reader.stop()
            self.reader.join()
            event.accept()
