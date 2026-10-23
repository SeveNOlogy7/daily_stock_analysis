# -*- coding: utf-8 -*-
"""Wave 2 tests: TdxLocalFetcher registration / behavior / config surface.

Plan: .omz/plans/sess_e87ee49d-53a9-4947-bffc-95ef3ff5f852-issue2143-local-cache.md (Wave 2).

Global test conventions (critic blocker fixes, mandatory):
- Every case touching TDX_* config must monkeypatch.setenv/delenv FIRST and then
  call ``Config.reset_instance()`` (src/config.py) -- ``Config.get_instance()``
  only reads env on first instantiation, so a stale singleton makes registration
  and config assertions lie. An autouse fixture resets the singleton again after
  each test (post-monkeypatch-undo safety for other test files).
- Cases that may touch manager circuit-breaker health reset
  ``DataFetcherManager.reset_daily_source_health()`` in the autouse fixture
  (``_daily_source_health`` is class-level state persisting across tests).
"""

import shutil
import struct
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from data_provider.base import (
    STANDARD_COLUMNS,
    DataFetcherManager,
    is_bse_code,
)
from data_provider.tdx_day_parser import DAY_RECORD_STRUCT
from src.config import Config, get_config

pytestmark = pytest.mark.unit


# === 合成 fixture 工具（与 Wave 1 同款：struct.pack 合成字节，零真实 TDX 依赖） ===


def _pack_record(
    date_int: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    amount: float,
    volume: int,
    reserved: int = 0,
) -> bytes:
    return struct.pack(
        DAY_RECORD_STRUCT,
        date_int,
        int(round(open_ * 100)),
        int(round(high * 100)),
        int(round(low * 100)),
        int(round(close * 100)),
        float(amount),
        int(volume),
        reserved,
    )


def _records_for_dates(dates, base_price: float = 10.0):
    """Deterministic OHLCV records: prices drift +0.1 yuan per bar."""
    records = []
    for index, day in enumerate(dates):
        open_ = base_price + index * 0.1
        records.append(
            _pack_record(
                int(day.strftime("%Y%m%d")),
                open_,
                open_ + 0.5,
                open_ - 0.2,
                open_ + 0.3,
                1_000_000.0 + index * 1000,
                100_000 + index * 100,
            )
        )
    return records


def _write_day_file(path: Path, records) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(records))
    return path


def _make_tdx_tree(tmp_path: Path, style: str = "install") -> Path:
    """Build a minimal vipdoc tree.

    style="install": returns the TDX install root containing ``vipdoc/``.
    style="vipdoc": returns the vipdoc directory itself (``sh/lday`` inside).
    """
    if style == "install":
        root = tmp_path / "new_tdx"
        vipdoc = root / "vipdoc"
    else:
        root = tmp_path
        vipdoc = root
    (vipdoc / "sh" / "lday").mkdir(parents=True, exist_ok=True)
    (vipdoc / "sz" / "lday").mkdir(parents=True, exist_ok=True)
    return root


def _make_fetcher(tmp_path: Path, monkeypatch) -> "TdxLocalFetcher":
    """Construct a TdxLocalFetcher bound to a synthetic vipdoc tree.

    Layout: TDX_LOCAL_PATH points at ``tmp_path`` (install-root style) whose
    ``vipdoc/`` holds ``sh|sz/lday`` -- behavior tests then write day files at
    ``tmp_path/vipdoc/<mkt>/lday/<mkt><code>.day``. Exercises the
    resolve_vipdoc_root auto-descend branch on every fetch.
    """
    from data_provider.tdx_local_fetcher import TdxLocalFetcher

    vipdoc = tmp_path / "vipdoc"
    (vipdoc / "sh" / "lday").mkdir(parents=True, exist_ok=True)
    (vipdoc / "sz" / "lday").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TDX_LOCAL_PATH", str(tmp_path))
    monkeypatch.delenv("TDX_LOCAL_PRIORITY", raising=False)
    monkeypatch.delenv("TDX_LOCAL_MAX_STALE_DAYS", raising=False)
    Config.reset_instance()
    return TdxLocalFetcher()


@pytest.fixture(autouse=True)
def _isolate_global_state(monkeypatch):
    """Global test conventions (plan Wave 2, critic blocker fix)."""
    from data_provider.base import DataFetcherManager as _Manager

    Config.reset_instance()
    _Manager.reset_daily_source_health()
    yield
    Config.reset_instance()
    _Manager.reset_daily_source_health()


# === 注册面（5 例） ===


def test_not_registered_without_env(monkeypatch):
    """默认环境（不设 TDX_LOCAL_PATH）不注册本地源：CI 排序与改动前完全一致。"""
    monkeypatch.delenv("TDX_LOCAL_PATH", raising=False)
    Config.reset_instance()
    manager = DataFetcherManager()
    assert "TdxLocalFetcher" not in manager.available_fetchers


def test_not_registered_when_path_missing(monkeypatch, tmp_path):
    """TDX_LOCAL_PATH 指向不存在的目录 → 不注册（D4 门槛 a）。"""
    monkeypatch.setenv("TDX_LOCAL_PATH", str(tmp_path / "no_such_tdx"))
    Config.reset_instance()
    manager = DataFetcherManager()
    assert "TdxLocalFetcher" not in manager.available_fetchers


def test_registered_first_by_default_when_path_exists(monkeypatch, tmp_path):
    """路径存在 → 注册且排序后居首位（优先级 0 + 列表序稳定排序，D7）。"""
    root = _make_tdx_tree(tmp_path, style="install")
    monkeypatch.setenv("TDX_LOCAL_PATH", str(root))
    monkeypatch.delenv("TDX_LOCAL_PRIORITY", raising=False)
    Config.reset_instance()
    manager = DataFetcherManager()
    names = manager.available_fetchers
    assert "TdxLocalFetcher" in names
    assert names[0] == "TdxLocalFetcher"
    # 同优先级 0 的 Efinance 严格排在其后（稳定排序保持列表序）
    assert names.index("TdxLocalFetcher") < names.index("EfinanceFetcher")


def test_priority_env_override_reorders(monkeypatch, tmp_path):
    """TDX_LOCAL_PRIORITY=5 → 排到 efinance/akshare/pytdx 之后。"""
    root = _make_tdx_tree(tmp_path)
    monkeypatch.setenv("TDX_LOCAL_PATH", str(root))
    monkeypatch.setenv("TDX_LOCAL_PRIORITY", "5")
    Config.reset_instance()
    manager = DataFetcherManager()
    names = manager.available_fetchers
    local_index = names.index("TdxLocalFetcher")
    assert local_index > names.index("EfinanceFetcher")
    assert local_index > names.index("AkshareFetcher")
    assert local_index > names.index("PytdxFetcher")


def test_is_available_for_request_false_when_dir_removed(monkeypatch, tmp_path):
    """构造后删除目录 → is_available_for_request 返回 False（D4 门槛 b）。"""
    from data_provider.tdx_local_fetcher import TdxLocalFetcher

    root = _make_tdx_tree(tmp_path)
    monkeypatch.setenv("TDX_LOCAL_PATH", str(root))
    Config.reset_instance()
    fetcher = TdxLocalFetcher()
    assert fetcher.is_available_for_request("daily_data") is True
    shutil.rmtree(root)
    assert fetcher.is_available_for_request("daily_data") is False


# === 行为面（6 例） ===


def test_get_daily_data_reads_local_file(tmp_path, monkeypatch):
    """合成 sh600519.day（30 条）→ get_daily_data 返回 ['code']+STANDARD_COLUMNS 契约。"""
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    start = date(2026, 1, 1)
    dates = [start + timedelta(days=i) for i in range(30)]
    _write_day_file(
        tmp_path / "vipdoc" / "sh" / "lday" / "sh600519.day",
        _records_for_dates(dates),
    )

    df = fetcher.get_daily_data("600519", start_date="2026-01-01", end_date="2026-01-30")

    assert len(df) == 30
    assert list(df.columns)[:9] == ["code"] + STANDARD_COLUMNS
    assert (df["code"] == "600519").all()
    # 价格 ÷100 转元（首条 open=10.0, close=10.3）
    assert df["open"].iloc[0] == pytest.approx(10.0, abs=1e-9)
    assert df["close"].iloc[0] == pytest.approx(10.3, abs=1e-9)
    assert df["volume"].iloc[0] == 100_000
    # pct_chg 首行为 0（.day 无涨跌幅列，由 close 计算并 fillna(0)）
    assert df["pct_chg"].iloc[0] == 0
    # ma5/ma20 由基类 _calculate_indicators 生成，本 fetcher 不自己算
    assert df["ma5"].iloc[0] == pytest.approx(df["close"].iloc[0])
    assert df["ma20"].iloc[4] == pytest.approx(df["close"].iloc[:5].mean(), abs=0.01)


def test_window_filtering_start_end(tmp_path, monkeypatch):
    """文件 60 条、请求窗口只覆盖中段 20 天 → 只返回窗口内行。"""
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    start = date(2026, 3, 1)
    dates = [start + timedelta(days=i) for i in range(60)]
    _write_day_file(
        tmp_path / "vipdoc" / "sh" / "lday" / "sh600519.day",
        _records_for_dates(dates),
    )

    df = fetcher.get_daily_data(
        "600519",
        start_date=(start + timedelta(days=20)).isoformat(),
        end_date=(start + timedelta(days=39)).isoformat(),
    )

    assert len(df) == 20
    assert df["date"].iloc[0] == pd.Timestamp(start + timedelta(days=20))
    assert df["date"].iloc[-1] == pd.Timestamp(start + timedelta(days=39))


def test_days_semantics_matches_base_contract(tmp_path, monkeypatch):
    """只传 days=5 → 窗口 = today-10d..today（base.py:467-500 契约）。

    fixture 日期按 datetime.now() 动态回溯生成，断言集合相等，不写死日期
    （避免午夜/周末漂移误挂）。
    """
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    today = datetime.now().date()
    dates = [today - timedelta(days=offset) for offset in range(20, -1, -1)]
    _write_day_file(
        tmp_path / "vipdoc" / "sz" / "lday" / "sz000001.day",
        _records_for_dates(dates),
    )

    df = fetcher.get_daily_data("000001", days=5)

    window_start = today - timedelta(days=10)
    expected = [d for d in dates if d >= window_start]
    returned = [d.date() if hasattr(d, "date") else d for d in df["date"]]
    assert returned == expected


def test_bse_code_returns_empty(tmp_path, monkeypatch):
    """BSE 码 → _fetch_raw_data 空 + allow_empty_daily_data True → 空 df 不抛（D6/D8）。"""
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    assert is_bse_code("920748")
    assert fetcher.allow_empty_daily_data is True

    raw = fetcher._fetch_raw_data("920748", "2026-01-01", "2026-01-30")
    assert raw is not None and raw.empty

    df = fetcher.get_daily_data("920748", start_date="2026-01-01", end_date="2026-01-30")
    assert df.empty


def test_hk_code_returns_empty_defensively(tmp_path, monkeypatch):
    """港股码直接调 fetcher → 空（manager 层另有市场表过滤，D8 防御）。"""
    fetcher = _make_fetcher(tmp_path, monkeypatch)
    raw = fetcher._fetch_raw_data("00700", "2026-01-01", "2026-01-30")
    assert raw is not None and raw.empty

    df = fetcher.get_daily_data("00700", start_date="2026-01-01", end_date="2026-01-30")
    assert df.empty


def test_support_table_entry():
    """市场支持表：TdxLocalFetcher 仅支持 cn（base.py:801 按 name 查表）。"""
    assert DataFetcherManager._DAILY_MARKET_FETCHER_SUPPORT["TdxLocalFetcher"] == {"cn"}


# === 配置面（3 例） ===


def test_config_defaults_when_unset(monkeypatch):
    """清 env → path None / priority 0 / max_stale_days 10。"""
    monkeypatch.delenv("TDX_LOCAL_PATH", raising=False)
    monkeypatch.delenv("TDX_LOCAL_PRIORITY", raising=False)
    monkeypatch.delenv("TDX_LOCAL_MAX_STALE_DAYS", raising=False)
    Config.reset_instance()
    config = get_config()
    assert config.tdx_local_path is None
    assert config.tdx_local_priority == 0
    assert config.tdx_local_max_stale_days == 10


def test_config_env_parsing(monkeypatch, tmp_path):
    """setenv 三键 → 正确解析；TDX_LOCAL_PRIORITY=-1 走 parse_env_int 最小值钳制。"""
    monkeypatch.setenv("TDX_LOCAL_PATH", str(tmp_path))
    monkeypatch.setenv("TDX_LOCAL_PRIORITY", "3")
    monkeypatch.setenv("TDX_LOCAL_MAX_STALE_DAYS", "20")
    Config.reset_instance()
    config = get_config()
    assert config.tdx_local_path == str(tmp_path)
    assert config.tdx_local_priority == 3
    assert config.tdx_local_max_stale_days == 20

    # 对齐 TICKFLOW_PRIORITY 样板（config.py:1915）：minimum=0 时负值钳制为 0
    monkeypatch.setenv("TDX_LOCAL_PRIORITY", "-1")
    Config.reset_instance()
    config = get_config()
    assert config.tdx_local_priority == 0


def test_config_registry_contains_tdx_keys():
    """registry 三个 key 存在、category == data_source、help_key 指向 settings.data_source.*。"""
    from src.core.config_registry import get_field_definition, get_registered_field_keys

    registered = set(get_registered_field_keys())
    for key in ("TDX_LOCAL_PATH", "TDX_LOCAL_PRIORITY", "TDX_LOCAL_MAX_STALE_DAYS"):
        assert key in registered, f"{key} not registered in _FIELD_DEFINITIONS"
        field = get_field_definition(key)
        assert field["category"] == "data_source", f"{key} category"
        assert field["help_key"] == f"settings.data_source.{key}", f"{key} help_key"
