from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1000)


class ConfigStatus(BaseModel):
    has_tmdb_key: bool
    has_qas: bool
    has_pansou: bool
    has_proxy: bool = False
    cloud_root: str
    local_root: str
    version: str = "0.5.0"
