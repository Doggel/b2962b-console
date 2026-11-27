"""Control B2962B outputs, trigger measurements, and export CSV data."""

import argparse
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
from queue import Empty, Queue
import re
import sys
from threading import Thread
import tomllib

from b2962b_configure import BUSY_OPERATIONS, IDLE_ACTIONS, configure, require_idle, require_no_error
from visa_read_iv import CHANNELS, export_iv


FROZEN = getattr(sys, 'frozen', False)
ROOT = Path(sys.executable if FROZEN else __file__).resolve().parent
LOCAL_PACKAGES = str(ROOT / '.packages')
TARGETS = {'CH1': (1,), 'CH2': (2,), 'CH1 + CH2': CHANNELS}
FOLDER_PREF = ROOT / '.iv_export_folder'
SCAN_TEMPLATE = ROOT / 'b2962b_scan.toml'
SCAN_PROFILE = ROOT / '.b2962b_scan_form.json'


@contextmanager
def connect():
    if not FROZEN and LOCAL_PACKAGES not in sys.path:
        sys.path.insert(0, LOCAL_PACKAGES)
    import pyvisa

    config = tomllib.loads(SCAN_TEMPLATE.read_text(encoding='utf-8-sig'))
    address = config.get('address', '').strip()
    with closing(pyvisa.ResourceManager()) as manager:
        if not address:
            matches = [r for r in manager.list_resources('USB?*INSTR')
                       if re.match(r'USB\d*::0x2A8D::0x9701::', r, re.I)]
            if len(matches) != 1:
                raise RuntimeError('请在 b2962b_scan.toml 填写 Connection Expert 显示的 VISA 地址。')
            address = matches[0]
        with closing(manager.open_resource(address, open_timeout=3000)) as instrument:
            instrument.timeout = 3000
            instrument.write_termination = '\n'
            instrument.read_termination = '\n'
            identity = instrument.query('*IDN?').strip()
            model = identity.split(',')[1:2]
            if not model or model[0].strip().upper() != 'B2962B':
                raise RuntimeError(f'连接的设备不是 B2962B：{identity}')
            yield instrument, identity


def read_output(instrument, channel):
    reply = instrument.query(f':OUTP{channel}?').strip().upper()
    if reply not in ('0', '1', 'OFF', 'ON'):
        raise RuntimeError(f'CH{channel} 返回了无法识别的输出状态：{reply}')
    return reply in ('1', 'ON')


def read_outputs(instrument):
    return {channel: read_output(instrument, channel) for channel in CHANNELS}


@dataclass(frozen=True)
class Source:
    mode: str
    level: float
    positive_limit: float
    negative_limit: float

    def describe(self):
        if self.mode == 'VOLT':
            source, unit, limit, limit_unit = '电压源', 'V', '限流', 'A'
        else:
            source, unit, limit, limit_unit = '电流源', 'A', '限压', 'V'
        return (f'{source}设定值  {self.level:.9g} {unit}\n'
                f'正向{limit}  {abs(self.positive_limit):.9g} {limit_unit}\n'
                f'负向{limit}  {-abs(self.negative_limit):.9g} {limit_unit}')


def read_source(instrument, channel):
    modes = {'VOLT': 'CURR', 'CURR': 'VOLT'}
    mode = instrument.query(f':SOUR{channel}:FUNC:MODE?').strip().upper()
    if mode not in modes:
        raise RuntimeError(f'CH{channel} 返回了无法识别的源模式：{mode}')
    limit = f':SENS{channel}:{modes[mode]}:PROT'
    values = [float(instrument.query(command)) for command in
              (f':SOUR{channel}:{mode}?', f'{limit}:POS?', f'{limit}:NEG?')]
    if any(not math.isfinite(value) or abs(value) >= 9e37 for value in values):
        raise RuntimeError(f'CH{channel} 返回的设定值或保护限值无效。')
    return Source(mode, *values)


def set_output(instrument, channel, enabled, confirmed=None):
    if channel not in CHANNELS:
        raise ValueError('通道必须是 CH1 或 CH2。')
    if enabled:
        if confirmed is None or read_source(instrument, channel) != confirmed:
            raise RuntimeError(f'CH{channel} 的设定值或限值未确认或已变化，请重新核对。')
    instrument.write(f':OUTP{channel} {"ON" if enabled else "OFF"}')
    states = read_outputs(instrument)
    if states[channel] != enabled:
        error = instrument.query(':SYST:ERR?').strip()
        raise RuntimeError(f'CH{channel} 的输出状态未达到预期。仪器错误队列：{error}')
    return states


def close_both_outputs(instrument):
    errors = {}
    for channel in CHANNELS:
        try:
            instrument.write(f':OUTP{channel} OFF')
        except Exception as error:
            # A communication error on one write must not skip the other channel.
            errors[channel] = str(error) or type(error).__name__

    outputs, problems = {}, []
    for channel in CHANNELS:
        try:
            outputs[channel] = read_output(instrument, channel)
        except Exception as error:
            outputs[channel] = None
            problems.append(f'CH{channel} 状态未确认（{str(error) or type(error).__name__}）')
        else:
            if outputs[channel]:
                detail = f'（{errors[channel]}）' if channel in errors else ''
                problems.append(f'CH{channel} 仍开启{detail}')
    return outputs, problems


def scan_active(instrument):
    reply = instrument.query(':STAT:OPER:COND?').strip().upper()
    radix = {'#B': 2, '#Q': 8, '#H': 16}.get(reply[:2])
    status = int(reply[2:], radix) if radix else int(reply)
    return (status & IDLE_ACTIONS) != IDLE_ACTIONS or bool(status & BUSY_OPERATIONS)


def require_scan_idle(instrument):
    if scan_active(instrument):
        raise RuntimeError('仪器仍在运行或等待触发，请等本轮测量结束。')


def channels_grouped(instrument):
    group = instrument.query(':SYST:GRO:DEF?').strip().replace(' ', '')
    if group == '(@1,2)':
        return True
    if group == '(@1),(@2)':
        return False
    raise RuntimeError(f'无法识别当前通道分组：{group}')


@dataclass(frozen=True)
class DeviceState:
    identity: str
    outputs: dict
    running: bool
    grouped: bool


def read_device(instrument, identity):
    return DeviceState(identity, read_outputs(instrument), scan_active(instrument), channels_grouped(instrument))


def query_device():
    with connect() as (instrument, identity):
        return read_device(instrument, identity)


@dataclass(frozen=True)
class ScanRun:
    identity: str
    totals: dict[int, int | None]
    folder: Path | None
    close_outputs: bool = False


def acquisition_totals(instrument, channels):
    def count(command):
        reply = instrument.query(command).strip().upper()
        if reply in ('INF', 'INFINITY'):
            return 0
        return max(0, int(reply))

    totals = {}
    for channel in channels:
        total = count(f':ARM{channel}:ACQ:COUN?') * count(f':TRIG{channel}:ACQ:COUN?')
        totals[channel] = total if 0 < total <= 100000 else None
    return totals


def buffer_counts(instrument, channels):
    counts = {}
    for channel in channels:
        try:
            count = int(instrument.query(f':SYST:DATA:QUAN? (@{channel})').strip())
        except Exception:
            # Some instrument states do not expose progress. Keep polling operation status.
            continue
        if 0 <= count <= 100000:
            counts[channel] = count
    return counts


def observe_scan(scan):
    with connect() as (instrument, identity):
        state = read_device(instrument, identity)
        counts = buffer_counts(instrument, scan.totals) if scan and scan.identity == identity else {}
        return state, counts


def initiate_scan(instrument, channels):
    if channels not in TARGETS.values():
        raise ValueError('请选择 CH1、CH2 或两路通道。')
    require_scan_idle(instrument)
    if channels_grouped(instrument) and channels != CHANNELS:
        raise RuntimeError('仪器目前已分组，请选择 CH1 + CH2 同时触发。')
    outputs = read_outputs(instrument)
    off = [f'CH{channel}' for channel in channels if not outputs[channel]]
    if off:
        raise RuntimeError('请先手动开启输出：' + '、'.join(off))
    require_no_error(instrument, '触发前检查')
    selected = ','.join(str(channel) for channel in channels)
    instrument.write(f':INIT (@{selected})')
    require_no_error(instrument, '启动扫描')


def export_completed(instrument, channels, folder=ROOT):
    require_scan_idle(instrument)
    return export_iv(instrument.query, folder, channels, before_save=lambda: require_scan_idle(instrument))


def reset_defaults(instrument):
    require_idle(instrument)
    instrument.write('*RST')
    if instrument.query('*OPC?').strip() != '1':
        raise RuntimeError('仪器没有确认复位完成，请刷新状态。')
    require_no_error(instrument, '恢复默认参数')
    require_idle(instrument)


def resolve_folder(value):
    folder = Path(value.strip().strip('"')).expanduser()
    if not folder.is_absolute():
        folder = ROOT / folder
    folder = folder.resolve()
    if not folder.is_dir():
        raise ValueError(f'保存位置不存在，请选择一个已有文件夹：{folder}')
    return folder


def preferred_folder():
    try:
        return resolve_folder(FOLDER_PREF.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ROOT


def run_window():
    import tkinter as tk
    from tkinter import filedialog, messagebox
    from b2962b_console_view import ConsoleView
    from b2962b_scan_form import edit_scan_parameters, read_last_profile
    from b2962b_window import show_main_window

    root = tk.Tk()
    root.withdraw()
    device = None
    results = Queue()
    busy = False
    poll = None
    polling = False
    queued = None
    tracked_scan = None
    draft = None

    def show_states():
        controls_busy = busy and (not polling or queued is not None)
        idle = device is not None and not device.running and tracked_scan is None
        outputs = device.outputs if device is not None else {}
        selected = TARGETS[view.target.get()]
        view.set_control(view.refresh, not controls_busy)
        view.set_control(view.pick, not controls_busy and idle and not device.grouped, active_state='readonly')
        view.set_control(view.start, not controls_busy and idle and all(outputs.get(ch) for ch in selected))
        view.set_control(view.export, not controls_busy and idle)
        both_off = all(outputs.get(channel) is False for channel in CHANNELS)
        view.set_control(view.close_both, not controls_busy and not both_off)
        outputs_off = idle and both_off
        view.set_control(view.setup, not controls_busy and (outputs_off or (device is None and tracked_scan is None)))
        view.set_control(view.reset, not controls_busy and outputs_off)
        for control in (view.folder_entry, view.folder_button, view.auto_export_check, view.auto_close_check):
            view.set_control(control, not controls_busy and tracked_scan is None)
        for channel in CHANNELS:
            view.set_output(channel, outputs.get(channel), controls_busy, idle)

    def schedule_poll():
        nonlocal poll
        if poll is None and (tracked_scan is not None or (device is not None and device.running)):
            poll = root.after(900, poll_status)

    def show_result(result, message, *, error=False):
        nonlocal device
        device = result
        fields = device.identity.split(',')
        serial = fields[2].strip() if len(fields) > 2 else ''
        if device.grouped and view.target.get() != 'CH1 + CH2':
            view.target.set('CH1 + CH2')
        details = []
        if device.running:
            details.append('扫描进行中或等待触发')
        if device.grouped:
            details.append('双通道分组')
        view.set_connection(f'已连接  {serial}'.strip(), '  ·  '.join(details), connected=True)
        view.set_feedback(message, error=error)
        show_states()
        schedule_poll()

    def finish(callback, background):
        nonlocal busy, polling, queued, device
        try:
            result, error = results.get_nowait()
        except Empty:
            root.after(60, finish, callback, background)
            return
        busy = False
        polling = False
        if queued is not None:
            request, queued = queued, None
            run(*request)
            return
        if error:
            if background:
                view.set_feedback('暂时无法读取扫描状态，正在重试。', error=True)
            else:
                device = None
                view.set_connection('仪器状态未确认', '请刷新状态')
                view.set_feedback(f'操作未确认：{error}', error=True)
                show_states()
            schedule_poll()
        else:
            callback(result)

    def run(work, callback, pending=None, *, background=False):
        nonlocal busy, poll, polling, queued
        if busy:
            if polling and not background and queued is None:
                queued = work, callback, pending
                if pending:
                    view.set_feedback(pending)
                show_states()
            return
        if poll is not None:
            root.after_cancel(poll)
            poll = None
        busy = True
        polling = background
        if pending:
            view.set_feedback(pending)
        if not background:
            show_states()

        def worker():
            try:
                results.put((work(), None))
            except Exception as error:
                results.put((None, str(error) or type(error).__name__))

        Thread(target=worker, daemon=True).start()
        root.after(60, finish, callback, background)

    def show_observation(observation, idle_message):
        nonlocal tracked_scan
        state, counts = observation
        if tracked_scan is None:
            show_result(state, '扫描进行中或等待触发…' if state.running else idle_message)
            return
        scan = tracked_scan
        if state.identity != scan.identity:
            tracked_scan = None
            view.set_progress('本轮扫描的仪器连接已变化', outcome='incomplete')
            show_result(state, '仪器已变化，无法执行本轮扫描的自动操作。', error=True)
            return

        labels = [f'CH{ch} 已采 {counts.get(ch, "—")}/{total or "—"} 点' for ch, total in scan.totals.items()]
        percent = 0
        if all(total and ch in counts for ch, total in scan.totals.items()):
            percent = 100 * sum(min(total, counts[ch]) for ch, total in scan.totals.items()) / sum(scan.totals.values())
        if state.running:
            view.set_progress('  ·  '.join(labels), percent)
            show_result(state, '扫描进行中或等待触发…')
            return

        tracked_scan = None
        complete = all(total is not None and counts.get(ch) == total for ch, total in scan.totals.items())
        if complete:
            summary = '扫描完成'
        elif any(total is not None and ch in counts and counts[ch] < total for ch, total in scan.totals.items()):
            summary = '扫描结束，点数不足'
        else:
            summary = '扫描结束，点数未确认'
        view.set_progress('  ·  '.join([summary, *labels]), percent,
                          outcome='complete' if complete else 'incomplete')
        finish_scan_actions(state, scan, summary, complete)

    def refresh_status():
        scan = tracked_scan
        run(lambda: observe_scan(scan), lambda result: show_observation(result, '已从仪器刷新状态'),
            '正在读取仪器状态…')

    def poll_status():
        nonlocal poll
        poll = None
        scan = tracked_scan
        run(lambda: observe_scan(scan), lambda result: show_observation(result, '仪器空闲，可点「导出 CSV」。'),
            background=True)

    def open_scan_settings():
        nonlocal draft
        try:
            profile = draft if draft is not None else read_last_profile(SCAN_PROFILE, SCAN_TEMPLATE)
            selected = edit_scan_parameters(root, profile, SCAN_TEMPLATE)
        except (OSError, ValueError, KeyError) as error:
            view.set_feedback(f'无法载入扫描参数：{error}', error=True)
            return
        if selected is None:
            return
        draft, grouped, channels = selected
        profile = draft

        def work():
            with connect() as (instrument, identity):
                instrument.timeout = 10000
                configure(instrument, grouped, channels)
                return read_device(instrument, identity)

        def done(result):
            view.target.set(' + '.join(f'CH{ch}' for ch in channels))
            view.parameter_summary.set('已下发  ·  ' + '  /  '.join(
                f'CH{ch} {plan[3]} 点' for ch, plan in channels.items()))
            message = '参数已下发并读回核对。开启所需输出后，可启动扫描。'
            try:
                SCAN_PROFILE.write_text(json.dumps(profile, ensure_ascii=False, indent=2, allow_nan=False),
                                        encoding='utf-8')
            except (OSError, ValueError):
                message += '\n未能记住表单参数。'
            show_result(result, message)

        run(work, done, '正在下发并核对扫描参数…')

    def request_reset():
        if not messagebox.askyesno(
            '恢复默认参数',
            '将复位整台 B2962B，恢复 CH1 和 CH2 的仪器初始设置。\n'
            '请先导出需要保留的扫描结果。\n\n确认复位？',
            parent=root, default=messagebox.NO,
        ):
            return

        def work():
            with connect() as (instrument, identity):
                instrument.timeout = 15000
                reset_defaults(instrument)
                return read_device(instrument, identity)

        def done(result):
            view.parameter_summary.set('仪器已恢复默认参数')
            show_result(result, '仪器已恢复初始设置。可重新下发自定义扫描参数。')

        run(work, done, '正在复位仪器…')

    def switch(channel, enabled, expected_identity=None, confirmed=None):
        if not enabled:
            cancel_auto_export(channel)

        def work():
            with connect() as (instrument, identity):
                if expected_identity is not None and identity != expected_identity:
                    raise RuntimeError('连接的仪器已变化，请重新核对。')
                if enabled:
                    require_scan_idle(instrument)
                set_output(instrument, channel, enabled, confirmed)
                return read_device(instrument, identity)

        action = '开启' if enabled else '关闭'
        run(work, lambda result: show_result(result, f'CH{channel} 输出已{action}，仪器已确认'),
            f'正在{action} CH{channel} 输出…')

    def request_close_both():
        cancel_auto_export()

        def work():
            with connect() as (instrument, identity):
                outputs, problems = close_both_outputs(instrument)
                state = DeviceState(identity, outputs, scan_active(instrument), channels_grouped(instrument))
                return state, problems

        def done(result):
            state, problems = result
            message = '；'.join(problems) if problems else 'CH1 和 CH2 输出均已关闭，仪器已确认。'
            show_result(state, message, error=bool(problems))

        run(work, done, '正在关闭并核对两路输出…')

    def cancel_auto_export(channel=None):
        nonlocal tracked_scan
        if tracked_scan and (channel is None or channel in tracked_scan.totals):
            tracked_scan = replace(tracked_scan, folder=None)

    def request_on(channel):
        def read_confirmation():
            with connect() as (instrument, identity):
                return identity, read_source(instrument, channel)

        def confirm(result):
            identity, source = result
            if messagebox.askyesno(f'开启 CH{channel} 输出',
                                   f'CH{channel}\n\n{source.describe()}\n\n确认开启输出？',
                                   parent=root, default=messagebox.NO):
                switch(channel, True, identity, source)
            else:
                view.set_feedback(f'已取消开启 CH{channel}')
                show_states()

        run(read_confirmation, confirm, f'正在读取 CH{channel} 设定值和限值…')

    def start_scan():
        selected = TARGETS[view.target.get()]
        expected_identity = device.identity
        close_outputs = view.auto_close_outputs.get()
        try:
            folder = resolve_folder(view.destination.get()) if view.auto_export.get() else None
        except (OSError, ValueError) as error:
            view.set_feedback(str(error), error=True)
            return

        def work():
            with connect() as (instrument, identity):
                if identity != expected_identity:
                    raise RuntimeError('连接的仪器已变化，请刷新状态并重新核对。')
                totals = acquisition_totals(instrument, selected)
                initiate_scan(instrument, selected)
                return ScanRun(identity, totals, folder, close_outputs)

        def done(scan):
            nonlocal tracked_scan
            tracked_scan = scan
            view.set_progress('  ·  '.join(f'CH{ch} 已采 0/{total or "—"} 点' for ch, total in scan.totals.items()))
            show_result(replace(device, running=True), '已触发，正在读取扫描进度…')

        run(work, done, '正在启动扫描…')

    def export_scan():
        selected = TARGETS[view.target.get()]
        try:
            folder = resolve_folder(view.destination.get())
        except (OSError, ValueError) as error:
            view.set_feedback(str(error), error=True)
            return
        def work():
            with connect() as (instrument, identity):
                instrument.timeout = 15000
                path = export_completed(instrument, selected, folder)
                return read_device(instrument, identity), path

        def done(result):
            readings, path = result
            message = saved_export_message(path, folder, '已保存') if path else '所选通道没有有效数据，未生成 CSV。'
            show_result(readings, message, error=path is None)

        run(work, done, '正在读取扫描结果…')

    def saved_export_message(path, folder, label):
        message = f'{label}：{path}'
        try:
            FOLDER_PREF.write_text(str(folder), encoding='utf-8')
        except OSError:
            message += '\n下次启动时可能需要重新选择保存位置。'
        return message

    def finish_scan_actions(state, scan, summary, complete):
        # Shut down first. OUTP OFF preserves the acquired measurement buffer.
        close_needed = scan.close_outputs and any(state.outputs.get(ch) is not False for ch in CHANNELS)
        export_requested = complete and scan.folder is not None
        if not close_needed and not export_requested:
            closed = '两路输出均已关闭。' if scan.close_outputs else ''
            show_result(state, f'{summary}。{closed}可点「导出 CSV」。', error=not complete)
            return

        def work():
            with connect() as (instrument, identity):
                if identity != scan.identity:
                    raise RuntimeError('连接的仪器已变化，无法执行本轮扫描的自动操作。')
                require_scan_idle(instrument)
                outputs, problems = close_both_outputs(instrument) if close_needed else (state.outputs, [])
                path = None
                if export_requested:
                    try:
                        instrument.timeout = 15000
                        if buffer_counts(instrument, scan.totals) != scan.totals:
                            raise RuntimeError('仪器缓冲区点数已变化')
                        path = export_completed(instrument, tuple(scan.totals), scan.folder)
                        if path is None:
                            raise RuntimeError('所选通道没有有效数据')
                    except Exception as error:
                        problems.append(f'自动导出失败：{str(error) or type(error).__name__}')
                return replace(state, outputs=outputs), path, problems

        def done(result):
            readings, path, problems = result
            messages = [f'{summary}。']
            if scan.close_outputs and all(readings.outputs.get(ch) is False for ch in CHANNELS):
                messages.append('两路输出均已关闭。')
            if problems:
                messages.append('；'.join(problems) + '。')
            if path:
                messages.append(saved_export_message(path, scan.folder, '已自动导出'))
            else:
                messages.append('可点「导出 CSV」。')
            show_result(readings, ''.join(messages), error=bool(problems) or not complete)

        pending = '正在关闭两路输出…' if close_needed else '正在自动导出 CSV…'
        run(work, done, f'{summary}。{pending}')

    def choose_folder():
        try:
            initial = resolve_folder(view.destination.get())
        except (OSError, ValueError):
            initial = ROOT
        folder = filedialog.askdirectory(parent=root, initialdir=str(initial), title='选择 CSV 保存文件夹')
        if folder:
            view.destination.set(folder)

    view = ConsoleView(root, TARGETS, preferred_folder(), {
        'refresh': refresh_status, 'setup': open_scan_settings, 'reset': request_reset,
        'on': request_on, 'off': lambda channel: switch(channel, False),
        'close_both': request_close_both,
        'target_changed': lambda event: show_states(), 'start': start_scan, 'export': export_scan,
        'folder': choose_folder,
    })

    def close_window():
        if busy:
            return
        root.destroy()

    root.protocol('WM_DELETE_WINDOW', close_window)
    show_states()
    show_main_window(root)
    root.after_idle(refresh_status)
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='read the instrument and output status without switching')
    if parser.parse_args().check:
        state = query_device()
        print(state.identity)
        for channel, enabled in state.outputs.items():
            print(f'CH{channel}: {"ON" if enabled else "OFF"}')
        print(f'Trigger: {"active" if state.running else "idle"}; channels: {"grouped" if state.grouped else "independent"}')
    else:
        run_window()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'无法完成操作：{error}', file=sys.stderr)
        sys.exit(1)
