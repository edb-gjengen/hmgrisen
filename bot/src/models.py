from typing import Optional

from pydantic import BaseModel
from pydantic import Field


class GroupDiscordRole(BaseModel):
    """A Discord role connected to a Galtinn group"""

    id: int
    discord_id: int
    description: str


class GroupProfile(BaseModel):
    """Extra information about a Galtinn group, including its Discord roles"""

    id: int
    posix_name: str
    description: str
    group_type: str = Field(alias="type")
    discord_roles: list[GroupDiscordRole]


class Group(BaseModel):
    """A Galtinn group"""

    id: int
    name: str
    profile: Optional[GroupProfile]


class UserDiscordProfile(BaseModel):
    """The link between a Galtinn user and a Discord user"""

    id: int
    discord_id: int
    user: int


class DuskenUser(BaseModel):
    """A Galtinn user"""

    id: int
    username: str
    is_volunteer: bool
    is_member: bool
    groups: list[Group]
    discord_profile: Optional[UserDiscordProfile]


class BasicResponse(BaseModel):
    """A page of results from a paginated Galtinn endpoint"""

    count: int
    next: Optional[str]
    previous: Optional[str]
    results: list


class Users(BasicResponse):
    """A page of Galtinn users"""

    results: list[DuskenUser]


class DiscordProfiles(BasicResponse):
    """A page of Discord profiles"""

    results: list[UserDiscordProfile]


class Groups(BasicResponse):
    """A page of Galtinn groups"""

    results: list[Group]
