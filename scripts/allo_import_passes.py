"""Issue reviewed legacy three-walk credits without a WordPress plugin.

CSV headers: email,remaining_uses. Run once with production DB and encryption
key configured. The output CSV contains secrets and must be delivered privately.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
from pathlib import Path

from sqlalchemy import select

from database.db import engine, get_session
from database.models import AlloWebCode, Base
from utils.allo_v2 import _cipher, _hash_code, _lock, _new_code


async def run(source: Path, output: Path) -> None:
    if output.exists():
        raise SystemExit("Output already exists; choose a new filename")
    cipher = _cipher()
    with source.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or not {"email", "remaining_uses"}.issubset(rows[0]):
        raise SystemExit("CSV must contain email,remaining_uses")
    clean = []
    for row in rows:
        email = (row.get("email") or "").strip().lower()
        try:
            uses = int(row.get("remaining_uses") or "")
        except ValueError as exc:
            raise SystemExit(f"Invalid uses for {email}") from exc
        if not email or "@" not in email or not 1 <= uses <= 3:
            raise SystemExit(f"Invalid email or uses: {email}")
        clean.append((email, uses))
    if len({email for email, _ in clean}) != len(clean):
        raise SystemExit("Duplicate email in CSV; review manually")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    issued = []
    async with get_session() as session:
        await _lock(session)
        for email, uses in clean:
            existing = await session.scalar(select(AlloWebCode).where(
                AlloWebCode.kind == "pass", AlloWebCode.owner_email == email,
                AlloWebCode.active.is_(True)))
            if existing:
                raise SystemExit(f"An active pass already exists for {email}; review manually")
            code = _new_code()
            session.add(AlloWebCode(code_hash=_hash_code(code),
                                    code_encrypted=cipher.encrypt(code.encode()).decode(),
                                    kind="pass", owner_email=email, total_uses=uses))
            issued.append({"email": email, "remaining_uses": uses, "code": code})
        # Write the private delivery file before committing so a failed write
        # cannot create credits whose codes were lost.
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["email", "remaining_uses", "code"])
            writer.writeheader()
            writer.writerows(issued)
        try:
            output.chmod(0o600)
            await session.commit()
        except Exception:
            output.unlink(missing_ok=True)
            raise
    print(f"Issued {len(issued)} codes; deliver {output} privately")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.input, args.output))
