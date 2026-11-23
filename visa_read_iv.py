"""Export completed B2962B measurements to a combined CSV."""

import ctypes as c
import csv
from datetime import datetime
from decimal import Decimal
from itertools import zip_longest
from pathlib import Path
import sys


CHANNELS = (1, 2)
# Field order within each channel's block, with units kept in a separate CSV row.
FIELDS = (('TIME', 'Time', 's'), ('VOLT', 'Voltage', 'V'),
          ('SOUR', 'Source', None), ('CURR', 'Current', 'mA'))
ROOT = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent
INVALID_READING = Decimal('9e37')


def export_iv(query, folder=ROOT, channels=CHANNELS, before_save=None):
    """Use an existing VISA query function and return the saved path, if any."""
    if not channels or any(channel not in CHANNELS for channel in channels):
        raise ValueError('Select CH1, CH2, or both channels.')
    fmt = query(':FORM?').strip().upper()
    if not fmt.startswith('ASC'):
        raise RuntimeError('仪器数据格式不是 ASCII。请先在仪器 I/O 设置中选择 ASCII。')

    columns, units, data = [], [], []
    for channel in CHANNELS:
        mode = query(f':SOUR{channel}:FUNC:MODE?').strip().upper()
        source_unit = {'CURR': 'mA', 'VOLT': 'V'}.get(mode, '')
        columns.extend(f'CH{channel}_{name}' for _, name, _ in FIELDS)
        channel_units = [source_unit if unit is None else unit for _, _, unit in FIELDS]
        units.extend(channel_units)
        if channel not in channels:
            data.extend([] for _ in FIELDS)
            continue
        arrays = []
        for (field, _, _), unit in zip(FIELDS, channel_units):
            raw = query(f':FETC:ARR:{field}? (@{channel})').strip()
            converted = []
            for token in raw.split(','):
                if not token.strip():
                    continue
                value = Decimal(token)
                if not value.is_finite() or value.copy_abs() >= INVALID_READING:
                    converted.append(None)
                elif unit == 'mA':
                    # Shift the decimal point without stripping the instrument's trailing zeros.
                    converted.append(str(value.scaleb(3)))
                else:
                    converted.append(float(value))
            arrays.append(converted)
        valid_lengths = [len(values) for values in arrays if any(value is not None for value in values)]
        if len(set(valid_lengths)) > 1:
            print(f'CH{channel}: field lengths differ {valid_lengths}; verify row alignment.', flush=True)
        data.extend(arrays)
    if before_save is not None:
        before_save()
    if not any(value is not None for values in data for value in values):
        return None

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    path = Path(folder) / f'IV_CH1_CH2_{stamp}.csv'
    with path.open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.writer(file)
        writer.writerow(columns)
        writer.writerow(units)
        writer.writerows(zip_longest(*data, fillvalue=None))
    return path


def check(status):
    if status < 0:
        raise RuntimeError(f'VISA error: 0x{status & 0xffffffff:08X}')


def usb_addresses(visa, manager):
    find, count = c.c_uint32(), c.c_uint32()
    buffer = c.create_string_buffer(1024)
    check(visa.viFindRsrc(manager, b'USB?*INSTR', c.byref(find), c.byref(count), buffer))
    try:
        addresses = [buffer.value]
        for _ in range(count.value - 1):
            check(visa.viFindNext(find, buffer))
            addresses.append(buffer.value)
        return addresses
    finally:
        visa.viClose(find)


def visa_query(visa, instrument, command):
    request = (command + '\n').encode('ascii')
    transferred = c.c_uint32()
    check(visa.viWrite(instrument, request, len(request), c.byref(transferred)))
    buffer = c.create_string_buffer(65536)
    chunks = []
    while True:
        status = visa.viRead(instrument, buffer, len(buffer), c.byref(transferred))
        check(status)
        chunks.append(buffer.raw[:transferred.value])
        if status != 0x3fff0006:
            return b''.join(chunks).decode('ascii').strip()


def main():
    visa = c.WinDLL('visa64.dll')
    manager = c.c_uint32()
    check(visa.viOpenDefaultRM(c.byref(manager)))
    try:
        addresses = usb_addresses(visa, manager)
        print('Resources:', [address.decode() for address in addresses], flush=True)
        for address in addresses:
            instrument = c.c_uint32()
            check(visa.viOpen(manager, address, 0, 0, c.byref(instrument)))
            try:
                def query(command):
                    return visa_query(visa, instrument, command)

                identity = query('*IDN?')
                print('Identity:', identity, flush=True)
                if 'B2962B' not in identity.upper():
                    continue
                path = export_iv(query)
                print(f'Saved to {path}' if path else 'No valid data in either channel; no file saved', flush=True)
            finally:
                visa.viClose(instrument)
    finally:
        visa.viClose(manager)


if __name__ == '__main__':
    main()
