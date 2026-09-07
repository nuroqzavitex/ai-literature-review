import os
from sqlalchemy import create_engine, inspect

db_url = "postgresql+psycopg://postgres.zshkghkairojnuabrsgg:khongthichdungai@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres"

engine = create_engine(db_url)
inspector = inspect(engine)
columns = inspector.get_columns("v2_projects")
print("v2_projects columns:")
for col in columns:
    print(col["name"])
