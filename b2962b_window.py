"""Window placement and hover help shared by the B2962B desktop views."""

import ctypes
from ctypes import wintypes
import sys
import tkinter as tk
from tkinter import ttk


if sys.platform == 'win32':
    class MonitorInfo(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT), ('work', wintypes.RECT),
                    ('flags', wintypes.DWORD)]

    user32 = ctypes.WinDLL('user32')
    monitor_from_point = user32.MonitorFromPoint
    monitor_from_point.argtypes = (wintypes.POINT, wintypes.DWORD)
    monitor_from_point.restype = wintypes.HANDLE
    get_monitor_info = user32.GetMonitorInfoW
    get_monitor_info.argtypes = (wintypes.HANDLE, ctypes.POINTER(MonitorInfo))
    get_monitor_info.restype = wintypes.BOOL


def _work_area(window, x, y):
    if sys.platform == 'win32':
        monitor = monitor_from_point(wintypes.POINT(x, y), 2)  # Nearest monitor.
        info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
        if get_monitor_info(monitor, ctypes.byref(info)):
            return info.work.left, info.work.top, info.work.right, info.work.bottom
    left, top = window.winfo_vrootx(), window.winfo_vrooty()
    return left, top, left + window.winfo_vrootwidth(), top + window.winfo_vrootheight()


def _place(window, x, y, width, height, area):
    left, top, right, bottom = area
    x = max(left, min(x, right - width))
    y = max(top, min(y, bottom - height))
    window.geometry(f'+{x}+{y}')


def show_main_window(window):
    window.attributes('-topmost', True)
    window.deiconify()
    window.lift()
    window.after_idle(window.focus_force)
    window.after(350, window.attributes, '-topmost', False)


def center_dialog(dialog, owner):
    dialog.update_idletasks()
    border = max(0, owner.winfo_rootx() - owner.winfo_x())
    caption = max(0, owner.winfo_rooty() - owner.winfo_y())
    width = dialog.winfo_reqwidth() + 2 * border
    height = dialog.winfo_reqheight() + caption + border
    x = owner.winfo_rootx() + owner.winfo_width() // 2
    y = owner.winfo_rooty() + owner.winfo_height() // 2
    _place(dialog, x - width // 2, y - height // 2, width, height, _work_area(owner, x, y))


class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.timer = None
        self.popup = None
        widget.bind('<Enter>', self.schedule, add='+')
        for event in ('<Leave>', '<ButtonPress>', '<KeyPress>', '<Unmap>', '<Destroy>'):
            widget.bind(event, self.hide, add='+')

    def schedule(self, event):
        self.hide()
        self.timer = self.widget.after(1000, self.show)

    def show(self):
        self.timer = None
        widget = self.widget
        x, y = widget.winfo_pointerxy()
        if not widget.winfo_viewable() or widget.winfo_containing(x, y) is not widget:
            return
        popup = self.popup = tk.Toplevel(widget)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.transient(widget.winfo_toplevel())
        ttk.Label(popup, text=self.text, justify='left', wraplength=280, padding=(9, 6),
                  background='#FFF8DC', foreground='#283747', relief='solid', borderwidth=1).pack()
        popup.update_idletasks()
        width, height = popup.winfo_reqwidth(), popup.winfo_reqheight()
        area = _work_area(widget, x, y)
        top = y + 20 if y + 20 + height <= area[3] else y - height - 8
        _place(popup, x + 14, top, width, height, area)
        popup.deiconify()

    def hide(self, event=None):
        if self.timer is not None:
            self.widget.after_cancel(self.timer)
            self.timer = None
        if self.popup is not None:
            self.popup.destroy()
            self.popup = None
