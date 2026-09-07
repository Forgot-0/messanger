from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base_model import BaseModel, DateMixin

if TYPE_CHECKING:
    from app.profiles.models.profile import Profile


class Contact(BaseModel, DateMixin):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(30))
    contact: Mapped[str] = mapped_column(String(256))

    profile_id: Mapped[int] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    profile: Mapped[Profile] = relationship("Profile", back_populates="contacts")

    __table_args__ = (
        UniqueConstraint("profile_id", "provider", name="unique_profile_provider"),
    )
