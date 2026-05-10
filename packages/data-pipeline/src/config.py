import os


class Config:
    # TimescaleDB
    postgres_host: str = os.environ.get("POSTGRES_HOST", "localhost")
    postgres_port: int = int(os.environ.get("POSTGRES_PORT", "5432"))
    postgres_db: str = os.environ.get("POSTGRES_DB", "energy_trading")
    postgres_user: str = os.environ.get("POSTGRES_USER", "postgres")
    postgres_password: str = os.environ.get("POSTGRES_PASSWORD", "changeme")

    @classmethod
    def postgres_dsn(cls) -> str:
        return (
            f"postgresql+asyncpg://{cls.postgres_user}:{cls.postgres_password}"
            f"@{cls.postgres_host}:{cls.postgres_port}/{cls.postgres_db}"
        )

    # Kafka
    kafka_bootstrap_servers: str = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

    # ERCOT
    ercot_base_url: str = "https://api.ercot.com/api/public-reports"
    ercot_subscription_key: str = os.environ.get("ERCOT_API_KEY", "")
    ercot_username: str = os.environ.get("ERCOT_USERNAME", "")
    ercot_password: str = os.environ.get("ERCOT_PASSWORD", "")
    ercot_client_id: str = "fec253ea-0d06-4272-a5e6-b478baeecd70"
    ercot_auth_endpoint: str = (
        "https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com"
        "/B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token"
    )

    # PJM
    pjm_base_url: str = "https://api.pjm.com/api/v1"
    pjm_subscription_key: str = os.environ.get("PJM_API_KEY", "")
    pjm_page_size: int = 50_000


config = Config()
