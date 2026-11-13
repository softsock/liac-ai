"""Bounded visible conversation rows; archived pages remain available off-thread."""
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtWidgets import QListView, QAbstractItemView


def label(row):
    if row.get('role')=='boundary':
        return 'Session / pause'
    if row.get('role')=='user':
        return 'Simulated user' if row.get('origin')=='simulated' else 'Real user'
    return 'Liac initiative' if row.get('origin')=='initiative' else 'Liac reply'


class ConversationModel(QAbstractListModel):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.rows = []

    def rowCount(self,parent=QModelIndex()):
        return len(self.rows) if not parent.isValid() else 0

    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row()>=len(self.rows):
            return None
        row = self.rows[index.row()]
        if role==Qt.ItemDataRole.DisplayRole:
            return f"{label(row)} · {row.get('status','')} · {row.get('turn_id','')}\n{row.get('text','')}"
        if role==Qt.ItemDataRole.UserRole:
            return row

    def reset(self,rows):
        self.beginResetModel()
        self.rows = list(rows)[-1000:]
        self.endResetModel()

    def update(self,row):
        key = (row.get('turn_id'),row.get('role'))
        for i,item in enumerate(self.rows):
            if (item.get('turn_id'),item.get('role'))==key:
                self.rows[i] = {**item,**row}
                self.dataChanged.emit(self.index(i),self.index(i))
                return
        if len(self.rows)>=1000:
            self.beginRemoveRows(QModelIndex(),0,0)
            del self.rows[0]
            self.endRemoveRows()
        self.beginInsertRows(QModelIndex(),len(self.rows),len(self.rows))
        self.rows.append(row)
        self.endInsertRows()


class ConversationView(QListView):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.conversation = ConversationModel(self)
        self.setModel(self.conversation)
        self.setWordWrap(True)
        self.setSpacing(8)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    def toPlainText(self):
        return '\n\n'.join(self.conversation.data(self.conversation.index(i)) for i in range(self.conversation.rowCount()))

    def clear(self):
        self.conversation.reset([])
