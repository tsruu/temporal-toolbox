# app/schemas.py
from typing import Dict, Any, Optional
from pydantic import BaseModel


class ToolRequest(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]


class ToolResponse(BaseModel):
    status: str                  # "ok" or "error"
    result_text: str
    metadata: Optional[Dict[str, Any]] = None