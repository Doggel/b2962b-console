"""Native desktop layout for the B2962B control console."""

import tkinter as tk
from tkinter import ttk

from b2962b_window import Tooltip


BG = '#EEF3F8'
SURFACE = '#FFFFFF'
INK = '#17273B'
MUTED = '#506176'
BORDER = '#D7E0EA'
NAVY = '#112A44'
PRIMARY = '#145D88'
FONT = 'Microsoft YaHei UI'


class ConsoleView:
    def __init__(self, root, targets, folder, actions):
        self.target = tk.StringVar(root, 'CH1')
        self.destination = tk.StringVar(root, str(folder))
        self.connection = tk.StringVar(root, '正在连接 B2962B…')
        self.instrument_state = tk.StringVar(root, '状态未确认')
        self.parameter_summary = tk.StringVar(root, '设置源、步长、限值与触发条件')
        self.feedback = tk.StringVar(root, '正在读取仪器状态…')
        self.output_labels = {}
        self.output_buttons = {}
        self._configure_styles(root)

        root.title('B2962B 控制台')
        root.configure(background=BG)
        header = ttk.Frame(root, style='Console.Header.TFrame', padding=(21, 14))
        header.pack(fill='x')
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text='B2962B 控制台', style='Console.Title.TLabel').grid(row=0, column=0, sticky='w')
        self.refresh = ttk.Button(header, text='刷新状态', command=actions['refresh'], style='Console.Header.TButton')
        self.refresh.grid(row=0, column=1, rowspan=2, sticky='e', padx=(18, 0))
        Tooltip(self.refresh, '重新读取仪器连接、扫描进度和两路输出状态。')
        status_row = ttk.Frame(header, style='Console.Header.TFrame')
        status_row.grid(row=1, column=0, sticky='w', pady=(4, 0))
        self.connection_label = ttk.Label(status_row, textvariable=self.connection, style='Console.HeaderInfo.TLabel')
        self.connection_label.pack(side='left')
        ttk.Label(status_row, text='  |  ', style='Console.HeaderInfo.TLabel').pack(side='left')
        ttk.Label(status_row, textvariable=self.instrument_state, style='Console.HeaderInfo.TLabel').pack(side='left')

        content = ttk.Frame(root, style='Console.TFrame', padding=(18, 12, 18, 10))
        content.pack(fill='both', expand=True)
        setup_row = self._section(content, '1', '设置参数')
        ttk.Label(setup_row, textvariable=self.parameter_summary, style='Console.Muted.TLabel').pack(side='left')
        self.reset = self._button(setup_row, '恢复默认参数', actions['reset'])
        self.reset.pack(side='right')
        Tooltip(self.reset, '确认后复位仪器，恢复 CH1 和 CH2 的仪器初始设置。')
        self.setup = self._button(setup_row, '扫描参数', actions['setup'], primary=True)
        self.setup.pack(side='right', padx=(10, 7))
        Tooltip(self.setup, '打开双通道设置，可编辑扫描参数、导入或保存 TOML。')

        output_row = self._section(content, '2', '通道输出')
        for index, channel in enumerate((1, 2)):
            output_row.columnconfigure(index, weight=1, uniform='outputs')
            card = ttk.Frame(output_row, style='Console.Channel.TFrame', padding=(10, 7))
            card.grid(row=0, column=index, sticky='ew', padx=(0, 5) if index == 0 else (5, 0))
            ttk.Label(card, text=f'CH{channel}', style='Console.Channel.TLabel').pack(side='left')
            status = ttk.Label(card, text='未确认', style='Console.Unknown.TLabel', padding=(6, 3))
            status.pack(side='left', padx=(7, 2))
            self.output_labels[channel] = status
            off = self._button(card, '关闭输出', lambda ch=channel: actions['off'](ch), compact=True)
            off.pack(side='right')
            on = self._button(card, '开启输出', lambda ch=channel: actions['on'](ch), compact=True)
            on.pack(side='right', padx=(4, 6))
            Tooltip(on, f'核对源模式和初始值后开启 CH{channel} 输出。')
            Tooltip(off, f'关闭 CH{channel} 的仪器输出。')
            self.output_buttons[channel] = on, off
        self.close_both = self._button(output_row, '关闭两路输出', actions['close_both'])
        self.close_both.grid(row=1, column=0, columnspan=2, sticky='e', pady=(8, 0))
        Tooltip(self.close_both, '关闭 CH1 和 CH2 的输出，并核对两路开关状态。')

        scan_row = self._section(content, '3', '启动扫描')
        ttk.Label(scan_row, text='扫描与导出通道', style='Console.Card.TLabel').pack(side='left', padx=(0, 8))
        self.pick = ttk.Combobox(scan_row, textvariable=self.target, values=list(targets), width=13,
                                 state='readonly', style='Console.TCombobox')
        self.pick.pack(side='left')
        self.pick.bind('<<ComboboxSelected>>', actions['target_changed'])
        ttk.Label(scan_row, text='再次启动会覆盖上一轮数据。', style='Console.Muted.TLabel').pack(
            side='left', padx=(10, 0))
        self.start = self._button(scan_row, '启动扫描', actions['start'], primary=True)
        self.start.pack(side='right')
        Tooltip(self.start, '启动所选通道的扫描。设置为外部触发时，仪器会等待相应信号。')

        export_row = self._section(content, '4', '导出数据')
        ttk.Label(export_row, text='保存到', style='Console.Card.TLabel').pack(side='left', padx=(0, 8))
        self.folder_entry = ttk.Entry(export_row, textvariable=self.destination, width=30, style='Console.TEntry')
        self.folder_entry.pack(side='left', fill='x', expand=True)
        self.export = self._button(export_row, '导出 CSV', actions['export'], primary=True)
        self.export.pack(side='right', padx=(8, 0))
        Tooltip(self.export, '将所选通道最近一轮已完成的扫描数据写入 CSV。')
        self.folder_button = self._button(export_row, '选择文件夹…', actions['folder'])
        self.folder_button.pack(side='right', padx=(8, 0))
        Tooltip(self.folder_button, '选择 CSV 文件的保存位置。')

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
            self.feedback_label.configure(wraplength=max(100, event.width - 40))

    def set_output(self, channel, state, controls_busy, idle):
        text, style = {True: ('已开启', 'Console.On.TLabel'), False: ('已关闭', 'Console.Off.TLabel'),
                       None: ('未确认', 'Console.Unknown.TLabel')}[state]
        self.output_labels[channel].configure(text=text, style=style)
        on, off = self.output_buttons[channel]
        on.configure(state='normal' if not controls_busy and idle and state is False else 'disabled')
        off.configure(state='normal' if not controls_busy and state is not False else 'disabled')

    def set_connection(self, text, status, connected=False):
        self.connection.set(text)
        self.connection_label.configure(style='Console.Online.TLabel' if connected else 'Console.HeaderInfo.TLabel')
        self.instrument_state.set(status)

    def set_feedback(self, message, error=False):
        self.feedback.set(message)
        self.feedback_label.configure(style='Console.Error.TLabel' if error else 'Console.Status.TLabel')

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
    def _button(parent, text, command, primary=False, compact=False):
        role = 'Primary' if primary else 'Compact' if compact else 'Button'
        return ttk.Button(parent, text=text, command=command, style=f'Console.{role}.TButton')

    @staticmethod
    def _configure_styles(root):
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=(FONT, 10), background=BG, foreground=INK)
        style.configure('Console.TFrame', background=BG)
        style.configure('Console.Header.TFrame', background=NAVY)
        style.configure('Console.Card.TFrame', background=SURFACE, bordercolor=BORDER, relief='flat')
        style.configure('Console.Channel.TFrame', background='#F3F7FB')
        style.configure('Console.Status.TFrame', background='#E3EBF5')
        style.configure('Console.Title.TLabel', background=NAVY, foreground='#FFFFFF', font=(FONT, 18, 'bold'))
        style.configure('Console.HeaderInfo.TLabel', background=NAVY, foreground='#D6E3F0')
        style.configure('Console.Online.TLabel', background=NAVY, foreground='#B5EDD5')
        style.configure('Console.Card.TLabel', background=SURFACE, foreground=INK)
        style.configure('Console.Muted.TLabel', background=SURFACE, foreground=MUTED)
        style.configure('Console.Section.TLabel', background=SURFACE, foreground=INK, font=(FONT, 11, 'bold'))
        style.configure('Console.Step.TLabel', background='#E6F1F8', foreground=PRIMARY, font=(FONT, 10, 'bold'))
        style.configure('Console.Channel.TLabel', background='#F3F7FB', foreground=INK, font=(FONT, 10, 'bold'))
        style.configure('Console.On.TLabel', background='#D7F2E6', foreground='#16604C')
        style.configure('Console.Off.TLabel', background='#E4EBF4', foreground='#3E536A')
        style.configure('Console.Unknown.TLabel', background='#FFF0D7', foreground='#744A1F')
        style.configure('Console.Status.TLabel', background='#E3EBF5', foreground=INK)
        style.configure('Console.Error.TLabel', background='#E3EBF5', foreground='#932E2E')
        style.configure('Console.TEntry', padding=(6, 4), fieldbackground=SURFACE, bordercolor=BORDER)
        style.configure('Console.TCombobox', padding=(6, 4), fieldbackground=SURFACE, bordercolor=BORDER)
        style.map('Console.TCombobox', fieldbackground=[('readonly', SURFACE), ('disabled', '#EEF2F7')])

        for role, background, foreground, active, border, padding in (
            ('Primary', PRIMARY, '#FFFFFF', '#104D73', PRIMARY, (12, 5)),
            ('Button', SURFACE, INK, '#EAF2F8', BORDER, (10, 5)),
            ('Compact', SURFACE, INK, '#EAF2F8', BORDER, (6, 4)),
            ('Header', '#244867', '#FFFFFF', '#325D80', '#507190', (12, 5)),
        ):
            name = f'Console.{role}.TButton'
            style.configure(name, background=background, foreground=foreground, bordercolor=border,
                            lightcolor=border, darkcolor=border, padding=padding)
            style.map(name, background=[('disabled', '#E9EFF5'), ('pressed', active), ('active', active)],
                      foreground=[('disabled', '#65758A')], bordercolor=[('disabled', BORDER)])
