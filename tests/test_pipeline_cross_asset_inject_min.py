# -*- coding: utf-8 -*-
"""Minimal pipeline-injection verification for Issue #1910 (W2-inject).

Covers the injection contract left to W2-inject by the plan:

- switch ON -> cross-asset section reaches the analysis prompt;
- switch OFF -> zero behaviour change (no fetch, no keys, no prompt section);
- service raise -> fail-open, main analysis unaffected;
- context snapshot keeps the low-sensitivity summary only.

The full matrix (T14-T18) is owned by the downstream W2-tests task; this file
may be merged/absorbed there.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.analyzer import GeminiAnalyzer
from src.core.pipeline import StockAnalysisPipeline
from src.schemas.cross_asset_context import CrossAssetContext, CrossAssetItem


def _config(*, enabled: bool | None = True) -> SimpleNamespace:
    config = SimpleNamespace(
        market_review_enabled=True,
        daily_market_context_enabled=False,
        report_language="zh",
    )
    if enabled is not None:
        config.cross_asset_context_enabled = enabled
    return config


def _pipeline(*, enabled: bool | None = True) -> StockAnalysisPipeline:
    pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
    pipeline.config = _config(enabled=enabled)
    pipeline.analysis_skills = None
    return pipeline


def _risk_off_context() -> CrossAssetContext:
    return CrossAssetContext(
        market="cn",
        trade_date="2026-06-06",
        risk_appetite="risk_off",
        indices={
            "sh000001": CrossAssetItem(
                status="ok",
                value=3100.5,
                change_pct=-1.8,
                source="akshare",
                as_of="2026-06-06",
                stale=False,
                error=None,
            )
        },
        volatility={
            "VIX": CrossAssetItem(
                status="ok",
                value=25.3,
                change_pct=12.0,
                source="yfinance",
                as_of="2026-06-05",
                stale=True,
                error=None,
            )
        },
        impact_summary="外部环境偏 risk-off：VIX 25.3(+12%)，上证走弱",
        risk_tags=["vix_high", "cn_index_down"],
    )


def test_load_cross_asset_context_calls_service_when_enabled() -> None:
    pipeline = _pipeline(enabled=True)
    service = MagicMock()
    service.get_context.return_value = _risk_off_context()

    with patch(
        "src.core.pipeline.get_default_cross_asset_context_service",
        return_value=service,
    ) as factory:
        context = pipeline._load_cross_asset_context(
            "cn",
            target_date=date(2026, 6, 6),
            stock_code="600519",
        )

    factory.assert_called_once_with()
    service.get_context.assert_called_once_with(
        "cn",
        date(2026, 6, 6),
        "600519",
        config=pipeline.config,
    )
    assert context is not None
    assert context.risk_appetite == "risk_off"


def test_load_cross_asset_context_skips_when_switch_off() -> None:
    pipeline = _pipeline(enabled=False)

    with patch(
        "src.core.pipeline.get_default_cross_asset_context_service"
    ) as factory:
        context = pipeline._load_cross_asset_context(
            "cn",
            target_date=date(2026, 6, 6),
        )

    assert context is None
    factory.assert_not_called()


def test_load_cross_asset_context_treats_missing_attr_as_disabled() -> None:
    """Legacy config objects without the field must see zero behaviour change."""
    pipeline = _pipeline(enabled=None)

    with patch(
        "src.core.pipeline.get_default_cross_asset_context_service"
    ) as factory:
        context = pipeline._load_cross_asset_context(
            "cn",
            target_date=date(2026, 6, 6),
        )

    assert context is None
    factory.assert_not_called()


def test_load_cross_asset_context_fail_open_on_service_raise() -> None:
    pipeline = _pipeline(enabled=True)
    service = MagicMock()
    service.get_context.side_effect = RuntimeError("provider exploded")

    with patch(
        "src.core.pipeline.get_default_cross_asset_context_service",
        return_value=service,
    ):
        context = pipeline._load_cross_asset_context(
            "cn",
            target_date=date(2026, 6, 6),
        )

    assert context is None  # fail-open: main analysis continues


def test_attach_writes_safe_dict_and_summary_only_when_section_non_empty() -> None:
    pipeline = _pipeline()
    enhanced_context: dict = {"code": "600519"}

    pipeline._attach_cross_asset_context(
        enhanced_context,
        _risk_off_context(),
        report_language="zh",
    )

    assert enhanced_context["cross_asset_context"]["risk_appetite"] == "risk_off"
    assert "sh000001" in enhanced_context["cross_asset_context"]["indices"]
    # safe dict whitelist: no Chinese name field leakage beyond item keys
    assert "name" not in enhanced_context["cross_asset_context"]["indices"]["sh000001"]
    summary = enhanced_context["cross_asset_context_summary"]
    assert "外围环境与跨资产" in summary
    assert "risk-off" in summary
    assert "BEGIN_UNTRUSTED_CROSS_ASSET_SUMMARY" in summary


def test_switch_off_leaves_context_without_cross_asset_keys() -> None:
    pipeline = _pipeline(enabled=False)
    enhanced_context: dict = {"code": "600519"}

    # switch off -> _load_cross_asset_context returns None -> attach is a no-op
    loaded = pipeline._load_cross_asset_context(
        "cn",
        target_date=date(2026, 6, 6),
    )
    pipeline._attach_cross_asset_context(
        enhanced_context,
        loaded,
        report_language="zh",
    )

    assert "cross_asset_context" not in enhanced_context
    assert "cross_asset_context_summary" not in enhanced_context


def test_analyzer_prompt_contains_cross_asset_section_when_attached() -> None:
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._get_skill_prompt_sections = lambda: ("", "", False)
    context = {
        "code": "600519",
        "stock_name": "贵州茅台",
        "date": "2026-06-06",
        "today": {"close": 1800, "open": 1790, "high": 1810, "low": 1780},
        "cross_asset_context": _risk_off_context().to_safe_dict(),
    }

    prompt = analyzer._format_prompt(context, "贵州茅台", report_language="zh")

    assert "外围环境与跨资产" in prompt
    assert "risk-off" in prompt
    assert "上证指数与跨资产" not in prompt  # no accidental daily section title
    # section order: cross-asset after daily (absent here), before technical data
    assert prompt.index("外围环境与跨资产") < prompt.index("技术面数据")


def test_analyzer_prompt_has_no_cross_asset_section_when_switch_off() -> None:
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    analyzer._get_skill_prompt_sections = lambda: ("", "", False)
    context = {
        "code": "600519",
        "stock_name": "贵州茅台",
        "date": "2026-06-06",
        "today": {"close": 1800, "open": 1790, "high": 1810, "low": 1780},
    }

    prompt = analyzer._format_prompt(context, "贵州茅台", report_language="zh")

    assert "外围环境与跨资产" not in prompt
    assert "Cross-Asset Context" not in prompt


def test_context_snapshot_keeps_low_sensitivity_summary() -> None:
    pipeline = _pipeline()
    enhanced_context = {
        "code": "600519",
        "cross_asset_context": _risk_off_context().to_safe_dict(),
        "cross_asset_context_summary": "## 外围环境与跨资产\n- 外围风险偏好：risk-off",
    }

    snapshot = pipeline._build_context_snapshot(
        enhanced_context=enhanced_context,
        news_content=None,
        realtime_quote=None,
        chip_data=None,
    )

    sanitized = snapshot["enhanced_context"]
    assert "cross_asset_context_summary" in sanitized
    assert "cross_asset_context" in sanitized
    assert sanitized["cross_asset_context"]["risk_appetite"] == "risk_off"


def test_guardrail_receives_safe_dict_from_enhanced_context_and_is_idempotent() -> None:
    from src.cross_asset_context_guardrail import apply_cross_asset_context_guardrail

    result = SimpleNamespace(
        confidence_level="高",
        operation_advice="立即买入，激进加仓",
        phase_decision={"confidence_reason": "", "data_limitations": []},
        dashboard={"position_advice": "建议立即重仓买入"},
    )
    enhanced_context = {"cross_asset_context": _risk_off_context().to_safe_dict()}

    first = apply_cross_asset_context_guardrail(
        result,
        cross_asset_context=enhanced_context.get("cross_asset_context"),
        report_language="zh",
    )
    second = apply_cross_asset_context_guardrail(
        result,
        cross_asset_context=enhanced_context.get("cross_asset_context"),
        report_language="zh",
    )

    assert "confidence_capped_cross_asset_context" in first
    assert result.confidence_level == "中"  # capped once, not repeatedly
    assert second == []  # idempotent on second pass (phase -> daily -> cross-asset)
