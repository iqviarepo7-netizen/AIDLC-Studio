from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    git_remote: str = "origin"
    git_base_branch: str = "main"
    github_token: str | None = None
    gitlab_token: str | None = None
    gitlab_base_url: str = "https://gitlab.com"


settings = Settings()
