"""AstrBot event API stub。"""


class _Filter:
    def command(self, *a, **k):
        def deco(f):
            f._is_command = True
            f._command_name = a[0] if a else None
            return f
        return deco

    def command_group(self, *a, **k):
        def deco(f):
            f._is_group = True
            f.command = self.command
            return f
        return deco

    def permission_type(self, *a, **k):
        def deco(f):
            f._permission = a
            return f
        return deco

    def event_message_type(self, *a, **k):
        def deco(f):
            f._event_message_type = a
            return f
        return deco

    def llm_tool(self, name=None):
        def deco(f):
            f._llm_tool_name = name
            return f
        return deco

    class EventMessageType:
        ALL = "all"
        GROUP_MESSAGE = "group_message"

    class PermissionType:
        ADMIN = "admin"


filter = _Filter()


class AstrMessageEvent:
    pass


class MessageEventResult:
    pass
