import enum
from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Enum as SQLEnum,
    func
)
from sqlalchemy.orm import relationship
from app.database import Base


class CartridgeStatus(str, enum.Enum):
    IN_USE = "in_use"                   # В работе (в кабинете у сотрудника)
    PENDING_VENDOR = "pending_vendor"   # Ожидает заправщика (принят в IT-отделе)
    AT_VENDOR = "at_vendor"             # На заправке (передан поставщику по акту)
    READY_FOR_PICKUP = "ready_for_pickup" # Готов к выдаче (вернулся с заправки)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String(100), primary_key=True, index=True)
    value = Column(Text, nullable=True)
    description = Column(String(255), nullable=True)


class ADUser(Base):
    __tablename__ = "ad_users"

    samaccountname = Column(String(100), primary_key=True, index=True)
    display_name = Column(String(255), nullable=False, index=True)
    department = Column(String(255), nullable=True)
    cabinet = Column(String(100), nullable=True)
    phone = Column(String(100), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    cartridges = relationship("Cartridge", back_populates="current_user")


class Cartridge(Base):
    __tablename__ = "cartridges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    marker_label = Column(String(100), unique=True, index=True, nullable=False)
    qr_code = Column(String(100), unique=True, index=True, nullable=True)
    model = Column(String(100), nullable=False)
    cabinet = Column(String(100), nullable=False)
    status = Column(
        SQLEnum(CartridgeStatus),
        default=CartridgeStatus.IN_USE,
        nullable=False,
        index=True
    )
    current_user_id = Column(
        String(100),
        ForeignKey("ad_users.samaccountname", ondelete="SET NULL"),
        nullable=True
    )
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    current_user = relationship("ADUser", back_populates="cartridges")
    history = relationship("HistoryLog", back_populates="cartridge", cascade="all, delete-orphan", order_by="desc(HistoryLog.timestamp)")
    batch_items = relationship("BatchItem", back_populates="cartridge")


class Batch(Base):
    """Акт передачи картриджей поставщику услуг заправки."""
    __tablename__ = "batches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    act_number = Column(String(100), unique=True, index=True, nullable=False)
    vendor_name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(50), default="open")  # open / closed
    notes = Column(Text, nullable=True)

    items = relationship("BatchItem", back_populates="batch", cascade="all, delete-orphan")


class BatchItem(Base):
    __tablename__ = "batch_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(Integer, ForeignKey("batches.id", ondelete="CASCADE"), nullable=False)
    cartridge_id = Column(Integer, ForeignKey("cartridges.id", ondelete="CASCADE"), nullable=False)
    action_required = Column(String(100), default="Заправка")  # Заправка, Восстановление, Замена барабана

    batch = relationship("Batch", back_populates="items")
    cartridge = relationship("Cartridge", back_populates="batch_items")


class HistoryLog(Base):
    __tablename__ = "history_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cartridge_id = Column(Integer, ForeignKey("cartridges.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(100), nullable=False)  # Приемка, Передача поставщику, Возврат, Выдача, Создание
    user_name = Column(String(255), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    details = Column(Text, nullable=True)

    cartridge = relationship("Cartridge", back_populates="history")
