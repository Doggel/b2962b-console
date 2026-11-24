"""Configure a B2962B over VISA, leaving the scan to the front panel."""

import argparse
import math
import re
import sys
import tomllib
from contextlib import closing
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRIGGERS = {'AINT', 'TIM', 'BUS', 'INT1', 'INT2', *(f'EXT{i}' for i in range(1, 15))}
CHANNEL_KEYS = ('enabled source mode initial start stop step points values round_trip compliance '
                'measure wire nplc voltage_nplc current_nplc trigger pulse')
# Operation Status register, Figure 1-5 in the B2961B/B2962B SCPI reference.
IDLE_ACTIONS = (1 << 1) | (1 << 4) | (1 << 7) | (1 << 10)
BUSY_OPERATIONS = (1 << 0) | (1 << 13)


def table(value, name, keys):
    if not isinstance(value, dict):
        raise ValueError(f'{name} 必须是 TOML 配置表')
    unknown = value.keys() - set(keys.split())
    if unknown:
        raise ValueError(f'{name} 存在未知参数：{", ".join(sorted(unknown))}')
    return value


def number(value, name, minimum, maximum):
    if type(value) not in (float, int) or not minimum <= value <= maximum:
        raise ValueError(f'{name} 必须为 {minimum:g} 到 {maximum:g} 之间的数字')
    return value


def count(value, name, minimum=1):
    if type(value) is not int or not minimum <= value <= 100000:
        raise ValueError(f'{name} 必须为 {minimum} 到 100000 之间的整数')
    return value


def points_from_step(start, stop, step, label):
    # Use the decimal input values so, for example, 0.3 / 0.1 gives exactly 3 steps.
    first, last, stride = (Fraction(str(v)) for v in (start, stop, step))
    intervals = abs(last - first) / stride
    if intervals.denominator != 1:
        raise ValueError(f'{label} |stop - start| 必须是 step 的整数倍。请调整终点或步长。')
    return count(intervals.numerator + 1, f'{label} 由步长计算的单程点数', 2)


def flag(value, name):
    if type(value) is not bool:
        raise ValueError(f'{name} 必须为 true 或 false')
    return value


def channel_plan(ch, config):
    label = f'ch{ch}'
    source_kind = config.get('source', 'voltage')
    if source_kind not in ('voltage', 'current'):
        raise ValueError(f'{label}.source 必须为 voltage 或 current')
    voltage_source = source_kind == 'voltage'
    source = 'VOLT' if voltage_source else 'CURR'
    limit_kind = 'CURR' if voltage_source else 'VOLT'
    maximum = 210 if voltage_source else 3.03
    s, m = f':SOUR{ch}', f':SENS{ch}'
    writes, checks = [], []

    def set_value(header, value, *, verify=True):
        arg = format(value, '.12g') if type(value) is float else str(value)
        writes.append(f'{header} {arg}')
        if verify:
            checks.append((header + '?', value))

    mode = config.get('mode', 'linear')
    if mode not in ('fixed', 'linear', 'log', 'list'):
        raise ValueError(f'{label}.mode 必须为 fixed、linear、log 或 list')
    initial = number(config.get('initial', 0), f'{label}.initial', -maximum, maximum)
    compliance = number(config.get('compliance'), f'{label}.compliance', 1e-12, 3.03 if voltage_source else 210)
    measurement = config.get('measure', ['voltage', 'current'])
    if (not isinstance(measurement, list) or not measurement
            or any(item not in ('voltage', 'current') for item in measurement)):
        raise ValueError(f'{label}.measure 必须包含 voltage 或 current')
    wire = config.get('wire', 2)
    if type(wire) is not int or wire not in (2, 4):
        raise ValueError(f'{label}.wire 必须为 2 或 4')

    set_value(f'{s}:FUNC:MODE', source)
    set_value(f'{s}:FUNC:TRIG:CONT', 0)
    set_value(f'{m}:{limit_kind}:PROT', compliance)
    set_value(f'{s}:{source}:RANG:AUTO', 1)
    set_value(f'{s}:{source}', initial)
    set_value(f'{m}:REM', int(wire == 4))
    for name, code in [('voltage', 'VOLT'), ('current', 'CURR'), ('resistance', 'RES')]:
        enabled = name in measurement
        writes.append(f'{m}:FUNC:{"ON" if enabled else "OFF"} "{code}"')
        checks.append((f'{m}:FUNC:STAT? "{code}"', int(enabled)))

    # This firmware shares the aperture and its auto setting across V and I per channel.
    integration = [config[key] for key in ('nplc', 'voltage_nplc', 'current_nplc') if key in config]
    if integration and any(value != integration[0] for value in integration):
        raise ValueError(f'{label} 的电压和电流共用积分时间，请改用一个 nplc 参数')
    nplc = integration[0] if integration else 'auto'
    sense = f'{m}:{"CURR" if "current" in measurement else "VOLT"}:NPLC'
    set_value(f'{sense}:AUTO', int(nplc == 'auto'))
    if nplc != 'auto':
        set_value(sense, number(nplc, f'{label}.nplc', 0.00048, 100))

    pulse = table(config.get('pulse', {}), f'{label}.pulse', 'width_s delay_s')
    set_value(f'{s}:FUNC:SHAP', 'PULS' if pulse else 'DC')
    if pulse:
        if mode == 'fixed':
            raise ValueError(f'{label} 的脉冲配置适用于扫描模式')
        set_value(f'{s}:PULS:DEL', number(pulse.get('delay_s', 0), f'{label}.pulse.delay_s', 0, 100000))
        set_value(f'{s}:PULS:WIDT', number(pulse.get('width_s'), f'{label}.pulse.width_s', 50e-6, 100000))

    round_trip = flag(config.get('round_trip', False), f'{label}.round_trip')
    if round_trip and mode not in ('linear', 'log'):
        raise ValueError(f'{label}.round_trip 仅适用于 linear 或 log')
    values = None
    points = 1
    step = None
    if mode in ('linear', 'log'):
        start = number(config.get('start'), f'{label}.start', -maximum, maximum)
        stop = number(config.get('stop'), f'{label}.stop', -maximum, maximum)
        if start == stop or (mode == 'log' and start * stop <= 0):
            raise ValueError(f'{label} 起止值必须不同，对数扫描还要求同号且非零')
        if mode == 'linear' and 'step' in config:
            step = number(config['step'], f'{label}.step', 0, 2 * maximum)
            if step == 0:
                raise ValueError(f'{label}.step 必须大于 0，扫描方向由 start 和 stop 决定')
            points = points_from_step(start, stop, step, label)
        else:
            if mode == 'log' and 'points' not in config:
                raise ValueError(f'{label} 的对数扫描请填写 points，线性步长 step 不适用')
            points = count(config.get('points'), f'{label}.points', 2)
        if round_trip:
            count(2 * points - 1, f'{label} 往返点数')
            if mode == 'linear':
                forward = [start + (stop - start) * i / (points - 1) for i in range(points)]
            else:
                first, last = math.log(abs(start)), math.log(abs(stop))
                forward = [math.copysign(math.exp(first + (last - first) * i / (points - 1)), start)
                           for i in range(points)]
            forward[0], forward[-1] = start, stop
            values = forward + forward[-2::-1]
        else:
            set_value(f'{s}:{source}:MODE', 'SWE')
            set_value(f'{s}:SWE:SPAC', 'LIN' if mode == 'linear' else 'LOG')
            set_value(f'{s}:SWE:STA', 'SING')
            set_value(f'{s}:SWE:DIR', 'UP' if start < stop else 'DOWN')
            set_value(f'{s}:SWE:RANG', 'BEST')
            set_value(f'{s}:{source}:STAR', min(start, stop))
            set_value(f'{s}:{source}:STOP', max(start, stop))
            if step is None:
                set_value(f'{s}:{source}:POIN', points)
            else:
                set_value(f'{s}:{source}:STEP', step)
                checks.append((f'{s}:{source}:POIN?', points))
    if mode == 'list':
        raw = config.get('values')
        if not isinstance(raw, list):
            raise ValueError(f'{label}.values 必须为数字列表')
        count(len(raw), f'{label}.values 的点数')
        values = [number(v, f'{label}.values', -maximum, maximum) for v in raw]
    if values is not None:
        points = len(values)
        set_value(f'{s}:{source}:MODE', 'LIST')
        for offset in range(0, points, 100):
            append = ':APP' if offset else ''
            chunk = ','.join(format(v, '.12g') for v in values[offset:offset + 100])
            writes.append(f'{s}:LIST:{source}{append} {chunk}')
        set_value(f'{s}:LIST:{source}:STAR', 1)
        checks.append((f'{s}:LIST:{source}:POIN?', points))
    if mode == 'fixed':
        set_value(f'{s}:{source}:MODE', 'FIX')
        # A source trigger switches a fixed channel to its separate triggered level.
        set_value(f'{s}:{source}:TRIG', initial)

    trigger = table(config.get('trigger', {}), f'{label}.trigger',
                    'repeat source acquire source_count acquire_count period_s source_delay_s acquire_delay_s')
    repeat = count(trigger.get('repeat', 1), f'{label}.trigger.repeat')
    timing = []
    for action, name in [('TRAN', 'source'), ('ACQ', 'acquire')]:
        arm = f':ARM{ch}:{action}'
        trig = f':TRIG{ch}:{action}'
        input_source = trigger.get(name, 'AINT')
        if not isinstance(input_source, str) or input_source not in TRIGGERS:
            raise ValueError(f'{label}.trigger.{name} 无效，请使用 {", ".join(sorted(TRIGGERS))}')
        total = count(trigger.get(f'{name}_count', points), f'{label}.trigger.{name}_count')
        count(repeat * total, f'{label} {name} 总触发次数')
        delay = number(trigger.get(f'{name}_delay_s', 0), f'{label}.trigger.{name}_delay_s', 0, 100000)
        set_value(f'{arm}:SOUR', 'AINT')
        set_value(f'{arm}:DEL', 0)
        set_value(f'{arm}:BYP', 'OFF', verify=False)
        set_value(f'{arm}:COUN', 1, verify=False)
        set_value(f'{trig}:BYP', 'OFF', verify=False)
        set_value(f'{trig}:SOUR', input_source)
        set_value(f'{trig}:COUN', total)
        if repeat != 1:
            set_value(f'{arm}:COUN', repeat)
        else:
            checks.append((f'{arm}:COUN?', 1))
        set_value(f'{trig}:DEL', delay)
        period = None
        if input_source == 'TIM':
            period = number(trigger.get('period_s'), f'{label}.trigger.period_s', 1e-5, 100000)
            set_value(f'{trig}:TIM', period)
        timing.append((input_source, total, period, delay, repeat))
    return writes, checks, timing, points, mode


def load_plan(path):
    return build_plan(tomllib.loads(path.read_text(encoding='utf-8-sig')))


def build_plan(config, *, preset=False):
    """Validate stored channel parameters without enforcing apply selections for a preset."""
    table(config, '扫描配置', 'address group_channels ch1 ch2')
    address = config.get('address', '')
    if not isinstance(address, str):
        raise ValueError('address 必须是字符串')
    grouped = flag(config.get('group_channels', False), 'group_channels')
    channels = {}
    for ch in (1, 2):
        entry = table(config.get(f'ch{ch}', {}), f'ch{ch}', CHANNEL_KEYS)
        enabled = flag(entry.get('enabled', False), f'ch{ch}.enabled')
        if enabled or (preset and entry.keys() - {'enabled'}):
            channels[ch] = channel_plan(ch, entry)
    if not preset:
        if not channels:
            raise ValueError('请启用至少一个通道')
        if grouped:
            require_matching_triggers(channels)
    return address.strip(), grouped, channels


def require_matching_triggers(channels):
    missing = [f'CH{ch}' for ch in (1, 2) if ch not in channels]
    if missing:
        raise ValueError('同步分组需要两路都启用。请勾选 ' + '、'.join(missing) + ' 的「下发参数」。')

    ch1, ch2 = channels[1][2], channels[2][2]
    differences = []
    for action, left, right in zip(('源', '测量'), ch1, ch2):
        for label, a, b in zip(('触发源', '触发次数', '定时周期 (s)', '触发延时 (s)'), left, right):
            if a != b:
                a = '未使用' if a is None else a
                b = '未使用' if b is None else b
                differences.append(f'{action}{label}：CH1 = {a}，CH2 = {b}')
    if ch1[0][4] != ch2[0][4]:
        differences.append(f'重复次数：CH1 = {ch1[0][4]}，CH2 = {ch2[0][4]}')
    if differences:
        raise ValueError('同步分组要求两路对应的触发设置一致。\n\n'
                         + '\n'.join(differences)
                         + '\n\n固定偏置通道如需逐点采集，请填写与扫描通道相同的触发次数。')


def require_no_error(instrument, context):
    reply = instrument.query(':SYST:ERR?').strip()
    if int(reply.split(',', 1)[0]) != 0:
        raise RuntimeError(f'{context} → {reply}')


def require_idle(instrument):
    for ch in (1, 2):
        if instrument.query(f':OUTP{ch}?').strip() not in ('0', 'OFF'):
            raise RuntimeError(f'CH{ch} 输出未关闭。请结束测量并在面板上关闭两路输出后重试。')
    reply = instrument.query(':STAT:OPER:COND?').strip().upper()
    radix = {'#B': 2, '#Q': 8, '#H': 16}.get(reply[:2])
    status = int(reply[2:], radix) if radix else int(reply)
    if (status & IDLE_ACTIONS) != IDLE_ACTIONS or status & BUSY_OPERATIONS:
        raise RuntimeError('仪器触发系统未空闲，或有程序/自检正在运行。请结束操作后重试。')


def configure(instrument, grouped, channels):
    require_idle(instrument)
    require_no_error(instrument, '仪器原有错误')

    def send(command):
        instrument.write(command)
        require_no_error(instrument, command)

    def set_group(expected):
        send(f':SYST:GRO:DEF {expected}')
        reply = instrument.query(':SYST:GRO:DEF?').replace(' ', '').strip()
        if reply != expected:
            raise RuntimeError(f'通道分组读回不一致：预期 {expected}，实际 {reply}')

    set_group('(@1),(@2)')
    for ch, (writes, _, _, _, _) in channels.items():
        print(f'正在设置 CH{ch}……', flush=True)
        for command in writes:
            send(command)
    if grouped:
        set_group('(@1,2)')
    print('通道分组：' + ('CH1 与 CH2' if grouped else '两路独立'))
    for _, checks, _, _, _ in channels.values():
        for query, expected in checks:
            reply = instrument.query(query).strip().strip('"').upper()
            if type(expected) in (int, float):
                value = {'OFF': '0', 'ON': '1'}.get(reply, reply)
                try:
                    matched = math.isclose(float(value), expected, rel_tol=1e-6, abs_tol=1e-15)
                except ValueError:
                    matched = False
            else:
                matched = reply.startswith(expected)
            if not matched:
                raise RuntimeError(f'{query} 预期 {expected}，仪器返回 {reply}。请核对设置后再扫描。')
    require_no_error(instrument, '读回核对')
    require_idle(instrument)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', nargs='?', type=Path, default=ROOT / 'b2962b_scan.toml')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--preview', action='store_true', help='打印命令，不接触仪器')
    mode.add_argument('--check', action='store_true', help='只查询仪器身份和通道输出状态')
    args = parser.parse_args()
    address, grouped, channels = load_plan(args.config)
    if args.preview:
        print(':SYST:GRO:DEF (@1),(@2)')
    for ch, (writes, _, timing, points, scan_mode) in channels.items():
        print(f'CH{ch} {scan_mode}，每轮源序列 {points} 点；源触发 {timing[0][1]} 次，测量触发 {timing[1][1]} 次')
        if args.preview:
            print('\n'.join(writes))
    if args.preview:
        if grouped:
            print(':SYST:GRO:DEF (@1,2)')
        return
    sys.path.insert(0, str(ROOT / '.packages'))
    import pyvisa

    with closing(pyvisa.ResourceManager()) as manager:
        if not address:
            candidates = [r for r in manager.list_resources('USB?*INSTR')
                          if re.match(r'USB\d*::0x2A8D::0x9701::', r, re.I)]
            if len(candidates) != 1:
                raise RuntimeError('没有找到唯一的 B2962B。请在 TOML 填写 Connection Expert 的完整 VISA 地址。')
            address = candidates[0]
        try:
            instrument = manager.open_resource(address)
        except pyvisa.errors.VisaIOError as error:
            raise RuntimeError(
                f'无法打开 VISA 地址 {address}。请先在 Connection Expert 确认 *IDN? 能返回，'
                f'再关闭 Interactive IO 后重试。\n{error}'
            ) from error
        with closing(instrument):
            instrument.timeout = 10000
            instrument.write_termination = '\n'
            instrument.read_termination = '\n'
            identity = instrument.query('*IDN?').strip()
            if len(identity.split(',')) < 2 or identity.split(',')[1].strip().upper() != 'B2962B':
                raise RuntimeError(f'地址对应的仪器不是 B2962B：{identity}')
            print(identity)
            if args.check:
                for ch in (1, 2):
                    print(f'CH{ch} OUTP = {instrument.query(f":OUTP{ch}?").strip()}')
                return
            configure(instrument, grouped, channels)
    print('设置已核对。按 Cancel / Local 回到面板，核对参数后开启要使用的通道并触发。')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'未完成：{error}', file=sys.stderr)
        print('若已开始下发命令，部分设置可能已经改变。请在启动前核对仪器。', file=sys.stderr)
        sys.exit(1)
