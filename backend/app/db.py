import os

from sqlalchemy import URL, create_engine

bank_id = os.environ["BANK_ID"]
engine = create_engine(
    URL.create(
        "postgresql+psycopg", username=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"], host=os.environ["DB_HOST"],
        database=os.environ["DB_NAME"],
    ),
    pool_pre_ping=True, connect_args={"connect_timeout": 2},
)
