# RIG SHIM — phone's real rokdabus.py (K-spelling) lives on the device.
# Wraps the deploy rockdabus (C-spelling) so routes/plumbing test identically.
import rockdabus as _rb
def __getattr__(name):
    return getattr(_rb, name)
try:
    from rockdabus import *  # noqa
except Exception:
    pass
