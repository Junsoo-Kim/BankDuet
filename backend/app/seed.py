from sqlalchemy import text
from app.db import bank_id, engine


def seed():
    customer_name = {"kb": "민지", "b": "준호"}[bank_id]
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO demo_customer (id, display_name) VALUES (:id, :display_name)
            ON CONFLICT (id) DO NOTHING
        """), {"id": bank_id + "-demo", "display_name": customer_name})


if __name__ == "__main__":
    seed()
