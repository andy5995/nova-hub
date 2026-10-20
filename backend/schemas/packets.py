"""Packet schemas for Nova Hub APIs"""

from datetime import datetime, timezone
from typing import Annotated, List, Optional
from pydantic import BaseModel, ConfigDict, PlainSerializer

# The database holds naive UTC. Said so on the wire, as RFC 3339 ("...Z"), which
# is what the spec's date-time format promises.
UtcDateTime = Annotated[datetime, PlainSerializer(
    lambda d: d.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
    return_type=str, when_used="json")]

# The packets' and nodelists' bodies are raw bytes, read from and written to the
# request directly, so FastAPI cannot see them to document them.
BINARY = {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}


class PacketInfo(BaseModel):
    """Basic packet information"""
    filename: str
    league: str
    game_type: str
    source: str
    dest: str
    sequence: int
    received_at: UtcDateTime
    retrieved_at: Optional[UtcDateTime] = None
    file_size: int


class PacketListResponse(BaseModel):
    """List of packets"""
    packets: List[PacketInfo]


class PacketUploadResponse(BaseModel):
    """Response from packet upload"""
    status: str
    filename: str
    packet_id: int


class PacketDetail(BaseModel):
    """Detailed packet information (for management)"""
    id: int
    filename: str
    league_id: int
    league_name: str
    game_type: str
    source_bbs_index: str
    dest_bbs_index: str
    sequence_number: int
    file_size: int
    checksum: Optional[str] = None
    uploaded_at: datetime
    downloaded_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    is_processed: bool
    is_downloaded: bool
    has_error: bool
    error_message: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
