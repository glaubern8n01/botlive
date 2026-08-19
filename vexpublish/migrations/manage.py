"""Migracao do banco isolado do VexPublish.

  python vexpublish/migrations/manage.py upgrade
  python vexpublish/migrations/manage.py downgrade --confirm

O downgrade exige --confirm de proposito. Nunca aponte VEXPUBLISH_DATABASE_PATH
para o banco de campanhas nem para o banco do BotLive.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vexpublish.core import store  # noqa: E402


def upgrade() -> int:
    store.migrar()
    with store.conectar() as db:
        versao = db.execute("PRAGMA user_version").fetchone()[0]
        tabelas = [
            linha[0]
            for linha in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'vexpublish_%'"
            )
        ]
    print(f"banco={store.DB_PATH}")
    print(f"schema_version={versao}")
    print(f"tabelas={len(tabelas)}: {sorted(tabelas)}")
    return 0


def downgrade(confirmado: bool) -> int:
    if not confirmado:
        print("Recusado: use --confirm para remover as tabelas do VexPublish.")
        return 1
    with store.conectar() as db:
        db.execute("PRAGMA foreign_keys=OFF")
        for tabela in sorted(store.TABELAS):
            db.execute(f"DROP TABLE IF EXISTS {tabela}")
        db.execute("PRAGMA user_version=0")
    print(f"tabelas removidas de {store.DB_PATH}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Migracao do VexPublish")
    parser.add_argument("acao", choices=["upgrade", "downgrade"])
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    return upgrade() if args.acao == "upgrade" else downgrade(args.confirm)


if __name__ == "__main__":
    raise SystemExit(main())
