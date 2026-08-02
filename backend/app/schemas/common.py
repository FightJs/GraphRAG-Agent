from pydantic import BaseModel
from typing import Any
import uuid

def new_trace() -> str:
    return str(uuid.uuid4())[:8]

class Resp(BaseModel):
    code: int = 0
    msg: str = "ok"
    data: Any = None
    trace_id: str = ""

    @classmethod
    def ok(cls, data: Any = None, msg: str = "ok") -> "Resp":
        return cls(code=0, msg=msg, data=data, trace_id=new_trace())

    @classmethod
    def err(cls, code: int, msg: str) -> "Resp":
        return cls(code=code, msg=msg, trace_id=new_trace())
