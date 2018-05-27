# Copyright (C) 2011 Chris Dekter
# Copyright (C) 2018 Thomas Hess <thomas.hess@udo.edu>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
import os.path
import logging

from PyQt4.QtCore import Qt
from PyQt4.QtGui import QHeaderView, QMessageBox, QFileDialog, QAction, QWidget, QIcon, QMenu, QCursor
from PyQt4.QtGui import QListWidget, QListWidgetItem, QBrush

from autokey import iomediator
from autokey import model
from autokey import configmanager as cm

from . import common as ui_common
from . import autokey_treewidget as ak_tree


logger = ui_common.logger.getChild("CentralWidget")  # type: logging.Logger


class CentralWidget(*ui_common.inherits_from_ui_file_with_name("centralwidget")):

    def __init__(self, parent):
        super(CentralWidget, self).__init__(parent)
        logger.debug("CentralWidget instance created.")
        self.setupUi(self)
        self.dirty = False
        self.configManager = None
        self.recorder = iomediator.Recorder(self.scriptPage)

        self.cutCopiedItems = []
        for column_index in range(3):
            self.treeWidget.setColumnWidth(column_index, cm.ConfigManager.SETTINGS[cm.COLUMN_WIDTHS][column_index])

        h_view = self.treeWidget.header()
        h_view.setResizeMode(QHeaderView.ResizeMode(QHeaderView.Interactive | QHeaderView.ResizeToContents))

        self.logHandler = None
        self.listWidget.hide()

        self.factory = None  # type: ak_tree.WidgetItemFactory
        self.context_menu = None  # type: QMenu
        self.action_clear_log = self._create_action("edit-clear-history", "Clear Log", None, self.on_clear_log)
        self.listWidget.addAction(self.action_clear_log)
        self.action_save_log = self._create_action("edit-clear-history", "Save Log As…", None, self.on_save_log)
        self.listWidget.addAction(self.action_save_log)

    @staticmethod
    def _create_action(icon_name: str, text: str, parent: QWidget=None, to_be_called_slot_function=None) -> QAction:
        icon = QIcon.fromTheme(icon_name)
        action = QAction(icon, text, parent)
        action.triggered.connect(to_be_called_slot_function)
        return action

    def init(self, app):
        self.configManager = app.configManager
        self.logHandler = ListWidgetHandler(self.listWidget, app)
        # Create and connect the custom context menu
        self.context_menu = self._create_treewidget_context_menu()
        self.treeWidget.customContextMenuRequested.connect(lambda position: self.context_menu.popup(QCursor.pos()))

    def _create_treewidget_context_menu(self) -> QMenu:
        main_window = self.topLevelWidget()
        context_menu = QMenu()
        context_menu.addAction(main_window.action_create)
        context_menu.addAction(main_window.action_rename_item)
        context_menu.addAction(main_window.action_clone_item)
        context_menu.addAction(main_window.action_cut_item)
        context_menu.addAction(main_window.action_copy_item)
        context_menu.addAction(main_window.action_paste_item)
        context_menu.addSeparator()
        context_menu.addAction(main_window.action_delete_item)
        context_menu.addSeparator()
        context_menu.addAction(main_window.action_run_script)
        return context_menu

    def populate_tree(self, config):
        self.factory = ak_tree.WidgetItemFactory(config.folders)
        root_folders = self.factory.get_root_folder_list()
        for item in root_folders:
            self.treeWidget.addTopLevelItem(item)

        self.treeWidget.sortItems(0, Qt.AscendingOrder)
        self.treeWidget.setCurrentItem(self.treeWidget.topLevelItem(0))
        self.on_treeWidget_itemSelectionChanged()

    def set_splitter(self, window_size):
        pos = cm.ConfigManager.SETTINGS[cm.HPANE_POSITION]
        self.splitter.setSizes([pos, window_size.width() - pos])

    def set_dirty(self, dirty: bool):
        self.dirty = dirty

    def promptToSave(self):
        if cm.ConfigManager.SETTINGS[cm.PROMPT_TO_SAVE]:
            # TODO: i18n
            result = QMessageBox.question(
                self.topLevelWidget(),
                "Save changes?",
                "There are unsaved changes. Would you like to save them?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )

            if result == QMessageBox.Yes:
                return self.on_save()
            elif result == QMessageBox.Cancel:
                return True
            else:
                return False
        else:
            # don't prompt, just save
            return self.on_save()

    # ---- Signal handlers

    def on_treeWidget_itemChanged(self, item, column):
        if item is self.treeWidget.selectedItems()[0] and column == 0:
            newText = str(item.text(0))
            if ui_common.validate(
                    not ui_common.EMPTY_FIELD_REGEX.match(newText),
                    "The name can't be empty.",
                    None,
                    self.topLevelWidget()):
                self.topLevelWidget().app.monitor.suspend()
                self.stack.currentWidget().set_item_title(newText)
                self.stack.currentWidget().rebuild_item_path()

                persistGlobal = self.stack.currentWidget().save()
                self.topLevelWidget().app.monitor.unsuspend()
                self.topLevelWidget().app.config_altered(persistGlobal)

                self.treeWidget.sortItems(0, Qt.AscendingOrder)
            else:
                item.update()

    def on_treeWidget_itemSelectionChanged(self):
        model_items = self.__getSelection()

        if len(model_items) == 1:
            model_item = model_items[0]
            if isinstance(model_item, model.Folder):
                self.stack.setCurrentIndex(0)
                self.folderPage.load(model_item)

            elif isinstance(model_item, model.Phrase):
                self.stack.setCurrentIndex(1)
                self.phrasePage.load(model_item)

            elif isinstance(model_item, model.Script):
                self.stack.setCurrentIndex(2)
                self.scriptPage.load(model_item)

            self.topLevelWidget().update_actions(model_items, True)
            self.set_dirty(False)
            self.topLevelWidget().cancel_record()

        else:
            self.topLevelWidget().update_actions(model_items, False)

    def on_new_topfolder(self):
        logger.info("User initiates top-level folder creation")
        message_box = QMessageBox(
            QMessageBox.Question,
            "Create Folder",
            "Create folder in the default location?",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            self.topLevelWidget()

        )
        message_box.button(QMessageBox.No).setText("Create elsewhere")  # TODO: i18n
        result = message_box.exec_()

        self.topLevelWidget().app.monitor.suspend()

        if result == QMessageBox.Yes:
            logger.debug("User creates a new top-level folder.")
            self.__createFolder(None)

        elif result == QMessageBox.No:
            logger.debug("User creates a new folder and chose to create it elsewhere")
            path = QFileDialog.getExistingDirectory(
                self.topLevelWidget(),
                "Where should the folder be created?"
            )
            if path != "":
                path = str(path)
                name = os.path.basename(path)
                folder = model.Folder(name, path=path)
                new_item = ak_tree.FolderWidgetItem(None, folder)
                self.treeWidget.addTopLevelItem(new_item)
                self.configManager.folders.append(folder)
                self.topLevelWidget().app.config_altered(True)

            self.topLevelWidget().app.monitor.unsuspend()
        else:
            logger.debug("User canceled top-level folder creation.")
            self.topLevelWidget().app.monitor.unsuspend()

    def on_new_folder(self):
        parent_item = self.treeWidget.selectedItems()[0]
        self.__createFolder(parent_item)

    def __createFolder(self, parent_item):
        folder = model.Folder("New Folder")
        new_item = ak_tree.FolderWidgetItem(parent_item, folder)
        self.topLevelWidget().app.monitor.suspend()

        if parent_item is not None:
            parentFolder = self.__extractData(parent_item)
            parentFolder.add_folder(folder)
        else:
            self.treeWidget.addTopLevelItem(new_item)
            self.configManager.folders.append(folder)

        folder.persist()
        self.topLevelWidget().app.monitor.unsuspend()

        self.treeWidget.sortItems(0, Qt.AscendingOrder)
        self.treeWidget.setCurrentItem(new_item)
        self.on_treeWidget_itemSelectionChanged()
        self.on_rename()

    def on_new_phrase(self):
        self.topLevelWidget().app.monitor.suspend()
        parent_item = self.treeWidget.selectedItems()[0]
        parent = self.__extractData(parent_item)

        phrase = model.Phrase("New Phrase", "Enter phrase contents")
        new_item = ak_tree.PhraseWidgetItem(parent_item, phrase)
        parent.add_item(phrase)
        phrase.persist()

        self.topLevelWidget().app.monitor.unsuspend()
        self.treeWidget.sortItems(0, Qt.AscendingOrder)
        self.treeWidget.setCurrentItem(new_item)
        self.treeWidget.setItemSelected(parent_item, False)
        self.on_treeWidget_itemSelectionChanged()
        self.on_rename()

    def on_new_script(self):
        self.topLevelWidget().app.monitor.suspend()
        parent_item = self.treeWidget.selectedItems()[0]
        parent = self.__extractData(parent_item)

        script = model.Script("New Script", "#Enter script code")
        new_item = ak_tree.ScriptWidgetItem(parent_item, script)
        parent.add_item(script)
        script.persist()

        self.topLevelWidget().app.monitor.unsuspend()
        self.treeWidget.sortItems(0, Qt.AscendingOrder)
        self.treeWidget.setCurrentItem(new_item)
        self.treeWidget.setItemSelected(parent_item, False)
        self.on_treeWidget_itemSelectionChanged()
        self.on_rename()

    def on_undo(self):
        self.stack.currentWidget().undo()

    def on_redo(self):
        self.stack.currentWidget().redo()

    def on_copy(self):
        source_objects = self.__getSelection()

        for source in source_objects:
            if isinstance(source, model.Phrase):
                new_obj = model.Phrase('', '')
            else:
                new_obj = model.Script('', '')
            new_obj.copy(source)
            self.cutCopiedItems.append(new_obj)

    def on_clone(self):
        source_object = self.__getSelection()[0]
        parent_item = self.treeWidget.selectedItems()[0].parent()
        parent = self.__extractData(parent_item)

        if isinstance(source_object, model.Phrase):
            new_obj = model.Phrase('', '')
            new_obj.copy(source_object)
            new_item = ak_tree.PhraseWidgetItem(parent_item, new_obj)
        else:
            new_obj = model.Script('', '')
            new_obj.copy(source_object)
            new_item = ak_tree.ScriptWidgetItem(parent_item, new_obj)

        parent.add_item(new_obj)
        self.topLevelWidget().app.monitor.suspend()
        new_obj.persist()

        self.topLevelWidget().app.monitor.unsuspend()
        self.treeWidget.sortItems(0, Qt.AscendingOrder)
        self.treeWidget.setCurrentItem(new_item)
        self.treeWidget.setItemSelected(parent_item, False)
        self.on_treeWidget_itemSelectionChanged()
        self.topLevelWidget().app.config_altered(False)

    def on_cut(self):
        self.cutCopiedItems = self.__getSelection()
        self.topLevelWidget().app.monitor.suspend()

        source_items = self.treeWidget.selectedItems()
        result = [f for f in source_items if f.parent() not in source_items]
        for item in result:
            self.__removeItem(item)

        self.topLevelWidget().app.monitor.unsuspend()
        self.topLevelWidget().app.config_altered(False)

    def on_paste(self):
        parent_item = self.treeWidget.selectedItems()[0]
        parent = self.__extractData(parent_item)
        self.topLevelWidget().app.monitor.suspend()

        new_items = []
        for item in self.cutCopiedItems:
            if isinstance(item, model.Folder):
                f = ak_tree.WidgetItemFactory(None)
                new_item = ak_tree.FolderWidgetItem(parent_item, item)
                f.processFolder(new_item, item)
                parent.add_folder(item)
            elif isinstance(item, model.Phrase):
                new_item = ak_tree.PhraseWidgetItem(parent_item, item)
                parent.add_item(item)
            else:
                new_item = ak_tree.ScriptWidgetItem(parent_item, item)
                parent.add_item(item)

            item.persist()

            new_items.append(new_item)

        self.treeWidget.sortItems(0, Qt.AscendingOrder)
        self.treeWidget.setCurrentItem(new_items[-1])
        self.on_treeWidget_itemSelectionChanged()
        self.cutCopiedItems = []
        for item in new_items:
            self.treeWidget.setItemSelected(item, True)
        self.topLevelWidget().app.monitor.unsuspend()
        self.topLevelWidget().app.config_altered(False)

    def on_delete(self):
        widget_items = self.treeWidget.selectedItems()
        self.topLevelWidget().app.monitor.suspend()

        if len(widget_items) == 1:
            widget_item = widget_items[0]
            data = self.__extractData(widget_item)
            if isinstance(data, model.Folder):
                header = "Delete Folder?"
                msg = "Are you sure you want to delete the '{deleted_folder}' folder and all the items in it?".format(
                    deleted_folder=data.title)
            else:
                entity_type = "Script" if isinstance(data, model.Script) else "Phrase"
                header = "Delete {}?".format(entity_type)
                msg = "Are you sure you want to delete '{element}'?".format(element=data.description)
        else:
            item_count = len(widget_items)
            header = "Delete {item_count} selected items?".format(item_count=item_count)
            msg = "Are you sure you want to delete the {item_count} selected folders/items?".format(
                item_count=item_count)
        result = QMessageBox.question(self.topLevelWidget(), header, msg, QMessageBox.Yes | QMessageBox.No)

        if result == QMessageBox.Yes:
            for widget_item in widget_items:
                self.__removeItem(widget_item)

        self.topLevelWidget().app.monitor.unsuspend()
        if result == QMessageBox.Yes:
            self.topLevelWidget().app.config_altered(False)

    def on_rename(self):
        widget_item = self.treeWidget.selectedItems()[0]
        self.treeWidget.editItem(widget_item, 0)

    def on_save(self):
        logger.info("User requested file save.")
        if self.stack.currentWidget().validate():
            self.topLevelWidget().app.monitor.suspend()
            persist_global = self.stack.currentWidget().save()
            self.topLevelWidget().save_completed(persist_global)
            self.set_dirty(False)

            item = self.treeWidget.selectedItems()[0]
            item.update()
            self.treeWidget.update()
            self.treeWidget.sortItems(0, Qt.AscendingOrder)
            self.topLevelWidget().app.monitor.unsuspend()
            return False

        return True

    def on_reset(self):
        self.stack.currentWidget().reset()
        self.set_dirty(False)
        self.topLevelWidget().cancel_record()

    def on_save_log(self):
        file_name = QFileDialog.getSaveFileName(
            self.topLevelWidget(),
            "Save log file",
            "",
            ""  # TODO: File type filter. Maybe "*.log"?
        )
        if file_name != "":
            try:
                with open(file_name, "w") as log_file:
                    for i in range(self.listWidget.count()):
                        text = self.listWidget.item(i).text()
                        log_file.write(text)
                        log_file.write('\n')
            except IOError:
                logger.exception("Error saving log file")

    def on_clear_log(self):
        self.listWidget.clear()

    def move_items(self, sourceItems, target):
        target_model_item = self.__extractData(target)

        # Filter out any child objects that belong to a parent already in the list
        result = [f for f in sourceItems if f.parent() not in sourceItems]

        self.topLevelWidget().app.monitor.suspend()

        for source in result:
            self.__removeItem(source)
            source_model_item = self.__extractData(source)

            if isinstance(source_model_item, model.Folder):
                target_model_item.add_folder(source_model_item)
                self.__moveRecurseUpdate(source_model_item)
            else:
                target_model_item.add_item(source_model_item)
                source_model_item.path = None
                source_model_item.persist()

            target.addChild(source)

        self.topLevelWidget().app.monitor.unsuspend()
        self.treeWidget.sortItems(0, Qt.AscendingOrder)
        self.topLevelWidget().app.config_altered(True)

    def __moveRecurseUpdate(self, folder):
        folder.path = None
        folder.persist()

        for subfolder in folder.folders:
            self.__moveRecurseUpdate(subfolder)

        for child in folder.items:
            child.path = None
            child.persist()

    # ---- Private methods

    def get_selected_item(self):
        return self.__getSelection()

    def __getSelection(self):
        items = self.treeWidget.selectedItems()
        ret = [self.__extractData(item) for item in items]

        # Filter out any child objects that belong to a parent already in the list
        result = [f for f in ret if f.parent not in ret]
        return result

    @staticmethod
    def __extractData(item):
        variant = item.data(3, Qt.UserRole)
        return variant

    def __removeItem(self, widgetItem):
        parent = widgetItem.parent()
        item = self.__extractData(widgetItem)
        self.__deleteHotkeys(item)

        if parent is None:
            removed_index = self.treeWidget.indexOfTopLevelItem(widgetItem)
            self.treeWidget.takeTopLevelItem(removed_index)
            self.configManager.folders.remove(item)
        else:
            removed_index = parent.indexOfChild(widgetItem)
            parent.removeChild(widgetItem)

            if isinstance(item, model.Folder):
                item.parent.remove_folder(item)
            else:
                item.parent.remove_item(item)

        item.remove_data()
        self.treeWidget.sortItems(0, Qt.AscendingOrder)

        if parent is not None:
            if parent.childCount() > 0:
                new_index = min((removed_index, parent.childCount() - 1))
                self.treeWidget.setCurrentItem(parent.child(new_index))
            else:
                self.treeWidget.setCurrentItem(parent)
        else:
            new_index = min((removed_index, self.treeWidget.topLevelItemCount() - 1))
            self.treeWidget.setCurrentItem(self.treeWidget.topLevelItem(new_index))

    def __deleteHotkeys(self, theItem):
        if model.TriggerMode.HOTKEY in theItem.modes:
            self.topLevelWidget().app.hotkey_removed(theItem)

        if isinstance(theItem, model.Folder):
            for subFolder in theItem.folders:
                self.__deleteHotkeys(subFolder)

            for item in theItem.items:
                if model.TriggerMode.HOTKEY in item.modes:
                    self.topLevelWidget().app.hotkey_removed(item)


class ListWidgetHandler(logging.Handler):

    def __init__(self, list_widget: QListWidget, app):
        logging.Handler.__init__(self)
        self.widget = list_widget
        self.app = app
        self.level = logging.DEBUG

        root_logger = logging.getLogger()
        log_format = "%(message)s"
        root_logger.addHandler(self)
        self.setFormatter(logging.Formatter(log_format))

    def flush(self):
        pass

    def emit(self, record):
        try:
            item = QListWidgetItem(self.format(record))
            if record.levelno > logging.INFO:
                item.setIcon(QIcon.fromTheme("dialog-warning"))
                item.setForeground(QBrush(Qt.red))

            else:
                item.setIcon(QIcon.fromTheme("dialog-information"))

            self.app.exec_in_main(self._add_item, item)

        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)

    def _add_item(self, item):
        self.widget.addItem(item)

        if self.widget.count() > 50:
            delItem = self.widget.takeItem(0)
            del delItem

        self.widget.scrollToBottom()
