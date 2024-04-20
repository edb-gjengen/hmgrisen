from datetime import datetime
from typing import Optional

from pydantic import BaseModel
from pydantic import Field


class GroupDiscordRole(BaseModel):
    id: int
    discord_id: int
    description: str


class GroupProfile(BaseModel):
    id: int
    posix_name: str
    description: str
    group_type: str = Field(alias="type")
    discord_roles: list[GroupDiscordRole]


class Group(BaseModel):
    id: int
    name: str
    profile: GroupProfile


class Membership(BaseModel):
    id: int
    start_date: datetime
    end_date: datetime
    order: int
    user: int
    membership_type: str
    is_valid: bool


class UserDiscordProfile(BaseModel):
    id: int
    discord_id: int
    user: int


class DuskenUser(BaseModel):
    id: int
    username: str
    email: str
    first_name: str
    last_name: str
    phone_number: str
    date_of_birth: Optional[datetime]
    legacy_id: Optional[int]
    place_of_study: Optional[int]
    active_member_card: Optional[int]
    is_volunteer: bool
    is_member: bool
    last_membership: Optional[Membership]
    groups: list[Group]
    discord_profile: Optional[UserDiscordProfile]


class BasicResponse(BaseModel):
    count: int
    next: Optional[str]
    previous: Optional[str]
    results: list


class Users(BasicResponse):
    results: list[DuskenUser]


class DiscordProfiles(BasicResponse):
    results: list[UserDiscordProfile]


class Groups(BasicResponse):
    results: list[Group]
