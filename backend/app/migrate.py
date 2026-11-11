"""轻量迁移：为已存在的表补齐新增字段（SQLite 友好）"""
from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateColumn
from app.database import engine, Base
import app.models  # noqa: F401  确保模型已注册


def ensure_columns():
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    changed = []
    with engine.begin() as conn:
        for tname, table in Base.metadata.tables.items():
            if tname not in existing_tables:
                continue
            cols = {c["name"] for c in insp.get_columns(tname)}
            for col in table.columns:
                if col.name in cols:
                    continue
                try:
                    ddl = CreateColumn(col).compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{tname}" ADD COLUMN {ddl}'))
                    changed.append(f"{tname}.{col.name}")
                except Exception as e:  # noqa
                    print(f"[migrate] skip {tname}.{col.name}: {e}")
    if changed:
        print(f"[migrate] 新增字段 {len(changed)} 个: {', '.join(changed[:12])}"
              + (" ..." if len(changed) > 12 else ""))
    return changed


if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    ensure_columns()
