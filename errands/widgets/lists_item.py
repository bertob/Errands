# Copyright 2023 Vlad Krupinskii <mrvladus@yandex.ru>
# SPDX-License-Identifier: MIT

from datetime import datetime
from icalendar import Calendar, Todo
from errands.widgets.components.box import Box
from gi.repository import Adw, Gtk, Gio, GObject
from errands.utils.data import UserData
from errands.utils.logging import Log
from errands.utils.sync import Sync


class ListItem(Gtk.ListBoxRow):
    def __init__(self, task_list, list_box, lists, window) -> None:
        super().__init__()
        self.task_list = task_list
        self.uid = task_list.list_uid
        self.window = window
        self.list_box = list_box
        self.lists = lists
        self._build_ui()
        self._add_actions()

    def _add_actions(self):
        group = Gio.SimpleActionGroup()
        self.insert_action_group(name="list_item", group=group)

        def _create_action(name: str, callback: callable) -> None:
            action: Gio.SimpleAction = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            group.add_action(action)

        def _delete(*args):
            def _confirm(_, res):
                if res == "cancel":
                    Log.debug("ListItem: Deleting list is cancelled")
                    return

                Log.info(f"Lists: Delete list '{self.uid}'")
                UserData.run_sql(
                    f"UPDATE lists SET deleted = 1 WHERE uid = '{self.uid}'",
                    f"DELETE FROM tasks WHERE list_uid = '{self.uid}'",
                )
                self.window.stack.remove(self.task_list)
                # Switch row
                next_row = self.get_next_sibling()
                prev_row = self.get_prev_sibling()
                self.list_box.remove(self)
                if next_row or prev_row:
                    self.list_box.select_row(next_row or prev_row)
                else:
                    self.window.stack.set_visible_child_name("status")
                    self.lists.status_page.set_visible(True)

                Sync.sync()

            dialog = Adw.MessageDialog(
                transient_for=self.window,
                hide_on_close=True,
                heading=_("Are you sure?"),  # type:ignore
                body=_("List will be permanently deleted"),  # type:ignore
                default_response="delete",
                close_response="cancel",
            )
            dialog.add_response("cancel", _("Cancel"))  # type:ignore
            dialog.add_response("delete", _("Delete"))  # type:ignore
            dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.connect("response", _confirm)
            dialog.present()

        def _rename(*args):
            def entry_changed(entry, _, dialog):
                text = entry.props.text.strip(" \n\t")
                names = [i["name"] for i in UserData.get_lists_as_dicts()]
                dialog.set_response_enabled("save", text and text not in names)

            def _confirm(_, res, entry):
                if res == "cancel":
                    Log.debug("ListItem: Editing list name is cancelled")
                    return
                Log.info(f"ListItem: Rename list {self.uid}")

                text = entry.props.text.rstrip().lstrip()
                UserData.run_sql(
                    f"""UPDATE lists SET name = '{text}', synced = 0
                    WHERE uid = '{self.uid}'"""
                )
                self.task_list.title.set_title(text)
                page: Adw.ViewStackPage = self.window.stack.get_page(self.task_list)
                page.set_name(text)
                page.set_title(text)
                Sync.sync()

            entry = Gtk.Entry(placeholder_text=_("New Name"))  # type:ignore
            dialog = Adw.MessageDialog(
                transient_for=self.window,
                hide_on_close=True,
                heading=_("Rename List"),  # type:ignore
                default_response="save",
                close_response="cancel",
                extra_child=entry,
            )
            dialog.add_response("cancel", _("Cancel"))  # type:ignore
            dialog.add_response("save", _("Save"))  # type:ignore
            dialog.set_response_enabled("save", False)
            dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
            dialog.connect("response", _confirm, entry)
            entry.connect("notify::text", entry_changed, dialog)
            dialog.present()

        def _export(*args):
            def _confirm(dialog, res):
                try:
                    file = dialog.save_finish(res)
                except:
                    Log.debug("List: Export cancelled")
                    return

                Log.info(f"List: Export '{self.uid}'")

                tasks = UserData.get_tasks_as_dicts(self.uid)
                calendar = Calendar()
                for task in tasks:
                    event = Todo()
                    event.add("uid", task["uid"])
                    event.add("related-to", task["parent"])
                    event.add("summary", task["text"])
                    if task["notes"]:
                        event.add("description", task["notes"])
                    event.add("priority", task["priority"])
                    if task["tags"]:
                        event.add("categories", task["tags"])
                    event.add("percent-complete", task["percent_complete"])
                    if task["color"]:
                        event.add("x-errands-color", task["color"])
                    event.add(
                        "dtstart",
                        datetime.fromisoformat(task["start_date"])
                        if task["start_date"]
                        else datetime.now(),
                    )
                    if task["end_date"]:
                        event.add(
                            "dtend",
                            datetime.fromisoformat(task["end_date"])
                            if task["end_date"]
                            else datetime.now(),
                        )
                    calendar.add_component(event)

                try:
                    with open(file.get_path(), "wb") as f:
                        f.write(calendar.to_ical())
                except Exception as e:
                    Log.error(f"List: Export failed. {e}")
                    self.window.add_toast(_("Export failed"))  # type:ignore

                self.window.add_toast(_("Exported"))  # type:ignore

            filter = Gtk.FileFilter()
            filter.add_pattern("*.ics")
            dialog = Gtk.FileDialog(
                initial_name=f"{self.uid}.ics", default_filter=filter
            )
            dialog.save(self.window, None, _confirm)

        _create_action("delete", _delete)
        _create_action("rename", _rename)
        _create_action("export", _export)

    def _build_ui(self):
        # Label
        self.label = Gtk.Label(
            halign="start",
            hexpand=True,
            ellipsize=3,
        )
        self.task_list.title.bind_property(
            "title",
            self.label,
            "label",
            GObject.BindingFlags.SYNC_CREATE,
        )
        # Menu
        menu: Gio.Menu = Gio.Menu.new()
        menu.append(_("Rename"), "list_item.rename")  # type:ignore
        menu.append(_("Delete"), "list_item.delete")  # type:ignore
        menu.append(_("Export"), "list_item.export")  # type:ignore
        # Click controller
        ctrl = Gtk.GestureClick()
        ctrl.connect("released", self.on_click)
        self.add_controller(ctrl)
        self.set_child(
            Box(
                children=[
                    self.label,
                    Gtk.MenuButton(
                        menu_model=menu,
                        icon_name="view-more-symbolic",
                        tooltip_text=_("Menu"),  # type:ignore
                    ),
                ],
                css_classes=["toolbar"],
            )
        )

    def on_click(self, *args):
        self.window.stack.set_visible_child_name(self.label.get_label())
        self.window.split_view.set_show_content(True)
