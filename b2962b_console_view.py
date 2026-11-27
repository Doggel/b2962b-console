"""Native desktop layout for the B2962B control console."""

import tkinter as tk
from tkinter import ttk

from b2962b_scan_form import scan_checkbox_style
from b2962b_window import Tooltip


BG = '#EEF3F8'
SURFACE = '#FFFFFF'
INK = '#17273B'
MUTED = '#506176'
BORDER = '#D7E0EA'
NAVY = '#112A44'
PRIMARY = '#14589B'
FONT = 'Microsoft YaHei UI'


class ConsoleView:
    def __init__(self, root, targets, folder, actions):
        self.target = tk.StringVar(root, 'CH1')
        self.destination = tk.StringVar(root, str(folder))
        self.connection = tk.StringVar(root, '正在连接 B2962B…')
        self.instrument_state = tk.StringVar(root)
        self.parameter_summary = tk.StringVar(root, '设置源、步长、限值与触发条件')
        self.feedback = tk.StringVar(root, '正在读取仪器状态…')
        self.progress_text = tk.StringVar(root, '未启动扫描')
        self.auto_export = tk.BooleanVar(root, False)
        self.auto_close_outputs = tk.BooleanVar(root, False)
        self.output_labels = {}
        self.output_buttons = {}
        self._configure_styles(root)
        checkbox_style = f'Console.{scan_checkbox_style(root)}'
        style = ttk.Style(root)
        style.configure(checkbox_style, background=SURFACE)
        style.map(checkbox_style, background=[('active', SURFACE), ('!active', SURFACE)])

        root.title('B2962B 控制台')
        root.configure(background=BG)
        header = ttk.Frame(root, style='Console.Header.TFrame', padding=(21, 14))
        header.pack(fill='x')
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text='B2962B 控制台', style='Console.Title.TLabel').grid(row=0, column=0, sticky='w')
        self.refresh = ttk.Button(header, text='刷新状态', command=actions['refresh'],
                                  style='Outline.Console.Blue.TButton')
        self.refresh.grid(row=0, column=1, rowspan=2, sticky='e', padx=(18, 0))
        Tooltip(self.refresh, '重新读取仪器连接、扫描进度和两路输出状态。')
        status_row = ttk.Frame(header, style='Console.Header.TFrame')
        status_row.grid(row=1, column=0, sticky='w', pady=(4, 0))
        self.connection_label = ttk.Label(status_row, textvariable=self.connection, style='Console.HeaderInfo.TLabel')
        self.connection_label.pack(side='left')
        ttk.Label(status_row, textvariable=self.instrument_state, style='Console.HeaderInfo.TLabel').pack(side='left')

        content = ttk.Frame(root, style='Console.TFrame', padding=(18, 12, 18, 10))
        content.pack(fill='both', expand=True)
        setup_row = self._section(content, '1', '设置参数')
        ttk.Label(setup_row, textvariable=self.parameter_summary, style='Console.Muted.TLabel').pack(side='left')
        self.reset = self._button(setup_row, '恢复默认参数', actions['reset'])
        self.reset.pack(side='right')
        Tooltip(self.reset, '确认后复位仪器，恢复 CH1 和 CH2 的仪器初始设置。')
        self.setup = self._button(setup_row, '扫描参数', actions['setup'])
        self.setup.pack(side='right', padx=(10, 7))
        Tooltip(self.setup, '打开双通道设置，可编辑扫描参数、导入或保存 TOML。')

        output_row = self._section(content, '2', '通道输出')
        for index, channel in enumerate((1, 2)):
            column = index * 2
            output_row.columnconfigure(column, weight=1, uniform='outputs')
            channel_row = ttk.Frame(output_row, style='Console.Card.TFrame')
            channel_row.grid(row=0, column=column, sticky='ew')
            ttk.Label(channel_row, text=f'CH{channel}', style='Console.Channel.TLabel').pack(side='left')
            status = ttk.Label(channel_row, text='未确认', style='Console.Unknown.TLabel')
            status.pack(side='left', padx=(9, 6))
            self.output_labels[channel] = status
            off = self._button(channel_row, '关闭输出', lambda ch=channel: actions['off'](ch), role='Stop')
            off.pack(side='right')
            on = self._button(channel_row, '开启输出', lambda ch=channel: actions['on'](ch))
            on.pack(side='right', padx=(0, 6))
            Tooltip(on, f'核对源模式和初始值后开启 CH{channel} 输出。')
            Tooltip(off, f'关闭 CH{channel} 的仪器输出。')
            self.output_buttons[channel] = on, off
        ttk.Separator(output_row, orient='vertical', style='Console.Vertical.TSeparator').grid(
            row=0, column=1, sticky='ns', padx=12, pady=3)
        self.auto_close_check = ttk.Checkbutton(output_row, text='扫描完成后关闭两路输出',
                                                variable=self.auto_close_outputs, style=checkbox_style)
        self.auto_close_check.grid(row=1, column=0, sticky='w', pady=(8, 0))
        Tooltip(self.auto_close_check, '勾选后，本轮扫描结束时关闭 CH1 和 CH2，包括仅用作偏置的通道。')
        self.close_both = self._button(output_row, '关闭两路输出', actions['close_both'], role='Stop')
        self.close_both.grid(row=1, column=2, sticky='e', pady=(8, 0))
        Tooltip(self.close_both, '关闭 CH1 和 CH2 的输出，并核对两路开关状态。')

        scan_body = self._section(content, '3', '启动扫描')
        scan_row = ttk.Frame(scan_body, style='Console.Card.TFrame')
        scan_row.pack(fill='x')
        ttk.Label(scan_row, text='扫描与导出通道', style='Console.Card.TLabel').pack(side='left', padx=(0, 8))
        self.pick = ttk.Combobox(scan_row, textvariable=self.target, values=list(targets), width=13,
                                 state='readonly', style='Console.TCombobox')
        self.pick.pack(side='left')
        self.pick.bind('<<ComboboxSelected>>', actions['target_changed'])
        ttk.Label(scan_row, text='再次启动会覆盖上一轮数据。', style='Console.Muted.TLabel').pack(
            side='left', padx=(10, 0))
        self.start = self._button(scan_row, '启动扫描', actions['start'])
        self.start.pack(side='right')
        Tooltip(self.start, '启动所选通道的扫描。设置为外部触发时，仪器会等待相应信号。')
        progress_row = ttk.Frame(scan_body, style='Console.Card.TFrame')
        progress_row.pack(fill='x', pady=(9, 0))
        ttk.Label(progress_row, textvariable=self.progress_text, style='Console.Card.TLabel').pack(side='right')
        self.progress = ttk.Progressbar(progress_row, mode='determinate', maximum=100,
                                        style='Console.Horizontal.TProgressbar')
        self.progress.pack(side='left', fill='x', expand=True, padx=(0, 12))

        export_body = self._section(content, '4', '导出数据')
        export_row = ttk.Frame(export_body, style='Console.Card.TFrame')
        export_row.pack(fill='x')
        ttk.Label(export_row, text='保存到', style='Console.Card.TLabel').pack(side='left', padx=(0, 8))
        self.folder_entry = ttk.Entry(export_row, textvariable=self.destination, width=30, style='Console.TEntry')
        self.folder_entry.pack(side='left', fill='x', expand=True)
        self.export = self._button(export_row, '导出 CSV', actions['export'])
        self.export.pack(side='right', padx=(8, 0))
        Tooltip(self.export, '将所选通道最近一轮已完成的扫描数据写入 CSV。')
        self.folder_button = self._button(export_row, '选择文件夹…', actions['folder'])
        self.folder_button.pack(side='right', padx=(8, 0))
        Tooltip(self.folder_button, '选择 CSV 文件的保存位置。')
        self.auto_export_check = ttk.Checkbutton(export_body, text='扫描完成后自动导出',
                                                 variable=self.auto_export, style=checkbox_style)
        self.auto_export_check.pack(anchor='w', pady=(7, 0))
        Tooltip(self.auto_export_check, '启动时记住所选通道和保存位置。仪器完成本轮扫描后自动保存 CSV。')

        status = ttk.Frame(root, padding=(20, 9), style='Console.Status.TFrame')
        status.pack(fill='x', side='bottom')
        self.feedback_label = ttk.Label(status, textvariable=self.feedback, style='Console.Status.TLabel',
                                        justify='left', wraplength=680)
        self.feedback_label.pack(fill='x')
        root.bind('<Configure>', self._set_wrap, add='+')
        root.update_idletasks()
        root.minsize(max(root.winfo_reqwidth(), 650), root.winfo_reqheight())

    def _set_wrap(self, event):
        if event.widget is self.feedback_label.winfo_toplevel():
            self._configure_changed(self.feedback_label, wraplength=max(100, event.width - 40))

    @staticmethod
    def _configure_changed(widget, **options):
        changes = {key: value for key, value in options.items() if str(widget.cget(key)) != str(value)}
        if changes:
            widget.configure(**changes)

    @staticmethod
    def _set_text(variable, value):
        if variable.get() != value:
            variable.set(value)

    def set_control(self, widget, enabled, *, active_state='normal'):
        self._configure_changed(widget, state=active_state if enabled else 'disabled')

    def set_progress(self, text, percent=0, *, outcome='running'):
        self._set_text(self.progress_text, text)
        style = {'running': 'Console.Horizontal.TProgressbar',
                 'complete': 'Console.Complete.Horizontal.TProgressbar',
                 'incomplete': 'Console.Incomplete.Horizontal.TProgressbar'}[outcome]
        self._configure_changed(self.progress, style=style)
        if float(self.progress.cget('value')) != percent:
            self.progress.configure(value=percent)

    def set_output(self, channel, state, controls_busy, idle):
        text, style = {True: ('已开启', 'Console.On.TLabel'), False: ('已关闭', 'Console.Off.TLabel'),
                       None: ('未确认', 'Console.Unknown.TLabel')}[state]
        self._configure_changed(self.output_labels[channel], text=text, style=style)
        on, off = self.output_buttons[channel]
        self.set_control(on, not controls_busy and idle and state is False)
        self.set_control(off, not controls_busy and state is not False)

    def set_connection(self, text, status, connected=False):
        self._set_text(self.connection, text)
        self._configure_changed(self.connection_label,
                                style='Console.Online.TLabel' if connected else 'Console.HeaderInfo.TLabel')
        self._set_text(self.instrument_state, f'  |  {status}' if status else '')

    def set_feedback(self, message, error=False):
        self._set_text(self.feedback, message)
        self._configure_changed(self.feedback_label, style='Console.Error.TLabel' if error else 'Console.Status.TLabel')

    @staticmethod
    def _section(parent, step, title):
        section = ttk.Frame(parent, style='Console.Card.TFrame', padding=(12, 8))
        section.pack(fill='x', pady=(0, 8))
        title_row = ttk.Frame(section, style='Console.Card.TFrame')
        title_row.pack(fill='x', pady=(0, 6))
        ttk.Label(title_row, text=step, style='Console.Step.TLabel', padding=(7, 2)).pack(side='left', padx=(0, 8))
        ttk.Label(title_row, text=title, style='Console.Section.TLabel').pack(side='left')
        body = ttk.Frame(section, style='Console.Card.TFrame')
        body.pack(fill='x')
        return body

    @staticmethod
    def _button(parent, text, command, role='Blue'):
        return ttk.Button(parent, text=text, command=command, style=f'Console.{role}.TButton')

    @staticmethod
    def _configure_styles(root):
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=(FONT, 10), background=BG, foreground=INK)
        style.configure('Console.TFrame', background=BG)
        style.configure('Console.Header.TFrame', background=NAVY)
        style.configure('Console.Card.TFrame', background=SURFACE, bordercolor=BORDER, relief='flat')
        style.configure('Console.Vertical.TSeparator', background=BORDER)
        style.configure('Console.Status.TFrame', background='#E3EBF5')
        style.configure('Console.Title.TLabel', background=NAVY, foreground='#FFFFFF', font=(FONT, 18, 'bold'))
        style.configure('Console.HeaderInfo.TLabel', background=NAVY, foreground='#D6E3F0')
        style.configure('Console.Online.TLabel', background=NAVY, foreground='#B5EDD5')
        style.configure('Console.Card.TLabel', background=SURFACE, foreground=INK)
        style.configure('Console.Muted.TLabel', background=SURFACE, foreground=MUTED)
        style.configure('Console.Section.TLabel', background=SURFACE, foreground=INK, font=(FONT, 11, 'bold'))
        style.configure('Console.Step.TLabel', background='#E6F1F8', foreground=PRIMARY, font=(FONT, 10, 'bold'))
        style.configure('Console.Channel.TLabel', background=SURFACE, foreground=INK, font=(FONT, 10, 'bold'))
        style.configure('Console.On.TLabel', background=SURFACE, foreground='#16604C')
        style.configure('Console.Off.TLabel', background=SURFACE, foreground='#3E536A')
        style.configure('Console.Unknown.TLabel', background=SURFACE, foreground='#744A1F')
        style.configure('Console.Status.TLabel', background='#E3EBF5', foreground=INK)
        style.configure('Console.Error.TLabel', background='#E3EBF5', foreground='#932E2E')
        style.configure('Console.TEntry', padding=(6, 4), fieldbackground=SURFACE, bordercolor=BORDER)
        style.configure('Console.TCombobox', padding=(6, 4), fieldbackground=SURFACE, bordercolor=BORDER)
        style.map('Console.TCombobox', fieldbackground=[('readonly', SURFACE), ('disabled', '#EEF2F7')])
        for prefix, color in (('Console', PRIMARY), ('Console.Complete', '#287E68'),
                              ('Console.Incomplete', '#AA6C1E')):
            style.configure(f'{prefix}.Horizontal.TProgressbar', background=color, troughcolor='#E2EAF4',
                            bordercolor='#CCD8E6', lightcolor=color, darkcolor=color, thickness=9)

        for role, background, active, padding in (
            ('Blue', '#426484', '#345370', (10, 5)),
            ('Stop', '#AC2E32', '#872125', (7, 5)),
        ):
            name = f'Console.{role}.TButton'
            style.configure(name, background=background, foreground='#FFFFFF', padding=padding,
                            borderwidth=0, focusthickness=0, relief='flat')
            style.map(name, background=[('disabled', '#ECEFF3'), ('pressed', active),
                                        ('active', active), ('focus', active)],
                      foreground=[('disabled', '#626E7B')], relief=[('!pressed', 'flat'), ('pressed', 'flat')])
        outline = 'Outline.Console.Blue.TButton'
        style.configure(outline, borderwidth=1, bordercolor='#819BB6', relief='solid')
        style.map(outline, bordercolor=[('disabled', '#CFD6E0')],
                  relief=[('!pressed', 'solid'), ('pressed', 'solid')])
