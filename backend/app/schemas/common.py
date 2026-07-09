from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class ConfigStatus(BaseModel):
    has_tmdb_key: bool
    has_qas: bool
    has_pansou: bool
    cloud_root: str
    local_root: str
    version: str = "2.0.0-dev"

