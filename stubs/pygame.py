# Minimal pygame stub for headless environments
# Prevents import errors when pygame isn't available

class _Stub:
    def __getattr__(self, name):
        return _Stub()
    def __call__(self, *args, **kwargs):
        return _Stub()

mixer = _Stub()
display = _Stub()
time = _Stub()
event = _Stub()

def init(*args, **kwargs):
    pass

def quit(*args, **kwargs):
    pass
