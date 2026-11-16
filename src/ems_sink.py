"""Legacy SQL adapter deliberately disabled in the Modbus baseline."""
class EMSSink:
    def __init__(self):
        raise RuntimeError("Direct EMS ingestion is disabled. Use the read-only Modbus bridge.")
