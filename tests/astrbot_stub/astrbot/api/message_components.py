"""AstrBot message_components stub:仅覆盖插件用到的组件。"""


class Plain:
    def __init__(self, text=""):
        self.text = text


class Image:
    def __init__(self, file=None, url=None):
        self.file = file
        self.url = url

    @classmethod
    def fromFileSystem(cls, path):
        return cls(file=path)


class At:
    def __init__(self, qq=""):
        self.qq = qq


class Reply:
    def __init__(self, id=None, message_id=None):
        self.id = id
        self.message_id = message_id
