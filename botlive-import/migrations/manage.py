"""Migracao do banco isolado de Importar/Adaptar/Publicar.

  python botlive-import/migrations/manage.py upgrade
  python botlive-import/migrations/manage.py downgrade --confirm
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local-agent"))

from importer import store  # noqa: E402


def upgrade() -> int:
    store.migrar()
    with store.conectar() as db:
        versao = db.execute("PRAGMA user_version").fetchone()[0]
        tabelas = [x[0] for x in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'import_%'")]
    print(f"banco={store.DB_PATH}")
    print(f"schema_version={versao}")
    print(f"tabelas={len(tabelas)}: {sorted(tabelas)}")
    return 0


def downgrade(confirmado: bool) -> int:
    if not confirmado:
        print("Recusado: use --confirm para remover as tabelas do modulo.")
        return 1
    with store.conectar() as db:
        db.execute("PRAGMA foreign_keys=OFF")
        for tabela in sorted(store.TABELAS):
            db.execute(f"DROP TABLE IF EXISTS {tabela}")
        db.execute("PRAGMA user_version=0")
    print(f"tabelas removidas de {store.DB_PATH}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Migracao do modulo de importacao")
    parser.add_argument("acao", choices=["upgrade", "downgrade"])
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    return upgrade() if args.acao == "upgrade" else downgrade(args.confirm)


if __name__ == "__main__":
    raise SystemExit(main())
