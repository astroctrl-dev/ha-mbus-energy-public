"""Guarded serial adapter; callable only from an explicitly approved dev job."""
from bus_timing import shared_timing_active, write_frame
from monthly_diagnostic import read_response
from raw_telegram_log import operation

@operation("archive_frame4")
def read_archive(snapshot, port, baud, address, meter_id, month_back, *, approved=False):
    if approved is not True or not shared_timing_active():
        raise ValueError("archive requires approval and shared bus timing")
    if baud not in (300,2400):
        raise ValueError("unsupported baud")
    import serial
    from archive_acquisition import collect_one
    with serial.Serial(port, baudrate=baud, bytesize=8, parity="E", stopbits=1,
                       timeout=5, write_timeout=5, exclusive=True) as ser:
        def exchange(tx):
            ser.reset_input_buffer()
            if write_frame(ser,tx) != len(tx):
                raise IOError("partial serial write")
            ser.flush()
            return read_response(ser)
        return collect_one(snapshot,address,meter_id,month_back,exchange,approved=True)
