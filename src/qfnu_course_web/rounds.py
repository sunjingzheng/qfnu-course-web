from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup


class RoundSelectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RoundOption:
    id: str
    name: str

    def as_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name}


def _id_from_tag(tag: object) -> str | None:
    get = getattr(tag, "get", None)
    if get is None:
        return None
    href = str(get("href") or "")
    values = parse_qs(urlparse(href).query).get("jx0502zbid")
    if values and values[0]:
        return values[0]
    onclick = str(get("onclick") or "")
    match = re.search(r"(?:jrxk|xsxkOpen)\(\s*['\"]?([^'\")\s]+)", onclick)
    return match.group(1) if match else None


def parse_rounds(html: str) -> list[RoundOption]:
    soup = BeautifulSoup(html, "html.parser")
    result: list[RoundOption] = []
    seen: set[str] = set()
    for tag in soup.find_all(True):
        round_id = _id_from_tag(tag)
        if not round_id or round_id in seen:
            continue
        name = tag.get_text(" ", strip=True) or round_id
        if name in {"进入", "进入选课", "选课"}:
            row = tag.find_parent("tr")
            row_text = row.get_text(" ", strip=True) if row else ""
            if row_text and row_text != name:
                name = row_text.removesuffix(name).strip() or round_id
            else:
                name = round_id
        result.append(RoundOption(id=round_id, name=name))
        seen.add(round_id)
    patterns = (
        r"jx0502zbid=([^&'\" >]+)",
        r"(?:jrxk|xsxkOpen)\(\s*['\"]([^'\"]+)",
    )
    for pattern in patterns:
        for round_id in re.findall(pattern, html):
            if round_id and round_id not in seen:
                result.append(RoundOption(id=round_id, name=round_id))
                seen.add(round_id)
    return result


def select_round(rounds: list[RoundOption], keywords: list[str]) -> RoundOption:
    if not rounds:
        raise RoundSelectionError("没有可用选课轮次")
    cleaned = [keyword.strip() for keyword in keywords if keyword.strip()]
    if not cleaned:
        return rounds[0]
    for keyword in cleaned:
        needle = keyword.casefold()
        matches = [
            item
            for item in rounds
            if needle in item.name.casefold() or needle in item.id.casefold()
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            names = "、".join(item.name for item in matches)
            raise RoundSelectionError(f"轮次关键字“{keyword}”匹配到多个轮次：{names}")
    raise RoundSelectionError("没有匹配轮次关键字的可用轮次")
