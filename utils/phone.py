"""Номера телефонов для входа в приложение: проверка и приведение к виду +31612345678 (E.164).

Принимаем только мобильные номера стран, где живёт сообщество (код по SMS на стационарный не дойдёт):
Нидерланды +31, Германия +49, Бельгия +32 и Украина +380.
"""
from __future__ import annotations

import re

# код страны → (допустимая длина национального номера без 0, шаблон начала мобильного номера)
MOBILE = {
    "31": ((9,), re.compile(r"^6[1-9]")),            # 06-xx xx xx xx
    "49": ((10, 11), re.compile(r"^1[5-7]")),         # 015x, 016x, 017x
    "32": ((9,), re.compile(r"^4[5-9]")),             # 04xx xx xx xx
    "380": ((9,), re.compile(r"^(39|50|6[3678]|7[3-9]|9[1-9])")),
}


def normalize(raw: str, cc: str = "") -> str | None:
    """+<код><номер> или None. cc — код страны из выбора флага; номер может быть и полным (+31…, 0031…)."""
    s = str(raw or "").strip()
    digits = re.sub(r"\D", "", s)
    if s.startswith("+") or digits.startswith("00"):
        digits = digits[2:] if digits.startswith("00") else digits
        cc = next((c for c in sorted(MOBILE, key=len, reverse=True) if digits.startswith(c)), "")
        national = digits[len(cc):] if cc else ""
    else:
        cc = re.sub(r"\D", "", cc or "")
        national = digits
    if cc not in MOBILE:
        return None
    national = national.lstrip("0")
    lengths, start = MOBILE[cc]
    if len(national) not in lengths or not start.match(national):
        return None
    return f"+{cc}{national}"

