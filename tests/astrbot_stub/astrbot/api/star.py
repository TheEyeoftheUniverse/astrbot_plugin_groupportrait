"""AstrBot star API stub。"""


class Context:
    pass


class Star:
    def __init__(self, context):
        self.context = context


def register(*a, **k):
    def deco(cls):
        cls._registered = a
        return cls
    return deco


class StarTools:
    _dir = None

    @staticmethod
    def get_data_dir(name):
        import os
        import tempfile
        if StarTools._dir is None:
            StarTools._dir = tempfile.mkdtemp(prefix="groupportrait_test_")
        d = os.path.join(StarTools._dir, name)
        os.makedirs(d, exist_ok=True)
        return d
