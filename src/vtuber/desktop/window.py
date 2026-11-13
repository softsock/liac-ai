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
    QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget, QCheckBox, QSpinBox, QDoubleSpinBox)

from vtuber.app import Config
from vtuber.desktop.bridge import RuntimeWorker
from vtuber.desktop.reader import TraceReader, details, history
from vtuber.minds.lmstudio import LMStudioSettings
from vtuber.minds.omp import OMPSettings
from vtuber.desktop.models import ConversationView
from vtuber.lab.archive import RunReader

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
        self.run_reader = None
        self._page_offset = 0
        self._pending_simulation = None
        self._resume_path = None
        self.setWindowTitle('LIAC · Conversation Lab')
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
        title = QLabel('LIAC  /  Conversation Lab')
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
        self.initiative = QCheckBox('Enable initiative')
        form.addRow(self.initiative)
        for label, field in [('Fast / Deep', self.backend), ('LM Studio', self.endpoint),
                ('Fast model', self.model), ('Tokenizer', self.tokenizer), ('OMP', self.omp),
                ('Luna model', self.luna_model), ('SQLite', self.db)]:
            form.addRow(label, field)
        layout.addWidget(self.settings)
        self.simulation = QGroupBox('Simulation')
        sim = QHBoxLayout(self.simulation)
        self.scenario = QLineEdit('skin-creator')
        self.scenario.setMaximumWidth(170)
        self.sim_turns = QSpinBox()
        self.sim_turns.setRange(1,100000)
        self.sim_turns.setValue(120)
        self.sim_duration = QSpinBox()
        self.sim_duration.setRange(0,86400*30)
        self.sim_duration.setSpecialValueText('No duration limit')
        self.sim_duration.setSuffix(' s')
        self.sim_model = QLineEdit('openai-codex/gpt-6-luna')
        self.sim_start = self._button('Start simulation', self.start_simulation)
        for widget in (QLabel('Scenario'),self.scenario,QLabel('Turns'),self.sim_turns,
                       self.sim_duration,self.sim_model,self.sim_start):
            sim.addWidget(widget)
        for text,action in [('Pause','simulation.pause'),('Resume','simulation.resume'),('Stop simulation','simulation.stop')]:
            sim.addWidget(self._button(text,lambda checked=False,a=action:self.worker.command(a) if self.worker else None))
        sim.addWidget(self._button('Resume saved…',self.resume_simulation))
        layout.addWidget(self.simulation)
        self.sim_progress = QLabel('Simulation idle · manual input pauses the simulated user')
        layout.addWidget(self.sim_progress)
        self.usage_label = QLabel('Provider usage / cost: unavailable until reported')
        layout.addWidget(self.usage_label)
        notice = QLabel('Local developer mode: full contexts and responses are recorded in .data/lab/. Keep this data private.')
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
        self.category.addItems(['All processes', 'Fast', 'Luna', 'Runtime', 'Context', 'Initiative', 'Simulator'])
        self.category.currentTextChanged.connect(self._filter)
        left_layout.addWidget(self.search)
        left_layout.addWidget(self.category)
        self.requests = QListWidget()
        self.requests.currentRowChanged.connect(self._select)
        left_layout.addWidget(self.requests, 1)
        page_controls = QHBoxLayout()
        page_controls.addWidget(self._button('Earlier',lambda:self._page(-200)))
        page_controls.addWidget(self._button('Later',lambda:self._page(200)))
        page_controls.addWidget(self._button('Refresh archive',self._refresh_archive))
        left_layout.addLayout(page_controls)
        split.addWidget(left)
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.addWidget(QLabel('Conversation'))
        self.chat = ConversationView()
        self.chat.clicked.connect(lambda index:self._select_turn(index.data(Qt.ItemDataRole.UserRole)['turn_id']))
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
        self.context_points = QComboBox()
        self.context_points.addItem('Context Timeline · select a captured point')
        self.context_points.currentIndexChanged.connect(self._context_point)
        right_layout.addWidget(self.context_points)
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
        for name, view in [('Input / Prompt', self.input), ('Output / Proposals', self.output), ('Context', self.context),
                ('Context / Diff', self.changes), ('Metrics', self.metrics), ('Raw JSON', self.raw),
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
                initiative_enabled=self.initiative.isChecked(),
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
        self.worker = RuntimeWorker(config, self.root / '.data/lab',simulation=self._pending_simulation,
                                    resume=self._resume_path)
        self._pending_simulation = None
        self._resume_path = None
        self.worker.ready.connect(self._ready)
        self.worker.output.connect(self._output)
        self.worker.record.connect(self._record)
        self.worker.status.connect(self._status)
        self.worker.journal_events.connect(self._events)
        self.worker.history.connect(self._restore_chat)
        self.worker.conversation_input.connect(self._conversation_input)
        self.worker.simulation_status.connect(self._simulation_status)
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
        elif self._pending_simulation:
            QTimer.singleShot(0,self.start_runtime)

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
            self.composer.clear()
            self.worker.command('submit', text)

    def _append_chat(self, text):
        self.chat.conversation.update(dict(turn_id='notice-'+str(len(self.chat.conversation.rows)),
            role='boundary',origin='runtime',text=text,status='notice'))

    @Slot(object)
    def _restore_chat(self, events):
        for event in events:
            payload = json.loads(event['payload_json'])
            self.chat.conversation.update(dict(turn_id=event['turn_id'],
                role='user' if event['kind']=='user.message.completed' else 'assistant',
                origin='manual' if event['kind']=='user.message.completed' else
                    ('initiative' if event['turn_id'].startswith('initiative_turn_') else 'reply'),
                text=payload['text'],status='restored'))

    @Slot(object)
    def _output(self, output):
        if not output.kind.startswith('reply.'):
            self.statusBar().showMessage(f'{output.kind} · {output.text}')
            return
        row = next((r for r in self.chat.conversation.rows if r.get('turn_id')==output.turn_id
                    and r.get('role')=='assistant'),{})
        text = (row.get('text','')+output.text if output.kind=='reply.delta' else
                output.text if output.kind=='reply.completed' else row.get('text',''))
        self.chat.conversation.update(dict(turn_id=output.turn_id,role='assistant',
            origin='initiative' if output.turn_id.startswith('initiative_turn_') else 'reply',
            text=text,status=output.kind.removeprefix('reply.'),reason=output.text if output.kind.endswith(('failed','cancelled')) else ''))

    def _flush(self):
        pass

    @Slot(object)
    def _record(self, record):
        self.records.append(record)
        row = record['row']
        item = QListWidgetItem(f"{row['time'][11:23]}  {row['kind']}\n{row['request_id']}")
        item.setToolTip(row['request_id'])
        self.requests.addItem(item)
        if len(self.records)>1000:
            del self.records[0]
            self.requests.takeItem(0)
        self._filter()
        selected = self.requests.currentRow()
        if selected < 0:
            self.requests.setCurrentRow(0)
        elif self.records[selected]['row']['request_id'] == row['request_id']:
            self._select(selected)

    def _filter(self):
        text = self.search.text().lower()
        prefix = {'Fast': ('fast.',), 'Luna': ('deep.', 'omp.'), 'Runtime': ('runtime.',),
                  'Context':('runtime.context','runtime.epoch','deep.decision'),
                  'Initiative':('initiative.',), 'Simulator':('simulator.',)}.get(self.category.currentText())
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
            self.run_reader = result['reader']
            self.chat.conversation.reset(result['conversation'])
            self.context_points.clear()
            self.context_points.addItem('Context Timeline · captured points')
            for point in self.run_reader.contexts:
                snapshot = point['snapshot']
                self.context_points.addItem(f"#{point['sequence']} · revision {snapshot['state']['revision']} · epoch {snapshot['epoch']['version']}",snapshot)
            self._set(self.metrics,result['summary'])
            self.records = []
            self.requests.clear()
            for record in result['records']:
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
        if not rows:
            self._set(self.raw,'No related records were captured.')
            return
        by_kind = {r['kind']: r['data'] for r in rows}
        first = by_kind.get('fast.started', {})
        deep = by_kind.get('deep.started', {})
        self._set(self.input, first.get('message', deep.get('request', 'Input is unavailable in this record.')))
        finish = by_kind.get('fast.finished')
        response = by_kind.get('deep.response')
        terminal = by_kind.get('deep.failed') or by_kind.get('deep.cancelled')
        decision_data = by_kind.get('deep.decision', {}).get('decision')
        self._set(self.output, finish or {'response': response, 'terminal': terminal,
                  'proposal':by_kind.get('deep.decision',{}).get('result'),
                  'decision': decision_data} if finish or response or terminal or decision_data else
                  by_kind.get('fast.progress') or list(by_kind.values()))
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
            old = before['state']['context_note'].splitlines()
            new = after['state']['context_note'].splitlines()
            diff = '\n'.join(difflib.unified_diff(old, new, fromfile='Before', tofile='After', lineterm=''))
            self._set(self.changes, pretty(decision['decision']) + '\n\n' + (diff or 'Markdown did not change.')+
                      '\n\nEpoch before\n'+pretty(before['epoch'])+'\n\nEpoch after\n'+pretty(after['epoch']))
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
        usage = data.get('usage',{})
        if usage:
            self.sim_progress.setToolTip('Provider usage (not billing confirmation): '+pretty(usage))
            def cost(actor):
                value = usage.get(actor,{}).get('cost_total')
                return f'${value:.5f}' if value is not None else 'unavailable'
            self.usage_label.setText(f"Reported provider cost: Luna {cost('luna')} · Simulator {cost('simulator')} (estimate)")
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
        def load():
            reader = RunReader(path)
            return dict(reader=reader,conversation=reader.page('conversation',offset=max(0,len(reader.conversation)-200)),
                records=[{'row':r,'path':r['path']} for r in reader.page('timeline',offset=self._page_offset)],
                summary=reader.summary())
        self.reader.load(load)

    @Slot(object)
    def _conversation_input(self,row):
        self.chat.conversation.update(row)

    @Slot(object)
    def _simulation_status(self,state):
        self.sim_progress.setText(f"Simulation: {state['phase']} · session {state['session']} · turns {state['turns']} · {state['elapsed_seconds']:.0f} s")

    def start_simulation(self):
        from vtuber.lab.__main__ import scenario
        try:
            self._pending_simulation = dict(scenario=scenario(self.scenario.text()),turns=self.sim_turns.value(),
                duration_seconds=self.sim_duration.value() or None,simulator_model=self.sim_model.text(),
                omp_executable=self.omp.text(),pause_scale=1)
        except (OSError,ValueError) as error:
            self._error(str(error))
            return
        if self.worker and self.worker.isRunning():
            self.stop_runtime()
        else:
            self.start_runtime()

    def resume_simulation(self):
        folder = QFileDialog.getExistingDirectory(self,'Resume a stopped simulation',str(self.root/'.data/lab'))
        if folder:
            reader = RunReader(Path(folder))
            self._pending_simulation = reader.manifest.get('simulation')
            self._resume_path = Path(folder)
            if self.worker and self.worker.isRunning():
                self.stop_runtime()
            else:
                self.start_runtime()

    def _select_turn(self,turn_id):
        for i,record in enumerate(self.records):
            if record['row']['request_id']==turn_id:
                self.requests.setCurrentRow(i)
                return
        if self.run_reader:
            self.reader.load(lambda:dict(records=self.run_reader.related(turn_id),selected=-1))

    def _context_point(self,index):
        snapshot = self.context_points.itemData(index)
        if snapshot:
            self._set(self.changes,'Captured Markdown\n\n'+snapshot['state']['context_note']+
                      '\n\nContext Epoch\n'+pretty(snapshot['epoch']))
            self.tabs.setCurrentWidget(self.changes)

    def _page(self,delta):
        if not self.run_reader:
            return
        self._page_offset = max(0,self._page_offset+delta)
        rows = self.run_reader.page('timeline',offset=self._page_offset)
        self.records = [{'row':r,'path':r['path']} for r in rows]
        self.requests.clear()
        for row in rows:
            self.requests.addItem(f"{row['time'][11:23]}  {row['kind']}\n{row['request_id']}")
        total = len(self.run_reader.conversation)
        offset = max(0,min(total-200,self._page_offset))
        self.chat.conversation.reset(self.run_reader.page('conversation',offset=offset))
        self._filter()

    def _refresh_archive(self):
        if self.trace_path:
            if self.worker and self.worker.isRunning():
                self._error('Stop Runtime to open the complete archive; live events remain visible.')
            else:
                self.load_history(self.trace_path)

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
