import gi

from gi.repository import Gtk, GLib, Gdk, Gio, GObject

from iplan.db.operations.project import read_projects
from iplan.db.models.list import List
from iplan.db.operations.list import update_list
from iplan.db.models.task import Task
from iplan.db.operations.task import create_task, read_tasks, read_task, update_task, find_new_task_position

from iplan.views.project.project_header import ProjectHeader
from iplan.views.project.project_list_task import ProjectListTask
from iplan.views.project.project_list_delete_dialog import ProjectListDeleteDialog


@Gtk.Template(resource_path='/ir/imansalmani/iplan/ui/project/project_list.ui')
class ProjectList(Gtk.Box):
    __gtype_name__ = "ProjectList"
    show_completed_tasks: bool = False
    scrolled_window: Gtk.ScrolledWindow = Gtk.Template.Child()
    tasks_box: Gtk.ListBox = Gtk.Template.Child()
    name_button: Gtk.Button = Gtk.Template.Child()
    name_entry: Gtk.Entry = Gtk.Template.Child()
    options_button: Gtk.MenuButton = Gtk.Template.Child()
    _list: List

    def __init__(self, _list: List) -> None:
        super().__init__()
        self._list = _list
        self.name_button.set_label(self._list.name)
        self.name_entry.get_buffer().set_text(self._list.name, -1)

        drop_target = Gtk.DropTarget.new(ProjectListTask, Gdk.DragAction.MOVE)
        drop_target.set_preload(True)
        drop_target.connect("drop", self.on_dropped)
        drop_target.connect("motion", self.on_motioned)
        drop_target.connect("leave", self.on_leaved)
        drop_target.connect("enter", self.on_entered)
        self.tasks_box.add_controller(drop_target)

        self.tasks_box.set_sort_func(self.sort)
        self.tasks_box.set_filter_func(self._filter)
        self.connect("map", self.on_mapped)
        self.connect("unmap", self.on_unmapped)

    # Actions
    def on_mapped(self, *args):
        self.disconnect_by_func(self.on_mapped)
        actions = self.props.root.props.application.actions
        # TODO: use handler and use action in ProjectLists and find focused list
        #actions["new_task"].connect("activate", self.on_new_button_clicked)
        # TODO: split this to specific functions
        actions["refresh_tasks"].connect("activate", self.refresh_tasks)
        self.fetch()

    def on_unmapped(self, *args):
        actions = self.props.root.props.application.actions
        actions["refresh_tasks"].disconnect_by_func(self.refresh_tasks)

    @Gtk.Template.Callback()
    def on_name_toggled(self, *args):
        # used by both name entry and name button
        # name_entry have binding to name button visibility
        name_button_visible = not self.name_button.get_visible()
        self.name_button.set_visible(name_button_visible)
        if name_button_visible:
            self._list.name = self.name_entry.get_buffer().get_text()
            self.name_button.set_label(self._list.name)
            update_list(self._list)
        else:
            self.name_entry.grab_focus_without_selecting()

    @Gtk.Template.Callback()
    def on_new_task_button_clicked(self, *args):
        task = create_task(
            "",
            project_id=self.props.root.props.application.project._id,
            list_id=self._list._id
        )

        task_ui = ProjectListTask(task, new=True)
        self.tasks_box.prepend(task_ui)
        task_ui.name_entry.grab_focus()

    @Gtk.Template.Callback()
    def on_completed_tasks_button_toggled(self, toggle_button):
        # TODO: remove only done tasks or verse
        self.options_button.popdown()
        self.show_completed_tasks = toggle_button.get_active()
        self.clear()
        self.fetch()

    @Gtk.Template.Callback()
    def on_delete_button_clicked(self, *args):
        self.options_button.popdown()
        dialog = ProjectListDeleteDialog(self)
        dialog.set_transient_for(self.get_root())
        dialog.present()

    def refresh_tasks(self, *args):
        self.clear()
        self.fetch()

    # UI
    def on_dropped(self, target: Gtk.DropTarget, source_row, x, y):
        # source_row moved by motion signal so it should drop on itself
        self.tasks_box.drag_unhighlight_row()
        task_in_db = read_task(source_row.task._id)
        if task_in_db != source_row.task:
            update_task(source_row.task, move_position=True)
        return True

    def on_motioned(self, target: Gtk.DropTarget, x, y):
        source_row: ProjectListTask = target.get_value()
        target_row: ProjectListTask = self.tasks_box.get_row_at_y(y)

        # None check
        if not source_row or not target_row:
            return 0

        # Move shadow_row
        if source_row != target_row:
            # index is reverse of position
            shadow_i = source_row.get_index()
            target_i = target_row.get_index()
            target_p = target_row.task.position
            if shadow_i == target_i - 1:
                source_row.task.position -= 1
                target_row.task.position +=1
            elif shadow_i < target_i:
                for i in range(shadow_i+1, target_i+1):
                    row = self.tasks_box.get_row_at_index(i)
                    row.task.position += 1
                source_row.task.position = target_p
            elif shadow_i == target_i + 1:
                source_row.task.position += 1
                target_row.task.position -=1
            elif shadow_i > target_i:
                for i in range(target_i, shadow_i):
                    row = self.tasks_box.get_row_at_index(i)
                    row.task.position -= 1
                source_row.task.position = target_p

            # Should use invalidate_sort() insteed of changed() for Refresh hightlight shape
            self.tasks_box.invalidate_sort()
            self.tasks_box.drag_unhighlight_row()
            self.tasks_box.drag_highlight_row(source_row)

        # Scroll when mouse near top nad bottom edges
        scrolled_window_height = self.scrolled_window.get_size(Gtk.Orientation.VERTICAL)
        tasks_box_height = self.tasks_box.get_size(Gtk.Orientation.VERTICAL)

        if tasks_box_height > scrolled_window_height:
            adjustment = self.scrolled_window.props.vadjustment
            step = adjustment.get_step_increment() / 3
            v_pos = adjustment.get_value()
            if y - v_pos > 475:
                adjustment.set_value(v_pos + step)
            elif y - v_pos < 25:
                adjustment.set_value(v_pos - step)

        return Gdk.DragAction.MOVE

    def on_leaved(self, target: Gtk.DropTarget):
        source_row: ProjectListTask = target.get_value()
        if source_row:
            source_row.moving_out = True
            self.tasks_box.invalidate_filter()

    def on_entered(self, target: Gtk.DropTarget, x, y):
        source_row: ProjectListTask = target.get_value()
        source_row.moving_out = False

        if source_row.task._list == self._list._id:
            self.tasks_box.invalidate_filter()
        else:
            source_row.task._list = self._list._id
            source_row.task.position = find_new_task_position(source_row.task._list)
            source_row.get_parent().remove(source_row)
            self.tasks_box.prepend(source_row)
            self.tasks_box.drag_highlight_row(source_row)

        return Gdk.DragAction.MOVE

    def sort(
            self,
            row1: Gtk.ListBoxRow,
            row2: Gtk.ListBoxRow) -> int:
        return row2.task.position - row1.task.position

    def _filter(self, row: Gtk.ListBoxRow) -> bool:
        return not row.moving_out

    def fetch(self):
        tasks = read_tasks(
            project_id=self.props.root.props.application.project._id,
            list_id=self._list._id,
            completed_tasks=self.show_completed_tasks
        )
        for task in tasks:
            self.tasks_box.append(ProjectListTask(task))

    def clear(self):
        while True:
            row = self.tasks_box.get_first_child()
            if row:
                self.tasks_box.remove(row)
            else:
                break
