from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from app.models import CartridgeStatus


# --- Настройки ---
class SettingItem(BaseModel):
    key: str
    value: Optional[str] = None
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SettingsDict(BaseModel):
    settings: Dict[str, Optional[str]]


class LdapTestRequest(BaseModel):
    host: Optional[str] = None
    base_dn: Optional[str] = None
    bind_user: Optional[str] = None
    bind_password: Optional[str] = None


class WhatsAppTestRequest(BaseModel):
    phone: str
    message: Optional[str] = None


# --- Пользователи AD ---
class ADUserBase(BaseModel):
    samaccountname: str
    display_name: str
    department: Optional[str] = None
    cabinet: Optional[str] = None
    phone: Optional[str] = None


class ADUserResponse(ADUserBase):
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# --- История ---
class HistoryLogResponse(BaseModel):
    id: int
    cartridge_id: int
    action: str
    user_name: Optional[str] = None
    timestamp: datetime
    details: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# --- Картриджи ---
class CartridgeBase(BaseModel):
    marker_label: str
    qr_code: Optional[str] = None
    model: str
    cabinet: str
    notes: Optional[str] = None


class CartridgeCreate(CartridgeBase):
    current_user_id: Optional[str] = None
    status: CartridgeStatus = CartridgeStatus.IN_USE


class CartridgeUpdate(BaseModel):
    marker_label: Optional[str] = None
    qr_code: Optional[str] = None
    model: Optional[str] = None
    cabinet: Optional[str] = None
    current_user_id: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[CartridgeStatus] = None


class CartridgeAcceptanceRequest(BaseModel):
    marker_label: str
    qr_code: Optional[str] = None
    model: str
    cabinet: str
    current_user_id: Optional[str] = None
    notes: Optional[str] = None
    action_required: Optional[str] = "Заправка"


class CartridgeResponse(CartridgeBase):
    id: int
    status: CartridgeStatus
    current_user_id: Optional[str] = None
    current_user: Optional[ADUserResponse] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CartridgeDetailResponse(CartridgeResponse):
    history: List[HistoryLogResponse] = []


# --- Акты (Batches) ---
class BatchItemResponse(BaseModel):
    id: int
    cartridge_id: int
    action_required: str
    cartridge: CartridgeResponse

    model_config = ConfigDict(from_attributes=True)


class BatchResponse(BaseModel):
    id: int
    act_number: str
    vendor_name: str
    created_at: datetime
    status: str
    notes: Optional[str] = None
    items: List[BatchItemResponse] = []

    model_config = ConfigDict(from_attributes=True)


class BatchCreateRequest(BaseModel):
    cartridge_ids: List[int]
    vendor_name: Optional[str] = None
    action_required: Optional[str] = "Заправка"
    notes: Optional[str] = None


class ReturnFromVendorRequest(BaseModel):
    cartridge_ids: List[int]
    notes: Optional[str] = None


class NotifyWhatsAppRequest(BaseModel):
    cartridge_ids: Optional[List[int]] = None  # Если None, оповещает все ready_for_pickup
