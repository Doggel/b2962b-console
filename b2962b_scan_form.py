"""Editable B2962B scan parameters backed by the existing SCPI planner."""

import json
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import tomllib

from b2962b_configure import TRIGGERS, build_plan
from b2962b_window import Tooltip, center_dialog


SOURCES = {'电压源': 'voltage', '电流源': 'current'}
MODES = {'线性扫描': 'linear', '对数扫描': 'log', '列表扫描': 'list', '固定偏置': 'fixed'}
TRIGGER_CHOICES = sorted(TRIGGERS, key=lambda name: (name.startswith('EXT'), len(name), name))
TOML_FILE_TYPES = [('TOML 参数文件', '*.toml'), ('所有文件', '*.*')]


def scan_checkbox(parent, **options):
    """Use the native Windows checkmark throughout the scan form."""
    style_name = scan_checkbox_style(parent)
    return ttk.Checkbutton(parent, style=style_name, **options)


def scan_checkbox_style(window):
    style = ttk.Style(window)
    name = 'ScanForm.TCheckbutton'
    indicator = 'ScanForm.indicator'
    if 'vista' not in style.theme_names():
        return 'TCheckbutton'
    if indicator not in style.element_names():
        style.element_create(indicator, 'from', 'vista', 'Checkbutton.indicator')
        layout = style.layout('TCheckbutton')

        def replace_indicator(elements):
            for index, (element, options) in enumerate(elements):
                if element == 'Checkbutton.indicator':
                    elements[index] = (indicator, options)
                elif 'children' in options:
                    replace_indicator(options['children'])

        replace_indicator(layout)
        style.layout(name, layout)
    return name


def read_template(path):
    return tomllib.loads(path.read_text(encoding='utf-8-sig'))


def write_preset(path, profile):
    """Write the scan schema's booleans, numbers, strings and arrays to TOML."""
    def section(values, header=''):
        if header:
            yield f'\n[{header}]\n'
        for key, value in values.items():
            if not isinstance(value, dict):
                yield f'{key} = {json.dumps(value, ensure_ascii=False, allow_nan=False)}\n'
        for key, value in values.items():
            if isinstance(value, dict):
                yield from section(value, f'{header}.{key}' if header else key)

    contents = ''.join(section(profile))
    temp = NamedTemporaryFile(dir=path.parent, delete=False, mode='w', encoding='utf-8')
    temp_path = Path(temp.name)
    try:
        with temp:
            temp.write(contents)
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def read_last_profile(preference, template):
    try:
        profile = json.loads(preference.read_text(encoding='utf-8'))
        build_plan(profile)
        return profile
    except (OSError, ValueError, TypeError):
        return read_template(template)


class ChannelFields:
    def __init__(self, page, channel):
        self.channel = channel
        self.fields = {}
        self.widgets = {}
        self.labels = {}
        self.enabled = tk.BooleanVar(page)
        self.round_trip = tk.BooleanVar(page)
        self.pulse = tk.BooleanVar(page)
        self.measure_voltage = tk.BooleanVar(page)
        self.measure_current = tk.BooleanVar(page)
        scan_checkbox(page, text=f'下发 CH{channel} 参数', variable=self.enabled).grid(
            column=0, row=0, columnspan=2, sticky='w', pady=(0, 7))
        source = ttk.LabelFrame(page, text='源与扫描', padding=9)
        sense = ttk.LabelFrame(page, text='测量与触发', padding=9)
        source.grid(row=1, column=0, sticky='nsew', padx=(0, 6))
        sense.grid(row=1, column=1, sticky='nsew', padx=(6, 0))
        for column in range(2):
            page.columnconfigure(column, weight=1)
        for section in (source, sense):
            section.columnconfigure(1, weight=1)

        self.add(source, 0, 'source', '源模式', SOURCES)
        self.add(source, 1, 'mode', '扫描方式', MODES)
        self.add(source, 2, 'initial', '初始输出')
        self.add(source, 3, 'compliance', '限值')
        self.add(source, 4, 'start', '起点')
        self.add(source, 5, 'stop', '终点')
        self.add(source, 6, 'step', '步长')
        self.add(source, 7, 'points', '点数（对数或旧模板）')
        self.add(source, 8, 'values', '列表值（逗号分隔）')
        self.widgets['round_trip'] = scan_checkbox(source, text='往返扫描', variable=self.round_trip)
        self.widgets['round_trip'].grid(row=9, column=0, columnspan=2, sticky='w', pady=2)
        self.widgets['pulse'] = scan_checkbox(source, text='脉冲输出', variable=self.pulse,
                                               command=self.update_fields)
        self.widgets['pulse'].grid(row=10, column=0, columnspan=2, sticky='w', pady=2)
        self.add(source, 11, 'delay_s', '脉冲延时 (s)')
        self.add(source, 12, 'width_s', '脉冲宽度 (s)')

        measure = ttk.Frame(sense)
        measure.grid(row=0, column=0, columnspan=2, sticky='w')
        scan_checkbox(measure, text='测量电压', variable=self.measure_voltage).pack(side='left', padx=(0, 6))
        scan_checkbox(measure, text='测量电流', variable=self.measure_current).pack(side='left')
        self.add(sense, 1, 'wire', '接线方式', ('2', '4'))
        self.add(sense, 2, 'nplc', '积分时间 (NPLC 或 auto)')
        self.add(sense, 3, 'trigger_source', '源触发', TRIGGER_CHOICES)
        self.add(sense, 4, 'trigger_acquire', '测量触发', TRIGGER_CHOICES)
        self.add(sense, 5, 'period_s', '定时周期 (s)')
        self.add(sense, 6, 'source_delay_s', '源触发延时 (s)')
        self.add(sense, 7, 'acquire_delay_s', '测量触发延时 (s)')
        self.add(sense, 8, 'source_count', '源触发次数')
        self.add(sense, 9, 'acquire_count', '测量触发次数')
        self.add(sense, 10, 'repeat', '重复次数')
        ttk.Label(sense, text='触发次数留空时按本轮点数计算。\nBUS、INT 和 EXT 需要相应触发事件。',
                  justify='left').grid(row=11, column=0, columnspan=2, sticky='w', pady=(8, 0))

    def add(self, pane, row, key, label, options=None):
        self.labels[key] = ttk.Label(pane, text=label)
        self.labels[key].grid(row=row, column=0, sticky='w', padx=(0, 8), pady=2)
        value = self.fields[key] = tk.StringVar(pane)
        if options:
            widget = ttk.Combobox(pane, textvariable=value, values=list(options), width=16, state='readonly')
            widget.bind('<<ComboboxSelected>>', lambda event: self.update_fields())
        else:
            widget = ttk.Entry(pane, textvariable=value, width=18)
        widget.grid(row=row, column=1, sticky='ew', pady=2)
        self.widgets[key] = widget

    def load(self, values):
        self.loaded = values
        default_source = 'voltage' if self.channel == 1 else 'current'
        default_mode = 'linear' if self.channel == 1 else 'fixed'
        pulse = values.get('pulse', {})
        trigger = values.get('trigger', {})
        measurement = values.get('measure', ['voltage', 'current'])
        sweep_values = values.get('values', [])
        source_choices = {value: label for label, value in SOURCES.items()}
        mode_choices = {value: label for label, value in MODES.items()}
        defaults = {
            'source': source_choices[values.get('source', default_source)],
            'mode': mode_choices[values.get('mode', default_mode)],
            'initial': values.get('initial', 0),
            'compliance': values.get('compliance', 0.001 if self.channel == 1 else 0.2),
            'start': values.get('start', 0), 'stop': values.get('stop', 0.1),
            'step': values.get('step', '' if 'points' in values else 0.01),
            'points': values.get('points', 11),
            'values': ', '.join(str(number) for number in sweep_values) if isinstance(sweep_values, list) else '',
            'delay_s': pulse.get('delay_s', 0.001), 'width_s': pulse.get('width_s', 0.01),
            'wire': values.get('wire', 2),
            'nplc': values.get('nplc', values.get('current_nplc', values.get('voltage_nplc', 'auto'))),
            'trigger_source': trigger.get('source', 'AINT'),
            'trigger_acquire': trigger.get('acquire', 'AINT'),
            'period_s': trigger.get('period_s', 0.1),
            'source_delay_s': trigger.get('source_delay_s', 0),
            'acquire_delay_s': trigger.get('acquire_delay_s', 0),
            'source_count': trigger.get('source_count', ''),
            'acquire_count': trigger.get('acquire_count', ''), 'repeat': trigger.get('repeat', 1),
        }
        for key, value in defaults.items():
            self.fields[key].set(str(value))
        self.enabled.set(values.get('enabled', self.channel == 1))
        self.round_trip.set(values.get('round_trip', False))
        self.pulse.set(bool(pulse))
        self.measure_voltage.set('voltage' in measurement)
        self.measure_current.set('current' in measurement)
        self.update_fields()

    def update_fields(self):
        mode = MODES.get(self.fields['mode'].get())
        voltage = SOURCES.get(self.fields['source'].get()) == 'voltage'
        unit = 'V' if voltage else 'A'
        self.labels['compliance'].configure(text='限流 (A)' if voltage else '限压 (V)')
        for key, label in {'initial': '初始输出', 'start': '起点', 'stop': '终点', 'step': '步长'}.items():
            self.labels[key].configure(text=f'{label} ({unit})')
        ranged = mode in ('linear', 'log')
        pulse_enabled = mode != 'fixed' and self.pulse.get()
        timed = any(self.fields[k].get() == 'TIM' for k in ('trigger_source', 'trigger_acquire'))
        for key, enabled in {'start': ranged, 'stop': ranged, 'step': mode == 'linear', 'points': mode == 'log',
                             'values': mode == 'list', 'round_trip': ranged, 'pulse': mode != 'fixed',
                             'delay_s': pulse_enabled, 'width_s': pulse_enabled, 'period_s': timed}.items():
            self.widgets[key].configure(state='normal' if enabled else 'disabled')

    def read(self, *, include_disabled=False):
        if not include_disabled and not self.enabled.get():
            return {**self.loaded, 'enabled': False}

        def field(key):
            return self.fields[key].get().strip()

        def numeric(key, kind=float):
            try:
                return kind(field(key))
            except ValueError as error:
                raise ValueError(f'CH{self.channel}「{self.labels[key].cget("text")}」请输入有效数值。') from error

        mode = MODES[field('mode')]
        nplc = 'auto' if field('nplc').lower() == 'auto' else numeric('nplc')
        settings = {
            'enabled': self.enabled.get(), 'source': SOURCES[field('source')], 'mode': mode,
            'initial': numeric('initial'), 'compliance': numeric('compliance'),
            'measure': [name for name, checked in (('voltage', self.measure_voltage), ('current', self.measure_current))
                        if checked.get()],
            'wire': numeric('wire', int), 'nplc': nplc,
        }
        if mode in ('linear', 'log'):
            settings.update(start=numeric('start'), stop=numeric('stop'), round_trip=self.round_trip.get())
            legacy_points = not field('step') and 'points' in self.loaded and 'step' not in self.loaded
            key = 'points' if mode == 'log' or legacy_points else 'step'
            settings[key] = numeric(key, float if key == 'step' else int)
        if mode == 'list':
            try:
                settings['values'] = [float(value) for value in re.split(r'[,，\s]+', field('values')) if value]
            except ValueError as error:
                raise ValueError(f'CH{self.channel} 列表值须为逗号分隔的数字。') from error
        if mode != 'fixed' and self.pulse.get():
            settings['pulse'] = {key: numeric(key) for key in ('delay_s', 'width_s')}
        trigger = settings['trigger'] = {
            'source': field('trigger_source'), 'acquire': field('trigger_acquire'),
            'source_delay_s': numeric('source_delay_s'), 'acquire_delay_s': numeric('acquire_delay_s'),
            'repeat': numeric('repeat', int),
        }
        if 'TIM' in (trigger['source'], trigger['acquire']):
            trigger['period_s'] = numeric('period_s')
        for key in ('source_count', 'acquire_count'):
            if field(key):
                trigger[key] = numeric(key, int)
        return settings


def edit_scan_parameters(parent, starting, template_path):
    dialog = tk.Toplevel(parent)
    dialog.withdraw()
    dialog.title('B2962B 扫描参数')
    dialog.transient(parent)
    layout = ttk.Frame(dialog, padding=12)
    layout.pack(fill='both', expand=True)
    grouped = tk.BooleanVar(dialog)
    group_check = scan_checkbox(layout, text='CH1 和 CH2 同步分组', variable=grouped)
    group_check.pack(anchor='w', pady=(0, 6))
    Tooltip(group_check, '协调双通道的扫描和采样时序。下发时两路都需启用，并匹配触发设置。')
    tabs = ttk.Notebook(layout)
    tabs.pack(fill='both', expand=True)
    channels = {}
    for channel in (1, 2):
        page = ttk.Frame(tabs, padding=8)
        tabs.add(page, text=f'CH{channel}')
        channels[channel] = ChannelFields(page, channel)

    status = tk.StringVar(dialog)
    ttk.Label(layout, textvariable=status, wraplength=670).pack(fill='x', pady=(8, 4))
    selected = None
    preset_path = None

    def load(profile):
        grouped.set(profile.get('group_channels', False))
        for ch, form in channels.items():
            form.load(profile.get(f'ch{ch}', {}))
        status.set('线性扫描按步长计算点数。启用某路后才会下发该路参数。')

    def reload():
        try:
            load(read_template(template_path))
        except (OSError, ValueError, KeyError) as error:
            status.set(f'无法读取 TOML：{error}')

    def current_profile(*, include_disabled=False):
        return {'group_channels': grouped.get(), **{
            f'ch{ch}': form.read(include_disabled=include_disabled) for ch, form in channels.items()
        }}

    def import_preset():
        nonlocal preset_path
        name = filedialog.askopenfilename(parent=dialog, title='导入扫描参数', filetypes=TOML_FILE_TYPES,
                                          initialdir=(preset_path or template_path).parent)
        if not name:
            return
        path = Path(name)
        try:
            profile = read_template(path)
            build_plan(profile, preset=True)
            load(profile)
        except (OSError, ValueError, KeyError) as error:
            messagebox.showwarning('无法导入参数', str(error), parent=dialog)
            return
        preset_path = path
        status.set(f'已导入 {path.name}。如需应用到仪器，请点「下发参数」。')

    def save_preset():
        nonlocal preset_path
        try:
            profile = current_profile(include_disabled=True)
            build_plan(profile, preset=True)
            initial = preset_path or template_path
            filename = 'b2962b_preset.toml' if initial == template_path else initial.name
            name = filedialog.asksaveasfilename(parent=dialog, title='保存扫描参数', filetypes=TOML_FILE_TYPES,
                                                initialdir=initial.parent, initialfile=filename,
                                                defaultextension='.toml')
            if not name:
                return
            path = Path(name)
            if path.resolve() == template_path.resolve():
                address = read_template(template_path).get('address', '')
                profile = {'address': address, **profile}
            write_preset(path, profile)
        except (OSError, ValueError, KeyError) as error:
            messagebox.showwarning('无法保存参数', str(error), parent=dialog)
            return
        preset_path = path
        status.set(f'已保存参数到 {path}')

    def submit(apply_settings):
        nonlocal selected
        try:
            profile = current_profile()
            _, group, plans = build_plan(profile)
        except (ValueError, KeyError) as error:
            status.set(str(error))
            if apply_settings:
                messagebox.showwarning('参数未下发', str(error), parent=dialog)
            return
        if apply_settings:
            selected = profile, group, plans
            dialog.destroy()
        else:
            status.set('  ·  '.join(f'CH{ch} 每轮 {points} 点，源触发 {timing[0][1]} 次，测量触发 {timing[1][1]} 次'
                                     for ch, (_, _, timing, points, _) in plans.items()))

    buttons = ttk.Frame(layout)
    buttons.pack(fill='x', pady=(4, 0))
    buttons.columnconfigure(1, weight=1, minsize=24)
    presets = ttk.Frame(buttons)
    presets.grid(row=0, column=0, sticky='w')
    actions = ttk.Frame(buttons)
    actions.grid(row=0, column=2, sticky='e')

    for frame, entries in (
        (presets, (
            ('载入默认模板', reload, '用程序自带的 TOML 模板填充两路参数。'),
            ('导入参数', import_preset, '从选定的 TOML 文件恢复两路表单设置。'),
            ('保存参数', save_preset, '选择位置和文件名，将当前两路设置保存为 TOML。'),
        )),
        (actions, (
            ('预览点数', lambda: submit(False), '计算每轮扫描的点数及触发次数。'),
            ('取消', dialog.destroy, '关闭本窗口，放弃本次尚未下发的表单修改。'),
            ('下发参数', lambda: submit(True), '检查当前设置，并将勾选通道的参数写入仪器。'),
        )),
    ):
        for index, (text, command, hint) in enumerate(entries):
            button = ttk.Button(frame, text=text, command=command)
            button.pack(side='left', padx=(8 if index else 0, 0))
            Tooltip(button, hint)

    load(starting)
    center_dialog(dialog, parent)
    dialog.deiconify()
    dialog.grab_set()
    dialog.focus_set()
    parent.wait_window(dialog)
    return selected
