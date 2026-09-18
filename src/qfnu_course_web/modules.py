from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModuleSpec:
    key: str
    label: str
    search: str
    operation: str
    entry: str
    filter_restricted: bool = True


MODULES: dict[str, ModuleSpec] = {
    "bxxk": ModuleSpec("bxxk", "必修选课", "xsxkBxxk", "bxxkOper", "comeInBxxk"),
    "xxxk": ModuleSpec("xxxk", "选修选课", "xsxkXxxk", "xxxkOper", "comeInXxxk"),
    "bxqjhxk": ModuleSpec(
        "bxqjhxk", "本学期计划选课", "xsxkBxqjhxk", "bxqjhxkOper", "comeInBxqjhxk"
    ),
    "knjxk": ModuleSpec("knjxk", "专业内跨年级选课", "xsxkKnjxk", "knjxkOper", "comeInKnjxk"),
    "fawxk": ModuleSpec("fawxk", "计划外选课", "xsxkFawxk", "fawxkOper", "comeInFawxk"),
    "ggxxkxk": ModuleSpec("ggxxkxk", "公选课选课", "xsxkGgxxkxk", "ggxxkxkOper", "comeInGgxxkxk"),
}
