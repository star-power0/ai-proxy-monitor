"""
CCSwitch 数据读取服务
从 ccswitch SQLite 数据库读取中转站信息
"""
import sqlite3
import json
import os
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class ProxyStation:
    """中转站信息"""
    id: str
    name: str
    base_url: str
    api_key: str
    category: str
    cost_multiplier: Optional[float]
    is_current: bool
    in_failover: bool
    provider_type: Optional[str]
    website_url: Optional[str]
    notes: Optional[str]
    # 动态检测字段
    balance: Optional[float] = None
    is_healthy: bool = True
    health_error: Optional[str] = None
    last_check: Optional[str] = None
    response_time_ms: Optional[int] = None
    available_models: list = field(default_factory=list)
    price_map: dict = field(default_factory=dict)


# 常见 ccswitch 配置路径
CCSWITCH_PATHS = [
    os.path.expanduser("~/.cc-switch/cc-switch.db"),
    os.path.expandvars(r"%APPDATA%\cc-switch\cc-switch.db"),
    os.path.expandvars(r"%LOCALAPPDATA%\cc-switch\cc-switch.db"),
    os.path.expandvars(r"%USERPROFILE%\.cc-switch\cc-switch.db"),
]


def find_ccswitch_db() -> Optional[str]:
    """自动查找 ccswitch 数据库文件"""
    for path in CCSWITCH_PATHS:
        if os.path.isfile(path):
            return path
    return None


def load_stations(db_path: Optional[str] = None) -> list[ProxyStation]:
    """从 ccswitch 数据库读取所有中转站"""
    if db_path is None:
        db_path = find_ccswitch_db()
    if db_path is None:
        raise FileNotFoundError("未找到 ccswitch 数据库文件，请确认 ccswitch 已安装并运行过。")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT p.id, p.name, p.settings_config, p.category,
               p.cost_multiplier, p.is_current, p.in_failover_queue,
               p.provider_type, p.website_url, p.notes,
               COALESCE(h.is_healthy, -1) as is_healthy,
               h.consecutive_failures, h.last_error, h.updated_at as health_updated
        FROM providers p
        LEFT JOIN provider_health h ON p.id = h.provider_id AND p.app_type = h.app_type
        WHERE p.app_type = 'claude'
        ORDER BY p.sort_index
    """)

    stations = []
    for row in cur.fetchall():
        cfg = json.loads(row["settings_config"])
        env = cfg.get("env", {})
        base_url = env.get("ANTHROPIC_BASE_URL", "").rstrip("/")
        api_key = ""
        for k, v in env.items():
            if "KEY" in k.upper() or "TOKEN" in k.upper():
                api_key = v or ""
                break

        if not base_url:
            continue

        stations.append(ProxyStation(
            id=row["id"],
            name=row["name"],
            base_url=base_url,
            api_key=api_key,
            category=row["category"] or "unknown",
            cost_multiplier=_parse_float(row["cost_multiplier"]),
            is_current=bool(row["is_current"]),
            in_failover=bool(row["in_failover_queue"]),
            provider_type=row["provider_type"],
            website_url=row["website_url"],
            notes=row["notes"],
            is_healthy=row["is_healthy"] == 1,
            health_error=row["last_error"],
            last_check=row["health_updated"],
        ))

    conn.close()
    return stations


def _parse_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def get_db_info(db_path: Optional[str] = None) -> dict:
    """获取数据库基本信息，用于调试"""
    if db_path is None:
        db_path = find_ccswitch_db()
    if db_path is None:
        return {"found": False, "path": None}
    return {
        "found": True,
        "path": db_path,
        "size_kb": os.path.getsize(db_path) // 1024,
        "modified": datetime.fromtimestamp(os.path.getmtime(db_path)).isoformat(),
    }
