"""Load service configuration from the environment."""
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """Configure storage, seeding, browser origins and cookies."""
    database_path: str = 'data/procurem.db'
    seed_on_startup: bool = True
    cors_origins: str = 'http://localhost:3000'
    cookie_secure: bool = False
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    @property
    def origins(self) -> list[str]:
        """Return explicitly allowed origins."""
        return [x.strip() for x in self.cors_origins.split(',') if x.strip() and x.strip() != '*']
