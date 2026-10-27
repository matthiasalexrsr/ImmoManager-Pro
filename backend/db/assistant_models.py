"""Personal assistant records; every service query predicates on the owner."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .orm_models import Base


class AssistantRow:
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    payload_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AssistantConversationORM(AssistantRow, Base):
    __tablename__ = "assistant_conversations"
    __table_args__ = (Index("ix_assistant_conversation_owner", "owner_id", "created_at", "id"),)


class ConversationChild:
    conversation_id: Mapped[str] = mapped_column(ForeignKey("assistant_conversations.id", ondelete="CASCADE"), nullable=False)


class AssistantMessageORM(AssistantRow, ConversationChild, Base):
    __tablename__ = "assistant_messages"
    __table_args__ = (Index("ix_assistant_message_page", "owner_id", "conversation_id", "created_at", "id"),)


class AssistantRunORM(AssistantRow, ConversationChild, Base):
    __tablename__ = "assistant_runs"
    __table_args__ = (Index("ix_assistant_run_work", "state", "updated_at", "id"),
                      Index("ix_assistant_run_page", "owner_id", "conversation_id", "created_at", "id"))


class AssistantAttachmentORM(AssistantRow, ConversationChild, Base):
    __tablename__ = "assistant_attachments"
    __table_args__ = (Index("ix_assistant_attachment_owner", "owner_id", "conversation_id", "created_at", "id"),)


class AssistantProposalORM(AssistantRow, ConversationChild, Base):
    __tablename__ = "assistant_proposals"
    __table_args__ = (Index("ix_assistant_proposal_owner", "owner_id", "conversation_id", "created_at", "id"),)


MODELS = (AssistantConversationORM, AssistantMessageORM, AssistantRunORM, AssistantAttachmentORM, AssistantProposalORM)
